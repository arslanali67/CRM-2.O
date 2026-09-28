"""M7: duplicate management. Done when: merge + undo work and no duplicate active domains exist."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app
from fakes import db


def co(client, name, domain="", **kw):
    r = client.post("/companies", json={"name": name, "domain": domain, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def person(client, cid, email, name=""):
    r = client.post(f"/companies/{cid}/contacts", json={"email": email, "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def pairs(client):
    return {(p["a"], p["b"]): p["reasons"] for p in client.get("/duplicates").json()}


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/duplicates"), ("post", "/duplicates/merge"), ("post", "/duplicates/dismiss"),
                         ("get", "/duplicates/merges"), ("post", "/duplicates/merges/1/undo")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_database_never_allows_two_active_companies_with_one_domain(client, test_url):
    co(client, "Acme", "acme.de")
    assert client.post("/companies", json={"name": "Acme 2", "domain": "acme.de"}).status_code == 409
    with pytest.raises(psycopg.errors.UniqueViolation):
        db(test_url, "INSERT INTO companies (name, domain) VALUES ('Acme 3', 'acme.de')")


def test_suggestions_by_domain_email_linkedin_and_name(client):
    a = co(client, "Acme GmbH", "acme.de")
    b = co(client, "Acme Jobs", "jobs.acme.de")           # same main domain
    c = co(client, "Acme GmbH Berlin", "acme.com")         # same brand + similar name, other TLD
    d = co(client, "Beta AG", linkedin_url="https://www.linkedin.com/company/beta/")
    e = co(client, "Beta Labs", linkedin_url="http://linkedin.com/company/beta")  # same LinkedIn
    f = co(client, "Gamma", "gamma.io")
    g = co(client, "Totally Different")
    person(client, g, "hr@careers.gamma.io")               # contact's email is at another company's domain
    h = co(client, "Unrelated Co", "unrelated.org")
    found = pairs(client)
    assert "domain" in found[(a, b)] and "domain" in found[(a, c)]
    assert "linkedin" in found[(d, e)]
    assert "email" in found[(f, g)]
    assert "name" in found[(a, c)]
    assert not [p for p in found if h in p]


def test_dismissed_pairs_are_not_suggested_again(client):
    a, b = co(client, "Acme", "acme.de"), co(client, "Acme Careers", "careers.acme.de")
    assert (a, b) in pairs(client)
    assert client.post("/duplicates/dismiss", json={"company_a": b, "company_b": a}).status_code == 200
    assert (a, b) not in pairs(client)


@pytest.fixture
def two(client, test_url):
    """Survivor 'Acme' (no domain) and duplicate 'Acme GmbH' with records of every kind."""
    s = co(client, "Acme")
    m = co(client, "Acme GmbH", "acme.de", city="Berlin", industry="AI")
    ct = person(client, m, "anna@acme.de", "Anna")
    rows = {"contact": ct}
    rows["draft"] = db(test_url, "INSERT INTO outbound_emails (company_id, contact_id, to_email, subject, body) "
                                 "VALUES (%s, %s, 'anna@acme.de', 'Hi', 'Body') RETURNING id", (m, ct))[0][0]
    rows["inbound"] = db(test_url, "INSERT INTO inbound_messages (company_id, contact_id, mailbox, uid, uidvalidity, "
                                   "from_email, subject, received_at, label, gmail_msgid, relevance) VALUES (%s, %s, 'all', 1, 1, "
                                   "'anna@acme.de', 'Re: Hi', now(), 'reply', 1, 'contact') RETURNING id", (m, ct))[0][0]
    rows["opp"] = client.post("/opportunities", json={"company_id": m, "title": "ML Engineer"}).json()["id"]
    rows["note"] = client.post("/notes", json={"entity_type": "company", "entity_id": m, "body": "Met"}).json()["id"]
    rows["task"] = client.post("/tasks", json={"title": "Call", "entity_type": "company", "entity_id": m}).json()["id"]
    client.post("/compose-list", json={"company_ids": [m]})
    return s, m, rows


def where(test_url, rows):
    q = {"contact": "SELECT company_id FROM contacts WHERE id = %s",
         "draft": "SELECT company_id FROM outbound_emails WHERE id = %s",
         "inbound": "SELECT company_id FROM inbound_messages WHERE id = %s",
         "opp": "SELECT company_id FROM opportunities WHERE id = %s",
         "note": "SELECT entity_id FROM notes WHERE id = %s",
         "task": "SELECT entity_id FROM tasks WHERE id = %s"}
    return {k: db(test_url, q[k], (v,))[0][0] for k, v in rows.items()}


def test_merge_moves_everything_and_undo_restores_it(client, test_url, two):
    s, m, rows = two
    r = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m})
    assert r.status_code == 200, r.text
    assert set(where(test_url, rows).values()) == {s}
    kept = client.get(f"/companies/{s}").json()
    assert (kept["domain"], kept["city"], kept["industry"]) == ("acme.de", "Berlin", "AI")  # blanks filled
    assert client.get(f"/companies/{m}").json()["archived_at"]
    assert [x["company_id"] for x in client.get("/compose-list").json()] == [s]
    assert db(test_url, "SELECT count(*) FROM audit_log WHERE action = 'company.merged' AND entity_id = %s", (s,)) \
        == [(1,)]
    later_note = client.post("/notes", json={"entity_type": "company", "entity_id": s, "body": "After"}).json()["id"]

    u = client.post(f"/duplicates/merges/{r.json()['id']}/undo")
    assert u.status_code == 200, u.text
    assert set(where(test_url, rows).values()) == {m}
    assert db(test_url, "SELECT entity_id FROM notes WHERE id = %s", (later_note,)) == [(s,)]  # newer record stays
    kept = client.get(f"/companies/{s}").json()
    assert (kept["domain"], kept["city"], kept["industry"]) == ("", "", "")
    assert client.get(f"/companies/{m}").json()["archived_at"] is None
    assert [x["company_id"] for x in client.get("/compose-list").json()] == [m]
    assert client.post(f"/duplicates/merges/{r.json()['id']}/undo").status_code == 409  # only once


def test_undo_keeps_fields_the_owner_changed_after_the_merge(client, test_url, two):
    s, m, _ = two
    g = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m}).json()
    db(test_url, "UPDATE companies SET city = 'Munich' WHERE id = %s", (s,))
    client.post(f"/duplicates/merges/{g['id']}/undo")
    assert client.get(f"/companies/{s}").json()["city"] == "Munich"


def test_do_not_contact_block_carries_over_and_undo_lifts_only_the_copy(client, test_url, two):
    s, m, _ = two
    blk = client.post("/suppressions", json={"kind": "company", "company_id": m, "reason": "asked not to"}).json()
    other = person(client, s, "boss@acme-holding.com")
    assert db(test_url, "SELECT is_suppressed('boss@acme-holding.com')") == [(False,)]
    g = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m}).json()
    assert g["snapshot"]["carried_block"]
    assert db(test_url, "SELECT is_suppressed('boss@acme-holding.com'), is_suppressed('anna@acme.de')") == \
        [(True, True)]
    client.post(f"/duplicates/merges/{g['id']}/undo")
    assert db(test_url, "SELECT is_suppressed('boss@acme-holding.com'), is_suppressed('anna@acme.de')") == \
        [(False, True)]
    assert db(test_url, "SELECT lifted_at IS NULL FROM suppressions WHERE id = %s", (blk["id"],)) == [(True,)]
    assert other


@pytest.mark.parametrize("status", ["approved", "queued", "sending"])
def test_merge_and_undo_refused_while_an_email_is_pending(client, test_url, two, status):
    s, m, rows = two
    set_status = ("UPDATE outbound_emails SET approved_at = now(), approved_content_hash = content_hash, "
                  "status = %s WHERE id = %s")
    db(test_url, set_status, (status, rows["draft"]))
    r = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m})
    assert r.status_code == 409 and "cancel" in r.json()["detail"]
    assert where(test_url, rows)["draft"] == m
    db(test_url, "UPDATE outbound_emails SET status = 'cancelled' WHERE id = %s", (rows["draft"],))
    g = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m}).json()
    db(test_url, "UPDATE outbound_emails SET status = 'draft', approved_at = NULL, approved_content_hash = NULL "
                 "WHERE id = %s", (rows["draft"],))
    db(test_url, set_status, (status, rows["draft"]))
    assert client.post(f"/duplicates/merges/{g['id']}/undo").status_code == 409


def test_undo_refused_if_the_domain_was_taken_meanwhile(client, test_url):
    s, m = co(client, "Acme", "acme-holding.com"), co(client, "Acme GmbH", "acme.de")
    g = client.post("/duplicates/merge", json={"survivor_id": s, "merged_id": m}).json()
    co(client, "Acme again", "acme.de")
    r = client.post(f"/duplicates/merges/{g['id']}/undo")
    assert r.status_code == 409 and "domain" in r.json()["detail"]
    assert client.get(f"/companies/{m}").json()["archived_at"]  # nothing half-undone


def test_later_merge_must_be_undone_first(client):
    a, b, c = co(client, "A1"), co(client, "A2"), co(client, "A3")
    g1 = client.post("/duplicates/merge", json={"survivor_id": a, "merged_id": b}).json()
    g2 = client.post("/duplicates/merge", json={"survivor_id": a, "merged_id": c}).json()
    r = client.post(f"/duplicates/merges/{g1['id']}/undo")
    assert r.status_code == 409 and f"#{g2['id']}" in r.json()["detail"]
    assert client.post(f"/duplicates/merges/{g2['id']}/undo").status_code == 200
    assert client.post(f"/duplicates/merges/{g1['id']}/undo").status_code == 200


def test_bad_merges_are_rejected(client):
    a, b = co(client, "A1"), co(client, "A2")
    assert client.post("/duplicates/merge", json={"survivor_id": a, "merged_id": a}).status_code == 422
    assert client.post("/duplicates/merge", json={"survivor_id": a, "merged_id": 999999}).status_code == 404
    client.post(f"/companies/{b}/archive")
    assert client.post("/duplicates/merge", json={"survivor_id": a, "merged_id": b}).status_code == 409
