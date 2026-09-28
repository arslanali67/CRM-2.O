"""M22: global search across companies, contacts, sent emails, replies, templates and notes.
Case-insensitive "contains" matching, served by pg_trgm indexes (migration 0018)."""
from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

PER_KIND = 5


def like_pattern(q: str) -> str:
    """'%q%' with LIKE wildcards in the user's text escaped (so '50%' matches literally)."""
    return "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


QUERIES = {
    "companies": "SELECT id, name AS title, domain AS detail, '/companies/' || id AS link FROM companies "
                 "WHERE archived_at IS NULL AND (lower(name) LIKE %(p)s OR domain LIKE %(p)s) "
                 "ORDER BY lower(name) = %(q)s DESC, lower(name) LIMIT %(n)s",
    "contacts": "SELECT ct.id, coalesce(nullif(ct.name, ''), ct.email) AS title, "
                "concat_ws(' · ', nullif(ct.email, ''), c.name) AS detail, '/contacts/' || ct.id AS link "
                "FROM contacts ct JOIN companies c ON c.id = ct.company_id WHERE ct.archived_at IS NULL "
                "AND (lower(ct.name) LIKE %(p)s OR ct.email LIKE %(p)s) ORDER BY lower(ct.name), ct.id LIMIT %(n)s",
    "emails": "SELECT id, subject AS title, to_email || ' · ' || status AS detail, '/outbox/' || id AS link "
              "FROM outbound_emails WHERE lower(subject) LIKE %(p)s OR lower(to_email) LIKE %(p)s "
              "ORDER BY coalesce(sent_at, created_at) DESC LIMIT %(n)s",
    "replies": "SELECT id, subject AS title, coalesce(nullif(from_name, ''), from_email) || coalesce(' · ' || label, '') "
               "AS detail, '/threads/' || coalesce(gmail_thrid, 'in-' || id) || '#in-' || id AS link "
               "FROM inbound_messages WHERE lower(subject) LIKE %(p)s OR lower(from_email || ' ' || from_name) LIKE %(p)s "
               "ORDER BY received_at DESC NULLS LAST LIMIT %(n)s",
    "templates": "SELECT id, name AS title, CASE WHEN archived_at IS NULL THEN 'template' ELSE 'archived template' END "
                 "AS detail, '/templates/' || id AS link FROM templates WHERE lower(name) LIKE %(p)s "
                 "ORDER BY archived_at IS NOT NULL, lower(name) LIMIT %(n)s",
    "notes": "SELECT n.id, left(n.body, 80) AS title, n.entity_type AS detail, "
             "CASE n.entity_type WHEN 'company' THEN '/companies/' || n.entity_id "
             "WHEN 'contact' THEN '/contacts/' || n.entity_id ELSE '/templates/' || n.entity_id END AS link "
             "FROM notes n WHERE n.deleted_at IS NULL AND lower(n.body) LIKE %(p)s ORDER BY n.created_at DESC LIMIT %(n)s",
}


@router.get("/search")
def search(q: str, conn=Depends(get_db)):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(422, "Type at least 2 characters")
    params = {"p": like_pattern(q), "q": q.lower(), "n": PER_KIND}
    return {"q": q, **{kind: conn.execute(sql, params).fetchall() for kind, sql in QUERIES.items()}}
