"""M19: job opportunity pipeline.

Only facts move a stage automatically: creation from a reply (-> new) and, from M20, recording an
interview (-> interviewing, via record_fact). AI labels never move a stage; they only produce a
suggestion the owner can accept with one click. Every stage change is logged by a DB trigger.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

Stage = Literal["new", "applied", "screening", "interviewing", "offer", "hired", "rejected", "withdrawn"]
STAGES = ("new", "applied", "screening", "interviewing", "offer", "hired", "rejected", "withdrawn")
OPEN = ("new", "applied", "screening", "interviewing", "offer")
# What a verified AI label would suggest. A suggestion only; never applied automatically.
AI_SUGGESTS = {"application_redirect": "applied", "interested": "screening", "needs_info": "screening",
               "interview_request": "interviewing", "scheduling": "interviewing", "offer": "offer",
               "rejection": "rejected", "not_hiring": "rejected"}


class OpportunityIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    inbound_message_id: int | None = None  # create from a reply (company and contact are taken from it)
    company_id: int | None = None          # or directly for a company
    contact_id: int | None = None

    @model_validator(mode="after")
    def _source(self):
        if (self.inbound_message_id is None) == (self.company_id is None):
            raise ValueError("give either inbound_message_id or company_id")
        return self


class StageIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    stage: Stage
    reason: str = Field("", max_length=500)


class EditIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    contact_id: int | None = None


def set_stage(conn, opportunity_id: int, stage: str, reason: str) -> bool:
    """Change a stage with a reason recorded in the history. Returns whether it changed."""
    conn.execute("SELECT set_config('app.stage_reason', %s, true)", (reason,))
    changed = conn.execute("UPDATE opportunities SET stage = %s, updated_at = now() WHERE id = %s AND stage <> %s "
                           "RETURNING id", (stage, opportunity_id, stage)).fetchone()
    conn.execute("SELECT set_config('app.stage_reason', '', true)")
    return bool(changed)


def record_fact(conn, opportunity_id: int, stage: str, reason: str) -> bool:
    """Automatic stage move for a recorded fact (e.g. M20: an interview was scheduled). Only moves forward
    out of new/applied/screening; never overrides a later or final stage."""
    current = conn.execute("SELECT stage FROM opportunities WHERE id = %s", (opportunity_id,)).fetchone()
    if not current or STAGES.index(current["stage"]) >= STAGES.index(stage) or current["stage"] not in OPEN:
        return False
    return set_stage(conn, opportunity_id, stage, reason)


def ai_suggestion(conn, opp: dict) -> dict | None:
    """The newest verified AI label on a reply from this company since the opportunity began."""
    a = conn.execute(
        "SELECT a.label, a.label_evidence, m.id AS inbound_message_id, m.received_at FROM inbound_messages m "
        "JOIN ai_analyses a ON a.inbound_message_id = m.id AND a.status = 'ok' "
        "WHERE m.company_id = %s AND m.label = 'reply' AND (m.id = %s OR m.received_at >= %s) "
        "ORDER BY m.received_at DESC NULLS LAST, m.id DESC LIMIT 1",
        (opp["company_id"], opp["inbound_message_id"], opp["created_at"])).fetchone()
    stage = AI_SUGGESTS.get(a["label"]) if a else None
    if not stage or stage == opp["stage"]:
        return None
    return {"stage": stage, "ai_label": a["label"], "evidence": a["label_evidence"],
            "inbound_message_id": a["inbound_message_id"]}


OPP_SELECT = ("SELECT o.*, c.name AS company_name, ct.name AS contact_name, ct.email AS contact_email, "
              "'/threads/' || coalesce(m.gmail_thrid, 'in-' || m.id) || '#in-' || m.id AS source_link, "
              "m.subject AS source_subject FROM opportunities o JOIN companies c ON c.id = o.company_id "
              "LEFT JOIN contacts ct ON ct.id = o.contact_id LEFT JOIN inbound_messages m ON m.id = o.inbound_message_id ")


def load(conn, opportunity_id: int) -> dict:
    o = conn.execute(OPP_SELECT + "WHERE o.id = %s", (opportunity_id,)).fetchone()
    if not o:
        raise HTTPException(404, "Opportunity not found")
    return o


@router.post("/opportunities", status_code=201)
def create(body: OpportunityIn, conn=Depends(get_db)):
    if body.inbound_message_id is not None:
        m = conn.execute("SELECT id, label, company_id, contact_id FROM inbound_messages WHERE id = %s",
                         (body.inbound_message_id,)).fetchone()
        if not m:
            raise HTTPException(404, "Message not found")
        if m["label"] != "reply" or not m["company_id"]:
            raise HTTPException(409, "Opportunities are created from replies linked to a company")
        company_id, contact_id = m["company_id"], body.contact_id or m["contact_id"]
        if conn.execute("SELECT 1 FROM opportunities WHERE inbound_message_id = %s", (m["id"],)).fetchone():
            raise HTTPException(409, "An opportunity already exists for this reply")
        reason = "created from a reply"
    else:
        if not conn.execute("SELECT 1 FROM companies WHERE id = %s", (body.company_id,)).fetchone():
            raise HTTPException(404, "Company not found")
        company_id, contact_id, reason = body.company_id, body.contact_id, "created manually"
    if contact_id and not conn.execute("SELECT 1 FROM contacts WHERE id = %s AND company_id = %s",
                                       (contact_id, company_id)).fetchone():
        raise HTTPException(404, "Contact not found at this company")
    conn.execute("SELECT set_config('app.stage_reason', %s, true)", (reason,))
    oid = conn.execute("INSERT INTO opportunities (company_id, contact_id, inbound_message_id, title) "
                       "VALUES (%s, %s, %s, %s) RETURNING id",
                       (company_id, contact_id, body.inbound_message_id, body.title)).fetchone()["id"]
    conn.execute("SELECT set_config('app.stage_reason', '', true)")
    audit(conn, "opportunity.created", "company", company_id, {"opportunity_id": oid, "title": body.title})
    return get_opportunity(oid, conn)


@router.get("/opportunities")
def list_opportunities(stage: Stage | None = None, company_id: int | None = None, conn=Depends(get_db)):
    rows = conn.execute(OPP_SELECT + "WHERE (%(s)s::text IS NULL OR o.stage = %(s)s) "
                        "AND (%(c)s::bigint IS NULL OR o.company_id = %(c)s) ORDER BY o.stage_changed_at DESC, o.id DESC",
                        {"s": stage, "c": company_id}).fetchall()
    for r in rows:
        r["suggestion"] = ai_suggestion(conn, r)
    counts = {r["stage"]: r["count"] for r in conn.execute(
        "SELECT stage, count(*) FROM opportunities GROUP BY stage").fetchall()}
    return {"opportunities": rows, "counts": counts, "stages": STAGES}


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: int, conn=Depends(get_db)):
    o = load(conn, opportunity_id)
    o["history"] = conn.execute("SELECT * FROM opportunity_stage_history WHERE opportunity_id = %s ORDER BY id",
                                (opportunity_id,)).fetchall()
    o["suggestion"] = ai_suggestion(conn, o)
    return o


@router.post("/opportunities/{opportunity_id}/stage")
def change_stage(opportunity_id: int, body: StageIn, conn=Depends(get_db)):
    o = load(conn, opportunity_id)
    if set_stage(conn, opportunity_id, body.stage, body.reason or "changed by owner"):
        audit(conn, "opportunity.stage_changed", "company", o["company_id"],
              {"opportunity_id": opportunity_id, "from": o["stage"], "to": body.stage, "reason": body.reason})
    return get_opportunity(opportunity_id, conn)


@router.put("/opportunities/{opportunity_id}")
def edit(opportunity_id: int, body: EditIn, conn=Depends(get_db)):
    o = load(conn, opportunity_id)
    if body.contact_id and not conn.execute("SELECT 1 FROM contacts WHERE id = %s AND company_id = %s",
                                            (body.contact_id, o["company_id"])).fetchone():
        raise HTTPException(404, "Contact not found at this company")
    conn.execute("UPDATE opportunities SET title = %s, contact_id = %s, updated_at = now() WHERE id = %s",
                 (body.title, body.contact_id, opportunity_id))
    return get_opportunity(opportunity_id, conn)
