"use client";
// F4: history of every email past draft, newest activity first, with status and bounce badges and filters.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, EmptyState, Loading, PageHeader, Tabs, ago } from "../ui";

const STATUSES = ["queued", "sending", "sent", "failed", "cancelled"];
const NO_FILTERS = { status: "", q: "", since: "", until: "" };
const TONE = { sent: "success", failed: "danger", cancelled: "", sending: "warning", queued: "accent" };

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
  function pickStatus(label) {
    const status = label.startsWith("all") ? "" : label.split(" ")[0];
    const f = { ...filters, status };
    setFilters(f); load(f);
  }
  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;

  return (
    <main>
      <PageHeader title="Email history" sub="Every email that left draft, newest activity first." />
      <Tabs tabs={[`all (${total})`, ...STATUSES.map((s) => `${s} (${data?.counts[s] || 0})`)]}
            value={filters.status ? `${filters.status} (${data?.counts[filters.status] || 0})` : `all (${total})`} onChange={pickStatus} />
      <form className="card filters" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <div className="filter-row" style={{ marginBottom: 0 }}>
          <input placeholder="Search recipient or subject" aria-label="Search" value={filters.q} onChange={(e) => set("q", e.target.value)} />
          <span className="range"><small>From</small><input type="date" aria-label="From date" value={filters.since} onChange={(e) => set("since", e.target.value)} />
            <small>to</small><input type="date" aria-label="To date" value={filters.until} onChange={(e) => set("until", e.target.value)} /></span>
          <button type="submit" className="btn-primary">Filter</button>
          <button type="button" className="btn-ghost" onClick={() => { setFilters(NO_FILTERS); load(NO_FILTERS); }}>Clear</button>
        </div>
      </form>

      {!data ? <Loading what="history" /> : data.emails.length === 0 ? (
        <EmptyState title="No emails match">Sent, queued and failed emails appear here once you approve and send drafts.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Status</th><th>To</th><th>Company</th><th>Subject</th><th>When</th><th /></tr></thead>
            <tbody>
              {data.emails.map((e) => (
                <tr key={e.id}>
                  <td><Badge tone={TONE[e.status]}>{e.status}</Badge>
                    {e.bounce_type && <> <Badge tone={e.bounce_type === "hard" ? "danger" : "warning"}>{e.bounce_type} bounce</Badge></>}</td>
                  <td><Link href={`/outbox/${e.id}`}>{e.to_email}</Link></td>
                  <td>{e.company_id ? <Link href={`/companies/${e.company_id}`}>{e.company_name}</Link> : "—"}</td>
                  <td>{e.subject}{(e.failure_reason || e.cancel_reason) && <div><small style={{ color: "var(--danger)" }}>{e.failure_reason || e.cancel_reason}</small></div>}</td>
                  <td><small title={new Date(e.last_activity_at).toLocaleString()}>{ago(e.last_activity_at)}</small></td>
                  <td><Link href={`/threads/${e.thread_key}`}><small>conversation</small></Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.truncated && <p><small style={{ color: "var(--muted)" }}>Showing the 500 most recent; narrow the filters to see older ones.</small></p>}
    </main>
  );
}
