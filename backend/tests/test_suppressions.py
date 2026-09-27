"""M25: do-not-contact list. Done when: no code path can send to a suppressed recipient.

DB tests cover every way into a send state (INSERT and UPDATE into approved / queued /
sending) against every block type, independent of the API.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.main import app

SEND_STATES = ["approved", "queued", "sending"]


# ---------- DB-level helpers (inside a rolled-back transaction) ----------

def company(db, name="Acme", domain="acme.de"):
    return db.execute("INSERT INTO companies (name, domain) VALUES (%s, %s) RETURNING id", (name, domain)).fetchone()[0]


def contact(db, company_id, email, cls="personal"):
    db.execute("INSERT INTO contacts (company_id, email, email_class) VALUES (%s, %s, %s)", (company_id, email, cls))


def block(db, kind, value):
    col = {"email": "email", "domain": "domain", "company": "company_id"}[kind]
    return db.execute(
        f"INSERT INTO suppressions (kind, {col}, reason) VALUES (%s, %s, 'test') RETURNING id", (kind, value)
    ).fetchone()[0]


def draft(db, to):
    return db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body) VALUES (%s, 's', 'b') RETURNING id", (to,)
    ).fetchone()[0]


def move_to(db, email_id, status):
    db.execute(
        "UPDATE outbound_emails SET status = %s, approved_at = now(), approved_content_hash = content_hash "
        "WHERE id = %s", (status, email_id))


def insert_in(db, to, status):
    db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body, status, approved_at, approved_content_hash) "
        "VALUES (%s, 's', 'b', %s, now(), email_content_hash(%s, 's', 'b'))", (to, status, to))


def blocked(db, fn, *args):
    """True if the DB refuses the operation as a do-not-contact violation."""
    try:
        with db.transaction():
            fn(db, *args)
        return False
    except errors.CheckViolation as e:
        assert "do-not-contact" in str(e)
        return True


def is_suppressed(db, addr):
    return db.execute("SELECT is_suppressed(%s)", (addr,)).fetchone()[0]


# ---------- no code path can send to a suppressed recipient ----------

@pytest.mark.parametrize("status", SEND_STATES)
@pytest.mark.parametrize("kind,value,recipient", [
    ("email", "anna@acme.de", "Anna@Acme.de"),
    ("domain", "acme.de", "jobs@acme.de"),
    ("domain", "acme.de", "jobs@eu.acme.de"),
    ("company", None, "info@acme.de"),              # company domain
    ("company", None, "cto.acme@gmail.com"),        # contact stored under the company
])
def test_every_path_into_a_send_state_is_blocked(db, status, kind, value, recipient):
    cid = company(db)
    contact(db, cid, "cto.acme@gmail.com")
    block(db, kind, cid if kind == "company" else value)
    assert is_suppressed(db, recipient)
    assert blocked(db, insert_in, recipient, status)                    # INSERT path
    assert blocked(db, lambda d: move_to(d, draft(d, recipient), status))  # UPDATE path


def test_unblocked_recipients_still_work(db):
    cid = company(db)
    block(db, "domain", "acme.de")
    block(db, "company", cid)
    for addr in ["jobs@notacme.de", "jobs@acme.de.evil.com", "someone@gmail.com"]:
        assert not is_suppressed(db, addr), addr
        move_to(db, draft(db, addr), "approved")


def test_drafts_and_terminal_states_are_not_blocked(db):
    block(db, "email", "anna@acme.de")
    i = draft(db, "anna@acme.de")  # drafting is fine; sending is not
    db.execute("UPDATE outbound_emails SET status = 'cancelled' WHERE id = %s", (i,))


def test_lifted_block_no_longer_blocks(db):
    s = block(db, "email", "anna@acme.de")
    db.execute("UPDATE suppressions SET lifted_at = now(), lift_reason = 'they asked us to write' WHERE id = %s", (s,))
    assert not is_suppressed(db, "anna@acme.de")
    move_to(db, draft(db, "anna@acme.de"), "approved")


def test_new_block_cancels_pending_emails_and_audits(db):
    a, q, s = draft(db, "jobs@acme.de"), draft(db, "hr@acme.de"), draft(db, "cto@acme.de")
    other = draft(db, "jobs@other.de")
    for i, st in [(a, "approved"), (q, "queued"), (s, "sending"), (other, "approved")]:
        move_to(db, i, st)
    sid = block(db, "domain", "acme.de")
    status = dict(db.execute("SELECT id, status FROM outbound_emails WHERE id = ANY(%s)", ([a, q, s, other],)).fetchall())
    assert status == {a: "cancelled", q: "cancelled", s: "sending", other: "approved"}
    audited = db.execute(
        "SELECT entity_id FROM audit_log WHERE action = 'outbound_email.cancelled' AND (data->>'suppression_id')::bigint = %s",
        (sid,)).fetchall()
    assert sorted(r[0] for r in audited) == sorted([a, q])
    assert blocked(db, move_to, a, "approved")  # a cancelled email cannot be re-approved while blocked


def test_blocks_are_immutable_and_never_deleted(db):
    s = block(db, "email", "anna@acme.de")
    for sql in ["UPDATE suppressions SET reason = 'x' WHERE id = %s", "UPDATE suppressions SET email = 'b@acme.de' WHERE id = %s",
                "DELETE FROM suppressions WHERE id = %s"]:
        with pytest.raises(errors.RaiseException):
            with db.transaction():
                db.execute(sql, (s,))
    with pytest.raises(errors.RaiseException):
        with db.transaction():
            db.execute("TRUNCATE suppressions CASCADE")
    with pytest.raises(errors.CheckViolation):  # lift needs a reason
        with db.transaction():
            db.execute("UPDATE suppressions SET lifted_at = now() WHERE id = %s", (s,))
    db.execute("UPDATE suppressions SET lifted_at = now(), lift_reason = 'ok' WHERE id = %s", (s,))
    with pytest.raises(errors.RaiseException):  # cannot un-lift or re-lift
        db.execute("UPDATE suppressions SET lifted_at = NULL, lift_reason = NULL WHERE id = %s", (s,))


def test_one_active_block_per_target(db):
    s = block(db, "domain", "acme.de")
    with pytest.raises(errors.UniqueViolation):
        with db.transaction():
            block(db, "domain", "acme.de")
    db.execute("UPDATE suppressions SET lifted_at = now(), lift_reason = 'ok' WHERE id = %s", (s,))
    block(db, "domain", "acme.de")  # re-blocking after a lift is allowed


# ---------- API ----------

def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/suppressions"), ("post", "/suppressions"), ("post", "/suppressions/1/lift"),
                         ("get", "/suppressions/check?email=a@b.de")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_api_add_check_list_lift(client):
    r = client.post("/suppressions", json={"kind": "domain", "value": "https://www.Blocked.de/x", "reason": "asked"})
    assert r.status_code == 201
    s = r.json()
    assert (s["domain"], s["cancelled_emails"]) == ("blocked.de", 0)
    assert client.get("/suppressions/check", params={"email": "jobs@sub.blocked.de"}).json()["suppressed"] is True
    assert client.post("/suppressions", json={"kind": "domain", "value": "blocked.de", "reason": "again"}).status_code == 409

    assert client.post(f"/suppressions/{s['id']}/lift", json={"reason": " "}).status_code == 422
    lifted = client.post(f"/suppressions/{s['id']}/lift", json={"reason": "they replied positively"}).json()
    assert lifted["lift_reason"] == "they replied positively" and lifted["lifted_at"]
    assert client.post(f"/suppressions/{s['id']}/lift", json={"reason": "again"}).status_code == 409
    assert client.post("/suppressions/999999/lift", json={"reason": "x"}).status_code == 404
    assert client.get("/suppressions/check", params={"email": "jobs@sub.blocked.de"}).json()["suppressed"] is False
    assert [x["id"] for x in client.get("/suppressions").json()] == [s["id"]]  # lifted stays listed


@pytest.mark.parametrize("body", [
    {"kind": "email", "value": "not-an-email", "reason": "x"},
    {"kind": "domain", "value": "", "reason": "x"},
    {"kind": "domain", "value": "not a domain", "reason": "x"},
    {"kind": "company", "reason": "x"},
    {"kind": "email", "value": "a@b.de", "reason": ""},
    {"kind": "phone", "value": "123", "reason": "x"},
])
def test_api_validation(client, body):
    assert client.post("/suppressions", json=body).status_code == 422


def test_api_company_block_shows_on_company_page_and_cancels(client, test_url):
    co = client.post("/companies", json={"name": "Blocked Co", "domain": "blockedco.de"}).json()
    ct = client.post(f"/companies/{co['id']}/contacts", json={"email": "ceo.blockedco@gmail.com"}).json()
    free = client.post(f"/companies/{co['id']}/contacts", json={"name": "No email"}).json()
    with psycopg.connect(test_url) as conn:  # an approved email waiting to go out
        conn.execute(
            "INSERT INTO outbound_emails (to_email, subject, body, status, approved_at, approved_content_hash) "
            "VALUES ('ceo.blockedco@gmail.com', 's', 'b', 'approved', now(), email_content_hash('ceo.blockedco@gmail.com', 's', 'b'))")

    assert client.post("/suppressions", json={"kind": "company", "company_id": 999999, "reason": "x"}).status_code == 404
    r = client.post("/suppressions", json={"kind": "company", "company_id": co["id"], "reason": "not hiring, asked"}).json()
    assert r["cancelled_emails"] == 1

    page = client.get(f"/companies/{co['id']}").json()
    assert page["block"]["id"] == r["id"]
    assert {c["id"]: c["suppressed"] for c in page["contacts"]} == {ct["id"]: True, free["id"]: True}
    with psycopg.connect(test_url) as conn:
        actions = [a for (a,) in conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'suppression' AND entity_id = %s ORDER BY id", (r["id"],))]
    assert actions == ["suppression.added"]
