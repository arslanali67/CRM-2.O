"""M7: duplicate suggestions, merge with snapshot, and undo. Nothing is ever merged automatically."""
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.companies import conflict_as_409
from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

NAME_SIMILARITY = 0.4  # pairs already share their first word
MOVED_BY_COMPANY = ("contacts", "outbound_emails", "inbound_messages", "opportunities", "notifications")
MOVED_BY_ENTITY = ("notes", "tasks")
FILLABLE = ("domain", "website", "industry", "city", "country", "description", "linkedin_url")
PENDING = ("approved", "queued", "sending")

SUGGESTIONS = """
WITH act AS (
    SELECT id, name, name_key(name) AS nk, split_part(name_key(name), ' ', 1) AS w, domain,
           main_domain(domain) AS md, linkedin_key(linkedin_url) AS lk
    FROM companies WHERE archived_at IS NULL
), hits AS (
    SELECT a.id AS a, b.id AS b, 'domain' AS reason, a.domain || ' / ' || b.domain AS detail
    FROM act a JOIN act b ON b.md = a.md AND b.id > a.id WHERE a.md <> ''
  UNION ALL
    SELECT a.id, b.id, 'domain', a.domain || ' / ' || b.domain || ' (similar names)'
    FROM act a JOIN act b ON split_part(b.md, '.', 1) = split_part(a.md, '.', 1) AND b.md <> a.md AND b.id > a.id
    WHERE a.md <> '' AND similarity(a.nk, b.nk) >= %(sim)s
  UNION ALL
    SELECT least(a.id, b.id), greatest(a.id, b.id), 'email', ct.email || ' is at ' || b.domain
    FROM contacts ct JOIN act a ON a.id = ct.company_id
    JOIN act b ON b.md = main_domain(split_part(ct.email, '@', 2)) AND b.id <> a.id
    WHERE ct.archived_at IS NULL AND ct.email <> ''
      AND (split_part(ct.email, '@', 2) = b.domain OR split_part(ct.email, '@', 2) LIKE '%%.' || b.domain)
  UNION ALL
    SELECT a.id, b.id, 'linkedin', a.lk FROM act a JOIN act b ON b.lk = a.lk AND b.id > a.id WHERE a.lk <> ''
  UNION ALL
    SELECT a.id, b.id, 'name', a.name || ' / ' || b.name
    FROM act a JOIN act b ON b.w = a.w AND b.id > a.id WHERE a.w <> '' AND similarity(a.nk, b.nk) >= %(sim)s
)
SELECT h.a, h.b, ca.name AS a_name, ca.domain AS a_domain, cb.name AS b_name, cb.domain AS b_domain,
       array_agg(DISTINCT h.reason ORDER BY h.reason) AS reasons, array_agg(DISTINCT h.detail) AS details
FROM hits h JOIN companies ca ON ca.id = h.a JOIN companies cb ON cb.id = h.b
WHERE NOT EXISTS (SELECT 1 FROM duplicate_dismissals d WHERE d.company_a = h.a AND d.company_b = h.b)
GROUP BY h.a, h.b, ca.name, ca.domain, cb.name, cb.domain
ORDER BY count(DISTINCT h.reason) DESC, h.a, h.b
LIMIT 200
"""


class MergeIn(BaseModel):
    survivor_id: int
    merged_id: int


class DismissIn(BaseModel):
    company_a: int
    company_b: int


@router.get("/duplicates")
def suggestions(conn=Depends(get_db)):
    return conn.execute(SUGGESTIONS, {"sim": NAME_SIMILARITY}).fetchall()


@router.post("/duplicates/dismiss")
def dismiss(body: DismissIn, conn=Depends(get_db)):
    a, b = sorted((body.company_a, body.company_b))
    if a == b:
        raise HTTPException(422, "Pick two different companies")
    conn.execute("INSERT INTO duplicate_dismissals (company_a, company_b) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 (a, b))
    audit(conn, "duplicates.dismissed", "company", a, {"company_a": a, "company_b": b})
    return {"ok": True}


def refuse_pending(conn, ids: list[int]):
    """Lock both companies' emails; refuse while any is approved, queued or sending (its recipient must not shift)."""
    rows = conn.execute("SELECT status FROM outbound_emails WHERE company_id = ANY(%s) FOR UPDATE", (ids,)).fetchall()
    n = sum(r["status"] in PENDING for r in rows)
    if n:
        raise HTTPException(409, f"{n} email(s) are approved, queued or sending for these companies; "
                                 "wait for them to be sent or cancel them first")


def active_block(conn, company_id: int):
    return conn.execute("SELECT id FROM suppressions WHERE kind = 'company' AND company_id = %s "
                        "AND lifted_at IS NULL", (company_id,)).fetchone()


@router.post("/duplicates/merge")
def merge(body: MergeIn, conn=Depends(get_db)):
    s_id, m_id = body.survivor_id, body.merged_id
    if s_id == m_id:
        raise HTTPException(422, "Pick two different companies")
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM companies WHERE id = ANY(%s) ORDER BY id FOR UPDATE",
                                             ([s_id, m_id],)).fetchall()}
    if len(rows) < 2:
        raise HTTPException(404, "Company not found")
    if any(r["archived_at"] for r in rows.values()):
        raise HTTPException(409, "Both companies must be active")
    refuse_pending(conn, [s_id, m_id])
    s, m = rows[s_id], rows[m_id]

    moved = {t: [r["id"] for r in conn.execute(
        f"UPDATE {t} SET company_id = %s WHERE company_id = %s RETURNING id", (s_id, m_id)).fetchall()]
        for t in MOVED_BY_COMPANY}
    for t in MOVED_BY_ENTITY:
        moved[t] = [r["id"] for r in conn.execute(
            f"UPDATE {t} SET entity_id = %s WHERE entity_type = 'company' AND entity_id = %s RETURNING id",
            (s_id, m_id)).fetchall()]
    compose = {"removed": bool(conn.execute("DELETE FROM compose_list WHERE company_id = %s RETURNING 1",
                                            (m_id,)).fetchone())}
    compose["added"] = compose["removed"] and bool(conn.execute(
        "INSERT INTO compose_list (company_id) VALUES (%s) ON CONFLICT DO NOTHING RETURNING 1", (s_id,)).fetchone())

    conn.execute("UPDATE companies SET archived_at = now(), updated_at = now() WHERE id = %s", (m_id,))
    filled = {f: m[f] for f in FILLABLE if not s[f] and m[f]}  # after archiving, so the domain can move over
    if filled:
        conn.execute("UPDATE companies SET " + ", ".join(f"{f} = %({f})s" for f in filled)
                     + ", updated_at = now() WHERE id = %(id)s", {**filled, "id": s_id})

    carried = None
    block = active_block(conn, m_id)
    if block and not active_block(conn, s_id):
        carried = conn.execute(
            "INSERT INTO suppressions (kind, company_id, reason) VALUES ('company', %s, %s) RETURNING id",
            (s_id, f"Carried over from merged company {m['name']} (block #{block['id']})")).fetchone()["id"]

    snapshot = {"moved": moved, "compose": compose, "filled": filled, "carried_block": carried}
    row = conn.execute("INSERT INTO company_merges (survivor_id, merged_id, snapshot) VALUES (%s, %s, %s) "
                       "RETURNING *", (s_id, m_id, Jsonb(snapshot))).fetchone()
    audit(conn, "company.merged", "company", s_id, {"merge_id": row["id"], "merged_id": m_id, "merged_name": m["name"],
                                                   "moved": {t: len(v) for t, v in moved.items() if v},
                                                   "filled": sorted(filled), "carried_block": carried})
    return row


@router.get("/duplicates/merges")
def merges(conn=Depends(get_db)):
    return conn.execute(
        "SELECT g.*, s.name AS survivor_name, m.name AS merged_name FROM company_merges g "
        "JOIN companies s ON s.id = g.survivor_id JOIN companies m ON m.id = g.merged_id "
        "ORDER BY g.id DESC LIMIT 100").fetchall()


@router.post("/duplicates/merges/{merge_id}/undo")
def undo(merge_id: int, conn=Depends(get_db)):
    g = conn.execute("SELECT * FROM company_merges WHERE id = %s FOR UPDATE", (merge_id,)).fetchone()
    if not g:
        raise HTTPException(404, "Merge not found")
    if g["undone_at"]:
        raise HTTPException(409, "This merge was already undone")
    s_id, m_id = g["survivor_id"], g["merged_id"]
    later = conn.execute(
        "SELECT id FROM company_merges WHERE id > %s AND undone_at IS NULL "
        "AND (survivor_id = ANY(%s) OR merged_id = ANY(%s)) ORDER BY id DESC LIMIT 1",
        (merge_id, [s_id, m_id], [s_id, m_id])).fetchone()
    if later:
        raise HTTPException(409, f"Undo the later merge #{later['id']} first")
    conn.execute("SELECT id FROM companies WHERE id = ANY(%s) ORDER BY id FOR UPDATE", ([s_id, m_id],))
    refuse_pending(conn, [s_id, m_id])
    snap = g["snapshot"]

    for t in MOVED_BY_COMPANY:  # only rows still where the merge put them; newer records stay
        conn.execute(f"UPDATE {t} SET company_id = %s WHERE id = ANY(%s) AND company_id = %s",
                     (m_id, snap["moved"][t], s_id))
    for t in MOVED_BY_ENTITY:
        conn.execute(f"UPDATE {t} SET entity_id = %s WHERE id = ANY(%s) AND entity_type = 'company' "
                     "AND entity_id = %s", (m_id, snap["moved"][t], s_id))
    if snap["compose"]["added"]:
        conn.execute("DELETE FROM compose_list WHERE company_id = %s", (s_id,))
    if snap["compose"]["removed"]:
        conn.execute("INSERT INTO compose_list (company_id) VALUES (%s) ON CONFLICT DO NOTHING", (m_id,))
    for f, v in snap["filled"].items():  # clear only values the owner has not changed since
        conn.execute(f"UPDATE companies SET {f} = '', updated_at = now() WHERE id = %s AND {f} = %s", (s_id, v))
    if snap["carried_block"]:
        conn.execute("UPDATE suppressions SET lifted_at = now(), lift_reason = %s WHERE id = %s "
                     "AND lifted_at IS NULL", (f"Merge #{merge_id} undone", snap["carried_block"]))
    with conflict_as_409("Cannot undo: the merged company's domain is now used by another active company"):
        conn.execute("UPDATE companies SET archived_at = NULL, updated_at = now() WHERE id = %s", (m_id,))
    row = conn.execute("UPDATE company_merges SET undone_at = now() WHERE id = %s RETURNING *", (merge_id,)).fetchone()
    audit(conn, "company.merge_undone", "company", s_id, {"merge_id": merge_id, "merged_id": m_id})
    return row
