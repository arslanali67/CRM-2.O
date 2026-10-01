"use client";
// F6: one opportunity. Header with a stage stepper, the AI suggestion banner (accept only by click), interviews and
// the stage history as a timeline beside tasks and notes.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { Badge, ErrorState, Loading, ago, useDialog, useToast } from "../../ui";
import { InterviewsPanel } from "../interviews";
import { STAGES, StageBadge } from "../shared";

const PATH = ["new", "applied", "screening", "interviewing", "offer", "hired"];

export default function Opportunity() {
  const { id } = useParams();
  const router = useRouter();
  const dialog = useDialog();
  const toast = useToast();
  const [o, setO] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    const res = await fetch(`/api/opportunities/${id}`);
    if (res.status === 401) return router.replace("/login");
    const data = await res.json();
    res.ok ? setO(data) : setError(data.detail);
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function move(to, why = "") {
    const r = await fetch(`/api/opportunities/${id}/stage`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage: to, reason: why }) });
    toast(r.ok ? `Moved to ${to}.` : "Couldn't change the stage.", r.ok ? "" : "error");
    load();
  }
  async function change(to) {
    if (to === o.stage) return;
    const reason = await dialog.prompt(`Move to ${to}?`, { label: "Reason (optional)", placeholder: "Why? It is kept in the history.",
      confirmLabel: `Move to ${to}`, danger: ["rejected", "withdrawn"].includes(to) });
    if (reason === null) return;
    move(to, reason);
  }

  if (!o) return error ? <ErrorState>{error}</ErrorState> : <Loading what="opportunity" />;
  const at = PATH.indexOf(o.stage);
  const closed = ["rejected", "withdrawn"].includes(o.stage);

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href="/opportunities">← Opportunities</Link> · <Link href={`/companies/${o.company_id}`}>{o.company_name}</Link></p>

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 0 }}>
            <h1 style={{ margin: 0 }}>{o.title}</h1>
            <div className="mini-stats" style={{ marginTop: 6 }}>
              <span><StageBadge stage={o.stage} /></span>
              {o.contact_name && <span>contact <Link href={`/contacts/${o.contact_id}`}><b>{o.contact_name}</b></Link></span>}
              <span>{o.source_link ? <>from reply <Link href={o.source_link}>{o.source_subject}</Link></> : "created by hand"}</span>
              <span>since <b>{new Date(o.created_at).toLocaleDateString()}</b></span>
              <span>in this stage <b>{ago(o.stage_changed_at).replace(" ago", "")}</b></span>
            </div>
          </div>
          <div className="head-actions">
            {!closed && o.stage !== "hired" && <>
              <button className="btn-danger btn-sm" onClick={() => change("rejected")}>Rejected</button>
              <button className="btn-sm" onClick={() => change("withdrawn")}>Withdrawn</button></>}
            {(closed || o.stage === "hired") && <button className="btn-sm" onClick={() => change("new")}>Re-open</button>}
          </div>
        </div>

        <ol className="stepper" aria-label="Stage" style={{ listStyle: "none", padding: 0, margin: "16px 0 0" }}>
          {PATH.map((s, i) => (
            <li key={s} className={`stepper-item${!closed && i < at ? " done" : ""}${s === o.stage ? " current" : ""}`} aria-current={s === o.stage ? "step" : undefined}>
              <button type="button" className="stepper-btn" onClick={() => change(s)} disabled={s === o.stage} aria-label={`Move to ${s}`}>
                <span className="n">{!closed && i < at ? "✓" : i + 1}</span><span>{s}</span>
              </button>
            </li>
          ))}
        </ol>
        {closed && <p style={{ margin: "10px 0 0", color: "var(--muted)" }}><small>This opportunity is {o.stage}. Use Re-open to bring it back to new.</small></p>}
      </section>

      {o.suggestion && (
        <section className="card" style={{ marginTop: 12, borderColor: "var(--accent)", background: "var(--accent-bg)" }}>
          AI read the latest reply as <b>{o.suggestion.ai_label.replaceAll("_", " ")}</b>
          {o.suggestion.evidence && <> (“<i>{o.suggestion.evidence}</i>”)</>}. Move to <b>{o.suggestion.stage}</b>?{" "}
          <button className="btn-primary btn-sm" onClick={() => move(o.suggestion.stage, `accepted AI suggestion (${o.suggestion.ai_label})`)}>Yes, move</button>
          <div><small style={{ color: "var(--muted)" }}>AI never moves a stage by itself.</small></div>
        </section>
      )}

      <div className="panel-grid" style={{ marginTop: 16 }}>
        <div style={{ display: "grid", gap: 16, alignContent: "start", minWidth: 0 }}>
          <InterviewsPanel opportunityId={o.id} onChange={load} />
          <section className="card">
            <h3 style={{ marginTop: 0 }}>Stage history</h3>
            <ol className="history-line" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {[...o.history].reverse().map((h) => (
                <li key={h.id} data-history>
                  <span className="hl-dot" />
                  <div>{h.from_stage ? <><Badge>{h.from_stage}</Badge> → </> : "created as "}<Badge tone="accent">{h.to_stage}</Badge>
                    {h.reason && <div>“{h.reason}”</div>}
                    <small style={{ color: "var(--muted)" }}>{new Date(h.at).toLocaleString()} · {h.actor}</small></div>
                </li>
              ))}
            </ol>
          </section>
        </div>
        <div style={{ display: "grid", gap: 16, alignContent: "start", minWidth: 0 }}>
          <section className="card"><TasksPanel entityType="opportunity" entityId={o.id} /></section>
          <section className="card"><NotesPanel entityType="opportunity" entityId={o.id} /></section>
        </div>
      </div>
    </main>
  );
}
