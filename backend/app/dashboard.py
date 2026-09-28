"""M18: dashboard. One call, a handful of indexed queries.

KPI definitions (PROJECT.md M18), for the chosen period:
  leads        active companies (+ count per stage; not period-bound)
  sent         emails with status 'sent' in the period (+ daily series)
  replies      inbound messages labelled 'reply' received in the period (+ distinct companies)
  reply_rate   companies emailed in the period that replied after being emailed / companies emailed in the period
  interested   replies in the period whose verified AI label is interested / interview_request / scheduling /
               needs_info / offer
  offers       replies in the period with verified AI label 'offer'
Opportunities and interviews are placeholders until M19 / M20.
"""
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends

from app.deps import get_db, require_owner
from app.opportunities import OPEN as OPEN_STAGES

router = APIRouter(dependencies=[Depends(require_owner)])

INTERESTED = ["interested", "interview_request", "scheduling", "needs_info", "offer"]
PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}
SERIES_DAYS_ALL = 90


def since_for(period: str) -> datetime | None:
    days = PERIODS[period]
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


def opportunity_counts(conn) -> dict:
    """M19: open opportunities now (not period-bound), plus the count per stage."""
    by_stage = {r["stage"]: r["n"] for r in conn.execute(
        "SELECT stage, count(*) AS n FROM opportunities GROUP BY stage").fetchall()}
    return {"available": True, "open": sum(n for s, n in by_stage.items() if s in OPEN_STAGES), "by_stage": by_stage}


def kpis(conn, since: datetime | None) -> dict:
    p = {"since": since, "interested": INTERESTED}
    leads = conn.execute("SELECT stage, count(*) AS n FROM companies WHERE archived_at IS NULL GROUP BY stage").fetchall()
    sent = conn.execute(
        "SELECT count(*) AS sent, count(DISTINCT company_id) AS companies_emailed FROM outbound_emails "
        "WHERE status = 'sent' AND (%(since)s::timestamptz IS NULL OR sent_at >= %(since)s)", p).fetchone()
    replies = conn.execute(
        "SELECT count(*) FILTER (WHERE m.label = 'reply') AS replies, "
        "count(DISTINCT m.company_id) FILTER (WHERE m.label = 'reply') AS companies_replied, "
        "count(*) FILTER (WHERE m.label = 'bounce') AS bounces, "
        "count(*) FILTER (WHERE m.label = 'auto_reply') AS auto_replies, "
        "count(*) FILTER (WHERE m.label = 'reply' AND a.status = 'ok' AND a.label = ANY(%(interested)s)) AS interested, "
        "count(*) FILTER (WHERE m.label = 'reply' AND a.status = 'ok' AND a.label = 'offer') AS offers "
        "FROM inbound_messages m LEFT JOIN ai_analyses a ON a.inbound_message_id = m.id "
        "WHERE m.label IN ('reply', 'bounce', 'auto_reply') "
        "AND (%(since)s::timestamptz IS NULL OR m.received_at >= %(since)s)", p).fetchone()
    replied_after_email = conn.execute(
        "WITH emailed AS (SELECT company_id, min(sent_at) AS first_sent FROM outbound_emails WHERE status = 'sent' "
        "AND company_id IS NOT NULL AND (%(since)s::timestamptz IS NULL OR sent_at >= %(since)s) GROUP BY company_id) "
        "SELECT count(*) AS n FROM emailed e WHERE EXISTS (SELECT 1 FROM inbound_messages m WHERE m.company_id = "
        "e.company_id AND m.label = 'reply' AND m.received_at >= e.first_sent)", p).fetchone()["n"]
    emailed = sent["companies_emailed"]
    return {
        "leads": {"total": sum(r["n"] for r in leads), "by_stage": {r["stage"]: r["n"] for r in leads}},
        "sent": sent["sent"], "companies_emailed": emailed,
        "replies": replies["replies"], "companies_replied": replies["companies_replied"],
        "reply_rate": round(replied_after_email / emailed, 4) if emailed else None,
        "interested": replies["interested"], "offers": replies["offers"],
        "bounces": replies["bounces"], "auto_replies": replies["auto_replies"],
        "opportunities": opportunity_counts(conn),
        "interviews": {"available": False, "after": "M20"},
    }


def sent_series(conn, since: datetime | None) -> list[dict]:
    cutoff = since or datetime.now(timezone.utc) - timedelta(days=SERIES_DAYS_ALL)
    start = cutoff.date()
    # Same cut-off as the 'sent' KPI, so the series always adds up to it.
    rows = {r["day"]: r["n"] for r in conn.execute(
        "SELECT (sent_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n FROM outbound_emails "
        "WHERE status = 'sent' AND sent_at >= %s GROUP BY 1", (cutoff,)).fetchall()}
    days = (datetime.now(timezone.utc).date() - start).days
    return [{"day": d, "sent": rows.get(d, 0)} for d in (start + timedelta(days=i) for i in range(days + 1))]


def feeds(conn, today: date) -> dict:
    return {
        "latest_replies": conn.execute(
            "SELECT m.id, m.from_email, m.from_name, m.subject, m.received_at, m.label, m.company_id, c.name AS "
            "company_name, a.label AS ai_label, coalesce(m.gmail_thrid, 'in-' || m.id) AS thread_key "
            "FROM inbound_messages m LEFT JOIN companies c ON c.id = m.company_id "
            "LEFT JOIN ai_analyses a ON a.inbound_message_id = m.id AND a.status = 'ok' "
            "WHERE m.label IN ('reply', 'auto_reply', 'bounce') ORDER BY m.received_at DESC NULLS LAST, m.id DESC LIMIT 8"
        ).fetchall(),
        "tasks": conn.execute(
            "SELECT id, title, due_date, due_date < %s AS overdue FROM tasks WHERE done_at IS NULL AND deleted_at IS NULL "
            "AND due_date IS NOT NULL AND due_date <= %s ORDER BY due_date, id LIMIT 8",
            (today, today + timedelta(days=7))).fetchall(),
        "activity": conn.execute(
            "SELECT id, at, actor, action, entity_type, entity_id, data FROM audit_log ORDER BY id DESC LIMIT 12"
        ).fetchall(),
    }


@router.get("/dashboard")
def dashboard(period: Literal["7", "30", "90", "all"] = "30", today: date | None = None, conn=Depends(get_db)):
    started = time.perf_counter()
    since = since_for(period)
    out = {"period": period, "since": since, "kpis": kpis(conn, since), "sent_series": sent_series(conn, since),
           **feeds(conn, today or datetime.now(timezone.utc).date())}
    out["query_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out
