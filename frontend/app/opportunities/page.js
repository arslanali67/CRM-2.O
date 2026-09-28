"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { STAGES, StageBadge } from "./shared";

// Grouped by stage (a drag-and-drop board is Phase 3).
export default function Opportunities() {
  const router = useRouter();
  const [data, setData] = useState(null);

  async function load() {
    const res = await fetch("/api/opportunities");
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function move(o, stage) {
    await fetch(`/api/opportunities/${o.id}/stage`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage }),
    });
    load();
  }

  if (!data) return <p>Loading…</p>;
  return (
    <main>
      <p><Link href="/">← Home</Link></p>
      <h1>Opportunities</h1>
      <p style={{ color: "gray" }}><small>Create one from a reply (Inbox or thread). Stages only move by your choice or a
        recorded fact; AI labels only suggest.</small></p>
      {STAGES.map((stage) => {
        const items = data.opportunities.filter((o) => o.stage === stage);
        return (
          <section key={stage} style={{ marginBottom: 16 }}>
            <h3 style={{ marginBottom: 4 }}><StageBadge stage={stage} /> {items.length}</h3>
            {items.map((o) => (
              <div key={o.id} style={{ borderLeft: "3px solid #ddd", paddingLeft: 8, margin: "4px 0" }}>
                <Link href={`/opportunities/${o.id}`}><b>{o.title}</b></Link> · <Link href={`/companies/${o.company_id}`}>{o.company_name}</Link>
                {o.contact_name && <small> · {o.contact_name}</small>}{" "}
                <select aria-label={`Stage of ${o.title}`} value={o.stage} onChange={(e) => move(o, e.target.value)}>
                  {STAGES.map((s) => <option key={s}>{s}</option>)}
                </select>
                {o.suggestion && (
                  <span> <small>AI suggests <b>{o.suggestion.stage}</b></small>{" "}
                    <button onClick={() => move(o, o.suggestion.stage)}>Accept</button></span>
                )}
              </div>
            ))}
          </section>
        );
      })}
      {data.opportunities.length === 0 && <p>No opportunities yet.</p>}
    </main>
  );
}
