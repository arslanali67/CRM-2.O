"""Shared request dependencies: owner check, DB connection, audit logging."""
import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app import settings


def require_owner(request: Request) -> str:
    if not request.session.get("owner"):
        raise HTTPException(401, "Not signed in")
    return settings.OWNER_EMAIL


def get_db():
    # One connection per request; commits on success, rolls back on error.
    with psycopg.connect(settings.DATABASE_URL, row_factory=dict_row) as conn:
        yield conn


def audit(conn, action: str, entity_type: str | None = None, entity_id: int | None = None, data: dict | None = None):
    conn.execute(
        "INSERT INTO audit_log (actor, action, entity_type, entity_id, data) VALUES ('owner', %s, %s, %s, %s)",
        (action, entity_type, entity_id, Jsonb(data or {})),
    )
