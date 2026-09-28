"""M23: 360° views. The company overview (summary header) and the contact page, each in one call.
Every related record carries a `link` to where it lives in the UI."""
from fastapi import APIRouter, Depends

from app.companies import fetch
from app.deps import get_db, require_owner
from app.history import EMAIL_COLUMNS, FROM

router = APIRouter(dependencies=[Depends(require_owner)])

INBOUND = ("SELECT m.id, m.from_email, m.from_name, m.subject, m.received_at, m.label, m.bounce_type, m.company_id, "
           "coalesce(m.gmail_thrid, 'in-' || m.id) AS thread_key, a.label AS ai_label, a.summary AS ai_summary, "
           "'/threads/' || coalesce(m.gmail_thrid, 'in-' || m.id) || '#in-' || m.id AS link "
           "FROM inbound_messages m LEFT JOIN ai_analyses a ON a.inbound_message_id = m.id AND a.status = 'ok' ")


@router.get("/companies/{company_id}/overview")
def company_overview(company_id: int, conn=Depends(get_db)):
    c = fetch(conn, "companies", company_id)
    stats = conn.execute(
        "SELECT (SELECT count(*) FROM contacts WHERE company_id = %(id)s AND archived_at IS NULL) AS contacts, "
        "(SELECT count(*) FROM outbound_emails WHERE company_id = %(id)s AND status <> 'draft') AS emails, "
        "(SELECT count(*) FROM outbound_emails WHERE company_id = %(id)s AND status = 'sent') AS sent, "
        "(SELECT max(sent_at) FROM outbound_emails WHERE company_id = %(id)s AND status = 'sent') AS last_emailed_at, "
        "(SELECT count(*) FROM inbound_messages WHERE company_id = %(id)s AND label = 'reply') AS replies, "
        "(SELECT count(*) FROM tasks WHERE done_at IS NULL AND deleted_at IS NULL AND ((entity_type = 'company' AND "
        " entity_id = %(id)s) OR (entity_type = 'contact' AND entity_id IN (SELECT id FROM contacts WHERE "
        " company_id = %(id)s)))) AS open_tasks, "
        "(EXISTS (SELECT 1 FROM suppressions WHERE lifted_at IS NULL AND kind = 'company' AND company_id = %(id)s) "
        " OR (%(domain)s <> '' AND is_suppressed('probe@' || %(domain)s))) AS blocked",
        {"id": company_id, "domain": c["domain"]}).fetchone()
    last_reply = conn.execute(INBOUND + "WHERE m.company_id = %s AND m.label = 'reply' "
                                        "ORDER BY m.received_at DESC NULLS LAST, m.id DESC LIMIT 1", (company_id,)).fetchone()
    return {"company": {k: c[k] for k in ("id", "name", "domain", "stage", "close_reason", "archived_at")},
            **stats, "last_reply": last_reply, "opportunity": {"available": False, "after": "M19"}}


@router.get("/contacts/{contact_id}")
def contact_detail(contact_id: int, conn=Depends(get_db)):
    ct = fetch(conn, "contacts", contact_id)
    company = conn.execute("SELECT id, name, domain, stage FROM companies WHERE id = %s", (ct["company_id"],)).fetchone()
    email = ct["email"] or None  # '' must never match other records
    suppressed = bool(conn.execute(
        "SELECT (%(email)s::text IS NOT NULL AND is_suppressed(%(email)s)) OR EXISTS (SELECT 1 FROM suppressions "
        "WHERE lifted_at IS NULL AND kind = 'company' AND company_id = %(co)s) AS s",
        {"email": email, "co": ct["company_id"]}).fetchone()["s"])
    emails = conn.execute(
        f"SELECT {EMAIL_COLUMNS}, '/outbox/' || e.id AS link {FROM} WHERE e.contact_id = %(id)s "
        "OR (%(email)s::text IS NOT NULL AND lower(e.to_email) = %(email)s) "
        "ORDER BY coalesce(e.sent_at, e.created_at) DESC, e.id DESC", {"id": contact_id, "email": email}).fetchall()
    replies = conn.execute(
        INBOUND + "WHERE m.contact_id = %(id)s OR (%(email)s::text IS NOT NULL AND m.from_email = %(email)s) "
                  "ORDER BY m.received_at DESC NULLS LAST, m.id DESC", {"id": contact_id, "email": email}).fetchall()
    notes = conn.execute("SELECT * FROM notes WHERE entity_type = 'contact' AND entity_id = %s AND deleted_at IS NULL "
                         "ORDER BY created_at DESC, id DESC", (contact_id,)).fetchall()
    tasks = conn.execute("SELECT *, '/tasks' AS link FROM tasks WHERE entity_type = 'contact' AND entity_id = %s "
                         "AND deleted_at IS NULL ORDER BY done_at IS NOT NULL, due_date NULLS LAST, id",
                         (contact_id,)).fetchall()
    timeline = conn.execute(
        "SELECT * FROM audit_log WHERE (entity_type = 'contact' AND entity_id = %(id)s) "
        "OR (%(email)s::text IS NOT NULL AND ("
        "    (entity_type = 'outbound_email' AND data->>'to_email' = %(email)s) "
        "    OR (entity_type = 'suppression' AND data->>'email' = %(email)s) "
        "    OR (action LIKE 'inbound.%%' AND data->>'from_email' = %(email)s))) "
        "ORDER BY id DESC LIMIT 500", {"id": contact_id, "email": email}).fetchall()
    return {"contact": ct, "company": {**company, "link": f"/companies/{company['id']}"}, "suppressed": suppressed,
            "emails": emails, "replies": replies, "notes": notes, "tasks": tasks, "timeline": timeline}
