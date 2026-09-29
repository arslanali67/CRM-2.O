"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";

export default function ComposeList() {
  const router = useRouter();
  const [items, setItems] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [cvs, setCvs] = useState([]);
  const [form, setForm] = useState({ template_id: "", attach_cv: false, cv_version_id: "" });
  const [result, setResult] = useState(null);
  const [msg, setMsg] = useState("");

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

  async function remove(id) {
    await fetch(`/api/compose-list/${id}`, { method: "DELETE" });
    load();
  }

  async function createDrafts(e) {
    e.preventDefault();
    const body = { template_id: Number(form.template_id), attach_cv: form.attach_cv, personalize: !!form.personalize,
                   ...(form.attach_cv && form.cv_version_id ? { cv_version_id: Number(form.cv_version_id) } : {}) };
    const res = await fetch("/api/compose-list/drafts", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) return setMsg(errorText(data));
    setMsg("");
    setResult(data);
    load();
  }

  if (!items) return <p>Loading…</p>;
  const ready = items.filter((i) => !i.problem).length;

  return (
    <main style={{ maxWidth: 900 }}>
      <p><Link href="/">← Home</Link> · <Link href="/companies">Leads</Link> · <Link href="/outbox">Outbox</Link></p>
      <h1>Compose list</h1>
      <p style={{ color: "var(--muted)" }}>
        Leads handed off for outreach, each with the best recipient (careers → personal → generic; blocked and
        unsuitable addresses are never picked).
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr><th align="left">Company</th><th align="left">Stage</th><th align="left">Recipient</th><th /></tr></thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.company_id} style={{ borderTop: "1px solid var(--border)" }}>
              <td><Link href={`/companies/${i.company_id}`}>{i.name}</Link></td>
              <td>{i.stage}</td>
              <td>
                {i.recipient
                  ? <>{i.recipient.email} <mark>{i.recipient.email_class}</mark>{i.recipient.name && ` · ${i.recipient.name}`}</>
                  : <span style={{ color: "var(--danger)" }}>{i.problem}</span>}
              </td>
              <td><button onClick={() => remove(i.company_id)}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p>Empty. Select leads on the <Link href="/companies">Leads</Link> page and add them here.</p>}

      <h2 style={{ marginTop: 32 }}>Create drafts</h2>
      <p style={{ color: "var(--muted)" }}>Drafts are only drafts: each one must be reviewed and approved on its own in the Outbox.</p>
      <form onSubmit={createDrafts} style={{ display: "grid", gap: 8, maxWidth: 480 }}>
        <select required aria-label="Template" value={form.template_id} onChange={(e) => setForm({ ...form, template_id: e.target.value })}>
          <option value="">Choose a template…</option>
          {templates.map((t) => <option key={t.id} value={t.id}>{t.name} (v{t.version})</option>)}
        </select>
        <label>
          <input type="checkbox" checked={form.attach_cv} onChange={(e) => setForm({ ...form, attach_cv: e.target.checked })} /> Attach CV
        </label>
        {form.attach_cv && (
          cvs.length ? (
            <select aria-label="CV version" value={form.cv_version_id} onChange={(e) => setForm({ ...form, cv_version_id: e.target.value })}>
              {cvs.map((c) => <option key={c.id} value={c.id}>{c.label}{c.is_default ? " (default)" : ""}</option>)}
            </select>
          ) : <p style={{ color: "var(--danger)" }}>No CV uploaded yet. <Link href="/profile">Upload one</Link>.</p>
        )}
        <label>
          <input type="checkbox" checked={!!form.personalize} onChange={(e) => setForm({ ...form, personalize: e.target.checked })} />
          {" "}Personalize from verified facts (AI)
          <br /><small style={{ color: "var(--muted)" }}>Fills the template&apos;s <code>{"{{personal_line}}"}</code> with 1–2 sentences built only
            from each company&apos;s verified facts (Research tab); every sentence cites its facts and anything unproven is dropped.
            One AI request per company, at most 10 per run; others get the fallback text. This can take a minute.</small>
        </label>
        <button type="submit" disabled={!ready}>Create {ready} draft(s)</button>
        {msg && <p role="alert" style={{ color: "var(--danger)" }}>{msg}</p>}
      </form>
      {result && (
        <div style={{ marginTop: 12 }}>
          <p>{result.created.length} draft(s) created. <Link href="/outbox">Review them in the Outbox →</Link></p>
          {result.personalization && <p>Personalized: {result.personalization.personalized} · fallback text: {result.personalization.fallback}
            {result.personalization.errors.length > 0 && <small style={{ color: "var(--danger)" }}> · {result.personalization.errors.join("; ")}</small>}</p>}
          {result.skipped.length > 0 && (
            <ul>{result.skipped.map((s) => <li key={s.company_id}>{s.name}: {s.reason}</li>)}</ul>
          )}
        </div>
      )}
    </main>
  );
}
