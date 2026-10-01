"""M28: analytics. Reply and bounce rates by template version, country, industry and source.

Definitions (PROJECT.md M28), for emails sent in the period:
  replied      a real reply (label 'reply') is credited to the latest email sent to that company before the
               reply arrived; an email counts as replied if at least one reply is credited to it
  bounce       the email itself was marked bounced (hard / soft) by M15
  opportunities  opportunities created from replies credited to the email (manual ones are not attributable)
Industry values like "A, B" are split: the company counts in each. Groups under FEW_DATA sent are flagged.
"""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends

from app.dashboard import PERIODS, since_for
from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

FEW_DATA = 10
EMAILS = """
WITH credit AS (  -- per reply, the latest email sent to that company before it (index outbound_emails_sent_company)
    SELECT m.id AS msg_id, e.id AS email_id
    FROM inbound_messages m
    CROSS JOIN LATERAL (SELECT id FROM outbound_emails
                        WHERE company_id = m.company_id AND status = 'sent' AND sent_at <= m.received_at
                        ORDER BY sent_at DESC, id DESC LIMIT 1) e
    WHERE m.label = 'reply'
), per_email AS (
    SELECT cr.email_id, count(DISTINCT cr.msg_id) AS replies, count(DISTINCT o.id) AS opportunities
    FROM credit cr LEFT JOIN opportunities o ON o.inbound_message_id = cr.msg_id
    GROUP BY cr.email_id
)
SELECT e.id, e.bounce_type, coalesce(pe.replies, 0) > 0 AS replied, coalesce(pe.opportunities, 0) AS opportunities,
       coalesce(t.name || ' v' || v.version, '(no template)') AS template_version,
       coalesce(nullif(btrim(c.country), ''), '(unknown)') AS country,
       c.industry,
       CASE WHEN c.source = 'csv_import' THEN 'CSV: ' || coalesce(nullif(c.source_detail->>'file', ''), '(file unknown)')
            ELSE 'Manual' END AS source
FROM outbound_emails e
LEFT JOIN companies c ON c.id = e.company_id
LEFT JOIN template_versions v ON v.id = e.template_version_id
LEFT JOIN templates t ON t.id = v.template_id
LEFT JOIN per_email pe ON pe.email_id = e.id
WHERE e.status = 'sent' AND (%(since)s::timestamptz IS NULL OR e.sent_at >= %(since)s)
"""


def industries(value: str | None) -> list[str]:
    parts = [p.strip() for p in (value or "").split(",") if p.strip()]
    return list(dict.fromkeys(parts)) or ["(none)"]


def stats(rows: list[dict]) -> dict:
    sent = len(rows)
    replied = sum(r["replied"] for r in rows)
    hard = sum(r["bounce_type"] == "hard" for r in rows)
    soft = sum(r["bounce_type"] == "soft" for r in rows)
    rate = lambda n: round(n / sent, 4) if sent else None  # noqa: E731
    return {"sent": sent, "replied": replied, "reply_rate": rate(replied),
            "bounced_hard": hard, "bounced_soft": soft, "bounce_rate": rate(hard + soft),
            "opportunities": sum(r["opportunities"] for r in rows), "few_data": sent < FEW_DATA}


def breakdown(rows: list[dict], key) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        for k in key(r):
            groups[k].append(r)
    return sorted(({"group": k, **stats(v)} for k, v in groups.items()), key=lambda g: (-g["sent"], g["group"]))


@router.get("/analytics")
def analytics(period: str = "30", conn=Depends(get_db, scope="function")):
    if period not in PERIODS:
        period = "30"
    started = time.perf_counter()
    rows = conn.execute(EMAILS, {"since": since_for(period)}).fetchall()
    return {
        "period": period, "overall": stats(rows), "few_data_below": FEW_DATA,
        "by_template_version": breakdown(rows, lambda r: [r["template_version"]]),
        "by_country": breakdown(rows, lambda r: [r["country"]]),
        "by_industry": breakdown(rows, lambda r: industries(r["industry"])),
        "by_source": breakdown(rows, lambda r: [r["source"]]),
        "query_ms": round((time.perf_counter() - started) * 1000),
    }
