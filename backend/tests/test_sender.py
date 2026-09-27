"""M12: sending. Done when: sending is exactly-once and the safety tests are green.

A fake Gmail records every delivered message and files it in a fake Sent folder (that is what
recovery searches). No real mail server is ever contacted (see conftest.no_real_mail).
"""
import email as email_lib
import imaplib
import smtplib

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import sender, settings
from app.main import app
from conftest import RealMailServerBlocked

PDF = b"%PDF-1.7\n%%EOF\n"
APP_PW = "abcdefghijklmnop"


class FakeGmail:
    """mode: ok | login_fail | refuse | drop_before | accept_then_drop | data_5xx | data_4xx"""

    def __init__(self):
        self.mode = "ok"
        self.delivered = []   # messages Gmail actually accepted
        self.imap_down = False

    def smtp(self, gm):
        class SMTP:
            def __init__(self, host, port, timeout=None, context=None):
                if gm.mode == "connect_fail":
                    raise OSError("unreachable")

            def login(self, user, password):
                if gm.mode == "login_fail" or password != APP_PW:
                    raise smtplib.SMTPAuthenticationError(535, b"bad")

            def send_message(self, msg):
                if gm.mode == "refuse":
                    raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such user")})
                if gm.mode == "data_5xx":
                    raise smtplib.SMTPDataError(552, b"message rejected")
                if gm.mode == "data_4xx":
                    raise smtplib.SMTPDataError(451, b"try later")
                if gm.mode == "drop_before":
                    raise smtplib.SMTPServerDisconnected("gone")
                gm.delivered.append(email_lib.message_from_bytes(msg.as_bytes()))
                if gm.mode == "accept_then_drop":
                    raise smtplib.SMTPServerDisconnected("gone after accepting")
                return {}

            def quit(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return SMTP

    def imap(self, gm):
        class IMAP:
            def __init__(self, host, port, ssl_context=None, timeout=None):
                if gm.imap_down:
                    raise OSError("unreachable")

            def login(self, user, password):
                if password != APP_PW:
                    raise imaplib.IMAP4.error("auth")

            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"']

            def select(self, box, readonly=False):
                assert readonly
                return "OK", [str(len(gm.delivered)).encode()]

            def search(self, charset, *criteria):
                assert criteria[:2] == ("HEADER", "Message-ID")
                hits = [str(i + 1).encode() for i, m in enumerate(gm.delivered) if m["Message-ID"] == criteria[2]]
                return "OK", [b" ".join(hits)]

            def logout(self):
                pass
        return IMAP


@pytest.fixture
def gmail(monkeypatch):
    gm = FakeGmail()
    monkeypatch.setattr(smtplib, "SMTP_SSL", gm.smtp(gm))
    monkeypatch.setattr(imaplib, "IMAP4_SSL", gm.imap(gm))
    return gm


@pytest.fixture
def world(client, gmail, test_url, monkeypatch):
    """Connected account, two approved+queued emails (one with a CV), sending still OFF."""
    monkeypatch.setattr(settings, "DATABASE_URL", test_url)
    client.put("/profile", json={"full_name": "Arslan Ali", "email": "me@example.com"})
    client.post("/cv", params={"label": "Main", "filename": "Arslan_CV.pdf"}, content=PDF,
                headers={"Content-Type": "application/pdf"})
    client.put("/email-account", json={"email_address": "me@gmail.com", "display_name": "Arslan Ali",
                                       "app_password": APP_PW})
    assert client.post("/email-account/test").json()["connected"]
    tid = client.post("/templates", json={"name": "Intro", "subject": "Hello {{company_name}}",
                                          "body": "Hi {{contact_first_name | there}},\nI'm {{my_full_name}}."}).json()["id"]
    ids = {}
    for name, domain, contact in [("Acme", "acme.de", "Anna Schmidt"), ("Beta", "beta.io", "")]:
        cid = client.post("/companies", json={"name": name, "domain": domain}).json()["id"]
        client.post(f"/companies/{cid}/contacts", json={"name": contact, "email": f"jobs@{domain}"})
        client.post("/compose-list", json={"company_ids": [cid]})
        drafted = client.post("/compose-list/drafts", json={"template_id": tid, "attach_cv": name == "Acme"}).json()
        eid = drafted["created"][0]["email_id"]
        h = client.get(f"/outbound-emails/{eid}").json()["content_hash_hex"]
        assert client.post(f"/outbound-emails/{eid}/approve", json={"content_hash": h}).json()["status"] == "queued"
        ids[name] = (eid, cid)
    return ids


def db(test_url, sql, params=()):
    with psycopg.connect(test_url) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def status(test_url, eid):
    return db(test_url, "SELECT status FROM outbound_emails WHERE id = %s", (eid,))[0][0]


def enable(client):
    r = client.post("/sending/enable", json={"confirm": True})
    assert r.status_code == 200, r.text


def age_last_send(test_url, minutes=2):
    db(test_url, "UPDATE outbound_emails SET sent_at = sent_at - make_interval(mins => %s) WHERE status = 'sent'",
       (minutes,))


# ---------- guard ----------

def test_tests_can_never_reach_a_real_mail_server():
    with pytest.raises(RealMailServerBlocked):
        smtplib.SMTP_SSL("smtp.gmail.com", 465)
    with pytest.raises(RealMailServerBlocked):
        imaplib.IMAP4_SSL("imap.gmail.com", 993)
    with pytest.raises(RealMailServerBlocked):
        smtplib.SMTP("smtp.gmail.com", 587)
    with pytest.raises(RealMailServerBlocked):
        imaplib.IMAP4("imap.gmail.com", 143)


# ---------- kill switch ----------

def test_nothing_is_sent_while_the_kill_switch_is_off(world, gmail, test_url):
    for _ in range(3):
        r = sender.process_once()
        assert r["action"] == "wait" and {c["id"] for c in r["checks"] if not c["ok"]} == {12}
    assert gmail.delivered == [] and status(test_url, world["Acme"][0]) == "queued"


def test_enabling_needs_confirmation_and_a_tested_account(client, gmail):
    assert TestClient(app).post("/sending/enable", json={"confirm": True}).status_code == 401
    assert client.post("/sending/enable", json={"confirm": False}).status_code == 422
    assert client.post("/sending/enable", json={"confirm": True}).status_code == 409  # no account yet
    assert client.get("/sending").json()["enabled"] is False


def test_no_account_means_no_sending(world, client, test_url):
    enable(client)
    client.delete("/email-account")
    assert sender.process_once() == {"action": "no_account"}


# ---------- exactly one, exactly as approved ----------

def test_sends_exactly_the_approved_email(world, client, gmail, test_url):
    enable(client)
    preview = client.get(f"/outbound-emails/{world['Acme'][0]}").json()
    assert sender.process_once() == {"action": "sent", "email_id": world["Acme"][0]}
    assert len(gmail.delivered) == 1
    m = gmail.delivered[0]
    assert m["From"] == "Arslan Ali <me@gmail.com>" and m["To"] == "Anna Schmidt <jobs@acme.de>"
    assert m["Subject"] == preview["subject"] == "Hello Acme"
    body = next(p for p in m.walk() if p.get_content_type() == "text/plain").get_payload(decode=True).decode()
    assert body.strip() == preview["body"].strip()
    pdf = next(p for p in m.walk() if p.get_content_type() == "application/pdf")
    assert pdf.get_filename() == "Arslan_CV.pdf" and pdf.get_payload(decode=True) == PDF
    row = db(test_url, "SELECT status, sent_at, provider_message_id FROM outbound_emails WHERE id = %s",
             (world["Acme"][0],))[0]
    assert row[0] == "sent" and row[1] is not None and row[2] == m["Message-ID"]
    assert db(test_url, "SELECT stage FROM companies WHERE id = %s", (world["Acme"][1],))[0][0] == "contacted"


def test_one_email_per_tick_and_the_90s_gap(world, client, gmail, test_url):
    enable(client)
    assert sender.process_once()["action"] == "sent"
    r = sender.process_once()
    assert r["action"] == "wait" and "since the last send" in next(c for c in r["checks"] if c["id"] == 11)["detail"]
    assert len(gmail.delivered) == 1
    age_last_send(test_url)
    assert sender.process_once() == {"action": "sent", "email_id": world["Beta"][0]}
    assert sender.process_once() == {"action": "idle"}
    assert len(gmail.delivered) == 2
    assert {m["Message-ID"] for m in gmail.delivered} == {r[0] for r in db(
        test_url, "SELECT provider_message_id FROM outbound_emails WHERE status = 'sent'")}  # unique per email


def test_daily_cap_waits(world, client, gmail, test_url):
    enable(client)
    db(test_url, "UPDATE app_settings SET daily_cap = 1")
    sender.process_once()
    age_last_send(test_url)
    r = sender.process_once()
    assert r["action"] == "wait" and "daily cap" in next(c for c in r["checks"] if c["id"] == 11)["detail"]
    assert len(gmail.delivered) == 1


def test_stopping_takes_effect_before_the_next_email(world, client, gmail, test_url):
    enable(client)
    sender.process_once()
    client.post("/sending/disable")
    age_last_send(test_url)
    assert sender.process_once()["action"] == "wait"
    assert len(gmail.delivered) == 1


def test_sent_emails_are_never_picked_again(world, client, gmail, test_url):
    enable(client)
    for _ in range(6):
        sender.process_once()
        age_last_send(test_url)
    assert len(gmail.delivered) == 2


# ---------- failures: never twice ----------

def test_crash_after_gmail_accepted_is_recovered_without_resending(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "accept_then_drop"
    assert sender.process_once()["action"] == "interrupted"
    assert status(test_url, world["Acme"][0]) == "sending"
    gmail.mode = "ok"
    assert sender.process_once() == {"action": "recovered_sent", "email_id": world["Acme"][0]}
    assert status(test_url, world["Acme"][0]) == "sent"
    assert len(gmail.delivered) == 1  # exactly once


def test_crash_before_delivery_fails_for_review_and_is_not_resent(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "drop_before"
    assert sender.process_once()["action"] == "interrupted"
    mid = db(test_url, "SELECT provider_message_id FROM outbound_emails WHERE id = %s", (world["Acme"][0],))[0][0]
    assert mid  # the Message-ID was stored before the attempt
    gmail.mode = "ok"
    assert sender.process_once()["action"] == "recovering"  # not found yet, but too early to give up
    assert len(gmail.delivered) == 0
    db(test_url, "UPDATE outbound_emails SET send_started_at = now() - interval '11 minutes' WHERE id = %s",
       (world["Acme"][0],))
    assert sender.process_once()["action"] == "recovered_failed"
    reason = db(test_url, "SELECT status, failure_reason FROM outbound_emails WHERE id = %s", (world["Acme"][0],))[0]
    assert reason[0] == "failed" and "needs review (not resent)" in reason[1]
    assert len(gmail.delivered) == 0


def test_recovery_blocks_the_lane_while_the_outcome_is_unknown(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "accept_then_drop"
    sender.process_once()
    gmail.mode, gmail.imap_down = "ok", True
    for _ in range(3):
        assert sender.process_once()["action"] == "recovering"
    assert len(gmail.delivered) == 1  # the next email waits until the first is resolved


def test_login_failure_goes_back_to_the_queue(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "login_fail"
    assert sender.process_once()["action"] == "not_sent"
    row = db(test_url, "SELECT status, provider_message_id FROM outbound_emails WHERE id = %s", (world["Acme"][0],))[0]
    assert row == ("queued", None)
    gmail.mode = "ok"
    assert sender.process_once()["action"] == "sent" and len(gmail.delivered) == 1


@pytest.mark.parametrize("mode,expected", [("refuse", "failed"), ("data_5xx", "failed"), ("data_4xx", "interrupted")])
def test_rejections(world, client, gmail, test_url, mode, expected):
    enable(client)
    gmail.mode = mode
    assert sender.process_once()["action"] == expected
    assert len(gmail.delivered) == 0
    if expected == "failed":
        assert db(test_url, "SELECT failure_reason FROM outbound_emails WHERE id = %s", (world["Acme"][0],))[0][0]


def test_safety_checks_still_apply_at_send(world, client, gmail, test_url):
    enable(client)
    client.post("/suppressions", json={"kind": "domain", "value": "acme.de", "reason": "asked"})  # M25 cancels
    client.post("/leads/stage", json={"company_ids": [world["Beta"][1]], "stage": "on_hold"})
    for _ in range(3):
        sender.process_once()
    assert gmail.delivered == []
    assert status(test_url, world["Acme"][0]) == "cancelled" and status(test_url, world["Beta"][0]) == "cancelled"


def test_single_lane_lock(world, client, gmail, test_url):
    enable(client)
    with psycopg.connect(test_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (sender.SEND_LOCK,))
        assert sender.process_once() == {"action": "locked"}
        other.execute("SELECT pg_advisory_unlock(%s)", (sender.SEND_LOCK,))
    assert gmail.delivered == []
    assert sender.process_once()["action"] == "sent"


def test_events_and_status_endpoint(world, client, gmail, test_url):
    enable(client)
    sender.process_once()
    s = client.get("/sending").json()
    assert (s["enabled"], s["queued"], s["sent_24h"], s["account"]) == (True, 1, 1, "me@gmail.com")
    client.post("/sending/disable")
    actions = [a for (a,) in db(test_url, "SELECT action FROM audit_log WHERE action LIKE 'sending.%%' "
                                          "OR (entity_id = %s AND action LIKE 'outbound_email.%%') ORDER BY id",
                                (world["Acme"][0],))]
    assert actions[-4:] == ["sending.enabled", "outbound_email.sending", "outbound_email.sent", "sending.disabled"]
    sent_actor = db(test_url, "SELECT actor FROM audit_log WHERE action = 'outbound_email.sent' AND entity_id = %s",
                    (world["Acme"][0],))[0][0]
    assert sent_actor == "system"
