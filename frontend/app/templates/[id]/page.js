"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../../companies/shared";
import { TemplateFields } from "../editor";

async function call(url, method = "GET", body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export default function Template() {
  const { id } = useParams();
  const router = useRouter();
  const [t, setT] = useState(null);
  const [draft, setDraft] = useState(null);
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [leads, setLeads] = useState([]);
  const [previewFor, setPreviewFor] = useState({ company_id: "", version: "" });
  const [preview, setPreview] = useState(null);

  async function load() {
    const r = await call(`/api/templates/${id}`);
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setMsg(errorText(r.data));
    setT(r.data);
    setName(r.data.name);
    setDraft({ subject: r.data.versions[0].subject, body: r.data.versions[0].body });
  }
  useEffect(() => {
    load();
    call("/api/leads").then((r) => r.ok && setLeads(r.data.leads));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveVersion(e) {
    e.preventDefault();
    const r = await call(`/api/templates/${id}/versions`, "POST", draft);
    setMsg(!r.ok ? errorText(r.data) : r.data.created ? `Saved as version ${r.data.version}.` : "No changes to save.");
    if (r.ok) load();
  }

  async function rename() {
    const r = await call(`/api/templates/${id}`, "PUT", { name });
    setMsg(r.ok ? "Renamed." : errorText(r.data));
    if (r.ok) load();
  }

  async function toggleArchive() {
    const r = await call(`/api/templates/${id}/${t.archived_at ? "restore" : "archive"}`, "POST");
    setMsg(r.ok ? (t.archived_at ? "Restored." : "Archived.") : errorText(r.data));
    if (r.ok) load();
  }

  async function runPreview(e) {
    e.preventDefault();
    const body = { company_id: Number(previewFor.company_id), ...(previewFor.version ? { version: Number(previewFor.version) } : {}) };
    const r = await call(`/api/templates/${id}/preview`, "POST", body);
    setPreview(r.ok ? r.data : { ok: false, error: errorText(r.data) });
  }

  if (!t || !draft) return <p>{msg || "Loading…"}</p>;

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/templates">← Templates</Link></p>
      <h1>{t.name} <small>v{t.versions[0].version}{t.archived_at && " (archived)"}</small></h1>
      <p style={{ display: "flex", gap: 6 }}>
        <input aria-label="Template name" value={name} onChange={(e) => setName(e.target.value)} />
        <button onClick={rename} disabled={name === t.name}>Rename</button>
        <button onClick={toggleArchive}>{t.archived_at ? "Restore" : "Archive"}</button>
      </p>
      {msg && <p role="status">{msg}</p>}

      <form onSubmit={saveVersion} style={{ display: "grid", gap: 8 }}>
        <TemplateFields value={draft} onChange={setDraft} />
        <button type="submit">Save as new version</button>
      </form>

      <h2 style={{ marginTop: 32 }}>Preview against a lead</h2>
      <form onSubmit={runPreview} style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <select required aria-label="Lead" value={previewFor.company_id} onChange={(e) => setPreviewFor({ ...previewFor, company_id: e.target.value })}>
          <option value="">Choose a lead…</option>
          {leads.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <select aria-label="Version" value={previewFor.version} onChange={(e) => setPreviewFor({ ...previewFor, version: e.target.value })}>
          <option value="">current version</option>
          {t.versions.map((v) => <option key={v.version} value={v.version}>v{v.version}</option>)}
        </select>
        <button type="submit">Preview</button>
      </form>
      {preview && (
        <div style={{ border: "1px solid #ddd", padding: 12, marginTop: 8 }}>
          {preview.recipient
            ? <p>To: {preview.recipient.email} <mark>{preview.recipient.email_class}</mark></p>
            : preview.error ? null : <p style={{ color: "crimson" }}>No eligible recipient at this company.</p>}
          {preview.ok ? (
            <>
              <p><strong>{preview.subject}</strong></p>
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{preview.body}</pre>
            </>
          ) : (
            <p style={{ color: "crimson" }}>
              {preview.error || <>Cannot render (v{preview.version}). Unresolved: {preview.unresolved.map((u) => <code key={u}> {`{{${u}}}`}</code>)}. Fill them in (profile, company, contact) or add a fallback.</>}
            </p>
          )}
        </div>
      )}

      <h2 style={{ marginTop: 32 }}>Version history</h2>
      {t.versions.map((v) => (
        <details key={v.version}>
          <summary>v{v.version} · {new Date(v.created_at).toLocaleString()} · <code>{v.subject}</code></summary>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", background: "#f7f7f7", padding: 8 }}>{v.body}</pre>
        </details>
      ))}
    </main>
  );
}
