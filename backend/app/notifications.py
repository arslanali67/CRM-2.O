"""M17: in-app notifications. They are created by database triggers (migration 0017), which is what
guarantees exactly one per event; this module only lists them and marks them read. Nothing is emailed."""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

ORDER = ("n.read_at IS NOT NULL, CASE n.priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, "
         "n.created_at DESC, n.id DESC")


@router.get("/notifications")
def list_notifications(unread_only: bool = False, limit: int = Query(50, ge=1, le=500), conn=Depends(get_db, scope="function")):
    """Unread first, then by priority, newest first."""
    return conn.execute(
        f"SELECT n.*, c.name AS company_name FROM notifications n LEFT JOIN companies c ON c.id = n.company_id "
        f"WHERE (NOT %s OR n.read_at IS NULL) ORDER BY {ORDER} LIMIT %s",
        (unread_only, limit)).fetchall()


@router.get("/notifications/count")
def unread_count(conn=Depends(get_db, scope="function")):
    return conn.execute(
        "SELECT count(*) AS unread, count(*) FILTER (WHERE priority = 'high') AS high "
        "FROM notifications WHERE read_at IS NULL").fetchone()


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, conn=Depends(get_db, scope="function")):
    row = conn.execute("UPDATE notifications SET read_at = coalesce(read_at, now()) WHERE id = %s RETURNING id, link",
                       (notification_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Notification not found")
    return row


@router.post("/notifications/read-all")
def mark_all_read(conn=Depends(get_db, scope="function")):
    n = conn.execute("UPDATE notifications SET read_at = now() WHERE read_at IS NULL RETURNING id").fetchall()
    return {"marked": len(n)}
