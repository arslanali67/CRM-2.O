"""M17: notifications. Done when: exactly one notification per event, deep-linked."""
import json

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from psycopg.rows import dict_row

from app import ai_analysis, inbox_sync, sender, settings
from app.main import app
from fakes import age_last_send, db, enable


def notes(test_url, kind=None):
    return db(test_url, "SELECT kind, source_id, priority, title, body, link, read_at FROM notifications "
                        "WHERE %s::text IS NULL OR kind = %s ORDER BY id", (kind, kind))


def reply(gmail, sent, **kw):
    return gmail.inbound(kw.pop("frm", "Anna Schmidt <jobs@acme.de>"), in_reply_to=sent["acme"][1],
                         subject=kw.pop("subject", "Re: Hello Acme"), **kw)


def fake_ai(monkeypatch, answer):
    def post(url, headers, payload):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}
    monkeypatch.setattr(ai_analysis, "post_json", post)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-real")


# ---------- inbound events ----------

def test_reply_gives_exactly_one_deep_linked_notification(sent, gmail, test_url):
    reply(gmail, sent, body="Could we talk Tuesday?")
    for _ in range(3):  # repeated syncs, a daily re-scan and a relabel must not add more
        inbox_sync.sync_once()
    db(test_url, "UPDATE mailbox_sync SET last_rescan_at = now() - interval '2 days'")
    inbox_sync.sync_once()
    with psycopg.connect(test_url) as conn:
        conn.execute("UPDATE inbound_messages SET label = NULL")
    inbox_sync.sync_once()
    mid, thread = db(test_url, "SELECT id, gmail_thrid FROM inbound_messages")[0]
    from app.detection import label_message
    with psycopg.connect(test_url, row_factory=dict_row) as conn:
        label_message(conn, mid, force=True)  # label back to 'reply'
    n = notes(test_url)
    assert len(n) == 1
    kind, source, priority, title, body, link, _ = n[0]
    assert (kind, source, priority, title, body) == ("reply", str(mid), "normal", "Reply from Anna Schmidt",
                                                    "Re: Hello Acme")
    assert link == f"/threads/{thread}#in-{mid}"


@pytest.mark.parametrize("fixture,kind,priority", [
    ("auto", "auto_reply", "low"), ("hard", "bounce", "normal"), ("soft", "bounce", "low")])
def test_auto_replies_and_bounces(sent, gmail, test_url, fixture, kind, priority):
    from pathlib import Path
    names = {"auto": "outlook_ooo.eml", "hard": "gmail_hard_bounce.eml", "soft": "gmail_delayed.eml"}
    raw = (Path(__file__).parent / "fixtures" / names[fixture]).read_text(encoding="utf-8")
    gmail.inbound_raw(raw.replace("{{OUR_MSGID}}", sent["acme"][1]).replace("{{RCPT}}", "jobs@acme.de").encode())
    inbox_sync.sync_once()
    got = [n for n in notes(test_url) if n[0] != "send_cancelled"]
    assert [(n[0], n[2]) for n in got] == [(kind, priority)]
    assert got[0][5].startswith("/threads/")


def test_unrelated_mail_never_notifies(sent, gmail, test_url):
    gmail.inbound("Acme News <news@acme.de>", subject="Newsletter")  # company domain, but not a reply (no list header
    db(test_url, "UPDATE outbound_emails SET sent_at = now() - interval '90 days'")  # ...and not recently emailed)
    inbox_sync.sync_once()
    assert db(test_url, "SELECT label FROM inbound_messages")[0][0] == "unrelated"
    assert notes(test_url) == []


# ---------- AI re-prioritises the same notification ----------

def test_ai_analysis_updates_the_same_notification(sent, gmail, test_url, monkeypatch):
    reply(gmail, sent, body="We'd love to invite you to an interview next week.")
    inbox_sync.sync_once()
    fake_ai(monkeypatch, {"label": "interview_request", "label_evidence": "invite you to an interview",
                          "summary": "Acme invites the applicant to an interview."})
    ai_analysis.analyse_pending()
    n = notes(test_url)
    assert len(n) == 1
    assert (n[0][2], n[0][3], n[0][4]) == ("high", "Reply from Anna Schmidt · interview request",
                                          "Acme invites the applicant to an interview.")
    mid = db(test_url, "SELECT id FROM inbound_messages")[0][0]
    fake_ai(monkeypatch, {"label": "rejection", "label_evidence": "invite you to an interview", "summary": "x"})
    with psycopg.connect(test_url, row_factory=dict_row) as conn:
        ai_analysis.analyse_message(conn, mid)  # re-analysis: still one notification, title not stacked
    n = notes(test_url)
    assert len(n) == 1 and n[0][2] == "low" and n[0][3] == "Reply from Anna Schmidt · rejection"


def test_unverified_ai_changes_nothing_and_final_failure_notifies_once(sent, gmail, test_url, monkeypatch):
    reply(gmail, sent)
    inbox_sync.sync_once()
    fake_ai(monkeypatch, {"label": "offer", "label_evidence": "invented quote", "summary": "x"})
    ai_analysis.analyse_pending()
    assert [(n[0], n[2]) for n in notes(test_url)] == [("reply", "normal")]
    db(test_url, "UPDATE ai_analyses SET status = 'error', error = 'quota', attempts = 2")
    assert notes(test_url, "ai_failed") == []
    for _ in range(3):
        db(test_url, "UPDATE ai_analyses SET status = 'error', error = 'quota', attempts = attempts + 1")
    got = notes(test_url, "ai_failed")
    assert len(got) == 1 and got[0][4] == "quota"


# ---------- sending problems ----------

def test_failed_send_notifies_once_per_email(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "refuse"
    for _ in range(4):  # both emails fail; extra ticks find nothing more to do
        sender.process_once()
    got = notes(test_url, "send_failed")
    assert sorted(n[1] for n in got) == sorted([str(world["Acme"][0]), str(world["Beta"][0])])
    assert {n[5] for n in got} == {f"/outbox/{world['Acme'][0]}", f"/outbox/{world['Beta'][0]}"}


def test_send_time_cancellation_notifies(world, client, gmail, test_url):
    enable(client)
    client.post("/leads/stage", json={"company_ids": [world["Acme"][1]], "stage": "on_hold"})
    sender.process_once()
    got = notes(test_url, "send_cancelled")
    assert len(got) == 1 and got[0][4].startswith("4. Active lead")


def test_company_reply_cancellation_notifies(sent, gmail, test_url):
    db(test_url, "INSERT INTO outbound_emails (to_email, subject, body, company_id, status, approved_at, "
                 "approved_content_hash) VALUES ('hr@acme.de', 'F', 'b', %s, 'queued', now(), "
                 "email_content_hash('hr@acme.de', 'F', 'b'))", (sent["acme"][3],))
    reply(gmail, sent)
    inbox_sync.sync_once()
    assert [n[4] for n in notes(test_url, "send_cancelled")] == ["company replied; review first"]


def test_owner_actions_do_not_notify(world, client, gmail, test_url):
    client.post("/suppressions", json={"kind": "domain", "value": "acme.de", "reason": "asked"})  # M25 cancels Acme
    beta = world["Beta"][0]
    client.post(f"/outbound-emails/{beta}/unqueue")
    client.post(f"/outbound-emails/{beta}/discard")  # owner discards a draft
    assert db(test_url, "SELECT count(*) FROM outbound_emails WHERE status = 'cancelled'")[0][0] == 2
    assert notes(test_url) == []


# ---------- system problems ----------

def test_sync_failing_three_times_notifies_once_per_streak(sent, gmail, test_url):
    gmail.imap_down = True
    for _ in range(2):
        inbox_sync.sync_once()
    assert notes(test_url, "sync_failing") == []
    for _ in range(4):
        inbox_sync.sync_once()
    assert len(notes(test_url, "sync_failing")) == 2  # one per mailbox (both fail), not one per run
    gmail.imap_down = False
    inbox_sync.sync_once()  # recovers: the streak ends
    gmail.imap_down = True
    for _ in range(3):
        inbox_sync.sync_once()
    assert len(notes(test_url, "sync_failing")) == 4  # a new streak is a new event


# ---------- DB guarantee & API ----------

def test_database_rejects_a_second_notification_for_the_same_event(test_url):
    with psycopg.connect(test_url) as conn:
        conn.execute("DELETE FROM notifications")
        sql = ("INSERT INTO notifications (kind, source_type, source_id, priority, title, link) "
               "VALUES ('reply', 'inbound_message', '42', 'normal', 't', '/x')")
        conn.execute(sql)
        with pytest.raises(errors.UniqueViolation), conn.transaction():
            conn.execute(sql)
        conn.rollback()


def test_api(sent, client, gmail, test_url, monkeypatch):
    for path, method in [("/notifications", "get"), ("/notifications/count", "get"),
                         ("/notifications/1/read", "post"), ("/notifications/read-all", "post")]:
        assert getattr(TestClient(app), method)(path).status_code == 401
    reply(gmail, sent, body="We'd love to invite you to an interview.")
    reply(gmail, sent, frm="HR <hr@acme.de>", body="Thanks, noted.")
    inbox_sync.sync_once()
    fake_ai(monkeypatch, {"label": "interview_request", "label_evidence": "invite you to an interview", "summary": "s"})
    first = db(test_url, "SELECT min(id) FROM inbound_messages")[0][0]
    with psycopg.connect(test_url, row_factory=dict_row) as conn:
        ai_analysis.analyse_message(conn, first)
    assert client.get("/notifications/count").json() == {"unread": 2, "high": 1}
    listed = client.get("/notifications").json()
    assert listed[0]["priority"] == "high" and listed[0]["company_name"] == "Acme"  # high first
    r = client.post(f"/notifications/{listed[0]['id']}/read").json()
    assert r["link"].endswith(f"#in-{first}")
    assert client.get("/notifications/count").json()["unread"] == 1
    assert [n["id"] for n in client.get("/notifications", params={"unread_only": True}).json()] == [listed[1]["id"]]
    assert client.post("/notifications/read-all").json() == {"marked": 1}
    assert client.get("/notifications/count").json() == {"unread": 0, "high": 0}
    assert client.post("/notifications/999999/read").status_code == 404
