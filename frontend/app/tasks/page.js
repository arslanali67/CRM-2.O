"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { TaskRow, localToday } from "./panels";

const GROUPS = [["overdue", "Overdue", "crimson"], ["due_today", "Today"], ["upcoming", "Upcoming"], ["no_date", "No date"]];

export default function Tasks() {
  const router = useRouter();
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ title: "", due_date: "", details: "" });
  const [msg, setMsg] = useState("");

  async function load() {
    const res = await fetch(`/api/tasks?today=${localToday()}`);
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(e) {
    e.preventDefault();
    const res = await fetch("/api/tasks", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, due_date: form.due_date || null }),
    });
    if (!res.ok) return setMsg(errorText(await res.json()));
    setMsg("");
    setForm({ title: "", due_date: "", details: "" });
    load();
  }

  if (!data) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/">← Home</Link></p>
      <h1>Tasks</h1>
      <p style={{ color: "gray" }}>Follow-ups are reminders for you. Nothing here ever sends an email. Today is {data.today}.</p>

      <form onSubmit={add} style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        <input required placeholder="New task" aria-label="New task" value={form.title}
               onChange={(e) => setForm({ ...form, title: e.target.value })} style={{ flex: 1 }} />
        <input type="date" aria-label="Due date" value={form.due_date} onChange={(e) => setForm({ ...form, due_date: e.target.value })} />
        <button type="submit">Add task</button>
      </form>
      {msg && <p role="alert">{msg}</p>}

      {GROUPS.map(([key, label, color]) => (
        <section key={key}>
          <h2 style={{ color: data[key].length && color ? color : undefined }}>{label} ({data[key].length})</h2>
          <ul style={{ padding: 0 }}>{data[key].map((t) => <TaskRow key={t.id} task={t} onChange={load} showEntity />)}</ul>
        </section>
      ))}
      <details>
        <summary>Done ({data.done.length}{data.done.length === 50 ? ", most recent" : ""})</summary>
        <ul style={{ padding: 0 }}>{data.done.map((t) => <TaskRow key={t.id} task={t} onChange={load} showEntity />)}</ul>
      </details>
    </main>
  );
}
