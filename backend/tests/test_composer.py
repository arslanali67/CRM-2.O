"""M10: composer. Done when: nothing is queued without per-email approval."""
import inspect

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from app.main import app

PDF = b"%PDF-1.7\n%%EOF\n"
TEMPLATE = {"name": "Intro", "subject": "Application at {{company_name}}",
            "body": "Hi {{contact_first_name | there}},\n\nI'm {{my_full_name}}."}


def make_company(client, name, domain, email, contact_name=""):
    cid = client.post("/companies", json={"name": name, "domain": domain}).json()["id"]
    client.post(f"/companies/{cid}/contacts", json={"name": contact_name, "email": email})
    return cid


@pytest.fixture
def ready(client):
    """Profile, a CV, a template and three companies in the compose list (one without a usable recipient)."""
    client.put("/profile", json={"full_name": "Arslan Ali", "email": "me@example.com"})
    cv = client.post("/cv", params={"label": "Main", "filename": "cv.pdf"}, content=PDF,
                     headers={"Content-Type": "application/pdf"}).json()["id"]
    tid = client.post("/templates", json=TEMPLATE).json()["id"]
    acme = make_company(client, "Acme", "acme.de", "anna@acme.de", "Anna Schmidt")
    beta = make_company(client, "Beta", "beta.io", "jobs@beta.io")
    gamma = make_company(client, "Gamma", "gamma.fr", "noreply@gamma.fr")
    client.post("/compose-list", json={"company_ids": [acme, beta, gamma]})  # gamma is refused (unsuitable only)
    return {"template": tid, "cv": cv, "acme": acme, "beta": beta, "gamma": gamma}


def drafts(client, ready, **kw):
    r = client.post("/compose-list/drafts", json={"template_id": ready["template"], **kw})
    assert r.status_code == 201, r.text
    return r.json()


def email(client, email_id):
    return client.get(f"/outbound-emails/{email_id}").json()


def approve(client, email_id, content_hash=None):
    h = content_hash or email(client, email_id)["content_hash_hex"]
    return client.post(f"/outbound-emails/{email_id}/approve", json={"content_hash": h})


def statuses(test_url):
    with psycopg.connect(test_url) as conn:
        return dict(conn.execute("SELECT id, status FROM outbound_emails").fetchall())


def test_requires_login():
    c = TestClient(app)
    for method, path in [("post", "/compose-list/drafts"), ("get", "/outbox"), ("get", "/outbound-emails/1"),
                         ("put", "/outbound-emails/1"), ("post", "/outbound-emails/1/approve"),
                         ("post", "/outbound-emails/1/unqueue"), ("post", "/outbound-emails/1/discard")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_drafts_are_rendered_linked_and_leave_the_compose_list(client, ready):
    r = drafts(client, ready)
    assert sorted(x["name"] for x in r["created"]) == ["Acme", "Beta"]
    assert r["skipped"] == []  # gamma never made it into the list
    assert client.get("/compose-list").json() == []
    acme = next(x for x in r["created"] if x["name"] == "Acme")
    e = email(client, acme["email_id"])
    assert (e["status"], e["to_email"], e["subject"]) == ("draft", "anna@acme.de", "Application at Acme")
    assert e["body"] == "Hi Anna,\n\nI'm Arslan Ali."
    assert (e["company_name"], e["contact_name"], e["template_name"], e["template_version"]) == ("Acme", "Anna Schmidt", "Intro", 1)
    assert e["from"] == {"name": "Arslan Ali", "email": "me@example.com", "account_connected": False}
    assert e["cv_version_id"] is None
    assert e["checks"]["stage"] == "approval" and all(c["ok"] for c in e["checks"]["results"])


def test_unresolved_variables_skip_the_company(client, ready):
    tid = client.post("/templates", json={"name": "Strict", "subject": "Hi", "body": "Dear {{contact_name}}"}).json()["id"]
    r = client.post("/compose-list/drafts", json={"template_id": tid}).json()
    assert [x["name"] for x in r["created"]] == ["Acme"]
    assert r["skipped"] == [{"company_id": ready["beta"], "name": "Beta", "reason": "unresolved: contact_name"}]
    assert [x["name"] for x in client.get("/compose-list").json()] == ["Beta"]  # stays in the list


def test_cv_attachment_is_the_owners_choice(client, ready):
    with_cv = drafts(client, ready, attach_cv=True)["created"]
    assert {email(client, x["email_id"])["cv_label"] for x in with_cv} == {"Main"}
    e = email(client, with_cv[0]["email_id"])
    r = client.put(f"/outbound-emails/{e['id']}", json={"subject": e["subject"], "body": e["body"], "cv_version_id": None})
    assert r.json()["cv_version_id"] is None and r.json()["content_hash_hex"] != e["content_hash_hex"]
    assert client.put(f"/outbound-emails/{e['id']}", json={"subject": "s", "body": "b", "cv_version_id": 999999}).status_code == 404


def test_attach_cv_without_default_is_refused(client, ready, test_url):
    with psycopg.connect(test_url) as conn:
        conn.execute("UPDATE cv_versions SET is_default = false")
    assert client.post("/compose-list/drafts", json={"template_id": ready["template"], "attach_cv": True}).status_code == 422
    assert client.post("/compose-list/drafts", json={"template_id": 999999}).status_code == 404


# ---------- nothing is queued without per-email approval ----------

def test_creating_drafts_queues_nothing(client, ready, test_url):
    drafts(client, ready)
    assert set(statuses(test_url).values()) == {"draft"}


def test_approve_queues_exactly_that_one_email(client, ready, test_url):
    created = drafts(client, ready)["created"]
    first, second = created[0]["email_id"], created[1]["email_id"]
    r = approve(client, first)
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert statuses(test_url) == {first: "queued", second: "draft"}


def test_approval_is_bound_to_the_content_the_owner_saw(client, ready, test_url):
    i = drafts(client, ready)["created"][0]["email_id"]
    seen = email(client, i)["content_hash_hex"]
    e = email(client, i)
    client.put(f"/outbound-emails/{i}", json={"subject": e["subject"], "body": e["body"] + "\nP.S. edited elsewhere"})
    r = approve(client, i, content_hash=seen)
    assert r.status_code == 409
    assert statuses(test_url)[i] == "draft"
    assert approve(client, i, content_hash="0" * 64).status_code == 409
    assert client.post(f"/outbound-emails/{i}/approve", json={"content_hash": "not-hex"}).status_code == 422


def test_failed_checks_refuse_approval_and_are_audited(client, ready, test_url):
    i = drafts(client, ready)["created"][0]["email_id"]
    client.post("/leads/stage", json={"company_ids": [email(client, i)["company_id"]], "stage": "on_hold"})
    r = approve(client, i)
    assert r.status_code == 422 and r.json()["approved"] is False
    assert {c["id"] for c in r.json()["checks"] if not c["ok"]} == {4}
    assert statuses(test_url)[i] == "draft"
    with psycopg.connect(test_url) as conn:  # the failure was committed despite the 422
        assert conn.execute("SELECT count(*) FROM audit_log WHERE action = 'outbound_email.checks_failed' "
                            "AND entity_id = %s", (i,)).fetchone()[0] == 1


def test_editing_requires_back_to_draft_and_reapproval(client, ready, test_url):
    i = drafts(client, ready)["created"][0]["email_id"]
    approve(client, i)
    e = email(client, i)
    assert e["checks"]["stage"] == "send"
    assert client.put(f"/outbound-emails/{i}", json={"subject": "x", "body": "y"}).status_code == 409
    assert client.post(f"/outbound-emails/{i}/unqueue").json() == {"status": "draft"}
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT approved_at, approved_content_hash FROM outbound_emails WHERE id = %s",
                            (i,)).fetchone() == (None, None)
    client.put(f"/outbound-emails/{i}", json={"subject": "New subject", "body": "New body"})
    assert approve(client, i).json()["status"] == "queued"
    assert client.post(f"/outbound-emails/{i}/unqueue").status_code == 200
    assert client.post(f"/outbound-emails/{i}/unqueue").status_code == 409  # already a draft


def test_attachment_change_after_approval_is_rejected_by_the_database(client, ready, test_url):
    i = drafts(client, ready)["created"][0]["email_id"]
    approve(client, i)
    with psycopg.connect(test_url) as conn:
        with pytest.raises(errors.CheckViolation), conn.transaction():
            conn.execute("UPDATE outbound_emails SET cv_version_id = %s WHERE id = %s", (ready["cv"], i))


def test_there_is_no_bulk_approval():
    from app.composer import approve_and_queue
    paths = app.openapi()["paths"]
    assert {p for p in paths if "approv" in p} == {"/outbound-emails/{email_id}/approve"}
    assert set(paths["/outbound-emails/{email_id}/approve"]) == {"post"}
    params = inspect.signature(approve_and_queue).parameters
    assert params["email_id"].annotation is int  # exactly one email per call
    assert set(params["body"].annotation.model_fields) == {"content_hash"}  # one hash, no list of ids


def test_queued_requires_approval_in_the_database(test_url):
    with psycopg.connect(test_url) as conn:
        with pytest.raises(errors.CheckViolation), conn.transaction():
            conn.execute("INSERT INTO outbound_emails (to_email, subject, body, status) VALUES ('a@b.de', 's', 'b', 'queued')")


def test_discard_and_outbox(client, ready):
    created = drafts(client, ready)["created"]
    a, b = created[0]["email_id"], created[1]["email_id"]
    approve(client, a)
    assert client.post(f"/outbound-emails/{b}/discard").json() == {"status": "cancelled"}
    assert client.post(f"/outbound-emails/{a}/discard").status_code == 409  # only drafts
    box = client.get("/outbox", params={"status": "cancelled"}).json()
    assert box["counts"] == {"queued": 1, "cancelled": 1}
    assert [(e["id"], e["cancel_reason"]) for e in box["emails"]] == [(b, "discarded by owner")]
    assert [e["id"] for e in client.get("/outbox", params={"status": "queued"}).json()["emails"]] == [a]
    assert client.get("/outbox", params={"status": "bogus"}).status_code == 422
    assert client.get("/outbound-emails/999999").status_code == 404


def test_email_events_reach_the_company_timeline(client, ready):
    i = drafts(client, ready)["created"][0]["email_id"]
    approve(client, i)
    company = email(client, i)["company_id"]
    actions = [e["action"] for e in client.get(f"/companies/{company}/activity").json()]
    assert {"outbound_email.created", "outbound_email.approved", "outbound_email.queued"} <= set(actions)
