"""M19: opportunity pipeline. Done when: reply -> opportunity -> all stages, with history."""
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from psycopg.rows import dict_row

from app import inbox_sync, opportunities
from app.main import app
from fakes import db


@pytest.fixture
def reply(sent, gmail, test_url):
    gmail.inbound("Anna Schmidt <jobs@acme.de>", subject="Re: Hello Acme", in_reply_to=sent["acme"][1],
                  body="We'd like to talk about the ML Engineer role.")
    inbox_sync.sync_once()
    return db(test_url, "SELECT id, company_id, contact_id FROM inbound_messages WHERE label = 'reply'")[0]


def create(client, reply, title="ML Engineer"):
    r = client.post("/opportunities", json={"inbound_message_id": reply[0], "title": title})
    assert r.status_code == 201, r.text
    return r.json()


def ai(test_url, message_id, label):
    db(test_url, "INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence) "
                 "VALUES (%s, 'ok', 'fake', 1, %s, 'q') ON CONFLICT (inbound_message_id) DO UPDATE SET label = %s",
       (message_id, label, label))


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/opportunities"), ("post", "/opportunities"), ("get", "/opportunities/1"),
                         ("post", "/opportunities/1/stage"), ("put", "/opportunities/1")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_reply_to_opportunity_through_every_stage_with_history(client, reply, test_url):
    """The done-criterion in one walk: created from a reply, then every stage, all recorded."""
    o = create(client, reply)
    assert (o["stage"], o["company_id"], o["contact_id"], o["inbound_message_id"]) == ("new", reply[1], reply[2], reply[0])
    assert o["source_link"].endswith(f"#in-{reply[0]}")
    path = ["applied", "screening", "interviewing", "offer", "hired"]
    for stage in path:
        r = client.post(f"/opportunities/{o['id']}/stage", json={"stage": stage, "reason": f"to {stage}"}).json()
        assert r["stage"] == stage
    other = client.post("/opportunities", json={"company_id": reply[1], "title": "Data Engineer"}).json()
    for stage in ("rejected", "withdrawn"):
        client.post(f"/opportunities/{other['id']}/stage", json={"stage": stage})
    history = client.get(f"/opportunities/{o['id']}").json()["history"]
    assert [(h["from_stage"], h["to_stage"]) for h in history] == [
        (None, "new"), ("new", "applied"), ("applied", "screening"), ("screening", "interviewing"),
        ("interviewing", "offer"), ("offer", "hired")]
    assert history[0]["reason"] == "created from a reply" and history[3]["reason"] == "to interviewing"
    assert {h["actor"] for h in history} == {"owner"}
    covered = {h["to_stage"] for oid in (o["id"], other["id"])
               for h in client.get(f"/opportunities/{oid}").json()["history"]}
    assert covered == set(opportunities.STAGES)  # all 8 stages reached, each with history


def test_ai_labels_never_move_a_stage_only_suggest(client, reply, test_url):
    o = create(client, reply)
    ai(test_url, reply[0], "offer")
    got = client.get(f"/opportunities/{o['id']}").json()
    assert got["stage"] == "new"  # unchanged
    assert got["suggestion"] == {"stage": "offer", "ai_label": "offer", "evidence": "q", "inbound_message_id": reply[0]}
    client.post(f"/opportunities/{o['id']}/stage", json={"stage": "offer", "reason": "accepted AI suggestion"})
    assert client.get(f"/opportunities/{o['id']}").json()["suggestion"] is None  # nothing left to suggest
    ai(test_url, reply[0], "other")
    assert client.get(f"/opportunities/{o['id']}").json()["suggestion"] is None  # no mapping for 'other'


def test_facts_move_forward_only(client, reply, test_url):
    o = create(client, reply)
    with psycopg.connect(test_url, row_factory=dict_row) as conn:
        assert opportunities.record_fact(conn, o["id"], "interviewing", "interview scheduled") is True
        assert opportunities.record_fact(conn, o["id"], "interviewing", "again") is False  # already there
        conn.execute("UPDATE opportunities SET stage = 'offer' WHERE id = %s", (o["id"],))
        assert opportunities.record_fact(conn, o["id"], "interviewing", "late interview") is False  # never backwards
        conn.execute("UPDATE opportunities SET stage = 'rejected' WHERE id = %s", (o["id"],))
        assert opportunities.record_fact(conn, o["id"], "interviewing", "x") is False  # never out of a final stage
    history = client.get(f"/opportunities/{o['id']}").json()["history"]
    assert history[1]["reason"] == "interview scheduled" and history[1]["actor"] == "system"


def test_creation_rules(client, reply, test_url, sent):
    create(client, reply)
    assert client.post("/opportunities", json={"inbound_message_id": reply[0], "title": "x"}).status_code == 409
    auto = db(test_url, "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label, company_id) "
                        "VALUES ('ooo1', 'all', 'a@acme.de', 'contact', 'auto_reply', %s) RETURNING id", (reply[1],))[0][0]
    assert client.post("/opportunities", json={"inbound_message_id": auto, "title": "x"}).status_code == 409
    for body, status in [({"title": "x"}, 422), ({"title": "x", "inbound_message_id": 1, "company_id": 1}, 422),
                         ({"title": "", "company_id": reply[1]}, 422), ({"title": "x", "company_id": 999999}, 404),
                         ({"title": "x", "inbound_message_id": 999999}, 404),
                         ({"title": "x", "company_id": reply[1], "contact_id": 999999}, 404)]:
        assert client.post("/opportunities", json=body).status_code == status, body
    assert client.post("/opportunities/1/stage", json={"stage": "won"}).status_code == 422
    assert client.get("/opportunities/999999").status_code == 404


def test_listing_edit_and_counts(client, reply, test_url):
    o = create(client, reply)
    client.post("/opportunities", json={"company_id": reply[1], "title": "Backend role"})
    client.post(f"/opportunities/{o['id']}/stage", json={"stage": "screening"})
    listed = client.get("/opportunities").json()
    assert listed["counts"] == {"new": 1, "screening": 1} and listed["stages"][0] == "new"
    assert [x["title"] for x in client.get("/opportunities", params={"stage": "screening"}).json()["opportunities"]] == [
        "ML Engineer"]
    edited = client.put(f"/opportunities/{o['id']}", json={"title": "Senior ML Engineer", "contact_id": None}).json()
    assert (edited["title"], edited["contact_id"]) == ("Senior ML Engineer", None)
    dash = client.get("/dashboard").json()["kpis"]["opportunities"]
    assert dash == {"available": True, "open": 2, "by_stage": {"new": 1, "screening": 1}}
    ov = client.get(f"/companies/{reply[1]}/overview").json()["opportunities"]
    assert {x["title"] for x in ov} == {"Senior ML Engineer", "Backend role"} and ov[0]["link"].startswith("/opportunities/")


def test_notes_and_tasks_on_opportunities(client, reply):
    o = create(client, reply)
    n = client.post("/notes", json={"entity_type": "opportunity", "entity_id": o["id"], "body": "Salary 70k"})
    assert n.status_code == 201
    t = client.post("/tasks", json={"title": "Prepare case study", "due_date": "2026-10-02",
                                    "entity_type": "opportunity", "entity_id": o["id"]}).json()
    assert (t["entity_name"], t["entity_link"]) == ("ML Engineer", f"/opportunities/{o['id']}")


def test_history_is_append_only(client, reply, test_url):
    o = create(client, reply)
    with psycopg.connect(test_url) as conn:
        for sql in ["UPDATE opportunity_stage_history SET reason = 'x' WHERE opportunity_id = %s",
                    "DELETE FROM opportunity_stage_history WHERE opportunity_id = %s"]:
            with pytest.raises(errors.RaiseException), conn.transaction():
                conn.execute(sql, (o["id"],))
