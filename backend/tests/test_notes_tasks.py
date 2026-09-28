"""M21: notes & tasks. Done when: notes/tasks appear on every entity page and the due list is correct."""
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def ents(client):
    co = client.post("/companies", json={"name": "Acme", "domain": "acme.de"}).json()["id"]
    ct = client.post(f"/companies/{co}/contacts", json={"name": "Anna", "email": "anna@acme.de"}).json()["id"]
    tp = client.post("/templates", json={"name": "Intro", "subject": "Hi", "body": "Hello"}).json()["id"]
    return {"company": co, "contact": ct, "template": tp}


def task(client, title, due=None, **link):
    r = client.post("/tasks", json={"title": title, **({"due_date": due} if due else {}), **link})
    assert r.status_code == 201, r.text
    return r.json()


def titles(group):
    return [t["title"] for t in group]


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/notes?entity_type=company&entity_id=1"), ("post", "/notes"), ("put", "/notes/1"),
                         ("delete", "/notes/1"), ("get", "/tasks"), ("get", "/tasks/counts"), ("post", "/tasks"),
                         ("put", "/tasks/1"), ("post", "/tasks/1/done"), ("post", "/tasks/1/reopen"),
                         ("delete", "/tasks/1")]:
        assert getattr(c, method)(path).status_code == 401, path


# ---------- notes ----------

@pytest.mark.parametrize("etype", ["company", "contact", "template"])
def test_notes_on_every_entity(client, ents, etype):
    eid = ents[etype]
    n = client.post("/notes", json={"entity_type": etype, "entity_id": eid, "body": "  Met at meetup  "}).json()
    assert n["body"] == "Met at meetup" and n["edited_at"] is None
    edited = client.put(f"/notes/{n['id']}", json={"body": "Met at PyData"}).json()
    assert edited["body"] == "Met at PyData" and edited["edited_at"]
    assert [x["body"] for x in client.get("/notes", params={"entity_type": etype, "entity_id": eid}).json()] == ["Met at PyData"]
    client.delete(f"/notes/{n['id']}")
    assert client.get("/notes", params={"entity_type": etype, "entity_id": eid}).json() == []
    assert client.put(f"/notes/{n['id']}", json={"body": "x"}).status_code == 404  # deleted notes are gone for good


def test_notes_for_several_contacts_at_once(client, ents):
    other = client.post(f"/companies/{ents['company']}/contacts", json={"email": "jobs@acme.de"}).json()["id"]
    client.post("/notes", json={"entity_type": "contact", "entity_id": ents["contact"], "body": "a"})
    client.post("/notes", json={"entity_type": "contact", "entity_id": other, "body": "b"})
    got = client.get("/notes", params=[("entity_type", "contact"), ("entity_id", ents["contact"]), ("entity_id", other)]).json()
    assert sorted(x["body"] for x in got) == ["a", "b"]


@pytest.mark.parametrize("body,status", [
    ({"entity_type": "company", "entity_id": 999999, "body": "x"}, 404),
    ({"entity_type": "invoice", "entity_id": 1, "body": "x"}, 422),
    ({"entity_type": "company", "entity_id": 1, "body": "   "}, 422),
])
def test_note_validation(client, body, status):
    assert client.post("/notes", json=body).status_code == status


def test_note_events_show_on_company_timeline(client, ents):
    client.post("/notes", json={"entity_type": "company", "entity_id": ents["company"], "body": "x"})
    client.post("/notes", json={"entity_type": "contact", "entity_id": ents["contact"], "body": "y"})
    actions = [e["action"] for e in client.get(f"/companies/{ents['company']}/activity").json()]
    assert actions.count("note.created") == 2


# ---------- tasks: the due list ----------

def test_due_list_groups_relative_to_owner_today(client):
    task(client, "overdue-2", "2026-09-25")
    task(client, "overdue-1", "2026-09-26")
    task(client, "today", "2026-09-27")
    task(client, "tomorrow", "2026-09-28")
    task(client, "next month", "2026-10-15")
    task(client, "someday")
    r = client.get("/tasks", params={"today": "2026-09-27"}).json()
    assert r["today"] == "2026-09-27"
    assert titles(r["overdue"]) == ["overdue-2", "overdue-1"]  # oldest first
    assert titles(r["due_today"]) == ["today"]
    assert titles(r["upcoming"]) == ["tomorrow", "next month"]
    assert titles(r["no_date"]) == ["someday"]
    assert client.get("/tasks/counts", params={"today": "2026-09-27"}).json() == {"overdue": 2, "due_today": 1}


@pytest.mark.parametrize("today,expected", [
    ("2026-09-30", {"overdue": [], "due_today": ["end of month"], "upcoming": ["new year"]}),
    ("2026-10-01", {"overdue": ["end of month"], "due_today": [], "upcoming": ["new year"]}),
    ("2027-01-01", {"overdue": ["end of month"], "due_today": ["new year"], "upcoming": []}),
])
def test_due_list_across_month_and_year_boundaries(client, today, expected):
    task(client, "end of month", "2026-09-30")
    task(client, "new year", "2027-01-01")
    r = client.get("/tasks", params={"today": today}).json()
    assert {k: titles(r[k]) for k in expected} == expected


def test_same_tasks_different_timezones(client):
    """The owner's browser decides 'today': it can be the 28th in Karachi while still the 27th in UTC."""
    task(client, "call back", "2026-09-28")
    assert titles(client.get("/tasks", params={"today": "2026-09-28"}).json()["due_today"]) == ["call back"]
    assert titles(client.get("/tasks", params={"today": "2026-09-27"}).json()["upcoming"]) == ["call back"]


def test_done_reopen_edit_delete(client):
    t = task(client, "follow up", "2026-09-20")
    done = client.post(f"/tasks/{t['id']}/done").json()
    assert done["done_at"]
    r = client.get("/tasks", params={"today": "2026-09-27"}).json()
    assert titles(r["overdue"]) == [] and titles(r["done"]) == ["follow up"]
    client.post(f"/tasks/{t['id']}/reopen")
    assert titles(client.get("/tasks", params={"today": "2026-09-27"}).json()["overdue"]) == ["follow up"]
    edited = client.put(f"/tasks/{t['id']}", json={"title": "follow up again", "due_date": "2026-10-01"}).json()
    assert (edited["title"], edited["due_date"]) == ("follow up again", "2026-10-01")
    client.delete(f"/tasks/{t['id']}")
    r = client.get("/tasks", params={"today": "2026-09-27"}).json()
    assert all(titles(r[k]) == [] for k in ("overdue", "due_today", "upcoming", "no_date", "done"))
    assert client.post(f"/tasks/{t['id']}/done").status_code == 404


@pytest.mark.parametrize("etype", ["company", "contact", "template"])
def test_tasks_on_every_entity_with_label_and_link(client, ents, etype):
    task(client, f"{etype} task", "2026-10-01", entity_type=etype, entity_id=ents[etype])
    task(client, "unrelated", "2026-10-01")
    r = client.get("/tasks", params={"today": "2026-09-27", "entity_type": etype, "entity_id": ents[etype]}).json()
    assert titles(r["upcoming"]) == [f"{etype} task"]
    t = r["upcoming"][0]
    expected = {"company": ("Acme", f"/companies/{ents['company']}"),
                "contact": ("Anna", f"/companies/{ents['company']}"),
                "template": ("Intro", f"/templates/{ents['template']}")}[etype]
    assert (t["entity_name"], t["entity_link"]) == expected


@pytest.mark.parametrize("body,status", [
    ({"title": ""}, 422),
    ({"title": "x", "due_date": "2026-13-01"}, 422),
    ({"title": "x", "entity_type": "company"}, 422),
    ({"title": "x", "entity_id": 1}, 422),
    ({"title": "x", "entity_type": "company", "entity_id": 999999}, 404),
])
def test_task_validation(client, body, status):
    assert client.post("/tasks", json=body).status_code == status
    assert client.get("/tasks", params={"today": "not-a-date"}).status_code == 422


def test_tasks_never_create_or_send_emails(client, ents, test_url):
    t = task(client, "email them again", "2026-09-01", entity_type="contact", entity_id=ents["contact"])
    client.post(f"/tasks/{t['id']}/done")
    client.post(f"/tasks/{t['id']}/reopen")
    client.get("/tasks", params={"today": "2026-09-27"})
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT count(*) FROM outbound_emails").fetchone()[0] == 0


def test_task_audit_trail(client, ents, test_url):
    t = task(client, "x", "2026-10-01", entity_type="company", entity_id=ents["company"])
    client.post(f"/tasks/{t['id']}/done")
    client.post(f"/tasks/{t['id']}/reopen")
    client.put(f"/tasks/{t['id']}", json={"title": "y"})
    client.delete(f"/tasks/{t['id']}")
    solo = task(client, "standalone")
    with psycopg.connect(test_url) as conn:
        linked = [a for (a,) in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'task.%%' AND entity_type = "
                                             "'company' AND entity_id = %s ORDER BY id", (ents["company"],))]
        standalone = conn.execute("SELECT count(*) FROM audit_log WHERE entity_type = 'task' AND entity_id = %s",
                                  (solo["id"],)).fetchone()[0]
    assert linked == ["task.created", "task.completed", "task.reopened", "task.edited", "task.deleted"]
    assert standalone == 1
