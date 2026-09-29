"""M21: notes on companies/contacts/templates and follow-up tasks for the owner.

Tasks are reminders for a human. Nothing here can create or send an email.
"""
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.deps import audit, get_db, require_owner

router = APIRouter(dependencies=[Depends(require_owner)])

EntityType = Literal["company", "contact", "template", "opportunity", "interview"]
TABLES = {"company": "companies", "contact": "contacts", "template": "templates", "opportunity": "opportunities", "interview": "interviews"}
DONE_LIMIT = 50

# Label and page link for a task's linked entity (a contact links to its company page).
ENTITY_SQL = """
    CASE t.entity_type WHEN 'company' THEN co.name WHEN 'contact' THEN coalesce(nullif(ct.name, ''), ct.email)
                       WHEN 'template' THEN tp.name WHEN 'opportunity' THEN op.title
                       WHEN 'interview' THEN iv.title END AS entity_name,
    CASE t.entity_type WHEN 'company' THEN '/companies/' || t.entity_id
                       WHEN 'contact' THEN '/companies/' || ct.company_id
                       WHEN 'template' THEN '/templates/' || t.entity_id
                       WHEN 'opportunity' THEN '/opportunities/' || t.entity_id
                       WHEN 'interview' THEN '/opportunities/' || iv.opportunity_id || '#interview-' || t.entity_id
                       END AS entity_link
"""
TASK_SELECT = f"""
    SELECT t.*, {ENTITY_SQL}
    FROM tasks t
    LEFT JOIN companies co ON t.entity_type = 'company' AND co.id = t.entity_id
    LEFT JOIN contacts ct ON t.entity_type = 'contact' AND ct.id = t.entity_id
    LEFT JOIN templates tp ON t.entity_type = 'template' AND tp.id = t.entity_id
    LEFT JOIN opportunities op ON t.entity_type = 'opportunity' AND op.id = t.entity_id
    LEFT JOIN interviews iv ON t.entity_type = 'interview' AND iv.id = t.entity_id
"""


def require_entity(conn, entity_type: str, entity_id: int) -> None:
    if not conn.execute(f"SELECT 1 FROM {TABLES[entity_type]} WHERE id = %s", (entity_id,)).fetchone():
        raise HTTPException(404, f"{entity_type.capitalize()} not found")


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


# ---------- notes ----------

class NoteIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    entity_type: EntityType
    entity_id: int
    body: str = Field(min_length=1, max_length=10000)


class NoteEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    body: str = Field(min_length=1, max_length=10000)


def get_note(conn, note_id: int) -> dict:
    n = conn.execute("SELECT * FROM notes WHERE id = %s AND deleted_at IS NULL", (note_id,)).fetchone()
    if not n:
        raise HTTPException(404, "Note not found")
    return n


@router.get("/notes")
def list_notes(entity_type: EntityType, entity_id: list[int] = Query(), conn=Depends(get_db)):
    """Notes for one or more entities of one type (e.g. all contacts on a company page), newest first."""
    return conn.execute(
        "SELECT * FROM notes WHERE entity_type = %s AND entity_id = ANY(%s) AND deleted_at IS NULL "
        "ORDER BY created_at DESC, id DESC",
        (entity_type, entity_id),
    ).fetchall()


@router.post("/notes", status_code=201)
def create_note(body: NoteIn, conn=Depends(get_db)):
    require_entity(conn, body.entity_type, body.entity_id)
    n = conn.execute("INSERT INTO notes (entity_type, entity_id, body) VALUES (%s, %s, %s) RETURNING *",
                     (body.entity_type, body.entity_id, body.body)).fetchone()
    audit(conn, "note.created", body.entity_type, body.entity_id, {"note_id": n["id"]})
    return n


@router.put("/notes/{note_id}")
def edit_note(note_id: int, body: NoteEdit, conn=Depends(get_db)):
    n = get_note(conn, note_id)
    n = conn.execute("UPDATE notes SET body = %s, edited_at = now() WHERE id = %s RETURNING *",
                     (body.body, note_id)).fetchone()
    audit(conn, "note.edited", n["entity_type"], n["entity_id"], {"note_id": note_id})
    return n


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, conn=Depends(get_db)):
    n = get_note(conn, note_id)
    conn.execute("UPDATE notes SET deleted_at = now() WHERE id = %s", (note_id,))
    audit(conn, "note.deleted", n["entity_type"], n["entity_id"], {"note_id": note_id})
    return {"deleted": note_id}


# ---------- tasks ----------

class TaskIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    details: str = Field("", max_length=10000)
    due_date: date | None = None
    entity_type: EntityType | None = None
    entity_id: int | None = None

    @model_validator(mode="after")
    def _link(self):
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be given together")
        return self


class TaskEdit(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=300)
    details: str = Field("", max_length=10000)
    due_date: date | None = None


def get_task(conn, task_id: int) -> dict:
    t = conn.execute(TASK_SELECT + " WHERE t.id = %s AND t.deleted_at IS NULL", (task_id,)).fetchone()
    if not t:
        raise HTTPException(404, "Task not found")
    return t


def task_audit(conn, action: str, t: dict, **data):
    etype, eid = (t["entity_type"], t["entity_id"]) if t["entity_type"] else ("task", t["id"])
    audit(conn, action, etype, eid, {"task_id": t["id"], "title": t["title"], **data})


@router.get("/tasks")
def list_tasks(today: date | None = None, entity_type: EntityType | None = None, entity_id: int | None = None,
               conn=Depends(get_db)):
    """Grouped due list relative to `today` (the owner's browser date; defaults to the UTC date).
    With entity_type + entity_id, only that entity's tasks."""
    today = today or utc_today()
    where, params = "t.deleted_at IS NULL", []
    if entity_type and entity_id:
        where += " AND t.entity_type = %s AND t.entity_id = %s"
        params += [entity_type, entity_id]
    open_tasks = conn.execute(
        TASK_SELECT + f" WHERE {where} AND t.done_at IS NULL ORDER BY t.due_date NULLS LAST, t.id", params
    ).fetchall()
    done = conn.execute(
        TASK_SELECT + f" WHERE {where} AND t.done_at IS NOT NULL ORDER BY t.done_at DESC LIMIT {DONE_LIMIT}", params
    ).fetchall()
    return {
        "today": today,
        "overdue": [t for t in open_tasks if t["due_date"] and t["due_date"] < today],
        "due_today": [t for t in open_tasks if t["due_date"] == today],
        "upcoming": [t for t in open_tasks if t["due_date"] and t["due_date"] > today],
        "no_date": [t for t in open_tasks if t["due_date"] is None],
        "done": done,
    }


@router.get("/tasks/counts")
def task_counts(today: date | None = None, conn=Depends(get_db)):
    today = today or utc_today()
    return conn.execute(
        "SELECT count(*) FILTER (WHERE due_date < %(t)s) AS overdue, count(*) FILTER (WHERE due_date = %(t)s) AS due_today "
        "FROM tasks WHERE done_at IS NULL AND deleted_at IS NULL", {"t": today},
    ).fetchone()


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, conn=Depends(get_db)):
    if body.entity_type:
        require_entity(conn, body.entity_type, body.entity_id)
    tid = conn.execute(
        "INSERT INTO tasks (title, details, due_date, entity_type, entity_id) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (body.title, body.details, body.due_date, body.entity_type, body.entity_id),
    ).fetchone()["id"]
    t = get_task(conn, tid)
    task_audit(conn, "task.created", t, due_date=str(body.due_date) if body.due_date else None)
    return t


@router.put("/tasks/{task_id}")
def edit_task(task_id: int, body: TaskEdit, conn=Depends(get_db)):
    get_task(conn, task_id)
    conn.execute("UPDATE tasks SET title = %s, details = %s, due_date = %s, updated_at = now() WHERE id = %s",
                 (body.title, body.details, body.due_date, task_id))
    t = get_task(conn, task_id)
    task_audit(conn, "task.edited", t, due_date=str(body.due_date) if body.due_date else None)
    return t


@router.post("/tasks/{task_id}/done")
def complete_task(task_id: int, conn=Depends(get_db)):
    get_task(conn, task_id)
    conn.execute("UPDATE tasks SET done_at = coalesce(done_at, now()), updated_at = now() WHERE id = %s", (task_id,))
    t = get_task(conn, task_id)
    task_audit(conn, "task.completed", t)
    return t


@router.post("/tasks/{task_id}/reopen")
def reopen_task(task_id: int, conn=Depends(get_db)):
    get_task(conn, task_id)
    conn.execute("UPDATE tasks SET done_at = NULL, updated_at = now() WHERE id = %s", (task_id,))
    t = get_task(conn, task_id)
    task_audit(conn, "task.reopened", t)
    return t


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, conn=Depends(get_db)):
    t = get_task(conn, task_id)
    conn.execute("UPDATE tasks SET deleted_at = now() WHERE id = %s", (task_id,))
    task_audit(conn, "task.deleted", t)
    return {"deleted": task_id}
