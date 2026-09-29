"""M20: interview management. Done when: time zones are correct and reminders fire."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app import interviews
from app.main import app
from fakes import db

NY = "America/New_York"


@pytest.fixture
def opp(client):
    cid = client.post("/companies", json={"name": "Acme", "domain": "acme.de"}).json()["id"]
    return client.post("/opportunities", json={"company_id": cid, "title": "ML Engineer"}).json()


def add(client, opp, local="2026-10-06T10:00", zone="Europe/Berlin", **kw):
    return client.post(f"/opportunities/{opp['id']}/interviews",
                       json={"title": "First call", "local_start": local, "time_zone": zone, **kw})


def notes(test_url):
    return db(test_url, "SELECT source_id, title, link FROM notifications WHERE kind = 'interview' ORDER BY id")


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/interviews"), ("get", "/interviews/1"), ("put", "/interviews/1"),
                         ("post", "/interviews/1/status"), ("get", "/interviews/1/calendar.ics"),
                         ("get", "/opportunities/1/interviews"), ("post", "/opportunities/1/interviews"),
                         ("get", "/opportunities/1/interview-suggestion"), ("get", "/interview-zones")]:
        assert getattr(c, method)(path).status_code == 401, path


# ---------- time zones ----------

@pytest.mark.parametrize("local,zone,utc", [
    ("2026-10-06T10:00", "Europe/Berlin", "2026-10-06T08:00:00+00:00"),   # summer time, UTC+2
    ("2026-11-06T10:00", "Europe/Berlin", "2026-11-06T09:00:00+00:00"),   # winter time, UTC+1
    ("2026-10-06T10:00", NY, "2026-10-06T14:00:00+00:00"),                # EDT, UTC-4
    ("2026-11-06T10:00", NY, "2026-11-06T15:00:00+00:00"),                # EST, UTC-5
    ("2026-10-06T10:00", "Asia/Kolkata", "2026-10-06T04:30:00+00:00"),    # half-hour offset
    ("2026-10-06T10:00", "UTC", "2026-10-06T10:00:00+00:00"),
])
def test_local_time_is_stored_as_the_exact_instant(client, opp, local, zone, utc):
    r = add(client, opp, local, zone)
    assert r.status_code == 201, r.text
    i = r.json()
    assert datetime.fromisoformat(i["starts_at"]) == datetime.fromisoformat(utc)
    assert i["local_start"] == local and i["time_zone"] == zone and zone in i["local_label"]


@pytest.mark.parametrize("local,zone,why", [
    ("2026-03-29T02:30", "Europe/Berlin", "does not exist"),   # clocks jump 02:00 -> 03:00
    ("2026-10-25T02:30", "Europe/Berlin", "happens twice"),    # 02:00-03:00 repeats
    ("2026-03-08T02:30", NY, "does not exist"),
    ("2026-11-01T01:30", NY, "happens twice"),
    ("2026-10-06T10:00", "Mars/Olympus", "Unknown time zone"),
    ("2026-10-06T10:00", "CEST", "Unknown time zone"),         # abbreviations are ambiguous: IANA names only
])
def test_impossible_or_ambiguous_times_are_refused(client, opp, local, zone, why):
    r = add(client, opp, local, zone)
    assert r.status_code == 422 and why in r.json()["detail"]
    assert db_count(client) == 0


def db_count(client):
    return len(client.get("/interviews", params={"when": "all"}).json())


def test_times_just_around_a_dst_change_are_fine(client, opp):
    before = add(client, opp, "2026-03-29T01:59").json()
    after = add(client, opp, "2026-03-29T03:00").json()
    assert (datetime.fromisoformat(after["starts_at"]) - datetime.fromisoformat(before["starts_at"])).seconds == 60


# ---------- facts and data ----------

def test_recording_an_interview_moves_the_opportunity_forward_only(client, opp, test_url):
    add(client, opp)
    o = client.get(f"/opportunities/{opp['id']}").json()
    assert o["stage"] == "interviewing"
    assert o["history"][-1]["reason"] == "interview recorded: First call"
    client.post(f"/opportunities/{opp['id']}/stage", json={"stage": "offer"})
    add(client, opp, "2026-10-07T10:00")
    assert client.get(f"/opportunities/{opp['id']}").json()["stage"] == "offer"


def test_links_must_be_web_links(client, opp):
    assert add(client, opp, location="javascript:alert(1)").status_code == 422
    assert add(client, opp, location="ftp://files.example/x").status_code == 422
    assert add(client, opp, location="https://meet.example/abc").status_code == 201
    assert add(client, opp, kind="onsite", location="Torstraße 1, Berlin").status_code == 201
    assert add(client, opp, kind="onsite", location="Room: 3").status_code == 201
    assert add(client, opp, location=" DATA:text/html,x").status_code == 422


def test_edit_status_listing_and_pages(client, opp, test_url):
    future = add(client, opp, "2030-01-10T10:00").json()
    past = add(client, opp, "2020-01-10T10:00").json()
    upcoming = client.get("/interviews").json()
    assert [i["id"] for i in upcoming] == [future["id"]] and upcoming[0]["upcoming"]
    assert [i["id"] for i in client.get("/interviews", params={"when": "past"}).json()] == [past["id"]]
    r = client.put(f"/interviews/{future['id']}", json={"title": "Tech interview", "local_start": "2030-01-11T15:00",
                                                        "time_zone": NY, "duration_minutes": 90})
    assert r.json()["sequence"] == 1 and r.json()["local_start"] == "2030-01-11T15:00"
    done = client.post(f"/interviews/{future['id']}/status", json={"status": "done", "outcome": "went well"}).json()
    assert done["status"] == "done" and done["outcome"] == "went well" and not done["upcoming"]
    actions = [a for (a,) in db(test_url, "SELECT action FROM audit_log WHERE entity_type = 'interview' "
                                          "AND entity_id = %s ORDER BY id", (future["id"],))]
    assert actions == ["interview.created", "interview.updated", "interview.done"]
    overview = client.get(f"/companies/{opp['company_id']}/overview").json()
    assert {i["id"] for i in overview["interviews"]} == {future["id"], past["id"]}
    assert client.post("/notes", json={"entity_type": "interview", "entity_id": past["id"], "body": "Prep: STAR"}).status_code == 201
    t = client.post("/tasks", json={"title": "Send thank-you", "entity_type": "interview", "entity_id": past["id"]}).json()
    assert client.get("/tasks").json() and t["entity_type"] == "interview"


def test_dashboard_tile(client, opp):
    assert client.get("/dashboard").json()["kpis"]["interviews"] == {"available": True, "upcoming": 0, "next": None}
    add(client, opp, "2030-01-10T10:00")
    add(client, opp, "2030-02-10T10:00")
    tile = client.get("/dashboard").json()["kpis"]["interviews"]
    assert tile["upcoming"] == 2 and tile["next"]["title"] == "First call" and tile["next"]["company_name"] == "Acme"


# ---------- reminders ----------

def at(test_url, iid, offset):
    db(test_url, "UPDATE interviews SET starts_at = now() + %s::interval WHERE id = %s", (offset, iid))


def test_reminders_fire_24h_and_1h_before_exactly_once(client, opp, test_url):
    iid = add(client, opp, "2030-01-10T10:00").json()["id"]
    at(test_url, iid, "30 hours")
    assert interviews.reminders_tick()["created"] == 0
    at(test_url, iid, "23 hours")
    for _ in range(3):
        interviews.reminders_tick()
    n = notes(test_url)
    assert len(n) == 1 and n[0][1] == "Interview tomorrow: First call" and n[0][2].endswith(f"#interview-{iid}")
    at(test_url, iid, "50 minutes")
    for _ in range(3):
        interviews.reminders_tick()
    assert [t for _, t, _ in notes(test_url)] == ["Interview tomorrow: First call", "Interview in 1 hour: First call"]


def test_short_notice_gets_only_the_1h_reminder_and_past_or_cancelled_none(client, opp, test_url):
    soon = add(client, opp, "2030-01-10T10:00").json()["id"]
    at(test_url, soon, "30 minutes")
    interviews.reminders_tick()
    assert [t for _, t, _ in notes(test_url)] == ["Interview in 1 hour: First call"]
    gone = add(client, opp, "2030-01-10T11:00").json()["id"]
    at(test_url, gone, "-10 minutes")
    off = add(client, opp, "2030-01-10T12:00").json()["id"]
    at(test_url, off, "2 hours")
    client.post(f"/interviews/{off}/status", json={"status": "cancelled"})
    interviews.reminders_tick()
    assert len(notes(test_url)) == 1


def test_missed_reminder_catches_up_and_rescheduling_reminds_again(client, opp, test_url):
    iid = add(client, opp, "2030-01-10T10:00").json()["id"]
    at(test_url, iid, "5 hours")  # the app was off when the 24 h mark passed
    interviews.reminders_tick()
    assert [t for _, t, _ in notes(test_url)] == ["Interview tomorrow: First call"]
    at(test_url, iid, "20 hours")  # moved to another time: a fresh reminder
    interviews.reminders_tick()
    assert len(notes(test_url)) == 2


def test_reminders_respect_the_settings_switch(client, opp, test_url):
    iid = add(client, opp, "2030-01-10T10:00").json()["id"]
    at(test_url, iid, "2 hours")
    db(test_url, "UPDATE app_settings SET notify_kinds = ARRAY['reply']")
    assert interviews.reminders_tick()["created"] == 0 and notes(test_url) == []


# ---------- .ics ----------

def test_ics_export(client, opp):
    i = add(client, opp, "2026-10-06T10:00", "Europe/Berlin", duration_minutes=45, location="https://meet.example/x",
            interviewers="Ben Weber, CTO; Anna", notes="Bring portfolio.\nAsk about team size").json()
    r = client.get(f"/interviews/{i['id']}/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    text = r.text
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert f"UID:interview-{i['id']}@job-outreach-crm.local" in unfolded
    assert "DTSTART:20261006T080000Z" in unfolded and "DTEND:20261006T084500Z" in unfolded
    assert "SEQUENCE:0" in unfolded and "STATUS:CONFIRMED" in unfolded
    assert "Ben Weber\\, CTO\\; Anna" in unfolded and "Bring portfolio.\\nAsk about team size" in unfolded
    client.post(f"/interviews/{i['id']}/status", json={"status": "cancelled"})
    again = client.get(f"/interviews/{i['id']}/calendar.ics").text.replace("\r\n ", "")
    assert f"UID:interview-{i['id']}@" in again and "SEQUENCE:1" in again and "STATUS:CANCELLED" in again


def test_long_lines_fold_without_splitting_characters():
    line = "SUMMARY:" + "Vorstellungsgespräch über Größe " * 5
    folded = interviews.fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


# ---------- AI prefill, never acting ----------

def test_ai_found_interview_date_only_prefills(client, test_url):
    cid = client.post("/companies", json={"name": "Beta", "domain": "beta.io"}).json()["id"]
    mid = db(test_url, "INSERT INTO inbound_messages (gmail_msgid, mailbox, from_email, relevance, label, company_id, "
                       "received_at) VALUES ('g1', 'all', 'hr@beta.io', 'contact', 'reply', %s, now()) RETURNING id",
             (cid,))[0][0]
    extracted = {"dates": [{"text": "Tuesday 6 October at 10:00", "iso": "2026-10-06T10:00", "purpose": "interview",
                            "evidence": "Could you do Tuesday 6 October at 10:00?"}]}
    db(test_url, "INSERT INTO ai_analyses (inbound_message_id, status, model, prompt_version, label, label_evidence, "
                 "extracted) VALUES (%s, 'ok', 'fake', 1, 'interview_request', 'q', %s)", (mid, Jsonb(extracted)))
    o = client.post("/opportunities", json={"inbound_message_id": mid, "title": "Data Scientist"}).json()
    s = client.get(f"/opportunities/{o['id']}/interview-suggestion").json()
    assert s["local_start"] == "2026-10-06T10:00" and s["evidence"].startswith("Could you do")
    assert client.get(f"/opportunities/{o['id']}/interviews").json() == []  # nothing created by itself


def test_interviews_never_send_email(client, opp, test_url):
    iid = add(client, opp, "2030-01-10T10:00", interviewers="ben@acme.de").json()["id"]
    at(test_url, iid, "30 minutes")
    interviews.reminders_tick()
    client.post(f"/interviews/{iid}/status", json={"status": "cancelled"})
    assert db(test_url, "SELECT count(*) FROM outbound_emails") == [(0,)]
    assert datetime.now(timezone.utc)  # reminders are in-app notifications only
