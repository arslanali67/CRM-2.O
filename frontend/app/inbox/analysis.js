"use client";
import { useState } from "react";

const PRETTY = (s) => (s || "").replaceAll("_", " ");
const Quote = ({ text }) => <q style={{ color: "gray", fontStyle: "italic" }}>{text}</q>;

// M16 result. Every item shows its verified evidence quote. Links are plain text on purpose
// (they come from untrusted email); copy them if you want to open them.
export function Analysis({ messageId, analysis, onChange, aiEnabled }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function run() {
    setBusy(true);
    const res = await fetch(`/api/inbox/${messageId}/analyse`, { method: "POST" });
    const data = await res.json();
    setBusy(false);
    setMsg(res.ok ? "" : data.detail);
    if (res.ok) onChange();
  }

  const a = analysis;
  const x = a?.extracted || {};
  return (
    <div style={{ border: "1px solid #b9c7ff", background: "#f5f7ff", padding: 8, margin: "8px 0" }}>
      <b>AI analysis</b>{" "}
      {aiEnabled && <button onClick={run} disabled={busy}>{a ? "Analyse again" : "Analyse now"}</button>}
      {!a && <small> not analysed yet{!aiEnabled && " (add GEMINI_API_KEY to .env to enable)"}</small>}
      {msg && <small style={{ color: "crimson" }}> {msg}</small>}
      {a?.status === "error" && <div style={{ color: "crimson" }}><small>Error: {a.error} (retried automatically)</small></div>}
      {a?.status === "unverified" && <div><small>The model's label could not be proven from the email text, so it was not used.</small></div>}
      {a?.status === "ok" && (
        <div><mark>{PRETTY(a.label)}</mark> <Quote text={a.label_evidence} /></div>
      )}
      {a?.summary && <div><small>{a.summary}</small></div>}
      {x.dates?.length > 0 && <div><b>Dates:</b> {x.dates.map((d, i) => (
        <div key={i}>{d.iso || d.text} · {PRETTY(d.purpose)} <Quote text={d.evidence} /></div>))}</div>}
      {x.links?.length > 0 && <div><b>Links:</b> {x.links.map((l, i) => (
        <div key={i}><code>{l.url}</code> · {PRETTY(l.purpose)} <Quote text={l.evidence} /></div>))}</div>}
      {x.documents?.length > 0 && <div><b>Documents requested:</b> {x.documents.map((d, i) => (
        <div key={i}>{PRETTY(d.document)} <Quote text={d.evidence} /></div>))}</div>}
      {x.contacts?.length > 0 && <div><b>Contacts:</b> {x.contacts.map((c, i) => (
        <div key={i}>{c.name}{c.role && ` (${c.role})`}{c.email && ` · ${c.email}`} <Quote text={c.evidence} /></div>))}</div>}
      {a?.label === "unsubscribe_request" && (
        <div style={{ color: "crimson" }}><small>Suggestion: they asked not to be contacted. Consider adding a block on the
          Do-not-contact page. Nothing was blocked automatically.</small></div>
      )}
      {a?.dropped?.length > 0 && <div><small style={{ color: "gray" }}>{a.dropped.length} item(s) from the model were
        dropped because they could not be found in the email.</small></div>}
    </div>
  );
}
