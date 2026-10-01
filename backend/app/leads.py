"""M6: lead management (a lead is a company): filters, bulk stage changes, compose list.
M22 adds text, reply, AI-label, template and date filters."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai_analysis import LABELS
from app.deps import audit, get_db, require_owner
from app.search import like_pattern

AILabel = Literal[LABELS]

router = APIRouter(dependencies=[Depends(require_owner)])

Stage = Literal["new", "qualified", "contacted", "replied", "closed", "on_hold"]
MAX_ROWS = 500

# A company is blocked if it has an active company block or its domain is blocked.
BLOCKED_SQL = """(
    EXISTS (SELECT 1 FROM suppressions s WHERE s.lifted_at IS NULL AND s.kind = 'company' AND s.company_id = c.id)
    OR (c.domain <> '' AND is_suppressed('probe@' || c.domain))
)"""

# Best recipient per company: active, unblocked, never unsuitable; careers > personal > generic.
BEST_RECIPIENT_SQL = """
SELECT DISTINCT ON (ct.company_id) ct.company_id, ct.id AS contact_id, ct.email, ct.name, ct.email_class
FROM contacts ct
WHERE ct.company_id = ANY(%(ids)s) AND ct.archived_at IS NULL AND ct.email <> ''
  AND ct.email_class <> 'unsuitable' AND NOT is_suppressed(ct.email)
ORDER BY ct.company_id, CASE ct.email_class WHEN 'careers' THEN 0 WHEN 'personal' THEN 1 ELSE 2 END, ct.id
"""


def best_recipients(conn, company_ids: list[int]) -> dict[int, dict]:
    if not company_ids:
        return {}
    return {r["company_id"]: r for r in conn.execute(BEST_RECIPIENT_SQL, {"ids": company_ids}).fetchall()}


@router.get("/leads")
def list_leads(
    stage: Stage | None = None,
    country: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    source: Literal["manual", "csv_import"] | None = None,
    has_email: bool | None = None,
    has_careers: bool | None = None,
    include_blocked: bool = False,
    archived: bool = False,
    # M22 filters
    q: str | None = None,
    replied: bool | None = None,
    ai_label: AILabel | None = None,
    template_id: int | None = None,
    emailed_from: date | None = None,
    emailed_to: date | None = None,
    replied_from: date | None = None,
    replied_to: date | None = None,
    added_from: date | None = None,
    added_to: date | None = None,
    conn=Depends(get_db, scope="function"),
):
    blank = lambda v: v.strip() if v and v.strip() else None  # noqa: E731
    rows = conn.execute(
        # Per-company figures are computed once as grouped tables and joined (M22: < 300 ms at 10k companies),
        # instead of one lookup per company.
        f"""
        WITH x AS (
            SELECT company_id,
                   count(*) FILTER (WHERE archived_at IS NULL) AS contact_count,
                   count(*) FILTER (WHERE archived_at IS NULL AND email <> ''
                                    AND email_class <> 'unsuitable') AS usable_emails,
                   count(*) FILTER (WHERE archived_at IS NULL AND email_class = 'careers') AS careers_emails
            FROM contacts GROUP BY company_id),
        le AS (SELECT company_id, max(sent_at) AS last_emailed_at FROM outbound_emails
               WHERE status = 'sent' AND company_id IS NOT NULL GROUP BY company_id),
        lr AS (SELECT company_id, max(received_at) AS last_reply_at FROM inbound_messages
               WHERE label = 'reply' AND company_id IS NOT NULL GROUP BY company_id),
        -- Same meaning as BLOCKED_SQL: a company block on it, or a domain / company block covering its domain.
        bl AS (
            SELECT c2.id FROM companies c2 JOIN suppressions s ON s.lifted_at IS NULL AND (
                   (s.kind = 'company' AND s.company_id = c2.id)
                OR (s.kind = 'domain' AND c2.domain <> '' AND (c2.domain = s.domain OR c2.domain LIKE '%%.' || s.domain)))
            UNION
            SELECT c2.id FROM suppressions s JOIN companies sc ON sc.id = s.company_id AND sc.domain <> ''
            JOIN companies c2 ON c2.domain <> '' AND (c2.domain = sc.domain OR c2.domain LIKE '%%.' || sc.domain)
            WHERE s.lifted_at IS NULL AND s.kind = 'company')
        SELECT c.id, c.name, c.domain, c.city, c.country, c.industry, c.source, c.stage, c.stage_changed_at,
               c.close_reason, c.archived_at, c.created_at, coalesce(x.contact_count, 0) AS contact_count,
               coalesce(x.usable_emails, 0) AS usable_emails, coalesce(x.careers_emails, 0) AS careers_emails,
               (bl.id IS NOT NULL) AS blocked, (cl.company_id IS NOT NULL) AS in_compose_list,
               le.last_emailed_at, lr.last_reply_at
        FROM companies c
        LEFT JOIN x ON x.company_id = c.id
        LEFT JOIN le ON le.company_id = c.id
        LEFT JOIN lr ON lr.company_id = c.id
        LEFT JOIN (SELECT DISTINCT id FROM bl) bl ON bl.id = c.id
        LEFT JOIN compose_list cl ON cl.company_id = c.id
        WHERE (c.archived_at IS NOT NULL) = %(archived)s
          AND (%(stage)s::text IS NULL OR c.stage = %(stage)s)
          AND (%(country)s::text IS NULL OR lower(c.country) = lower(%(country)s))
          AND (%(city)s::text IS NULL OR lower(c.city) = lower(%(city)s))
          AND (%(industry)s::text IS NULL OR strpos(lower(c.industry), lower(%(industry)s)) > 0)
          AND (%(source)s::text IS NULL OR c.source = %(source)s)
          AND (%(has_email)s::boolean IS NULL OR (coalesce(x.usable_emails, 0) > 0) = %(has_email)s)
          AND (%(has_careers)s::boolean IS NULL OR (coalesce(x.careers_emails, 0) > 0) = %(has_careers)s)
          AND (%(include_blocked)s OR bl.id IS NULL)
          AND (%(q)s::text IS NULL OR lower(c.name) LIKE %(q)s OR c.domain LIKE %(q)s)
          AND (%(replied)s::boolean IS NULL OR (lr.last_reply_at IS NOT NULL) = %(replied)s)
          AND (%(ai_label)s::text IS NULL OR c.id IN (
                SELECT m.company_id FROM ai_analyses a JOIN inbound_messages m ON m.id = a.inbound_message_id
                WHERE a.status = 'ok' AND a.label = %(ai_label)s AND m.label = 'reply'))
          AND (%(template)s::bigint IS NULL OR c.id IN (
                SELECT o.company_id FROM template_versions tv JOIN outbound_emails o ON o.template_version_id = tv.id
                WHERE tv.template_id = %(template)s AND o.status = 'sent'))
          AND (%(emailed_from)s::date IS NULL OR le.last_emailed_at >= %(emailed_from)s)
          AND (%(emailed_to)s::date IS NULL OR le.last_emailed_at < %(emailed_to)s::date + 1)
          AND (%(replied_from)s::date IS NULL OR lr.last_reply_at >= %(replied_from)s)
          AND (%(replied_to)s::date IS NULL OR lr.last_reply_at < %(replied_to)s::date + 1)
          AND (%(added_from)s::date IS NULL OR c.created_at >= %(added_from)s)
          AND (%(added_to)s::date IS NULL OR c.created_at < %(added_to)s::date + 1)
        ORDER BY lower(c.name), c.id
        LIMIT {MAX_ROWS + 1}
        """,
        {"archived": archived, "stage": stage, "country": blank(country), "city": blank(city),
         "industry": blank(industry), "source": source, "has_email": has_email, "has_careers": has_careers,
         "include_blocked": include_blocked, "q": like_pattern(blank(q)) if blank(q) else None, "replied": replied,
         "ai_label": ai_label, "template": template_id, "emailed_from": emailed_from, "emailed_to": emailed_to,
         "replied_from": replied_from, "replied_to": replied_to, "added_from": added_from, "added_to": added_to},
    ).fetchall()
    return {"leads": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


class StageIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    company_ids: list[int] = Field(min_length=1, max_length=MAX_ROWS)
    stage: Stage
    close_reason: str = Field("", max_length=500)

    @model_validator(mode="after")
    def _reason(self):
        if self.stage == "closed" and not self.close_reason:
            raise ValueError("closing a lead needs a reason")
        return self


def require_companies(conn, ids: list[int]) -> None:
    found = {r["id"] for r in conn.execute("SELECT id FROM companies WHERE id = ANY(%s)", (ids,)).fetchall()}
    missing = sorted(set(ids) - found)
    if missing:
        raise HTTPException(404, f"Companies not found: {missing}")


@router.post("/leads/stage")
def set_stage(body: StageIn, conn=Depends(get_db, scope="function")):
    """Bulk stage change. Each actual change is logged by the DB trigger."""
    require_companies(conn, body.company_ids)
    reason = body.close_reason if body.stage == "closed" else None
    changed = conn.execute(
        "UPDATE companies SET stage = %s, close_reason = %s, updated_at = now() "
        "WHERE id = ANY(%s) AND (stage IS DISTINCT FROM %s OR close_reason IS DISTINCT FROM %s) RETURNING id",
        (body.stage, reason, body.company_ids, body.stage, reason),
    ).fetchall()
    return {"changed": len(changed)}


class ComposeIn(BaseModel):
    company_ids: list[int] = Field(min_length=1, max_length=MAX_ROWS)


@router.get("/compose-list")
def get_compose_list(conn=Depends(get_db, scope="function")):
    items = conn.execute(
        f"SELECT c.id AS company_id, c.name, c.domain, c.stage, cl.added_at, {BLOCKED_SQL} AS blocked "
        "FROM compose_list cl JOIN companies c ON c.id = cl.company_id ORDER BY cl.added_at, c.id"
    ).fetchall()
    best = best_recipients(conn, [i["company_id"] for i in items])
    for i in items:
        i["recipient"] = None if i["blocked"] else best.get(i["company_id"])
        i["problem"] = ("company is blocked" if i["blocked"]
                        else None if i["recipient"] else "no eligible recipient")
    return items


@router.post("/compose-list")
def add_to_compose_list(body: ComposeIn, conn=Depends(get_db, scope="function")):
    ids = sorted(set(body.company_ids))
    require_companies(conn, ids)
    companies = {r["id"]: r for r in conn.execute(
        f"SELECT c.id, c.name, c.archived_at, {BLOCKED_SQL} AS blocked FROM companies c WHERE c.id = ANY(%s)", (ids,)
    ).fetchall()}
    best = best_recipients(conn, ids)
    added, already, refused = [], [], []
    for cid in ids:
        c = companies[cid]
        reason = ("archived" if c["archived_at"] else "company is blocked" if c["blocked"]
                  else None if cid in best else "no eligible recipient")
        if reason:
            refused.append({"company_id": cid, "name": c["name"], "reason": reason})
        elif conn.execute("INSERT INTO compose_list (company_id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING company_id",
                          (cid,)).fetchone():
            added.append(cid)
        else:
            already.append(cid)
    if added:
        audit(conn, "compose_list.added", "compose_list", None, {"company_ids": added})
    return {"added": added, "already": already, "refused": refused}


@router.delete("/compose-list/{company_id}")
def remove_from_compose_list(company_id: int, conn=Depends(get_db, scope="function")):
    if not conn.execute("DELETE FROM compose_list WHERE company_id = %s RETURNING company_id", (company_id,)).fetchone():
        raise HTTPException(404, "Not in the compose list")
    audit(conn, "compose_list.removed", "compose_list", None, {"company_ids": [company_id]})
    return {"removed": company_id}
