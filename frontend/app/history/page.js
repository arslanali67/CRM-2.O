"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const STATUSES = ["queued", "sending", "sent", "failed", "cancelled"];
const NO_FILTERS = { status: "", q: "", since: "", until: "" };
const COLOR = { sent: "var(--success)", failed: "var(--danger)", cancelled: "var(--muted)", sending: "var(--warning)", queued: "var(--accent)" };

export default function History() {
  const router = useRouter();
  const [filters, setFilters] = useState(NO_FILTERS);
  const [data, setData] = useState(null);

  async function load(f = filters) {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
    const res = await fetch(`/api/history?${q}`);
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k, v) => setFilters({ ...filters, [k]: v });
  if (!data) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 1000 }}>
      <p><Link href="/">← Home</Link> · <Link href="/outbox">Outbox</Link></p>
      <h1>Email history</h1>
      <p><small>{STATUSES.map((s) => `${s}: ${data.counts[s] || 0}`).join(" · ")}</small></p>
      <form onSubmit={(e) => { e.preventDefault(); load(); }} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <select aria-label="Status" value={filters.status} onChange={(e) => set("status", e.target.value)}>
          <option value="">Status: any</option>
          {STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <input placeholder="Search recipient or subject" aria-label="Search" value={filters.q} onChange={(e) => set("q", e.target.value)} />
        <label>From <input type="date" value={filters.since} onChange={(e) => set("since", e.target.value)} /></label>
        <label>to <input type="date" value={filters.until} onChange={(e) => set("until", e.target.value)} /></label>
        <button type="submit">Filter</button>
        <button type="button" onClick={() => { setFilters(NO_FILTERS); load(NO_FILTERS); }}>Clear</button>
      </form>

      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
        <thead><tr><th align="left">Status</th><th align="left">To</th><th align="left">Company</th><th align="left">Subject</th><th align="left">When</th><th /></tr></thead>
        <tbody>
          {data.emails.map((e) => (
            <tr key={e.id} style={{ borderTop: "1px solid var(--border)", verticalAlign: "top" }}>
              <td style={{ color: COLOR[e.status] }}>{e.status}</td>
              <td><Link href={`/outbox/${e.id}`}>{e.to_email}</Link></td>
              <td>{e.company_id ? <Link href={`/companies/${e.company_id}`}>{e.company_name}</Link> : "—"}</td>
              <td>
                {e.subject}
                {(e.failure_reason || e.cancel_reason) && <div style={{ color: "var(--danger)" }}><small>{e.failure_reason || e.cancel_reason}</small></div>}
              </td>
              <td><small>{new Date(e.last_activity_at).toLocaleString()}</small></td>
              <td><Link href={`/threads/${e.thread_key}`}><small>thread</small></Link></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.emails.length === 0 && <p>No emails match.</p>}
      {data.truncated && <p>Showing the 500 most recent; narrow the filters to see older ones.</p>}
    </main>
  );
}
