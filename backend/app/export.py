"""M32: CSV exports and the full export (every table as JSON + CV PDFs, never the encrypted app password)."""
import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

CSV_QUERIES = {
    "companies": "SELECT id, name, domain, website, industry, city, country, stage, linkedin_url, source, created_at, "
                 "archived_at FROM companies ORDER BY id",
    "contacts": "SELECT ct.id, ct.company_id, c.name AS company, ct.name, ct.email, ct.role, ct.phone, "
                "ct.linkedin_url, ct.email_class, ct.created_at, ct.archived_at "
                "FROM contacts ct JOIN companies c ON c.id = ct.company_id ORDER BY ct.id",
    "sent_emails": "SELECT e.id, c.name AS company, e.to_email, e.subject, e.sent_at, e.provider_message_id "
                   "FROM outbound_emails e LEFT JOIN companies c ON c.id = e.company_id "
                   "WHERE e.status = 'sent' ORDER BY e.sent_at, e.id",
    "replies": "SELECT m.id, m.received_at, c.name AS company, m.from_email, m.from_name, m.subject, m.label, "
               "m.bounce_type, a.label AS ai_label FROM inbound_messages m "
               "LEFT JOIN companies c ON c.id = m.company_id "
               "LEFT JOIN ai_analyses a ON a.inbound_message_id = m.id AND a.status = 'ok' "
               "WHERE m.label IN ('reply', 'auto_reply', 'bounce') ORDER BY m.received_at, m.id",
}
SECRET_COLUMNS = {"email_account": {"password_encrypted"}}
FORMULA = ("=", "+", "-", "@", "\t", "\r")


def cell(v):
    """Plain text for spreadsheets; values that could run as formulas are prefixed with a quote."""
    s = "" if v is None else v.isoformat() if isinstance(v, datetime) else str(v)
    return "'" + s if s.startswith(FORMULA) else s


def stamp() -> str:
    return f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"


@router.get("/export/{kind}.csv")
def export_csv(kind: str, conn=Depends(get_db, scope="function")):
    if kind not in CSV_QUERIES:
        raise HTTPException(404, "Unknown export")
    cur = conn.execute(CSV_QUERIES[kind])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in cur.description])
    rows = cur.fetchall()
    w.writerows([cell(v) for v in r.values()] for r in rows)
    audit(conn, "export.csv", None, None, {"kind": kind, "rows": len(rows)})
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",  # BOM: Excel reads UTF-8
                    headers={"Content-Disposition": f'attachment; filename="crm-{kind}-{stamp()}.csv"'})


def jsonable(v):
    return v.hex() if isinstance(v, (bytes, memoryview)) else str(v)


@router.get("/export/full.zip")
def export_full(conn=Depends(get_db, scope="function")):
    tables = [r["tablename"] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename").fetchall()]
    buf = io.BytesIO()
    counts = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for t in tables:
            skip = SECRET_COLUMNS.get(t, set()) | ({"content"} if t == "cv_versions" else set())
            rows = [{k: v for k, v in r.items() if k not in skip}
                    for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall()]
            counts[t] = len(rows)
            z.writestr(f"tables/{t}.json", json.dumps(rows, default=jsonable, ensure_ascii=False, indent=1))
        for cv in conn.execute("SELECT id, label, content FROM cv_versions ORDER BY id").fetchall():
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", cv["label"])[:60] or "cv"
            z.writestr(f"cvs/{cv['id']}-{safe}.pdf", bytes(cv["content"]))
        z.writestr("README.txt", "Full export of the Job Outreach CRM: one JSON file per table, CV PDFs in cvs/.\n"
                                 "The encrypted Gmail app password is not included.\n")
    audit(conn, "export.full", None, None, {"tables": len(tables), "rows": sum(counts.values())})
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="crm-full-export-{stamp()}.zip"'})
