"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { STAGES, StageBadge } from "../shared";

export default function Opportunity() {
  const { id } = useParams();
  const router = useRouter();
  const [o, setO] = useState(null);
  const [msg, setMsg] = useState("");
  const [stage, setStage] = useState("");
  const [reason, setReason] = useState("");

  async function load() {
    const res = await fetch(`/api/opportunities/${id}`);
    if (res.status === 401) return router.replace("/login");
    const data = await res.json();
    if (!res.ok) return setMsg(data.detail);
    setO(data);
    setStage(data.stage);
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function move(to, why) {
    await fetch(`/api/opportunities/${id}/stage`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage: to, reason: why }),
    });
    setReason("");
    load();
  }

  if (!o) return <p>{msg || "Loading…"}</p>;
  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/opportunities">← Opportunities</Link> · <Link href={`/companies/${o.company_id}`}>{o.company_name}</Link></p>
      <h1 style={{ marginBottom: 4 }}>{o.title} <StageBadge stage={o.stage} /></h1>
      <p style={{ color: "gray" }}><small>
        {o.contact_name && <>Contact: <Link href={`/contacts/${o.contact_id}`}>{o.contact_name}</Link> · </>}
        {o.source_link ? <>From reply: <Link href={o.source_link}>{o.source_subject}</Link></> : "created manually"}
        {" · "}since {new Date(o.created_at).toLocaleDateString()}
      </small></p>

      {o.suggestion && (
        <p style={{ background: "#f5f7ff", padding: 8 }}>
          AI read the latest reply as <b>{o.suggestion.ai_label.replaceAll("_", " ")}</b>
          {o.suggestion.evidence && <> (“<i>{o.suggestion.evidence}</i>”)</>}. Move to <b>{o.suggestion.stage}</b>?{" "}
          <button onClick={() => move(o.suggestion.stage, `accepted AI suggestion (${o.suggestion.ai_label})`)}>Yes, move</button>
          <br /><small>AI never moves a stage by itself.</small>
        </p>
      )}

      <form onSubmit={(e) => { e.preventDefault(); move(stage, reason); }} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <select aria-label="Stage" value={stage} onChange={(e) => setStage(e.target.value)}>
          {STAGES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <input placeholder="Reason (optional)" aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
        <button type="submit" disabled={stage === o.stage}>Change stage</button>
      </form>

      <h2 style={{ marginTop: 24 }}>Stage history</h2>
      <ol>
        {o.history.map((h) => (
          <li key={h.id}>
            {h.from_stage ? <>{h.from_stage} → </> : "created as "}<b>{h.to_stage}</b>
            <small style={{ color: "gray" }}> · {new Date(h.at).toLocaleString()} · {h.actor}{h.reason && ` · ${h.reason}`}</small>
          </li>
        ))}
      </ol>

      <TasksPanel entityType="opportunity" entityId={o.id} />
      <NotesPanel entityType="opportunity" entityId={o.id} />
    </main>
  );
}
