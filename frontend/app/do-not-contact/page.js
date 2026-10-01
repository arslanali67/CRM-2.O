"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { useDialog, PageHeader, Loading, EmptyState } from "../ui";

const target = (s) => s.email || s.domain || `${s.company_name} (company)`;

export default function DoNotContact() {
  const dialog = useDialog();
  const router = useRouter();
  const [list, setList] = useState(null);
  const [form, setForm] = useState({ kind: "email", value: "", reason: "" });
  const [msg, setMsg] = useState("");

  async function load() {
    const res = await fetch("/api/suppressions");
    if (res.status === 401) return router.replace("/login");
    setList(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function add(e) {
    e.preventDefault();
    const res = await fetch("/api/suppressions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const data = await res.json();
    if (!res.ok) return setMsg(errorText(data));
    setMsg(`Blocked.${data.cancelled_emails ? ` ${data.cancelled_emails} pending email(s) cancelled.` : ""}`);
    setForm({ ...form, value: "", reason: "" });
    load();
  }

  async function lift(s) {
    const reason = await dialog.prompt(`Lift the block on ${target(s)}?`, { body: "A reason is required and kept in the audit log.", required: true, confirmLabel: "Lift block" });
    if (!reason?.trim()) return;
    const res = await fetch(`/api/suppressions/${s.id}/lift`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    });
    setMsg(res.ok ? "Block lifted." : errorText(await res.json()));
    load();
  }

  if (!list) return <Loading what="blocks" />;

  return (
    <main>
      <PageHeader title="Do-not-contact" />
      <p>Blocked recipients can never be approved, queued or sent to. Company blocks are added from the company page.</p>

      <form onSubmit={add} className="card" style={{ display: "grid", gap: 8 }}>
        <label>Block
          <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })} style={{ marginLeft: 8 }}>
            <option value="email">email address</option>
            <option value="domain">domain (and subdomains)</option>
          </select>
        </label>
        <input required placeholder={form.kind === "email" ? "name@company.com" : "company.com"} aria-label="Email or domain"
               value={form.value} onChange={(e) => setForm({ ...form, value: e.target.value })} />
        <input required placeholder="Reason, e.g. asked not to be contacted" aria-label="Reason"
               value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <button type="submit">Add block</button>
        {msg && <p role="status">{msg}</p>}
      </form>

      <div className="table-wrap" style={{ marginTop: 16 }}><table style={{ width: "100%" }}>
        <thead><tr><th align="left">Blocked</th><th align="left">Reason</th><th align="left">Status</th><th /></tr></thead>
        <tbody>
          {list.map((s) => (
            <tr key={s.id} style={{ opacity: s.lifted_at ? 0.55 : 1 }}>
              <td>{s.kind === "company" ? <Link href={`/companies/${s.company_id}`}>{target(s)}</Link> : target(s)}</td>
              <td>{s.reason}</td>
              <td>
                {s.lifted_at
                  ? <>lifted {new Date(s.lifted_at).toLocaleDateString()}: {s.lift_reason}</>
                  : <>active since {new Date(s.created_at).toLocaleDateString()}</>}
              </td>
              <td>{!s.lifted_at && <button onClick={() => lift(s)}>Lift</button>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {list.length === 0 && <EmptyState title="Nothing blocked">Blocked emails and domains appear here.</EmptyState>}
    </main>
  );
}
