"""M26: the 12 email safety checks, run at approval and again at send.

approve()        : M10's only way to approve an email. Any failed check refuses approval.
claim_for_send() : M12's only way to move a queued email to 'sending'. Re-runs all 12 under a
                   row lock; checks 11-12 failing means wait, anything else cancels the email.
Connections must use dict rows.
"""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.csv_import import clean_email
from app.deps import audit, get_db, require_owner
from app.templating import TOKEN_RE

Stage = Literal["approval", "send"]

CHECKS = {
    1: "Do-not-contact",
    2: "Valid address",
    3: "Known, suitable contact",
    4: "Active lead",
    5: "No duplicate in flight",
    6: "Recipient cooldown",
    7: "Company cooldown",
    8: "Variables resolved",
    9: "Content complete",
    10: "Approval valid",
    11: "Rate limits",
    12: "Kill switch",
}
TEMPORARY = {11, 12}  # at send: wait and retry instead of cancelling
SUBJECT_MAX, BODY_MAX = 200, 20000
IN_FLIGHT = ("approved", "queued", "sending")

router = APIRouter(dependencies=[Depends(require_owner)])


def get_settings(conn) -> dict:
    return conn.execute("SELECT * FROM app_settings WHERE id = 1").fetchone()


def run_checks(conn, email: dict, stage: Stage) -> list[dict]:
    """All 12 checks for one email. Each result: id, name, ok, applies, detail, temporary."""
    s = get_settings(conn)
    to = email["to_email"].strip().lower()
    contact = conn.execute("SELECT * FROM contacts WHERE id = %s", (email["contact_id"],)).fetchone() \
        if email.get("contact_id") else None
    company = conn.execute("SELECT * FROM companies WHERE id = %s", (email["company_id"],)).fetchone() \
        if email.get("company_id") else None
    results = []

    def add(i: int, ok: bool, detail: str = "", applies: bool = True):
        results.append({"id": i, "name": CHECKS[i], "ok": ok, "applies": applies, "detail": detail,
                        "temporary": i in TEMPORARY})

    def one(sql: str, *params):
        return conn.execute(sql, params).fetchone()

    # 1. Do-not-contact
    add(1, not one("SELECT is_suppressed(%s) AS s", to)["s"], "recipient is on the do-not-contact list")

    # 2. Valid address
    cleaned, why = clean_email(email["to_email"])
    add(2, cleaned == to and why is None, why or "address had to be cleaned; fix the contact first")

    # 3. Known, suitable contact
    if not contact:
        add(3, False, "recipient is not a stored contact")
    elif contact["archived_at"]:
        add(3, False, "contact is archived")
    elif contact["email"] != to or contact["company_id"] != email.get("company_id"):
        add(3, False, "recipient does not match the contact / company on this email")
    else:
        add(3, contact["email_class"] != "unsuitable", "contact's email class is unsuitable")

    # 4. Active lead
    if not company:
        add(4, False, "email is not linked to a company")
    elif company["archived_at"]:
        add(4, False, "company is archived")
    else:
        add(4, company["stage"] not in ("closed", "on_hold"), f"lead stage is {company['stage']}")

    # 5. No duplicate in flight
    dup = one("SELECT id FROM outbound_emails WHERE lower(to_email) = %s AND status = ANY(%s) AND id <> %s LIMIT 1",
              to, list(IN_FLIGHT), email.get("id") or 0)
    add(5, dup is None, f"email #{dup['id']} to this address is already in flight" if dup else "")

    # 6. Recipient cooldown
    last = one("SELECT max(sent_at) AS t FROM outbound_emails WHERE status = 'sent' AND lower(to_email) = %s "
               "AND sent_at > now() - make_interval(days => %s)", to, s["recipient_cooldown_days"])["t"]
    add(6, last is None, f"emailed on {last:%Y-%m-%d}; cooldown is {s['recipient_cooldown_days']} days" if last else "")

    # 7. Company cooldown
    last = one("SELECT max(sent_at) AS t FROM outbound_emails WHERE status = 'sent' AND company_id = %s "
               "AND sent_at > now() - make_interval(days => %s)", email.get("company_id"), s["company_cooldown_days"])["t"]
    add(7, last is None,
        f"company emailed on {last:%Y-%m-%d}; cooldown is {s['company_cooldown_days']} days" if last else "")

    # 8. Variables resolved
    text = email["subject"] + "\n" + email["body"]
    left = sorted({m.group(1) or m.group(0) for m in TOKEN_RE.finditer(text)})
    stray = "{{" in TOKEN_RE.sub("", text) or "}}" in TOKEN_RE.sub("", text)
    add(8, not left and not stray,
        ("unresolved: " + ", ".join(left)) if left else "stray braces in subject or body")

    # 9. Content complete
    subject, body = email["subject"].strip(), email["body"].strip()
    add(9, 1 <= len(subject) <= SUBJECT_MAX and 1 <= len(body) <= BODY_MAX,
        f"subject must be 1-{SUBJECT_MAX} characters and body 1-{BODY_MAX}")

    # 10. Approval valid (send only)
    if stage == "send":
        ok = (email["approved_at"] is not None and email["approved_content_hash"] == email["content_hash"]
              and one("SELECT %s > now() - make_interval(days => %s) AS fresh",
                      email["approved_at"], s["approval_max_age_days"])["fresh"])
        add(10, bool(ok), f"approval missing, changed or older than {s['approval_max_age_days']} days")
    else:
        add(10, True, "checked at send", applies=False)

    # 11. Rate limits
    if stage == "send":
        r = one("SELECT count(*) FILTER (WHERE sent_at > now() - interval '24 hours') AS day, "
                "max(sent_at) > now() - make_interval(secs => %s) AS too_soon "
                "FROM outbound_emails WHERE status = 'sent'", s["min_gap_seconds"])
        detail = (f"daily cap reached ({r['day']}/{s['daily_cap']} in 24 h)" if r["day"] >= s["daily_cap"]
                  else f"less than {s['min_gap_seconds']} s since the last send" if r["too_soon"] else "")
        add(11, not detail, detail)
    else:
        waiting = one("SELECT count(*) AS n FROM outbound_emails WHERE status = ANY(%s) AND id <> %s",
                      list(IN_FLIGHT), email.get("id") or 0)["n"]
        add(11, waiting < s["daily_cap"], f"{waiting} emails already waiting; daily cap is {s['daily_cap']}")

    # 12. Kill switch (send only)
    if stage == "send":
        add(12, s["sending_enabled"], "sending is switched off")
    else:
        add(12, True, "checked at send", applies=False)

    for r in results:
        if r["ok"] and r["applies"]:
            r["detail"] = ""
    return results


def failed(results: list[dict]) -> list[dict]:
    return [r for r in results if not r["ok"]]


def _audit_failure(conn, email_id: int, stage: Stage, bad: list[dict]):
    audit(conn, "outbound_email.checks_failed", "outbound_email", email_id,
          {"stage": stage, "failed": [{"id": r["id"], "name": r["name"], "detail": r["detail"]} for r in bad]})


def _lock(conn, email_id: int) -> dict:
    e = conn.execute("SELECT * FROM outbound_emails WHERE id = %s FOR UPDATE", (email_id,)).fetchone()
    if not e:
        raise HTTPException(404, "Email not found")
    return e


def approve(conn, email_id: int) -> dict:
    """Approve a draft only if every approval-stage check passes. Returns {approved, checks}."""
    e = _lock(conn, email_id)
    if e["status"] != "draft":
        raise HTTPException(409, f"Only drafts can be approved (this email is {e['status']})")
    results = run_checks(conn, e, "approval")
    bad = failed(results)
    if bad:
        _audit_failure(conn, email_id, "approval", bad)
        return {"approved": False, "checks": results}
    conn.execute("UPDATE outbound_emails SET status = 'approved', approved_at = now(), "
                 "approved_content_hash = content_hash WHERE id = %s", (email_id,))
    return {"approved": True, "checks": results}


def claim_for_send(conn, email_id: int) -> dict:
    """Re-run all 12 checks on a queued email under a row lock.
    Returns action 'send' (now status 'sending'), 'wait' (still queued) or 'cancelled'."""
    # ponytail: row lock covers one email; rate limits rely on M12's single-lane worker.
    e = _lock(conn, email_id)
    if e["status"] != "queued":
        return {"action": "skip", "status": e["status"], "checks": []}
    results = run_checks(conn, e, "send")
    bad = failed(results)
    if not bad:
        conn.execute("UPDATE outbound_emails SET status = 'sending' WHERE id = %s", (email_id,))
        return {"action": "send", "checks": results}
    if all(r["temporary"] for r in bad):
        return {"action": "wait", "checks": results}  # not audited: it is retried, and would repeat every tick
    reason = "; ".join(f"{r['id']}. {r['name']}: {r['detail']}" for r in bad)
    ctx = {"reason": "safety_checks", "failed": [r["id"] for r in bad]}
    conn.execute("SELECT set_config('app.status_context', %s, true)", (json.dumps(ctx),))
    conn.execute("UPDATE outbound_emails SET status = 'cancelled', cancel_reason = %s WHERE id = %s", (reason, email_id))
    conn.execute("SELECT set_config('app.status_context', '', true)")
    _audit_failure(conn, email_id, "send", bad)
    return {"action": "cancelled", "checks": results, "reason": reason}


@router.get("/outbound-emails/{email_id}/checks")
def dry_run(email_id: int, stage: Stage = "approval", conn=Depends(get_db)):
    """Run the checks without changing anything (for the composer UI)."""
    e = conn.execute("SELECT * FROM outbound_emails WHERE id = %s", (email_id,)).fetchone()
    if not e:
        raise HTTPException(404, "Email not found")
    results = run_checks(conn, e, stage)
    return {"stage": stage, "ok": not failed(results), "checks": results}
