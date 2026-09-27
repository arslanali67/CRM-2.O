"""M13: email history, per-email status timeline and threads.

A thread is Gmail's thread ID; an email without one yet is its own thread ("email-<id>").
Replies join these threads in M14/M15.
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.companies import fetch
from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

HistoryStatus = Literal["queued", "sending", "sent", "failed", "cancelled"]
THREAD_KEY = "coalesce(e.gmail_thrid, 'email-' || e.id)"
EMAIL_COLUMNS = f"""
    e.id, e.to_email, e.subject, e.status, e.company_id, c.name AS company_name, e.contact_id,
    e.created_at, e.approved_at, e.send_started_at, e.sent_at, e.cancel_reason, e.failure_reason,
    e.provider_message_id, e.gmail_msgid, e.gmail_thrid, {THREAD_KEY} AS thread_key,
    coalesce(e.sent_at, e.send_started_at, e.approved_at, e.created_at) AS last_activity_at
"""
FROM = "FROM outbound_emails e LEFT JOIN companies c ON c.id = e.company_id"
LIMIT = 500


@router.get("/history")
def history(status: HistoryStatus | None = None, company_id: int | None = None, since: date | None = None,
            until: date | None = None, q: str | None = None, conn=Depends(get_db)):
    """Every email past draft, newest activity first. Dates filter on the last activity (inclusive)."""
    q = q.strip() if q and q.strip() else None
    rows = conn.execute(
        f"""SELECT {EMAIL_COLUMNS} {FROM}
        WHERE e.status <> 'draft'
          AND (%(status)s::text IS NULL OR e.status = %(status)s)
          AND (%(company)s::bigint IS NULL OR e.company_id = %(company)s)
          AND (%(since)s::date IS NULL OR coalesce(e.sent_at, e.send_started_at, e.approved_at, e.created_at) >= %(since)s)
          AND (%(until)s::date IS NULL OR coalesce(e.sent_at, e.send_started_at, e.approved_at, e.created_at)
                                          < %(until)s::date + 1)
          AND (%(q)s::text IS NULL OR strpos(lower(e.to_email || ' ' || e.subject), lower(%(q)s)) > 0)
        ORDER BY last_activity_at DESC, e.id DESC LIMIT {LIMIT + 1}""",
        {"status": status, "company": company_id, "since": since, "until": until, "q": q},
    ).fetchall()
    counts = {r["status"]: r["count"] for r in conn.execute(
        "SELECT status, count(*) FROM outbound_emails WHERE status <> 'draft' GROUP BY status").fetchall()}
    return {"emails": rows[:LIMIT], "truncated": len(rows) > LIMIT, "counts": counts}


@router.get("/outbound-emails/{email_id}/timeline")
def timeline(email_id: int, conn=Depends(get_db)):
    """Every recorded event for one email, oldest first: status changes, check failures, recovery."""
    if not conn.execute("SELECT 1 FROM outbound_emails WHERE id = %s", (email_id,)).fetchone():
        raise HTTPException(404, "Email not found")
    return conn.execute(
        "SELECT id, at, actor, action, data FROM audit_log WHERE entity_type = 'outbound_email' AND entity_id = %s "
        "ORDER BY id", (email_id,)).fetchall()


@router.get("/threads/{thread_key}")
def thread(thread_key: str, conn=Depends(get_db)):
    emails = conn.execute(
        f"SELECT {EMAIL_COLUMNS}, e.body {FROM} WHERE {THREAD_KEY} = %s "
        "ORDER BY coalesce(e.sent_at, e.created_at), e.id", (thread_key,)).fetchall()
    if not emails:
        raise HTTPException(404, "Thread not found")
    return {"thread_key": thread_key, "gmail_thread": not thread_key.startswith("email-"), "emails": emails}


@router.get("/companies/{company_id}/emails")
def company_emails(company_id: int, conn=Depends(get_db)):
    """The company's emails (drafts included), grouped by thread, most recent thread first."""
    fetch(conn, "companies", company_id)
    rows = conn.execute(f"SELECT {EMAIL_COLUMNS} {FROM} WHERE e.company_id = %s "
                        "ORDER BY coalesce(e.sent_at, e.created_at), e.id", (company_id,)).fetchall()
    threads: dict[str, list] = {}
    for r in rows:
        threads.setdefault(r["thread_key"], []).append(r)
    return sorted(({"thread_key": k, "emails": v} for k, v in threads.items()),
                  key=lambda t: max(e["last_activity_at"] for e in t["emails"]), reverse=True)
