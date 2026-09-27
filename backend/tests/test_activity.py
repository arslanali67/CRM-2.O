"""M24: activity timeline. Done when: approved / queued / sent events are logged per email."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import settings
from app.deps import get_db
from app.main import app


def draft(db, to="jobs@acme.de"):
    return db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body) VALUES (%s, 's', 'b') RETURNING id", (to,)
    ).fetchone()[0]


def set_status(db, email_id, status):
    extra = ", sent_at = now()" if status == "sent" else ""
    db.execute(
        f"UPDATE outbound_emails SET status = %s, approved_at = coalesce(approved_at, now()), "
        f"approved_content_hash = content_hash{extra} WHERE id = %s", (status, email_id))


def events(db, email_id):
    return db.execute(
        "SELECT action, actor, data FROM audit_log WHERE entity_type = 'outbound_email' AND entity_id = %s ORDER BY id",
        (email_id,)).fetchall()


def test_full_lifecycle_is_logged_per_email(db):
    i = draft(db, "Jobs@Acme.de")
    for status in ["approved", "queued", "sending", "sent"]:
        set_status(db, i, status)
    ev = events(db, i)
    assert [a for a, _, _ in ev] == ["outbound_email.created", "outbound_email.approved", "outbound_email.queued",
                                     "outbound_email.sending", "outbound_email.sent"]
    assert [(d["from"], d["to"]) for _, _, d in ev] == [
        (None, "draft"), ("draft", "approved"), ("approved", "queued"), ("queued", "sending"), ("sending", "sent")]
    assert {d["to_email"] for _, _, d in ev} == {"jobs@acme.de"}
    assert {actor for _, actor, _ in ev} == {"system"}  # no app.actor on this connection


def test_each_email_has_its_own_events(db):
    a, b = draft(db, "a@acme.de"), draft(db, "b@acme.de")
    set_status(db, a, "approved")
    assert [x for x, _, _ in events(db, a)] == ["outbound_email.created", "outbound_email.approved"]
    assert [x for x, _, _ in events(db, b)] == ["outbound_email.created"]


def test_insert_directly_into_a_send_state_is_logged_as_that_state(db):
    i = db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body, status, approved_at, approved_content_hash) "
        "VALUES ('x@acme.de', 's', 'b', 'approved', now(), email_content_hash('x@acme.de', 's', 'b')) RETURNING id"
    ).fetchone()[0]
    assert [(a, d["from"], d["to"]) for a, _, d in events(db, i)] == [("outbound_email.approved", None, "approved")]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_terminal_states_logged(db, status):
    i = draft(db)
    set_status(db, i, "approved")
    db.execute("UPDATE outbound_emails SET status = %s WHERE id = %s", (status, i))
    assert events(db, i)[-1][0] == f"outbound_email.{status}"


def test_non_status_updates_are_not_status_events(db):
    i = draft(db)
    db.execute("UPDATE outbound_emails SET provider_message_id = '<m@x>' WHERE id = %s", (i,))
    db.execute("UPDATE outbound_emails SET status = 'draft' WHERE id = %s", (i,))  # same status
    assert len(events(db, i)) == 1


def test_actor_comes_from_connection(db):
    db.execute("SELECT set_config('app.actor', 'owner', true)")
    i = draft(db)
    assert events(db, i)[0][1] == "owner"


def test_block_auto_cancel_logs_once_per_email_as_system(db):
    db.execute("SELECT set_config('app.actor', 'owner', true)")
    i = draft(db, "jobs@blocked.de")
    set_status(db, i, "queued")
    sid = db.execute(
        "INSERT INTO suppressions (kind, domain, reason) VALUES ('domain', 'blocked.de', 'x') RETURNING id").fetchone()[0]
    last = events(db, i)[-1]
    assert last[0] == "outbound_email.cancelled" and last[1] == "system"
    assert last[2]["reason"] == "do_not_contact" and last[2]["suppression_id"] == sid
    assert [a for a, _, _ in events(db, i)].count("outbound_email.cancelled") == 1
    # context is cleared afterwards: later changes in the same transaction are not attributed to the block
    j = draft(db, "other@else.de")
    assert "suppression_id" not in events(db, j)[0][2] and events(db, j)[0][1] == "owner"


def test_api_connections_act_as_owner(test_url, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", test_url)
    gen = get_db()
    conn = next(gen)
    assert conn.execute("SELECT current_setting('app.actor')").fetchone()["current_setting"] == "owner"
    gen.close()


# ---------- API ----------

def test_requires_login():
    c = TestClient(app)
    for path in ["/activity", "/activity/company/1", "/companies/1/activity"]:
        assert c.get(path).status_code == 401, path


def test_feed_newest_first_with_paging(client):
    for n in range(5):
        client.post("/companies", json={"name": f"Co {n}"})
    page1 = client.get("/activity", params={"limit": 3}).json()
    assert [e["data"]["name"] for e in page1] == ["Co 4", "Co 3", "Co 2"]
    page2 = client.get("/activity", params={"limit": 3, "before_id": page1[-1]["id"]}).json()
    assert [e["data"]["name"] for e in page2[:2]] == ["Co 1", "Co 0"]
    assert client.get("/activity", params={"limit": 0}).status_code == 422
    assert client.get("/activity", params={"limit": 201}).status_code == 422


def test_company_timeline(client, test_url):
    acme = client.post("/companies", json={"name": "Acme", "domain": "acme.de"}).json()
    other = client.post("/companies", json={"name": "Other", "domain": "other.de"}).json()
    ct = client.post(f"/companies/{acme['id']}/contacts", json={"email": "cto.acme@gmail.com"}).json()
    client.post(f"/companies/{other['id']}/contacts", json={"email": "jobs@other.de"})
    with psycopg.connect(test_url) as conn:
        for to in ["cto.acme@gmail.com", "jobs@eu.acme.de", "jobs@other.de"]:
            conn.execute("INSERT INTO outbound_emails (to_email, subject, body) VALUES (%s, 's', 'b')", (to,))
    client.post("/suppressions", json={"kind": "company", "company_id": acme["id"], "reason": "asked"})

    tl = client.get(f"/companies/{acme['id']}/activity").json()
    got = {(e["entity_type"], e["action"], e["data"].get("to_email")) for e in tl}
    assert ("company", "company.created", None) in got
    assert ("contact", "contact.created", None) in got
    assert ("suppression", "suppression.added", None) in got
    assert ("outbound_email", "outbound_email.created", "cto.acme@gmail.com") in got
    assert ("outbound_email", "outbound_email.created", "jobs@eu.acme.de") in got
    assert not any(e["data"].get("to_email") == "jobs@other.de" for e in tl)
    assert not any(e["entity_type"] == "company" and e["entity_id"] == other["id"] for e in tl)
    assert [e["id"] for e in tl] == sorted((e["id"] for e in tl), reverse=True)

    ent = client.get(f"/activity/contact/{ct['id']}").json()
    assert [e["action"] for e in ent] == ["contact.created"]
    assert client.get("/companies/999999/activity").status_code == 404
