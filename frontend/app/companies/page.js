"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { COMPANY_FIELDS, errorText } from "./shared";

const EMPTY = Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, ""]));

export default function Companies() {
  const router = useRouter();
  const [list, setList] = useState(null);
  const [archived, setArchived] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [msg, setMsg] = useState("");

  async function load() {
    const res = await fetch(`/api/companies?archived=${archived}`);
    if (res.status === 401) return router.replace("/login");
    setList(await res.json());
  }
  useEffect(() => { load(); }, [archived]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(e) {
    e.preventDefault();
    const res = await fetch("/api/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    if (!res.ok) return setMsg(errorText(await res.json()));
    setMsg("Added.");
    setForm(EMPTY);
    load();
  }

  if (!list) return <p>Loading…</p>;

  return (
    <main>
      <p><Link href="/">← Home</Link></p>
      <h1>Companies</h1>
      <label>
        <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Show archived
      </label>
      <table style={{ width: "100%", marginTop: 12 }}>
        <thead><tr><th align="left">Name</th><th align="left">Domain</th><th align="left">City</th><th align="right">Contacts</th></tr></thead>
        <tbody>
          {list.map((c) => (
            <tr key={c.id}>
              <td><Link href={`/companies/${c.id}`}>{c.name}</Link></td>
              <td>{c.domain}</td>
              <td>{c.city}</td>
              <td align="right">{c.contact_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.length === 0 && <p>No {archived ? "archived " : ""}companies.</p>}

      <h2 style={{ marginTop: 32 }}>Add company</h2>
      <form onSubmit={add} style={{ display: "grid", gap: 8 }}>
        {COMPANY_FIELDS.map(([k, label, type]) => (
          <label key={k}>{label}
            {type === "textarea"
              ? <textarea rows={3} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={{ display: "block", width: "100%" }} />
              : <input type={type || "text"} required={k === "name"} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={{ display: "block", width: "100%" }} />}
          </label>
        ))}
        <button type="submit">Add company</button>
        {msg && <p role="status">{msg}</p>}
      </form>
    </main>
  );
}
