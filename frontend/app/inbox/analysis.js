"use client";
// M16 result, F5 layout. Every item shows its verified evidence quote. Links are plain text on purpose
// (they come from untrusted email); copy them if you want to open them.
import { useState } from "react";
import { Badge } from "../ui";

const PRETTY = (s) => (s || "").replaceAll("_", " ");
const Quote = ({ text }) => <q style={{ color: "var(--muted)", fontStyle: "italic" }}>{text}</q>;
const Row = ({ title, children }) => <div style={{ marginTop: 8 }}><b style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.03em" }}>{title}</b>{children}</div>;

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
    <section className="card analysis" aria-label="AI analysis" style={{ borderColor: "var(--accent)", background: "var(--accent-bg)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <b>AI analysis</b>
        {aiEnabled && <button className="btn-sm" onClick={run} disabled={busy}>{a ? "Analyse again" : "Analyse now"}</button>}
      </div>
      {!a && <small style={{ color: "var(--muted)" }}>Not analysed yet{!aiEnabled && " (add GEMINI_API_KEY to .env to enable)"}.</small>}
      {msg && <div className="error-box" role="alert" style={{ marginTop: 6 }}>{msg}</div>}
      {a?.status === "error" && <div style={{ color: "var(--danger)" }}><small>Error: {a.error} (retried automatically)</small></div>}
      {a?.status === "unverified" && <div><small>The model&apos;s label could not be proven from the email text, so it was not used.</small></div>}
      {a?.status === "ok" && <div style={{ marginTop: 6 }}><Badge tone="accent" data-ai-label>{PRETTY(a.label)}</Badge> <Quote text={a.label_evidence} /></div>}
      {a?.summary && <p style={{ margin: "8px 0 0" }}>{a.summary}</p>}
      {x.dates?.length > 0 && <Row title="Dates">{x.dates.map((d, i) => <div key={i}>{d.iso || d.text} · {PRETTY(d.purpose)} <Quote text={d.evidence} /></div>)}</Row>}
      {x.links?.length > 0 && <Row title="Links (copy to open)">{x.links.map((l, i) => <div key={i}><code>{l.url}</code> · {PRETTY(l.purpose)} <Quote text={l.evidence} /></div>)}</Row>}
      {x.documents?.length > 0 && <Row title="Documents requested">{x.documents.map((d, i) => <div key={i}>{PRETTY(d.document)} <Quote text={d.evidence} /></div>)}</Row>}
      {x.contacts?.length > 0 && <Row title="Contacts">{x.contacts.map((c, i) => <div key={i}>{c.name}{c.role && ` (${c.role})`}{c.email && ` · ${c.email}`} <Quote text={c.evidence} /></div>)}</Row>}
      {a?.label === "unsubscribe_request" && (
        <p style={{ color: "var(--danger)", margin: "8px 0 0" }}><small>Suggestion: they asked not to be contacted. Consider adding a block on the
          Do-not-contact page. Nothing was blocked automatically.</small></p>
      )}
      {a?.dropped?.length > 0 && <p style={{ margin: "8px 0 0" }}><small style={{ color: "var(--muted)" }}>{a.dropped.length} item(s) from the model were
        dropped because they could not be found in the email.</small></p>}
    </section>
  );
}
