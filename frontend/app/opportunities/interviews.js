"use client";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { NotesPanel } from "../tasks/panels";
import { useDialog } from "../ui";

const myZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const blank = () => ({ title: "", local_start: "", time_zone: myZone(), duration_minutes: 60, kind: "video",
                       location: "", interviewers: "", notes: "" });
const KINDS = [["video", "Video call"], ["phone", "Phone"], ["onsite", "On-site"]];

export function When({ i }) {
  const mine = new Date(i.starts_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  return (
    <span>
      <b>{i.local_label}</b>
      {i.time_zone !== myZone() && <small style={{ color: "var(--muted)" }}> · your time: {mine}</small>}
    </span>
  );
}

async function send(url, method, body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return { ok: r.ok, data: await r.json() };
}

export function InterviewsPanel({ opportunityId, onChange }) {
  const dialog = useDialog();
  const [list, setList] = useState([]);
  const [zones, setZones] = useState([]);
  const [form, setForm] = useState(null);      // null = closed; {id?} when adding/editing
  const [hint, setHint] = useState(null);
  const [msg, setMsg] = useState("");

  const load = () => fetch(`/api/opportunities/${opportunityId}/interviews`).then((r) => r.json()).then(setList);
  useEffect(() => {
    load();
    fetch("/api/interview-zones").then((r) => r.json()).then(setZones);
    fetch(`/api/opportunities/${opportunityId}/interview-suggestion`).then((r) => r.json()).then(setHint);
  }, [opportunityId]); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function save(e) {
    e.preventDefault();
    const { id, ...body } = form;
    const r = id ? await send(`/api/interviews/${id}`, "PUT", body)
                 : await send(`/api/opportunities/${opportunityId}/interviews`, "POST", body);
    if (!r.ok) return setMsg(errorText(r.data));
    setMsg(id ? "Interview updated." : "Interview recorded.");
    setForm(null);
    load();
    onChange?.();
  }

  async function status(i, s) {
    const outcome = s === "done" ? await dialog.prompt(`Mark "${i.title}" as done`, { label: "Outcome (optional)", placeholder: "How did it go?", defaultValue: i.outcome, confirmLabel: "Mark done" }) : "";
    if (outcome === null) return;
    if (s === "cancelled" && !await dialog.confirm(`Cancel "${i.title}"?`, { body: "Reminders stop; the calendar file shows it as cancelled.", danger: true, confirmLabel: "Cancel interview", cancelLabel: "Keep" })) return;
    await send(`/api/interviews/${i.id}/status`, "POST", { status: s, outcome });
    load();
  }

  return (
    <section className="card">
      <h3 style={{ marginTop: 0 }}>Interviews</h3>
      {list.length === 0 && <p>No interviews yet.</p>}
      {list.map((i) => (
        <div key={i.id} id={`interview-${i.id}`} style={{ borderTop: "1px solid var(--border)", padding: "8px 0" }}>
          <div>
            <b>{i.title}</b> · <When i={i} /> · {i.duration_minutes} min · {KINDS.find(([k]) => k === i.kind)?.[1]}
            {" "}<mark style={{ background: i.status === "scheduled" ? "var(--accent-bg)" : i.status === "done" ? "var(--success-bg)" : "var(--border)" }}>{i.status}</mark>
          </div>
          {i.location && <div>{/^https?:\/\//i.test(i.location)
            ? <a href={i.location} target="_blank" rel="noopener noreferrer">{i.location}</a> : i.location}</div>}
          {i.interviewers && <div><small>With: {i.interviewers}</small></div>}
          {i.notes && <div style={{ whiteSpace: "pre-wrap" }}><small>{i.notes}</small></div>}
          {i.outcome && <div><small>Outcome: {i.outcome}</small></div>}
          <div style={{ marginTop: 4 }}>
            <a href={`/api/interviews/${i.id}/calendar.ics`}>Add to calendar (.ics)</a>
            {i.status === "scheduled" && <>
              {" · "}<button onClick={() => setForm({ id: i.id, title: i.title, local_start: i.local_start, time_zone: i.time_zone,
                duration_minutes: i.duration_minutes, kind: i.kind, location: i.location, interviewers: i.interviewers, notes: i.notes })}>Edit</button>
              {" "}<button onClick={() => status(i, "done")}>Mark done</button>
              {" "}<button onClick={() => status(i, "cancelled")}>Cancel</button>
            </>}
          </div>
          <NotesPanel entityType="interview" entityId={i.id} compact />
        </div>
      ))}

      {!form && <p>
        <button onClick={() => setForm(blank())}>Record an interview</button>
        {hint && <> {" "}<button onClick={() => setForm({ ...blank(), title: "Interview", local_start: hint.local_start })}>
          Prefill from AI suggestion ({hint.text})</button>
          <br /><small style={{ color: "var(--muted)" }}>From the reply: “{hint.evidence}”. Check the time zone before saving.</small></>}
      </p>}
      {msg && <p>{msg}</p>}

      {form && (
        <form onSubmit={save} style={{ display: "grid", gap: 6, maxWidth: 520, border: "1px solid var(--border)", padding: 12 }}>
          <b>{form.id ? "Edit interview" : "Record an interview"}</b>
          <label>Title <input required value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="First call with CTO" /></label>
          <label>Date and time <input type="datetime-local" required value={form.local_start} onChange={(e) => set("local_start", e.target.value)} /></label>
          <label>Time zone it was agreed in{" "}
            <select value={form.time_zone} onChange={(e) => set("time_zone", e.target.value)}>
              {(zones.length ? zones : [form.time_zone]).map((z) => <option key={z}>{z}</option>)}
            </select>
          </label>
          <label>Duration (minutes) <input type="number" min={5} max={600} value={form.duration_minutes}
                                           onChange={(e) => set("duration_minutes", Number(e.target.value))} /></label>
          <label>Type <select value={form.kind} onChange={(e) => set("kind", e.target.value)}>
            {KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label>Meeting link or address <input value={form.location} onChange={(e) => set("location", e.target.value)} placeholder="https://… or street address" /></label>
          <label>Interviewers <input value={form.interviewers} onChange={(e) => set("interviewers", e.target.value)} /></label>
          <label>Notes <textarea rows={3} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></label>
          <span><button type="submit">Save</button> <button type="button" onClick={() => setForm(null)}>Close</button></span>
          <small style={{ color: "var(--muted)" }}>Reminders appear in the app 24 h and 1 h before. Nothing is ever emailed.</small>
        </form>
      )}
    </section>
  );
}
