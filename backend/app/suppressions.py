"""M25: do-not-contact list. Enforcement lives in the database (migration 0004)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.companies import conflict_as_409, fetch, normalize_domain
from app.deps import audit, get_db, require_owner
from app.email_class import EMAIL_RE

router = APIRouter(dependencies=[Depends(require_owner)])


class SuppressionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    kind: Literal["email", "domain", "company"]
    value: str = Field("", max_length=254)  # email or domain
    company_id: int | None = None
    reason: str = Field(min_length=1, max_length=500)


class LiftIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=500)


def target(body: SuppressionIn, conn) -> dict:
    t = {"email": None, "domain": None, "company_id": None}
    if body.kind == "email":
        email = body.value.lower()
        if not EMAIL_RE.match(email):
            raise HTTPException(422, "Not a valid email address")
        t["email"] = email
    elif body.kind == "domain":
        try:
            t["domain"] = normalize_domain(body.value)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        if not t["domain"]:
            raise HTTPException(422, "Domain is required")
    else:
        if body.company_id is None:
            raise HTTPException(422, "company_id is required")
        fetch(conn, "companies", body.company_id)
        t["company_id"] = body.company_id
    return t


@router.get("/suppressions")
def list_suppressions(conn=Depends(get_db, scope="function")):
    return conn.execute(
        "SELECT s.*, c.name AS company_name FROM suppressions s LEFT JOIN companies c ON c.id = s.company_id "
        "ORDER BY s.lifted_at IS NOT NULL, s.created_at DESC, s.id DESC"
    ).fetchall()


@router.post("/suppressions", status_code=201)
def add_suppression(body: SuppressionIn, conn=Depends(get_db, scope="function")):
    t = target(body, conn)
    with conflict_as_409("This is already blocked"):
        row = conn.execute(
            "INSERT INTO suppressions (kind, email, domain, company_id, reason) "
            "VALUES (%(kind)s, %(email)s, %(domain)s, %(company_id)s, %(reason)s) RETURNING *",
            {**t, "kind": body.kind, "reason": body.reason},
        ).fetchone()
    row["cancelled_emails"] = conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'outbound_email.cancelled' "
        "AND (data->>'suppression_id')::bigint = %s",
        (row["id"],),
    ).fetchone()["count"]
    audit(conn, "suppression.added", "suppression", row["id"],
          {"kind": body.kind, **{k: v for k, v in t.items() if v is not None}, "reason": body.reason,
           "cancelled_emails": row["cancelled_emails"]})
    return row


@router.post("/suppressions/{suppression_id}/lift")
def lift_suppression(suppression_id: int, body: LiftIn, conn=Depends(get_db, scope="function")):
    s = conn.execute("SELECT * FROM suppressions WHERE id = %s", (suppression_id,)).fetchone()
    if not s:
        raise HTTPException(404, "Block not found")
    if s["lifted_at"]:
        raise HTTPException(409, "This block is already lifted")
    row = conn.execute(
        "UPDATE suppressions SET lifted_at = now(), lift_reason = %s WHERE id = %s RETURNING *",
        (body.reason, suppression_id),
    ).fetchone()
    audit(conn, "suppression.lifted", "suppression", suppression_id, {"reason": body.reason})
    return row


@router.get("/suppressions/check")
def check(email: str, conn=Depends(get_db, scope="function")):
    return {"email": email, "suppressed": conn.execute("SELECT is_suppressed(%s)", (email,)).fetchone()["is_suppressed"]}
