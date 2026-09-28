"""M23: company / contact detail. Done when: every related record is reachable from the page."""
import psycopg
from fastapi.testclient import TestClient

from app import inbox_sync
from app.main import app
from fakes import db


def build(sent, client, gmail, test_url):
    """Acme with every kind of related record. Returns {kind: set(ids)} that must all be reachable."""
    acme_co, acme_email = sent["acme"][3], sent["acme"][0]
    anna = db(test_url, "SELECT id FROM contacts WHERE company_id = %s", (acme_co,))[0][0]
    ben = client.post(f"/companies/{acme_co}/contacts", json={"name": "Ben Weber", "email": "ben@acme.de",
                                                              "role": "CTO"}).json()["id"]
    gmail.inbound("Anna Schmidt <jobs@acme.de>", subject="Re: Hello Acme", in_reply_to=sent["acme"][1])
    gmail.inbound("Ben Weber <ben@acme.de>", subject="Hi from Ben")
    inbox_sync.sync_once()
    inbound = [r[0] for r in db(test_url, "SELECT id FROM inbound_messages WHERE company_id = %s", (acme_co,))]
    db(test_url, "INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence, "
                 "summary) VALUES (%s, 'ok', 'fake', 1, 'interested', 'q', 'Anna is interested.')", (inbound[0],))
    draft = db(test_url, "INSERT INTO outbound_emails (to_email, subject, body, company_id, contact_id) "
                         "VALUES ('ben@acme.de', 'Draft to Ben', 'b', %s, %s) RETURNING id", (acme_co, ben))[0][0]
    notes = [client.post("/notes", json={"entity_type": t, "entity_id": i, "body": f"note on {t}"}).json()["id"]
             for t, i in (("company", acme_co), ("contact", anna), ("contact", ben))]
    tasks = [client.post("/tasks", json={"title": f"task {t}", "due_date": "2026-10-01", "entity_type": t,
                                         "entity_id": i}).json()["id"] for t, i in (("company", acme_co), ("contact", ben))]
    block = client.post("/suppressions", json={"kind": "email", "value": "ben@acme.de", "reason": "asked"}).json()["id"]
    return {"company": acme_co, "contacts": {anna, ben}, "outbound": {acme_email, draft}, "inbound": set(inbound),
            "notes": set(notes), "tasks": set(tasks), "block": block, "anna": anna, "ben": ben}


def test_requires_login():
    c = TestClient(app)
    assert c.get("/companies/1/overview").status_code == 401 and c.get("/contacts/1").status_code == 401


def test_every_related_record_is_reachable(sent, client, gmail, test_url):
    w = build(sent, client, gmail, test_url)
    co = w["company"]
    company = client.get(f"/companies/{co}").json()
    threads = client.get(f"/companies/{co}/emails").json()
    contacts = {cid: client.get(f"/contacts/{cid}").json() for cid in w["contacts"]}
    notes = client.get("/notes", params=[("entity_type", "company"), ("entity_id", co)]).json() + \
        [n for c in contacts.values() for n in c["notes"]]
    tasks = client.get("/tasks", params={"entity_type": "company", "entity_id": co, "today": "2026-09-28"}).json()
    reachable = {
        "contacts": {c["id"] for c in company["contacts"]},
        "outbound": {e["id"] for t in threads for e in t["emails"]} | {e["id"] for c in contacts.values() for e in c["emails"]},
        "inbound": {m["id"] for t in threads for m in t["inbound"]} | {m["id"] for c in contacts.values() for m in c["replies"]},
        "notes": {n["id"] for n in notes},
        "tasks": {t["id"] for g in ("overdue", "due_today", "upcoming", "no_date") for t in tasks[g]}
        | {t["id"] for c in contacts.values() for t in c["tasks"]},
    }
    for kind in reachable:
        assert w[kind] <= reachable[kind], f"unreachable {kind}: {w[kind] - reachable[kind]}"
    # the block and every kind of event appear on a timeline
    ben_timeline = contacts[w["ben"]]["timeline"]
    assert any(e["entity_type"] == "suppression" and e["entity_id"] == w["block"] for e in ben_timeline)
    timeline = client.get(f"/companies/{co}/activity").json() + [e for c in contacts.values() for e in c["timeline"]]
    actions = {e["action"] for e in timeline}
    assert {"contact.created", "note.created", "task.created", "outbound_email.sent", "inbound.labeled",
            "suppression.added"} <= actions


def test_every_link_opens(sent, client, gmail, test_url):
    w = build(sent, client, gmail, test_url)
    for cid in w["contacts"]:
        c = client.get(f"/contacts/{cid}").json()
        assert c["company"]["link"] == f"/companies/{w['company']}"
        for e in c["emails"]:
            assert e["link"] == f"/outbox/{e['id']}"  # the UI page for it is backed by this API:
            assert client.get(f"/outbound-emails/{e['id']}").status_code == 200
        for m in c["replies"]:
            key, anchor = m["link"].removeprefix("/threads/").split("#")
            t = client.get(f"/threads/{key}").json()
            assert anchor == f"in-{m['id']}" and m["id"] in {x["id"] for x in t["inbound"]}


def test_overview_header(sent, client, gmail, test_url):
    w = build(sent, client, gmail, test_url)
    o = client.get(f"/companies/{w['company']}/overview").json()
    assert (o["contacts"], o["sent"], o["emails"], o["replies"], o["open_tasks"]) == (2, 1, 1, 2, 2)
    assert o["last_emailed_at"] and o["blocked"] is False
    assert o["last_reply"]["link"].startswith("/threads/")
    assert o["opportunity"] == {"available": False, "after": "M19"}
    client.post("/suppressions", json={"kind": "company", "company_id": w["company"], "reason": "x"})
    assert client.get(f"/companies/{w['company']}/overview").json()["blocked"] is True
    assert client.get("/companies/999999/overview").status_code == 404


def test_contact_page(sent, client, gmail, test_url):
    w = build(sent, client, gmail, test_url)
    anna, ben = client.get(f"/contacts/{w['anna']}").json(), client.get(f"/contacts/{w['ben']}").json()
    assert (anna["suppressed"], ben["suppressed"]) == (False, True)
    assert [e["subject"] for e in anna["emails"]] == ["Hello Acme"] and anna["replies"][0]["ai_label"] == "interested"
    assert [e["subject"] for e in ben["emails"]] == ["Draft to Ben"] and [m["subject"] for m in ben["replies"]] == ["Hi from Ben"]
    assert [n["body"] for n in ben["notes"]] == ["note on contact"] and [t["title"] for t in ben["tasks"]] == ["task contact"]
    assert client.get("/contacts/999999").status_code == 404


def test_contact_without_email_does_not_match_other_records(sent, client, gmail, test_url):
    co = sent["acme"][3]
    nameless = client.post(f"/companies/{co}/contacts", json={"name": "Phone only"}).json()["id"]
    db(test_url, "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label) "
                 "VALUES ('z1', 'all', '', 'contact', 'unrelated')")
    c = client.get(f"/contacts/{nameless}").json()
    assert c["emails"] == [] and c["replies"] == [] and all(e["entity_id"] == nameless for e in c["timeline"])
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT count(*) FROM outbound_emails").fetchone()[0] >= 2
