"use client";
// F6: opportunities. Stage chips with counts, two views (By stage / Table), open-closed switch. Stages only move by
// the owner's choice or a recorded fact; an AI suggestion is only ever accepted with a click. Drag-and-drop is Phase 3.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Badge, EmptyState, Loading, PageHeader, Tabs, ago, useDialog, useToast } from "../ui";
import { STAGES, StageBadge } from "./shared";

const CLOSED = ["hired", "rejected", "withdrawn"];
const COLS = [["title", "Opportunity"], ["company_name", "Company"], ["contact_name", "Contact"], ["stage", "Stage"],
              ["stage_changed_at", "In stage"], ["next", "Next interview"]];

const fmtNext = (i) => i && new Date(i.starts_at).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default function Opportunities() {
  const router = useRouter();
  const dialog = useDialog();
  const toast = useToast();
  const [data, setData] = useState(null);
  const [next, setNext] = useState({});           // opportunity id -> its next scheduled interview
  const [view, setView] = useState("By stage");
  const [showClosed, setShowClosed] = useState(false);
  const [only, setOnly] = useState("");
  const [sort, setSort] = useState(["stage_changed_at", -1]);

  async function load() {
    const res = await fetch("/api/opportunities");
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
    const iv = await fetch("/api/interviews?when=upcoming").then((r) => (r.ok ? r.json() : []));
    const m = {};
    iv.forEach((i) => { if (!m[i.opportunity_id]) m[i.opportunity_id] = i; });  // list is ordered by start time
    setNext(m);
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function move(o, stage, reason = "") {
    if (stage === o.stage) return;
    const r = await fetch(`/api/opportunities/${o.id}/stage`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage, reason }) });
    toast(r.ok ? `${o.title} moved to ${stage}.` : "Couldn't move it.", r.ok ? "" : "error");
    load();
  }
  async function pick(o, stage) {
    if (["rejected", "withdrawn"].includes(stage)) {
      const reason = await dialog.prompt(`Mark "${o.title}" as ${stage}?`, { label: "Reason (optional)", confirmLabel: `Mark ${stage}`, danger: true });
      if (reason === null) return;
      return move(o, stage, reason);
    }
    move(o, stage);
  }

  const visible = useMemo(() => {
    const list = (data?.opportunities || []).filter((o) => (only ? o.stage === only : showClosed || !CLOSED.includes(o.stage)));
    const [key, dir] = sort;
    const val = (o) => key === "next" ? next[o.id]?.starts_at || "9" : key === "stage" ? STAGES.indexOf(o.stage) : (o[key] ?? "").toString().toLowerCase();
    return [...list].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * dir);
  }, [data, only, showClosed, sort, next]);

  const Card = ({ o }) => (
    <div className="opp-card" data-opp={o.id}>
      <Link href={`/opportunities/${o.id}`}><b>{o.title}</b></Link>
      <div><Link href={`/companies/${o.company_id}`}><small>{o.company_name}</small></Link>{o.contact_name && <small style={{ color: "var(--muted)" }}> · {o.contact_name}</small>}</div>
      <small style={{ color: "var(--muted)" }}>in {o.stage} {ago(o.stage_changed_at).replace(" ago", "")}</small>
      {next[o.id] && <div><Badge tone="warning">📅 {fmtNext(next[o.id])}</Badge></div>}
      {o.suggestion && (
        <div className="opp-suggest"><small>AI suggests <b>{o.suggestion.stage}</b></small>{" "}
          <button className="btn-sm" onClick={() => move(o, o.suggestion.stage, `accepted AI suggestion (${o.suggestion.ai_label})`)}>Accept</button></div>
      )}
      <select aria-label={`Stage of ${o.title}`} value={o.stage} onChange={(e) => pick(o, e.target.value)}>
        {STAGES.map((s) => <option key={s}>{s}</option>)}
      </select>
    </div>
  );

  if (!data) return <Loading what="opportunities" />;
  const counts = data.counts;
  const total = data.opportunities.length;
  const stages = STAGES.filter((s) => (only ? s === only : showClosed || !CLOSED.includes(s)));

  return (
    <main>
      <PageHeader title="Opportunities" sub="Create one from a reply (Inbox or conversation). Stages only move by your choice or a recorded fact; AI labels only suggest." />

      <div className="chips" role="group" aria-label="Stages" style={{ marginBottom: 12 }}>
        {STAGES.map((s) => (
          <button key={s} className={`chip-btn${only === s ? " on" : ""}`} data-stage-chip={s} aria-pressed={only === s} onClick={() => setOnly(only === s ? "" : s)}>
            <StageBadge stage={s} /> <b data-count>{counts[s] || 0}</b>
          </button>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Tabs tabs={["By stage", "Table"]} value={view} onChange={setView} />
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Show closed (hired, rejected, withdrawn)
        </label>
      </div>

      {total === 0 ? (
        <EmptyState title="No opportunities yet" action={<Link className="btn btn-primary" href="/inbox">Open the inbox</Link>}>
          Open a reply in the Inbox and click “Create opportunity”, or add one by hand on a company page.
        </EmptyState>
      ) : visible.length === 0 ? (
        <EmptyState title="Nothing open here">Everything is closed. Tick “Show closed” to see it.</EmptyState>
      ) : view === "By stage" ? (
        <div className="stage-board">
          {stages.map((s) => {
            const items = visible.filter((o) => o.stage === s);
            return (
              <section key={s} className="stage-col" aria-label={`Stage ${s}`}>
                <h3 style={{ margin: "0 0 8px" }}><StageBadge stage={s} /> <small style={{ color: "var(--muted)" }}>{items.length}</small></h3>
                {items.length === 0 ? <small style={{ color: "var(--muted)" }}>none</small> : items.map((o) => <Card key={o.id} o={o} />)}
              </section>
            );
          })}
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>{COLS.map(([k, label]) => (
              <th key={k} aria-sort={sort[0] === k ? (sort[1] === 1 ? "ascending" : "descending") : "none"}>
                <button type="button" className="th-sort" onClick={() => setSort(([c, d]) => [k, c === k ? -d : 1])}>{label}{sort[0] === k ? (sort[1] === 1 ? " ▲" : " ▼") : ""}</button></th>))}<th /></tr></thead>
            <tbody>
              {visible.map((o) => (
                <tr key={o.id}>
                  <td><Link href={`/opportunities/${o.id}`}><b>{o.title}</b></Link></td>
                  <td><Link href={`/companies/${o.company_id}`}>{o.company_name}</Link></td>
                  <td>{o.contact_name || "—"}</td>
                  <td><StageBadge stage={o.stage} /></td>
                  <td><small>{ago(o.stage_changed_at).replace(" ago", "")}</small></td>
                  <td><small>{next[o.id] ? fmtNext(next[o.id]) : "—"}</small></td>
                  <td>{o.suggestion && <button className="btn-sm" onClick={() => move(o, o.suggestion.stage, `accepted AI suggestion (${o.suggestion.ai_label})`)}>AI: {o.suggestion.stage} · Accept</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
