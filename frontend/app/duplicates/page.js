"use client";
// F3: duplicates. Each suggested pair side by side; the owner keeps one (merge, undoable) or dismisses the pair.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { Badge, EmptyState, Loading, PageHeader, useDialog, useToast } from "../ui";

const REASON = { domain: "same domain", email: "contact email", linkedin: "same LinkedIn", name: "similar name" };

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return { ok: r.ok, data: await r.json() };
}

function Side({ c, label, onKeep }) {
  return (
    <div className="dup-side">
      <small style={{ color: "var(--muted)" }}>{label}</small>
      <div><Link href={`/companies/${c.id}`}><b>{c.name}</b></Link></div>
      <div><small style={{ color: "var(--muted)" }}>{c.domain || "no domain"}</small></div>
      <button className="btn-sm" style={{ marginTop: 8 }} onClick={onKeep}>Keep {label.toLowerCase()}</button>
    </div>
  );
}

export default function Duplicates() {
  const dialog = useDialog();
  const toast = useToast();
  const router = useRouter();
  const [pairs, setPairs] = useState(null);
  const [merges, setMerges] = useState([]);

  async function load() {
    const r = await fetch("/api/duplicates");
    if (r.status === 401) return router.replace("/login");
    setPairs(await r.json());
    setMerges(await fetch("/api/duplicates/merges").then((x) => x.json()));
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(p, okMsg) {
    const r = await p;
    toast(r.ok ? okMsg : errorText(r.data), r.ok ? "" : "error");
    load();
  }

  async function merge(keep, drop) {
    if (!await dialog.confirm(`Merge "${drop.name}" into "${keep.name}"?`, { confirmLabel: "Merge",
      body: `All of ${drop.name}'s contacts, emails, replies, opportunities, notes and tasks move to ${keep.name}; ${drop.name} is archived. You can undo this below.` })) return;
    act(post("/api/duplicates/merge", { survivor_id: keep.id, merged_id: drop.id }), `Merged "${drop.name}" into "${keep.name}".`);
  }
  async function undo(g) {
    if (!await dialog.confirm(`Undo merge #${g.id}?`, { body: `${g.merged_name} is restored with the records the merge moved.`, confirmLabel: "Undo merge" })) return;
    act(post(`/api/duplicates/merges/${g.id}/undo`), `Merge #${g.id} undone.`);
  }

  if (!pairs) return <Loading what="duplicates" />;
  return (
    <main>
      <PageHeader title="Duplicates" sub="Suggestions only: nothing is merged unless you choose. A merge can be undone." />
      {pairs.length === 0 ? <EmptyState title="No likely duplicates">Companies that seem to be the same appear here.</EmptyState> : (
        <div style={{ display: "grid", gap: 12 }}>
          {pairs.map((p) => {
            const a = { id: p.a, name: p.a_name, domain: p.a_domain }, b = { id: p.b, name: p.b_name, domain: p.b_domain };
            return (
              <section key={`${p.a}-${p.b}`} className="card" data-pair={`${p.a}-${p.b}`}>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
                  {p.reasons.map((r) => <Badge key={r} tone="warning">{REASON[r] || r}</Badge>)}
                  <small style={{ color: "var(--muted)" }}>{p.details.join(" · ")}</small>
                </div>
                <div className="dup-grid">
                  <Side c={a} label="Left" onKeep={() => merge(a, b)} />
                  <div className="dup-vs" aria-hidden="true">↔</div>
                  <Side c={b} label="Right" onKeep={() => merge(b, a)} />
                </div>
                <div style={{ marginTop: 10, textAlign: "right" }}>
                  <button className="btn-ghost btn-sm" onClick={() => act(post("/api/duplicates/dismiss", { company_a: p.a, company_b: p.b }), "Marked as not a duplicate.")}>Not a duplicate</button>
                </div>
              </section>
            );
          })}
        </div>
      )}

      <h2>Merge history</h2>
      {merges.length === 0 ? <p style={{ color: "var(--muted)" }}>No merges yet.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>When</th><th>Merged</th><th>Into</th><th /></tr></thead>
            <tbody>
              {merges.map((g) => (
                <tr key={g.id}>
                  <td>{g.id}</td>
                  <td><small>{new Date(g.merged_at).toLocaleString()}</small></td>
                  <td><Link href={`/companies/${g.merged_id}`}>{g.merged_name}</Link></td>
                  <td><Link href={`/companies/${g.survivor_id}`}>{g.survivor_name}</Link></td>
                  <td style={{ textAlign: "right" }}>
                    {g.undone_at ? <small style={{ color: "var(--muted)" }}>undone {new Date(g.undone_at).toLocaleString()}</small>
                                 : <button className="btn-sm" onClick={() => undo(g)}>Undo</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
