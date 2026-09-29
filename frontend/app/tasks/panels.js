"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useDialog } from "../ui";

// The owner's local calendar date; the server never guesses "today".
export function localToday(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function call(url, method = "GET", body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  return { ok: res.ok, data: await res.json() };
}

export function NotesPanel({ entityType, entityId, compact = false }) {
  const dialog = useDialog();
  const [notes, setNotes] = useState([]);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState(null);

  const load = () => call(`/api/notes?entity_type=${entityType}&entity_id=${entityId}`).then((r) => r.ok && setNotes(r.data));
  useEffect(() => { load(); }, [entityType, entityId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(e) {
    e.preventDefault();
    if ((await call("/api/notes", "POST", { entity_type: entityType, entity_id: entityId, body: text })).ok) {
      setText("");
      load();
    }
  }
  async function save(e) {
    e.preventDefault();
    if ((await call(`/api/notes/${editing.id}`, "PUT", { body: editing.body })).ok) { setEditing(null); load(); }
  }
  async function remove(id) {
    if (await dialog.confirm("Delete this note?", { danger: true, confirmLabel: "Delete" })) { await call(`/api/notes/${id}`, "DELETE"); load(); }
  }

  return (
    <div>
      {!compact && <h2 style={{ marginTop: 32 }}>Notes</h2>}
      {notes.map((n) => (
        <div key={n.id} style={{ borderLeft: "3px solid var(--border)", paddingLeft: 8, margin: "8px 0" }}>
          {editing?.id === n.id ? (
            <form onSubmit={save} style={{ display: "grid", gap: 4 }}>
              <textarea rows={3} value={editing.body} onChange={(e) => setEditing({ ...editing, body: e.target.value })} />
              <div><button type="submit">Save</button> <button type="button" onClick={() => setEditing(null)}>Cancel</button></div>
            </form>
          ) : (
            <>
              <div style={{ whiteSpace: "pre-wrap" }}>{n.body}</div>
              <small style={{ color: "var(--muted)" }}>
                {new Date(n.created_at).toLocaleString()}{n.edited_at && " (edited)"} ·{" "}
                <button onClick={() => setEditing({ id: n.id, body: n.body })}>Edit</button>{" "}
                <button onClick={() => remove(n.id)}>Delete</button>
              </small>
            </>
          )}
        </div>
      ))}
      <form onSubmit={add} style={{ display: "flex", gap: 4 }}>
        <textarea rows={compact ? 1 : 2} required placeholder="Add a note…" aria-label="New note" value={text}
                  onChange={(e) => setText(e.target.value)} style={{ flex: 1 }} />
        <button type="submit">Add note</button>
      </form>
    </div>
  );
}

export function TaskRow({ task, onChange, showEntity = false }) {
  const dialog = useDialog();
  const toggle = async () => { await call(`/api/tasks/${task.id}/${task.done_at ? "reopen" : "done"}`, "POST"); onChange(); };
  const remove = async () => { if (await dialog.confirm("Delete this task?", { danger: true, confirmLabel: "Delete" })) { await call(`/api/tasks/${task.id}`, "DELETE"); onChange(); } };
  return (
    <li style={{ margin: "4px 0", listStyle: "none" }}>
      <label style={{ textDecoration: task.done_at ? "line-through" : "none" }}>
        <input type="checkbox" checked={!!task.done_at} onChange={toggle} /> {task.title}
      </label>
      {task.due_date && <small style={{ color: "var(--muted)" }}> · due {task.due_date}</small>}
      {showEntity && task.entity_link && <small> · <Link href={task.entity_link}>{task.entity_name}</Link></small>}
      {task.details && <div style={{ color: "var(--muted)", marginLeft: 24, whiteSpace: "pre-wrap" }}>{task.details}</div>}
      {" "}<button onClick={remove} aria-label={`Delete task ${task.title}`}>×</button>
    </li>
  );
}

export function TasksPanel({ entityType, entityId }) {
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ title: "", due_date: "" });

  const load = () => call(`/api/tasks?today=${localToday()}&entity_type=${entityType}&entity_id=${entityId}`)
    .then((r) => r.ok && setData(r.data));
  useEffect(() => { load(); }, [entityType, entityId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(title, due_date) {
    const r = await call("/api/tasks", "POST", { title, due_date: due_date || null, entity_type: entityType, entity_id: entityId });
    if (r.ok) { setForm({ title: "", due_date: "" }); load(); }
  }

  if (!data) return null;
  const open = [...data.overdue, ...data.due_today, ...data.upcoming, ...data.no_date];

  return (
    <div>
      <h2 style={{ marginTop: 32 }}>Tasks</h2>
      {data.overdue.length > 0 && <p style={{ color: "var(--danger)" }}>{data.overdue.length} overdue</p>}
      <ul style={{ padding: 0 }}>{open.map((t) => <TaskRow key={t.id} task={t} onChange={load} />)}</ul>
      <form onSubmit={(e) => { e.preventDefault(); add(form.title, form.due_date); }} style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <input required placeholder="Follow-up task for you…" aria-label="New task" value={form.title}
               onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ flex: 1 }} />
        <input type="date" aria-label="Due date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
        <button type="submit">Add task</button>
        <button type="button" onClick={() => add("Follow up", localToday(3))}>Follow up in 3 days</button>
        <button type="button" onClick={() => add("Follow up", localToday(7))}>in 1 week</button>
      </form>
      {data.done.length > 0 && (
        <details><summary>{data.done.length} done</summary>
          <ul style={{ padding: 0 }}>{data.done.map((t) => <TaskRow key={t.id} task={t} onChange={load} />)}</ul>
        </details>
      )}
    </div>
  );
}
