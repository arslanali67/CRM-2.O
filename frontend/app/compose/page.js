"use client";
// F4: Compose as a stepper: 1 Leads -> 2 Template & options -> 3 Create. Drafts are only drafts: each email is
// reviewed and approved on its own in the Outbox.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { Badge, EmptyState, Loading, PageHeader, Spinner } from "../ui";

const STEPS = ["Leads", "Template & options", "Create"];

function Steps({ at, go }) {
  return (
    <ol className="steps" aria-label="Compose steps" style={{ listStyle: "none", padding: 0 }}>
      {STEPS.map((s, i) => (
        <li key={s} className={`step${i < at ? " done" : ""}`} aria-current={i === at ? "step" : undefined}>
          <button type="button" className="btn-ghost" style={{ padding: 0, minHeight: 0, gap: 8, color: "inherit" }}
                  onClick={() => i < at && go(i)} disabled={i > at}>
            <span className="n">{i < at ? "✓" : i + 1}</span>{s}
          </button>
        </li>
      ))}
    </ol>
  );
}

export default function Compose() {
  const router = useRouter();
  const [items, setItems] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [cvs, setCvs] = useState([]);
  const [form, setForm] = useState({ template_id: "", attach_cv: false, cv_version_id: "", personalize: false });
  const [step, setStep] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const res = await fetch("/api/compose-list");
    if (res.status === 401) return router.replace("/login");
    setItems(await res.json());
  }
  useEffect(() => {
    load();
    fetch("/api/templates").then((r) => r.json()).then(setTemplates);
    fetch("/api/cv").then((r) => r.json()).then((list) => {
      setCvs(list);
      const def = list.find((c) => c.is_default);
      if (def) setForm((f) => ({ ...f, cv_version_id: String(def.id) }));
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const [coverage, setCoverage] = useState(null);   // F7: which leads have verified facts
  useEffect(() => {
    if (!form.personalize || !items) return setCoverage(null);
    Promise.all(items.map((i) => fetch(`/api/companies/${i.company_id}/facts`).then((r) => (r.ok ? r.json() : [])).catch(() => [])))
      .then((all) => setCoverage({ with: all.filter((f) => f.length).length, missing: items.filter((_, n) => !all[n].length) }));
  }, [form.personalize, items]);

  async function remove(id) {
    await fetch(`/api/compose-list/${id}`, { method: "DELETE" });
    load();
  }

  async function createDrafts() {
    setBusy(true);
    setError("");
    const body = { template_id: Number(form.template_id), attach_cv: form.attach_cv, personalize: !!form.personalize,
                   ...(form.attach_cv && form.cv_version_id ? { cv_version_id: Number(form.cv_version_id) } : {}) };
    const res = await fetch("/api/compose-list/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json();
    setBusy(false);
    if (!res.ok) return setError(errorText(data));
    setResult(data);
    load();
  }
  function again() { setResult(null); setStep(0); }

  if (!items) return <Loading what="compose list" />;
  const ready = items.filter((i) => !i.problem).length;
  const template = templates.find((t) => String(t.id) === form.template_id);

  return (
    <main>
      <PageHeader title="Compose" sub="Turn leads into drafts. Nothing is sent from here: every email is reviewed and approved on its own in the Outbox." />
      <Steps at={result ? 3 : step} go={setStep} />

      {result ? (
        <section className="card" style={{ borderColor: "var(--success)" }}>
          <h2 style={{ marginTop: 0 }}>{result.created.length} draft(s) created.</h2>
          {result.personalization && <p>Personalized: {result.personalization.personalized} · fallback text: {result.personalization.fallback}
            {result.personalization.errors.length > 0 && <small style={{ color: "var(--danger)" }}> · {result.personalization.errors.join("; ")}</small>}</p>}
          {result.skipped.length > 0 && (<>
            <p style={{ marginBottom: 4 }}><b>Skipped ({result.skipped.length}):</b></p>
            <ul style={{ marginTop: 0 }}>{result.skipped.map((s) => <li key={s.company_id}>{s.name}: {s.reason}</li>)}</ul>
          </>)}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link className="btn btn-primary" href="/outbox">Review them in the Outbox →</Link>
            <button onClick={again}>Compose more</button>
          </div>
        </section>
      ) : step === 0 ? (
        <section className="card">
          <h2 style={{ marginTop: 0 }}>1. Leads in the compose list</h2>
          <p style={{ color: "var(--muted)" }}>Each lead gets its best recipient (careers → personal → generic). Blocked and unsuitable addresses are never picked.</p>
          {items.length === 0 ? (
            <EmptyState title="The compose list is empty" action={<Link className="btn btn-primary" href="/companies">Choose leads</Link>}>
              Select leads on the Leads page and click “Add to compose list”.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Company</th><th>Stage</th><th>Recipient</th><th /></tr></thead>
                <tbody>
                  {items.map((i) => (
                    <tr key={i.company_id}>
                      <td><Link href={`/companies/${i.company_id}`}>{i.name}</Link></td>
                      <td><Badge>{i.stage}</Badge></td>
                      <td>{i.recipient
                        ? <>{i.recipient.email} <Badge tone="accent">{i.recipient.email_class}</Badge>{i.recipient.name && <small style={{ color: "var(--muted)" }}> · {i.recipient.name}</small>}</>
                        : <span style={{ color: "var(--danger)" }}>{i.problem}</span>}</td>
                      <td style={{ textAlign: "right" }}><button className="btn-sm btn-ghost" onClick={() => remove(i.company_id)}>Remove</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="dialog-actions">
            <span style={{ marginRight: "auto", color: "var(--muted)" }}>{ready} of {items.length} ready</span>
            <button className="btn-primary" disabled={!ready} onClick={() => setStep(1)}>Next: template</button>
          </div>
        </section>
      ) : step === 1 ? (
        <section className="card" style={{ maxWidth: 680 }}>
          <h2 style={{ marginTop: 0 }}>2. Template and options</h2>
          <label className="field"><span>Template</span>
            <select required aria-label="Template" value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
              <option value="">Choose a template…</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name} (v{t.version})</option>)}
            </select>
            {template && <small className="hint">Subject: {template.subject} · <Link href={`/templates/${template.id}`}>preview it against a lead</Link></small>}
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <input type="checkbox" checked={form.attach_cv} onChange={(e) => setForm({ ...form, attach_cv: e.target.checked })} /> Attach CV
          </label>
          {form.attach_cv && (cvs.length ? (
            <select aria-label="CV version" value={form.cv_version_id} onChange={(e) => setForm({ ...form, cv_version_id: e.target.value })} style={{ marginBottom: 12 }}>
              {cvs.map((c) => <option key={c.id} value={c.id}>{c.label}{c.is_default ? " (default)" : ""}</option>)}
            </select>
          ) : <p style={{ color: "var(--danger)" }}>No CV uploaded yet. <Link href="/profile">Upload one</Link>.</p>)}
          <label style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
            <input type="checkbox" checked={!!form.personalize} onChange={(e) => setForm({ ...form, personalize: e.target.checked })} style={{ marginTop: 3 }} />
            <span>Personalize from verified facts (AI)<br /><small style={{ color: "var(--muted)" }}>Fills the template&apos;s <code>{"{{personal_line}}"}</code> with 1–2 sentences
              built only from each company&apos;s verified facts (Research tab); every sentence cites its facts and anything unproven is dropped.
              One AI request per company, at most 10 per run; the others get the fallback text.</small></span>
          </label>
          {coverage && (
            <p data-coverage style={{ margin: "8px 0 0" }}>
              <b>{coverage.with} of {items.length}</b> leads have verified facts; the others get your fallback sentence.
              {coverage.missing.length > 0 && <small style={{ display: "block", color: "var(--muted)" }}>Research: {coverage.missing.slice(0, 8).map((m, n) => (
                <span key={m.company_id}>{n ? ", " : ""}<Link href={`/companies/${m.company_id}`}>{m.name}</Link></span>))}{coverage.missing.length > 8 && ` and ${coverage.missing.length - 8} more`}</small>}
            </p>)}
          <div className="dialog-actions">
            <button onClick={() => setStep(0)}>Back</button>
            <button className="btn-primary" disabled={!form.template_id || (form.attach_cv && !cvs.length)} onClick={() => setStep(2)}>Next: review</button>
          </div>
        </section>
      ) : (
        <section className="card" style={{ maxWidth: 680 }}>
          <h2 style={{ marginTop: 0 }}>3. Create drafts</h2>
          <dl className="dl" style={{ marginBottom: 12 }}>
            <dt>Leads</dt><dd>{ready} ready{items.length > ready && `, ${items.length - ready} will be skipped`}</dd>
            <dt>Template</dt><dd>{template ? `${template.name} (v${template.version})` : "—"}</dd>
            <dt>CV</dt><dd>{form.attach_cv ? cvs.find((c) => String(c.id) === form.cv_version_id)?.label || "default" : "not attached"}</dd>
            <dt>Personalize</dt><dd>{form.personalize ? "yes, from verified facts" : "no"}</dd>
          </dl>
          <p style={{ color: "var(--muted)" }}>Creating drafts sends nothing and approves nothing.</p>
          {error && <p role="alert" className="error-box">{error}</p>}
          <div className="dialog-actions">
            <button onClick={() => setStep(1)} disabled={busy}>Back</button>
            <button type="button" className="btn-primary" disabled={busy || !ready} onClick={createDrafts}>{busy && <Spinner />}Create {ready} draft(s)</button>
          </div>
        </section>
      )}
    </main>
  );
}
