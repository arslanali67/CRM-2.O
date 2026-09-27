"""M10: email composer. Drafts from the compose list, exact preview, per-email approval.

There is deliberately no endpoint that approves more than one email.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import safety
from app.deps import audit, get_db, require_owner
from app.leads import get_compose_list
from app.templates import variable_values
from app.templating import RenderError, render_strict

router = APIRouter(dependencies=[Depends(require_owner)])

OUTBOX_STATUSES = ("draft", "approved", "queued", "sending", "sent", "failed", "cancelled")


class DraftsIn(BaseModel):
    template_id: int
    attach_cv: bool = False
    cv_version_id: int | None = None  # default: the default CV


class DraftEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=safety.SUBJECT_MAX)
    body: str = Field(min_length=1, max_length=safety.BODY_MAX)
    cv_version_id: int | None = None  # None = no attachment


class ApproveIn(BaseModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")  # the hash of the version the owner looked at


def require_cv(conn, cv_version_id: int) -> None:
    if not conn.execute("SELECT 1 FROM cv_versions WHERE id = %s", (cv_version_id,)).fetchone():
        raise HTTPException(404, "CV version not found")


def load_email(conn, email_id: int) -> dict:
    e = conn.execute(
        "SELECT e.*, encode(e.content_hash, 'hex') AS content_hash_hex, c.name AS company_name, "
        "ct.name AS contact_name, ct.email_class, cv.label AS cv_label, cv.filename AS cv_filename, "
        "t.name AS template_name, tv.version AS template_version "
        "FROM outbound_emails e LEFT JOIN companies c ON c.id = e.company_id "
        "LEFT JOIN contacts ct ON ct.id = e.contact_id LEFT JOIN cv_versions cv ON cv.id = e.cv_version_id "
        "LEFT JOIN template_versions tv ON tv.id = e.template_version_id LEFT JOIN templates t ON t.id = tv.template_id "
        "WHERE e.id = %s", (email_id,)).fetchone()
    if not e:
        raise HTTPException(404, "Email not found")
    for k in ("content_hash", "approved_content_hash"):
        e.pop(k)
    return e


@router.post("/compose-list/drafts", status_code=201)
def create_drafts(body: DraftsIn, conn=Depends(get_db)):
    version = conn.execute(
        "SELECT tv.* FROM template_versions tv JOIN templates t ON t.id = tv.template_id "
        "WHERE t.id = %s AND t.archived_at IS NULL ORDER BY tv.version DESC LIMIT 1", (body.template_id,)).fetchone()
    if not version:
        raise HTTPException(404, "Active template not found")
    cv_id = None
    if body.attach_cv:
        cv_id = body.cv_version_id or (conn.execute("SELECT id FROM cv_versions WHERE is_default").fetchone() or {}).get("id")
        if cv_id is None:
            raise HTTPException(422, "No default CV; upload one on the Profile page or pick a version")
        require_cv(conn, cv_id)

    created, skipped = [], []
    for item in get_compose_list(conn):
        if item["problem"]:
            skipped.append({"company_id": item["company_id"], "name": item["name"], "reason": item["problem"]})
            continue
        r = item["recipient"]
        values, _ = variable_values(conn, item["company_id"], r["contact_id"])
        try:
            content = render_strict(version["subject"], version["body"], values)
        except RenderError as e:
            skipped.append({"company_id": item["company_id"], "name": item["name"],
                            "reason": "unresolved: " + ", ".join(e.unresolved)})
            continue
        email_id = conn.execute(
            "INSERT INTO outbound_emails (to_email, subject, body, company_id, contact_id, template_version_id, "
            "cv_version_id) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (r["email"], content["subject"], content["body"], item["company_id"], r["contact_id"], version["id"], cv_id),
        ).fetchone()["id"]
        conn.execute("DELETE FROM compose_list WHERE company_id = %s", (item["company_id"],))
        created.append({"email_id": email_id, "company_id": item["company_id"], "name": item["name"], "to": r["email"]})
    audit(conn, "compose.drafts_created", "template", body.template_id,
          {"version": version["version"], "created": len(created), "skipped": len(skipped), "cv_version_id": cv_id})
    return {"created": created, "skipped": skipped}


@router.get("/outbox")
def outbox(status: str = "draft", conn=Depends(get_db)):
    if status not in OUTBOX_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(OUTBOX_STATUSES)}")
    counts = {r["status"]: r["count"] for r in
              conn.execute("SELECT status, count(*) FROM outbound_emails GROUP BY status").fetchall()}
    emails = conn.execute(
        "SELECT e.id, e.to_email, e.subject, e.status, e.created_at, e.approved_at, e.sent_at, e.cancel_reason, "
        "e.cv_version_id IS NOT NULL AS has_attachment, c.name AS company_name, e.company_id "
        "FROM outbound_emails e LEFT JOIN companies c ON c.id = e.company_id WHERE e.status = %s "
        "ORDER BY coalesce(e.sent_at, e.approved_at, e.created_at) DESC, e.id DESC LIMIT 500", (status,)).fetchall()
    return {"counts": counts, "emails": emails}


@router.get("/outbound-emails/{email_id}")
def get_email(email_id: int, conn=Depends(get_db)):
    """The exact email as it will be sent, plus the safety check results for its next step."""
    e = load_email(conn, email_id)
    profile = conn.execute("SELECT full_name, email FROM profile WHERE id = 1").fetchone()
    e["from"] = {"name": profile["full_name"], "email": profile["email"]}  # the sending account is connected in M11
    stage = "send" if e["status"] in ("approved", "queued") else "approval" if e["status"] == "draft" else None
    if stage:
        raw = conn.execute("SELECT * FROM outbound_emails WHERE id = %s", (email_id,)).fetchone()
        e["checks"] = {"stage": stage, "results": safety.run_checks(conn, raw, stage)}
    return e


@router.put("/outbound-emails/{email_id}")
def edit_draft(email_id: int, body: DraftEdit, conn=Depends(get_db)):
    e = load_email(conn, email_id)
    if e["status"] != "draft":
        raise HTTPException(409, "Only drafts can be edited; pull it back to draft first")
    if body.cv_version_id is not None:
        require_cv(conn, body.cv_version_id)
    conn.execute("UPDATE outbound_emails SET subject = %s, body = %s, cv_version_id = %s WHERE id = %s",
                 (body.subject, body.body, body.cv_version_id, email_id))
    audit(conn, "outbound_email.edited", "outbound_email", email_id, {"to_email": e["to_email"]})
    return get_email(email_id, conn)


@router.post("/outbound-emails/{email_id}/approve")
def approve_and_queue(email_id: int, body: ApproveIn, conn=Depends(get_db)):
    """Approve exactly one email, exactly as displayed, and queue it. Failed checks are refused (422)."""
    current = conn.execute("SELECT encode(content_hash, 'hex') AS h, status FROM outbound_emails WHERE id = %s FOR UPDATE",
                           (email_id,)).fetchone()
    if not current:
        raise HTTPException(404, "Email not found")
    if current["h"] != body.content_hash:
        raise HTTPException(409, "This email changed since you viewed it; review it again before approving")
    result = safety.approve(conn, email_id)
    if not result["approved"]:
        # A normal return (not an exception) so the audit entry for the failed checks is committed.
        return JSONResponse(status_code=422, content=jsonable_encoder(result))
    conn.execute("UPDATE outbound_emails SET status = 'queued' WHERE id = %s", (email_id,))
    return {"approved": True, "status": "queued", "checks": result["checks"]}


@router.post("/outbound-emails/{email_id}/unqueue")
def back_to_draft(email_id: int, conn=Depends(get_db)):
    e = load_email(conn, email_id)
    if e["status"] not in ("approved", "queued"):
        raise HTTPException(409, f"Only approved or queued emails can go back to draft (this one is {e['status']})")
    conn.execute("UPDATE outbound_emails SET status = 'draft', approved_at = NULL, approved_content_hash = NULL "
                 "WHERE id = %s", (email_id,))
    return {"status": "draft"}


@router.post("/outbound-emails/{email_id}/discard")
def discard(email_id: int, conn=Depends(get_db)):
    e = load_email(conn, email_id)
    if e["status"] != "draft":
        raise HTTPException(409, "Only drafts can be discarded")
    conn.execute("UPDATE outbound_emails SET status = 'cancelled', cancel_reason = 'discarded by owner' WHERE id = %s",
                 (email_id,))
    return {"status": "cancelled"}
