"use client";
import { useEffect, useRef, useState } from "react";

const full = { display: "block", width: "100%", boxSizing: "border-box" };

// Subject + body fields with click-to-insert variables (inserted at the cursor of the last focused field).
export function TemplateFields({ value, onChange }) {
  const [vars, setVars] = useState(null);
  const refs = { subject: useRef(null), body: useRef(null) };
  const lastField = useRef("body");

  useEffect(() => { fetch("/api/templates/variables").then((r) => r.ok && r.json()).then(setVars); }, []);

  function insert(name) {
    const field = lastField.current;
    const el = refs[field].current;
    const token = `{{${name}}}`;
    const start = el?.selectionStart ?? value[field].length;
    const end = el?.selectionEnd ?? start;
    onChange({ ...value, [field]: value[field].slice(0, start) + token + value[field].slice(end) });
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(start + token.length, start + token.length); });
  }

  return (
    <>
      <label className="field"><span>Subject</span>
        <input ref={refs.subject} required value={value.subject} style={full}
               onFocus={() => { lastField.current = "subject"; }}
               onChange={(e) => onChange({ ...value, subject: e.target.value })} />
      </label>
      <label className="field"><span>Body (plain text)</span>
        <textarea ref={refs.body} required rows={12} value={value.body} style={{ ...full, fontFamily: "inherit" }}
                  onFocus={() => { lastField.current = "body"; }}
                  onChange={(e) => onChange({ ...value, body: e.target.value })} />
      </label>
      {vars && (
        <details open className="card" style={{ padding: 12 }}>
          <summary>Insert a variable (use <code>{"{{name | fallback}}"}</code> for a fallback when empty)</summary>
          {Object.entries(vars).map(([group, names]) => (
            <p key={group} style={{ display: "flex", flexWrap: "wrap", gap: 4, margin: "8px 0 0", alignItems: "center" }}>
              <strong style={{ width: 70, fontSize: 12, color: "var(--muted)" }}>{group}</strong>
              {names.map((n) => <button type="button" className="btn-sm" key={n} onClick={() => insert(n)}>{n}</button>)}
            </p>
          ))}
        </details>
      )}
    </>
  );
}

// F4: live preview of unsaved text against a chosen lead (POST /templates/preview; saves nothing).
export function LivePreview({ subject, body }) {
  const [leads, setLeads] = useState([]);
  const [lead, setLead] = useState("");
  const [p, setP] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/leads?has_email=true").then((r) => r.ok && r.json()).then((d) => {
      if (!d) return;
      setLeads(d.leads);
      if (d.leads.length) setLead((cur) => cur || String(d.leads[0].id));
    });
  }, []);

  useEffect(() => {
    if (!lead || (!subject && !body)) { setP(null); return; }
    setBusy(true);
    const t = setTimeout(async () => {
      const r = await fetch("/api/templates/preview", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject, body, company_id: Number(lead) }) });
      setBusy(false);
      setP(r.ok ? await r.json() : { ok: false, problems: ["The preview couldn't be made."] });
    }, 400);
    return () => clearTimeout(t);
  }, [subject, body, lead]);

  return (
    <section className="card preview" aria-label="Live preview" data-busy={busy || undefined}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <b>Live preview</b>
        <select aria-label="Preview lead" value={lead} onChange={(e) => setLead(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
          {leads.length === 0 && <option value="">No leads with an email yet</option>}
          {leads.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
      </div>
      {!p ? <p style={{ color: "var(--muted)", margin: 0 }}>{leads.length ? "Start typing to see the email for this lead." : "Import or add a lead to preview."}</p> : (
        <>
          <div className="mail-head">
            <div><small>To</small> {p.recipient ? <>{p.recipient.email} <span className="badge">{p.recipient.email_class}</span></>
              : <span style={{ color: "var(--danger)" }}>no eligible recipient at this company</span>}</div>
            {p.ok && <div><small>Subject</small> <b data-preview-subject>{p.subject}</b></div>}
          </div>
          {p.ok ? <pre className="mail-body" data-preview-body>{p.body}</pre> : (
            <div className="error-box" role="alert" data-preview-error>
              {p.unresolved?.length > 0 && <div>Not filled for this lead: {p.unresolved.map((u) => <code key={u}>{`{{${u}}}`}</code>).reduce((a, b) => [a, " ", b])}.
                Fill it in (profile, company, contact) or add a fallback like <code>{"{{name | text}}"}</code>.</div>}
              {p.problems?.map((x) => <div key={x}>{x}</div>)}
            </div>
          )}
          {p.fallbacks?.length > 0 && <p style={{ margin: "8px 0 0" }}><small style={{ color: "var(--warning)" }}>Fallback text used for: {p.fallbacks.join(", ")}</small></p>}
        </>
      )}
    </section>
  );
}
