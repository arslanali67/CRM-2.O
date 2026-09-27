"""M13: email history. Done when: every sent email is in history with its thread."""
import pytest
from fastapi.testclient import TestClient

from app import sender
from app.main import app
from fakes import age_last_send, db, enable


def send_all(client, test_url):
    enable(client)
    sent = 0
    for _ in range(4):
        if sender.process_once()["action"] == "sent":
            sent += 1
        age_last_send(test_url)
    return sent


def ids(test_url, eid):
    return db(test_url, "SELECT gmail_msgid, gmail_thrid FROM outbound_emails WHERE id = %s", (eid,))[0]


def test_requires_login():
    c = TestClient(app)
    for path in ["/history", "/outbound-emails/1/timeline", "/threads/email-1", "/companies/1/emails"]:
        assert c.get(path).status_code == 401, path


# ---------- provider IDs ----------

def test_gmail_ids_are_stored_right_after_sending(world, client, gmail, test_url):
    assert send_all(client, test_url) == 2
    for name, (eid, _) in world.items():
        msgid, thrid = ids(test_url, eid)
        assert msgid and thrid and msgid.isdigit()
    assert all(readonly for _, readonly in gmail.selects)  # the lookup never opens a mailbox for writing


def test_gmail_ids_are_backfilled_when_sent_folder_lags(world, client, gmail, test_url):
    enable(client)
    gmail.sent_folder_lag = True
    assert sender.process_once()["action"] == "sent"
    eid = world["Acme"][0]
    assert ids(test_url, eid) == (None, None)
    gmail.sent_folder_lag = False
    r = sender.process_once()  # Beta must wait for the 90 s gap, so the tick is spare
    assert r["action"] == "wait" and "ids" not in r  # retried at most every 5 minutes
    db(test_url, "UPDATE outbound_emails SET ids_checked_at = now() - interval '6 minutes' WHERE id = %s", (eid,))
    r = sender.process_once()
    assert r["ids"] == {"action": "ids_backfilled", "email_id": eid}
    assert ids(test_url, eid)[1] is not None


def test_backfill_gives_up_after_24_hours(world, client, gmail, test_url):
    enable(client)
    gmail.sent_folder_lag = True
    sender.process_once()
    eid = world["Acme"][0]
    db(test_url, "UPDATE outbound_emails SET sent_at = now() - interval '25 hours', ids_checked_at = NULL WHERE id = %s",
       (eid,))
    gmail.sent_folder_lag = False
    client.post("/sending/disable")
    assert "ids" not in sender.process_once()
    assert ids(test_url, eid) == (None, None)


def test_recovered_send_gets_its_ids(world, client, gmail, test_url):
    enable(client)
    gmail.mode = "accept_then_drop"
    sender.process_once()
    gmail.mode = "ok"
    assert sender.process_once()["action"] == "recovered_sent"
    assert ids(test_url, world["Acme"][0])[1] is not None


def test_id_lookup_failure_never_affects_the_send(world, client, gmail, test_url):
    enable(client)
    gmail.imap_down = True
    assert sender.process_once()["action"] == "sent"
    assert db(test_url, "SELECT status FROM outbound_emails WHERE id = %s", (world["Acme"][0],))[0][0] == "sent"
    assert ids(test_url, world["Acme"][0]) == (None, None)


# ---------- history ----------

def test_every_sent_email_is_in_history_with_its_thread(world, client, gmail, test_url):
    send_all(client, test_url)
    h = client.get("/history").json()
    sent = [e for e in h["emails"] if e["status"] == "sent"]
    assert {e["id"] for e in sent} == {eid for eid, _ in world.values()}
    for e in sent:
        assert e["sent_at"] and e["provider_message_id"] and e["gmail_thrid"]
        assert e["thread_key"] == e["gmail_thrid"]
        t = client.get(f"/threads/{e['thread_key']}").json()
        assert t["gmail_thread"] is True and [x["id"] for x in t["emails"]] == [e["id"]]


def test_history_excludes_drafts_and_shows_reasons(world, client, gmail, test_url):
    enable(client)
    client.post("/leads/stage", json={"company_ids": [world["Acme"][1]], "stage": "on_hold"})
    sender.process_once()  # Acme is cancelled by the send-time checks
    db(test_url, "INSERT INTO outbound_emails (to_email, subject, body) VALUES ('x@draft.de', 'draft', 'b')")
    h = client.get("/history").json()
    assert "draft" not in {e["status"] for e in h["emails"]} and "draft" not in h["counts"]
    acme = next(e for e in h["emails"] if e["id"] == world["Acme"][0])
    assert acme["status"] == "cancelled" and acme["cancel_reason"].startswith("4. Active lead")
    assert acme["thread_key"] == f"email-{acme['id']}"  # never sent: its own thread


@pytest.mark.parametrize("params,expected", [
    ({"status": "sent"}, {"Acme", "Beta"}),
    ({"status": "failed"}, set()),
    ({"q": "HELLO ACME"}, {"Acme"}),
    ({"q": "jobs@beta"}, {"Beta"}),
    ({"since": "2000-01-01"}, {"Acme", "Beta"}),
    ({"until": "2000-01-01"}, set()),
])
def test_history_filters(world, client, gmail, test_url, params, expected):
    send_all(client, test_url)
    names = {e["company_name"] for e in client.get("/history", params=params).json()["emails"]}
    assert names == expected


def test_history_company_filter_and_validation(world, client, gmail, test_url):
    send_all(client, test_url)
    got = client.get("/history", params={"company_id": world["Beta"][1]}).json()["emails"]
    assert [e["company_name"] for e in got] == ["Beta"]
    assert client.get("/history", params={"status": "draft"}).status_code == 422
    assert client.get("/history", params={"since": "yesterday"}).status_code == 422


# ---------- timeline & threads ----------

def test_status_timeline_is_complete_and_ordered(world, client, gmail, test_url):
    send_all(client, test_url)
    tl = client.get(f"/outbound-emails/{world['Acme'][0]}/timeline").json()
    steps = [(e["action"], e["actor"]) for e in tl]
    assert steps == [("outbound_email.created", "owner"), ("outbound_email.approved", "owner"),
                     ("outbound_email.queued", "owner"), ("outbound_email.sending", "system"),
                     ("outbound_email.sent", "system")]
    assert [e["id"] for e in tl] == sorted(e["id"] for e in tl)
    assert client.get("/outbound-emails/999999/timeline").status_code == 404


def test_emails_in_one_gmail_thread_are_grouped(world, client, gmail, test_url):
    enable(client)
    sender.process_once()
    age_last_send(test_url)
    first_mid = gmail.delivered[0]["Message-ID"]
    first_thread = ids(test_url, world["Acme"][0])[1]
    # Pretend Gmail put the second email into the first one's conversation (as a reply would be).
    original = gmail.gm_ids
    gmail.gm_ids = lambda i, m: (original(i, m)[0], first_thread if m["Message-ID"] != first_mid else original(i, m)[1])
    sender.process_once()
    t = client.get(f"/threads/{first_thread}").json()
    assert [e["id"] for e in t["emails"]] == [world["Acme"][0], world["Beta"][0]]
    assert "body" in t["emails"][0]
    assert client.get("/threads/nope").status_code == 404


def test_company_emails_grouped_by_thread(world, client, gmail, test_url):
    send_all(client, test_url)
    threads = client.get(f"/companies/{world['Acme'][1]}/emails").json()
    assert [[e["id"] for e in t["emails"]] for t in threads] == [[world["Acme"][0]]]
    assert threads[0]["thread_key"] == ids(test_url, world["Acme"][0])[1]
    assert client.get("/companies/999999/emails").status_code == 404
