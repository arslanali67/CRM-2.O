"""M14: inbox sync. Done when: a 24 h soak shows no missed and no duplicate messages.

Uses the fake Gmail (tests/fakes.py): All Mail + Spam with real IMAP semantics (UIDs, UIDVALIDITY,
the "n:*" quirk, dropped connections). The fake rejects any fetch that would mark mail as read.
"""
import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import inbox_sync, sender
from app.main import app
from fakes import ALL, SPAM, age_last_send, db, enable


@pytest.fixture
def sent(world, client, gmail, test_url):
    """Both world emails actually sent (fake), so replies have something to refer to."""
    enable(client)
    for _ in range(3):
        sender.process_once()
        age_last_send(test_url)
    rows = db(test_url, "SELECT id, provider_message_id, gmail_thrid, company_id FROM outbound_emails "
                        "WHERE status = 'sent' ORDER BY id")
    assert len(rows) == 2
    return {"acme": rows[0], "beta": rows[1]}


def stored(test_url):
    return {r[0]: r[1] for r in db(test_url, "SELECT gmail_msgid, relevance FROM inbound_messages")}


def test_requires_login():
    c = TestClient(app)
    for method, path in [("get", "/inbox"), ("get", "/inbox/1"), ("get", "/inbox-sync"), ("post", "/inbox-sync/run")]:
        assert getattr(c, method)(path).status_code == 401, path


def test_no_account_no_sync(client, gmail, test_url, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DATABASE_URL", test_url)
    assert inbox_sync.sync_once() == {"action": "no_account"}


# ---------- relevance: only outreach-related mail is stored ----------

def test_only_relevant_messages_are_stored(sent, gmail, test_url):
    acme = sent["acme"]
    cases = {
        gmail.inbound("Recruiter <someone@elsewhere.org>", in_reply_to=acme[1]): "reply_header",
        gmail.inbound("Anna <anna.x@unrelated.net>", thrid=acme[2]): "thread",
        gmail.inbound("Mail Delivery Subsystem <mailer-daemon@googlemail.com>", subject="Delivery failed"): "bounce",
        gmail.inbound("Beta Jobs <jobs@beta.io>", subject="Hello"): "contact",
        gmail.inbound("CEO <ceo@eu.acme.de>", subject="Hi"): "company_domain",
        gmail.inbound("Recruiter <jobs@acme.de>", box=SPAM, in_reply_to=acme[1]): "reply_header",
    }
    irrelevant = [gmail.inbound("Shop <deals@shop.example>", subject="50% off"),
                  gmail.inbound("Mum <mum@family.example>", subject="Dinner?")]
    own = gmail.inbound("Me <me@gmail.com>", subject="note to self")
    r = inbox_sync.sync_once()
    assert r["action"] == "synced"
    assert stored(test_url) == cases
    assert not set(irrelevant + [own]) & set(gmail.body_fetches)  # irrelevant bodies are never even downloaded
    links = db(test_url, "SELECT relevance, outbound_email_id, company_id FROM inbound_messages ORDER BY id")
    assert links[0] == ("reply_header", acme[0], acme[3])
    counts = db(test_url, "SELECT mailbox, seen_count, stored_count FROM mailbox_sync ORDER BY mailbox")
    assert counts == [("all", 8, 5), ("spam", 1, 1)]


def test_bounces_unrelated_to_crm_sends_are_not_stored(world, client, gmail, test_url):
    """No CRM email sent recently: a Mailer-Daemon message belongs to personal mail, not outreach."""
    personal = gmail.inbound("mailer-daemon@googlemail.com", subject="Delivery Status Notification")
    old_bounce_after_send = gmail.inbound("mailer-daemon@googlemail.com", subject="late",
                                          date=datetime.now(timezone.utc) - timedelta(days=5))
    assert inbox_sync.sync_once()["action"] == "synced"
    assert personal not in stored(test_url) and old_bounce_after_send not in stored(test_url)
    assert personal not in gmail.body_fetches


def test_read_only_and_peek(sent, gmail, test_url):
    gmail.inbound("Beta Jobs <jobs@beta.io>")
    inbox_sync.sync_once()
    assert gmail.selects and all(readonly for _, readonly in gmail.selects)
    # The fake raises on RFC822 / BODY[] (which would mark mail read); reaching here means only PEEK was used.
    assert gmail.body_fetches


def test_message_content_is_parsed(sent, gmail, test_url):
    gmail.inbound("Beta HR <jobs@beta.io>", subject="Interview", body="Can you talk Tuesday?",
                  attachments=["contract.pdf"])
    gmail.inbound("Beta HR <jobs@beta.io>", subject="HTML", html=True)
    gmail.inbound("Beta HR <jobs@beta.io>", subject="Huge", body="x" * 150_000)
    inbox_sync.sync_once()
    rows = {r[0]: r[1:] for r in db(test_url, "SELECT subject, from_name, body_text, attachment_names, body_truncated "
                                              "FROM inbound_messages")}
    assert rows["Interview"][0] == "Beta HR" and "Tuesday" in rows["Interview"][1]
    assert rows["Interview"][2] == ["contract.pdf"]  # names only
    assert "secret contents" not in str(db(test_url, "SELECT * FROM inbound_messages"))
    assert "Hello & welcome" in rows["HTML"][1] and "x()" not in rows["HTML"][1]
    assert len(rows["Huge"][1]) == 100_000 and rows["Huge"][3] is True


# ---------- cursor, lookback, resync ----------

def test_first_sync_looks_back_14_days(sent, gmail, test_url):
    old = gmail.inbound("jobs@beta.io", date=datetime.now(timezone.utc) - timedelta(days=20))
    recent = gmail.inbound("jobs@beta.io", date=datetime.now(timezone.utc) - timedelta(days=10))
    inbox_sync.sync_once()
    assert set(stored(test_url)) == {recent} and old not in stored(test_url)


def test_incremental_only_fetches_new_messages(sent, gmail, test_url):
    gmail.inbound("jobs@beta.io")
    inbox_sync.sync_once()
    gmail.header_fetch_uids.clear()
    db(test_url, "UPDATE mailbox_sync SET last_rescan_at = now()")
    inbox_sync.sync_once()  # nothing new: the "n:*" quirk returns the last UID, which must be ignored
    assert gmail.header_fetch_uids == []
    new = gmail.inbound("jobs@beta.io", subject="second")
    inbox_sync.sync_once()
    assert len(gmail.header_fetch_uids) == 1 and new in stored(test_url)


def test_uidvalidity_change_rescans_without_duplicates(sent, gmail, test_url):
    first = gmail.inbound("jobs@beta.io")
    inbox_sync.sync_once()
    gmail.boxes[ALL].renumber()
    second = gmail.inbound("jobs@beta.io", subject="after renumber")
    inbox_sync.sync_once()
    assert set(stored(test_url)) == {first, second}
    assert db(test_url, "SELECT count(*) FROM inbound_messages")[0][0] == 2
    assert db(test_url, "SELECT uidvalidity FROM mailbox_sync WHERE mailbox = 'all'")[0][0] == 2


def test_daily_rescan_catches_a_late_arrival_below_the_cursor(sent, gmail, test_url):
    inbox_sync.sync_once()
    late = gmail.inbound("jobs@beta.io")
    msg = gmail.boxes[ALL].msgs.pop()  # simulate a message that appears with a UID below the cursor
    msg["uid"] = 0
    gmail.boxes[ALL].msgs.insert(0, msg)
    inbox_sync.sync_once()
    assert late not in stored(test_url)  # incremental can't see it...
    db(test_url, "UPDATE mailbox_sync SET last_rescan_at = now() - interval '25 hours'")
    inbox_sync.sync_once()
    assert late in stored(test_url)      # ...the daily re-scan does


def test_dropped_connection_is_recorded_and_recovered(sent, gmail, test_url):
    msgs = [gmail.inbound("jobs@beta.io", subject=f"m{i}") for i in range(120)]  # > 2 batches
    # Regression: a failed *first* sync must not shrink the 14-day look-back for the retry.
    msgs.append(gmail.inbound("jobs@beta.io", subject="8 days old", date=datetime.now(timezone.utc) - timedelta(days=8)))
    gmail.fail_uid_calls_after = 5
    r = inbox_sync.sync_once()
    assert r["action"] == "error" and "OSError" in r["error"]
    assert db(test_url, "SELECT last_ok FROM mailbox_sync WHERE mailbox = 'all'")[0][0] is False
    partial = len(stored(test_url))
    gmail.fail_uid_calls_after = None
    assert inbox_sync.sync_once()["action"] == "synced"
    assert set(stored(test_url)) == set(msgs) and partial < len(msgs)
    assert db(test_url, "SELECT last_ok, last_error FROM mailbox_sync WHERE mailbox = 'all'")[0] == (True, None)


def test_sync_lock(sent, gmail, test_url):
    import psycopg
    with psycopg.connect(test_url, autocommit=True) as other:
        other.execute("SELECT pg_advisory_lock(%s)", (inbox_sync.SYNC_LOCK,))
        assert inbox_sync.sync_once() == {"action": "locked"}
        other.execute("SELECT pg_advisory_unlock(%s)", (inbox_sync.SYNC_LOCK,))


# ---------- the simulated 24 h soak ----------

def test_simulated_24h_soak_no_misses_no_duplicates(sent, gmail, test_url):
    """720 syncs (every 2 minutes for 24 h) with random arrivals of every kind, two mailbox renumbers,
    dropped connections, a message present in both folders, and daily re-scans."""
    rng = random.Random(20260927)
    acme = sent["acme"]
    expected, unexpected = set(), set()
    kinds = [
        lambda: (gmail.inbound("r@elsewhere.org", in_reply_to=acme[1]), True),
        lambda: (gmail.inbound("x@unrelated.net", thrid=acme[2]), True),
        lambda: (gmail.inbound("mailer-daemon@googlemail.com", subject="Undeliverable"), True),
        lambda: (gmail.inbound("jobs@beta.io"), True),
        lambda: (gmail.inbound("hr@acme.de", box=SPAM), True),
        lambda: (gmail.inbound("news@shop.example"), False),
        lambda: (gmail.inbound("friend@family.example"), False),
        lambda: (gmail.inbound("me@gmail.com"), False),
    ]
    for tick in range(720):
        for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3])):
            gm, relevant = rng.choice(kinds)()
            (expected if relevant else unexpected).add(gm)
        if tick in (200, 500):
            gmail.boxes[rng.choice([ALL, SPAM])].renumber()
        if tick == 333:  # the same Gmail message visible in both folders
            gm = gmail.inbound("jobs@beta.io", subject="in both")
            gmail.inbound("jobs@beta.io", subject="in both", box=SPAM, gm_msgid=gm)
            expected.add(gm)
        if rng.random() < 0.05:
            gmail.fail_uid_calls_after = rng.randint(0, 6)
        if tick % 360 == 0:
            db(test_url, "UPDATE mailbox_sync SET last_rescan_at = now() - interval '25 hours'")
        inbox_sync.sync_once()
        gmail.fail_uid_calls_after = None
    inbox_sync.sync_once()  # final settle (as the next scheduled run would)

    got = db(test_url, "SELECT gmail_msgid FROM inbound_messages")
    ids = [r[0] for r in got]
    assert len(ids) == len(set(ids)), "duplicates stored"
    assert set(ids) == expected, f"missed {len(expected - set(ids))}, extra {len(set(ids) - expected)}"
    assert not unexpected & set(ids)
    assert len(expected) > 300  # the soak really exercised the sync


# ---------- API & threads ----------

def test_inbox_api_and_thread_integration(sent, client, gmail, test_url):
    reply = gmail.inbound("Anna Schmidt <jobs@acme.de>", subject="Re: Hello Acme", thrid=sent["acme"][2],
                          body="Happy to chat!")
    assert client.post("/inbox-sync/run").json()["action"] == "synced"
    listed = client.get("/inbox").json()
    assert [m["subject"] for m in listed] == ["Re: Hello Acme"]
    m = listed[0]
    assert (m["relevance"], m["company_name"], m["thread_key"]) == ("thread", "Acme", sent["acme"][2])
    assert client.get("/inbox", params={"q": "anna"}).json()[0]["id"] == m["id"]
    assert client.get("/inbox", params={"company_id": sent["beta"][3]}).json() == []
    assert "Happy to chat!" in client.get(f"/inbox/{m['id']}").json()["body_text"]
    assert client.get("/inbox/999999").status_code == 404

    t = client.get(f"/threads/{sent['acme'][2]}").json()
    assert [e["id"] for e in t["emails"]] == [sent["acme"][0]] and [x["id"] for x in t["inbound"]] == [m["id"]]
    company = client.get(f"/companies/{sent['acme'][3]}/emails").json()
    assert [x["id"] for x in company[0]["inbound"]] == [m["id"]]

    status = client.get("/inbox-sync").json()
    assert status["account_ready"] is True and status["stored_total"] == 1
    assert {b["mailbox"] for b in status["mailboxes"]} == {"all", "spam"}
    assert reply in stored(test_url)
