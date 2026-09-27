"""M26: the 12 safety checks. Done when: all 12 gates are tested and re-checked at send time."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.safety import CHECKS, approve, claim_for_send, run_checks


# ---------- helpers (all inside the rolled-back ddb transaction) ----------

@pytest.fixture
def w(ddb):
    co = ddb.execute("INSERT INTO companies (name, domain, stage) VALUES ('Acme', 'acme.de', 'qualified') "
                     "RETURNING id").fetchone()["id"]
    ct = ddb.execute("INSERT INTO contacts (company_id, name, email, email_class) "
                     "VALUES (%s, 'Anna', 'anna@acme.de', 'personal') RETURNING id", (co,)).fetchone()["id"]
    other = ddb.execute("INSERT INTO contacts (company_id, email, email_class) VALUES (%s, 'jobs@acme.de', 'careers') "
                        "RETURNING id", (co,)).fetchone()["id"]
    return {"db": ddb, "company": co, "contact": ct, "other_contact": other}


def draft(db, company, contact, to="anna@acme.de", subject="Hello Acme", body="Hi Anna, I'm applying."):
    return db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body, company_id, contact_id) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id", (to, subject, body, company, contact)).fetchone()["id"]


def sent(db, to, company=None, ago="1 day", subject="s"):
    db.execute(
        "INSERT INTO outbound_emails (to_email, subject, body, company_id, status, approved_at, approved_content_hash, "
        "sent_at) VALUES (%s, %s, 'b', %s, 'sent', now() - %s::interval, email_content_hash(%s, %s, 'b'), "
        "now() - %s::interval)", (to, subject, company, ago, to, subject, ago))


def row(db, email_id):
    return db.execute("SELECT * FROM outbound_emails WHERE id = %s", (email_id,)).fetchone()


def failed_ids(checks):
    return {c["id"] for c in checks if not c["ok"]}


def queued(w):
    """A draft that passed approval and sits in the queue, with sending switched on."""
    db = w["db"]
    i = draft(db, w["company"], w["contact"])
    assert approve(db, i)["approved"]
    db.execute("UPDATE outbound_emails SET status = 'queued' WHERE id = %s", (i,))
    db.execute("UPDATE app_settings SET sending_enabled = true")
    return i


def audits(db, email_id, action="outbound_email.checks_failed"):
    return db.execute("SELECT data FROM audit_log WHERE action = %s AND entity_id = %s ORDER BY id",
                      (action, email_id)).fetchall()


# ---------- the happy path ----------

def test_exactly_12_checks():
    assert sorted(CHECKS) == list(range(1, 13))


def test_clean_email_passes_approval_and_send(w):
    db = w["db"]
    i = draft(db, w["company"], w["contact"])
    r = approve(db, i)
    assert r["approved"] and [c["id"] for c in r["checks"]] == list(range(1, 13))
    assert all(c["ok"] for c in r["checks"])
    assert {c["id"] for c in r["checks"] if not c["applies"]} == {10, 12}  # send-only checks
    e = row(db, i)
    assert e["status"] == "approved" and e["approved_content_hash"] == e["content_hash"]

    db.execute("UPDATE outbound_emails SET status = 'queued' WHERE id = %s", (i,))
    db.execute("UPDATE app_settings SET sending_enabled = true")
    s = claim_for_send(db, i)
    assert s["action"] == "send" and all(c["ok"] and c["applies"] for c in s["checks"])
    assert row(db, i)["status"] == "sending"


# ---------- every check refuses approval ----------

def fail_1(w): w["db"].execute("INSERT INTO suppressions (kind, email, reason) VALUES ('email', 'anna@acme.de', 'x')")
def fail_2(w): w["db"].execute("UPDATE contacts SET email = 'max@muster.de', email_class = 'personal' WHERE id = %s", (w["contact"],)); return "max@muster.de"  # noqa: E501,E702
def fail_3_unsuitable(w): w["db"].execute("UPDATE contacts SET email_class = 'unsuitable', email_class_manual = true WHERE id = %s", (w["contact"],))  # noqa: E501
def fail_3_archived(w): w["db"].execute("UPDATE contacts SET archived_at = now() WHERE id = %s", (w["contact"],))
def fail_3_mismatch(w): return "jobs@acme.de"  # recipient differs from the linked contact
def fail_4_closed(w): w["db"].execute("UPDATE companies SET stage = 'closed', close_reason = 'x' WHERE id = %s", (w["company"],))  # noqa: E501
def fail_4_on_hold(w): w["db"].execute("UPDATE companies SET stage = 'on_hold' WHERE id = %s", (w["company"],))
def fail_4_archived(w): w["db"].execute("UPDATE companies SET archived_at = now() WHERE id = %s", (w["company"],))
def fail_5(w):
    i = draft(w["db"], w["company"], w["contact"], subject="first")
    w["db"].execute("UPDATE outbound_emails SET status = 'approved', approved_at = now(), "
                    "approved_content_hash = content_hash WHERE id = %s", (i,))
def fail_6(w): sent(w["db"], "anna@acme.de", company=None, ago="20 days")   # 30-day recipient cooldown only
def fail_7(w): sent(w["db"], "jobs@acme.de", company=w["company"], ago="5 days")  # 14-day company cooldown
def fail_11(w):
    for n in range(20):
        w["db"].execute("INSERT INTO outbound_emails (to_email, subject, body, status, approved_at, approved_content_hash) "
                        "VALUES (%s, 's', 'b', 'approved', now(), email_content_hash(%s, 's', 'b'))",
                        (f"p{n}@elsewhere.de", f"p{n}@elsewhere.de"))


@pytest.mark.parametrize("mutate,expected", [
    (fail_1, {1}), (fail_2, {2}), (fail_3_unsuitable, {3}), (fail_3_archived, {3}), (fail_3_mismatch, {3}),
    (fail_4_closed, {4}), (fail_4_on_hold, {4}), (fail_4_archived, {4}), (fail_5, {5}), (fail_6, {6}),
    (fail_7, {7}), (fail_11, {11}),
])
def test_each_check_refuses_approval(w, mutate, expected):
    db = w["db"]
    to = mutate(w) or "anna@acme.de"
    i = draft(db, w["company"], w["contact"], to=to)
    r = approve(db, i)
    assert (r["approved"], failed_ids(r["checks"])) == (False, expected)
    assert all(c["detail"] for c in r["checks"] if not c["ok"])  # every failure explains itself
    assert row(db, i)["status"] == "draft"
    assert [f["id"] for f in audits(db, i)[-1]["data"]["failed"]] == sorted(expected)


@pytest.mark.parametrize("subject,body,expected", [
    ("Hello {{company_name}}", "b", {8}),
    ("Hello", "Hi {{contact_first_name | there}}", {8}),
    ("Hello", "stray }} brace", {8}),
    ("x" * 201, "b", {9}),
    ("Hello", "   ", {9}),
    ("Hello", "x" * 20001, {9}),
])
def test_content_checks_refuse_approval(w, subject, body, expected):
    i = draft(w["db"], w["company"], w["contact"], subject=subject, body=body)
    assert failed_ids(approve(w["db"], i)["checks"]) == expected


def test_missing_links_fail_3_and_4(w):
    i = draft(w["db"], None, None)
    assert failed_ids(approve(w["db"], i)["checks"]) == {3, 4}


def test_only_drafts_can_be_approved(w):
    i = queued(w)
    with pytest.raises(HTTPException) as e:
        approve(w["db"], i)
    assert e.value.status_code == 409


# ---------- everything is re-checked at send ----------

def test_kill_switch_off_means_wait_not_cancel(w):
    db = w["db"]
    i = queued(w)
    db.execute("UPDATE app_settings SET sending_enabled = false")
    r = claim_for_send(db, i)
    assert (r["action"], failed_ids(r["checks"])) == ("wait", {12})
    assert row(db, i)["status"] == "queued" and audits(db, i) == []


@pytest.mark.parametrize("prep,why", [
    (lambda db: [sent(db, f"x{n}@far.de", ago="2 hours") for n in range(20)], "daily cap"),
    (lambda db: sent(db, "x@far.de", ago="30 seconds"), "since the last send"),
])
def test_rate_limits_mean_wait(w, prep, why):
    db = w["db"]
    i = queued(w)
    prep(db)
    r = claim_for_send(db, i)
    assert r["action"] == "wait" and failed_ids(r["checks"]) == {11}
    assert why in next(c for c in r["checks"] if c["id"] == 11)["detail"]


def test_rate_limit_window_moves_on(w):
    db = w["db"]
    i = queued(w)
    for n in range(20):
        sent(db, f"x{n}@far.de", ago="25 hours")  # outside the rolling 24 h
    sent(db, "y@far.de", ago="2 minutes")          # outside the 90 s gap
    assert claim_for_send(db, i)["action"] == "send"


@pytest.mark.parametrize("change,expected", [
    (lambda w: w["db"].execute("UPDATE companies SET stage = 'closed', close_reason = 'x' WHERE id = %s", (w["company"],)), {4}),  # noqa: E501
    (lambda w: w["db"].execute("UPDATE contacts SET email_class = 'unsuitable', email_class_manual = true WHERE id = %s", (w["contact"],)), {3}),  # noqa: E501
    (lambda w: sent(w["db"], "jobs@acme.de", company=w["company"], ago="1 hour"), {7}),
    (lambda w: w["db"].execute("UPDATE outbound_emails SET approved_at = now() - interval '8 days' "
                               "WHERE status = 'queued'"), {10}),
])
def test_approved_then_unsafe_is_cancelled_at_send(w, change, expected):
    db = w["db"]
    i = queued(w)
    change(w)
    r = claim_for_send(db, i)
    assert (r["action"], failed_ids(r["checks"])) == ("cancelled", expected)
    e = row(db, i)
    assert e["status"] == "cancelled" and e["cancel_reason"].startswith(f"{min(expected)}. ")
    assert audits(db, i)[-1]["data"]["stage"] == "send"
    event = audits(db, i, "outbound_email.cancelled")[-1]["data"]
    assert event["reason"] == "safety_checks" and event["failed"] == sorted(expected)


def test_temporary_plus_permanent_failure_cancels(w):
    db = w["db"]
    i = queued(w)
    db.execute("UPDATE app_settings SET sending_enabled = false")
    db.execute("UPDATE companies SET stage = 'on_hold' WHERE id = %s", (w["company"],))
    assert claim_for_send(db, i)["action"] == "cancelled"


def test_block_after_approval_never_reaches_send(w):
    """M25 cancels it the moment it is blocked; the send claim then skips it. Check 1 also fails on its own."""
    db = w["db"]
    i = queued(w)
    before = row(db, i)
    fail_1(w)
    assert row(db, i)["status"] == "cancelled"
    assert claim_for_send(db, i)["action"] == "skip"
    assert failed_ids(run_checks(db, before, "send")) >= {1}


@pytest.mark.parametrize("edit,expected", [
    ({"subject": "Hi {{company_name}}"}, {8}),
    ({"body": " "}, {9}),
    ({"content_hash": b"\x00"}, {10}),
    ({"approved_at": None}, {10}),
])
def test_send_stage_content_and_approval_checks(w, edit, expected):
    """Content can't change after approval (DB constraint), so these are checked on the row as the worker sees it."""
    db = w["db"]
    e = {**row(db, queued(w)), **edit}
    assert failed_ids(run_checks(db, e, "send")) == expected


def test_duplicate_in_flight_rechecked_at_send(w):
    db = w["db"]
    i = queued(w)
    e = {**row(db, i), "id": 0}  # as if another row for the same address were being claimed
    assert failed_ids(run_checks(db, e, "send")) == {5}


def test_claim_skips_non_queued(w):
    i = draft(w["db"], w["company"], w["contact"])
    assert claim_for_send(w["db"], i)["action"] == "skip"
    with pytest.raises(HTTPException):
        claim_for_send(w["db"], 999999)


# ---------- API dry run ----------

def test_dry_run_endpoint(client, test_url):
    import psycopg
    assert TestClient(app).get("/outbound-emails/1/checks").status_code == 401
    assert client.get("/outbound-emails/999999/checks").status_code == 404
    co = client.post("/companies", json={"name": "Acme", "domain": "acme.de"}).json()["id"]
    ct = client.post(f"/companies/{co}/contacts", json={"email": "jobs@acme.de"}).json()["id"]
    with psycopg.connect(test_url) as conn:
        i = conn.execute("INSERT INTO outbound_emails (to_email, subject, body, company_id, contact_id) "
                         "VALUES ('jobs@acme.de', 'Hi', 'Body', %s, %s) RETURNING id", (co, ct)).fetchone()[0]
    r = client.get(f"/outbound-emails/{i}/checks").json()
    assert r["ok"] is True and len(r["checks"]) == 12
    r = client.get(f"/outbound-emails/{i}/checks", params={"stage": "send"}).json()
    assert r["ok"] is False and {c["id"] for c in r["checks"] if not c["ok"]} == {10, 12}  # not approved; sending off
    with psycopg.connect(test_url) as conn:
        assert conn.execute("SELECT status FROM outbound_emails WHERE id = %s", (i,)).fetchone()[0] == "draft"
