"""M24: activity timeline over the append-only audit_log."""
from fastapi import APIRouter, Depends, Query

from app.companies import fetch
from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

TIMELINE_LIMIT = 500


@router.get("/activity")
def feed(limit: int = Query(50, ge=1, le=200), before_id: int | None = None, conn=Depends(get_db, scope="function")):
    """Global feed, newest first. Pass the last id as before_id to load more."""
    return conn.execute(
        "SELECT * FROM audit_log WHERE (%(before)s::bigint IS NULL OR id < %(before)s) ORDER BY id DESC LIMIT %(limit)s",
        {"before": before_id, "limit": limit},
    ).fetchall()


@router.get("/activity/{entity_type}/{entity_id}")
def entity_timeline(entity_type: str, entity_id: int, conn=Depends(get_db, scope="function")):
    return conn.execute(
        "SELECT * FROM audit_log WHERE entity_type = %s AND entity_id = %s ORDER BY id DESC LIMIT %s",
        (entity_type, entity_id, TIMELINE_LIMIT),
    ).fetchall()


@router.get("/companies/{company_id}/activity")
def company_timeline(company_id: int, conn=Depends(get_db, scope="function")):
    """The company, its contacts, its company blocks, and emails to its contacts or domain."""
    fetch(conn, "companies", company_id)
    return conn.execute(
        """
        WITH c AS (SELECT id, domain FROM companies WHERE id = %(id)s),
             emails AS (SELECT email FROM contacts WHERE company_id = %(id)s AND email <> '')
        SELECT a.* FROM audit_log a, c
        WHERE (a.entity_type = 'company' AND a.entity_id = c.id)
           OR (a.entity_type = 'contact' AND a.entity_id IN (SELECT id FROM contacts WHERE company_id = c.id))
           OR (a.entity_type = 'suppression' AND a.entity_id IN (SELECT id FROM suppressions WHERE company_id = c.id))
           OR (a.entity_type = 'outbound_email' AND (
                  a.data->>'to_email' IN (SELECT email FROM emails)
                  OR (c.domain <> '' AND (split_part(a.data->>'to_email', '@', 2) = c.domain
                                          OR split_part(a.data->>'to_email', '@', 2) LIKE '%%.' || c.domain))))
        ORDER BY a.id DESC LIMIT %(limit)s
        """,
        {"id": company_id, "limit": TIMELINE_LIMIT},
    ).fetchall()
