"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { TemplateFields } from "./editor";

const EMPTY = { name: "", subject: "", body: "" };

export default function Templates() {
  const router = useRouter();
  const [list, setList] = useState(null);
  const [archived, setArchived] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState("");

  async function load() {
    const res = await fetch(`/api/templates?archived=${archived}`);
    if (res.status === 401) return router.replace("/login");
    setList(await res.json());
  }
  useEffect(() => { load(); }, [archived]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create(e) {
    e.preventDefault();
    const res = await fetch("/api/templates", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    const data = await res.json();
    if (!res.ok) return setMsg(errorText(data));
    router.push(`/templates/${data.id}`);
  }

  if (!list) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/">← Home</Link></p>
      <h1>Email templates</h1>
      <label><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived</label>
      <table style={{ width: "100%", marginTop: 12 }}>
        <thead><tr><th align="left">Name</th><th align="left">Current subject</th><th align="right">Version</th></tr></thead>
        <tbody>
          {list.map((t) => (
            <tr key={t.id}>
              <td><Link href={`/templates/${t.id}`}>{t.name}</Link></td>
              <td><code>{t.subject}</code></td>
              <td align="right">v{t.version}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.length === 0 && <p>No {archived ? "archived " : ""}templates.</p>}

      <h2 style={{ marginTop: 32 }}>New template</h2>
      <form onSubmit={create} style={{ display: "grid", gap: 8 }}>
        <label>Name<input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                          style={{ display: "block", width: "100%" }} /></label>
        <TemplateFields value={form} onChange={setForm} />
        <button type="submit">Create template</button>
        {msg && <p role="alert" style={{ color: "var(--danger)" }}>{msg}</p>}
      </form>
    </main>
  );
}
