"use client";
// F4: template page. Editor beside a live preview against a real lead; version history with "Use this version".
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { errorText } from "../../companies/shared";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { Badge, ErrorState, Loading, useToast } from "../../ui";
import { LivePreview, TemplateFields } from "../editor";

async function call(url, method = "GET", body) {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined,
                                 body: body ? JSON.stringify(body) : undefined });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export default function Template() {
  const { id } = useParams();
  const router = useRouter();
  const toast = useToast();
  const [t, setT] = useState(null);
  const [draft, setDraft] = useState(null);
  const [name, setName] = useState("");
  const [open, setOpen] = useState(null);
  const [error, setError] = useState("");

  async function load() {
    const r = await call(`/api/templates/${id}`);
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setError(errorText(r.data));
    setT(r.data);
    setName(r.data.name);
    setDraft({ subject: r.data.versions[0].subject, body: r.data.versions[0].body });
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function saveVersion(e) {
    e.preventDefault();
    const r = await call(`/api/templates/${id}/versions`, "POST", draft);
    toast(!r.ok ? errorText(r.data) : r.data.created ? `Saved as version ${r.data.version}.` : "No changes to save.", r.ok ? "" : "error");
    if (r.ok) load();
  }
  async function rename() {
    const r = await call(`/api/templates/${id}`, "PUT", { name });
    toast(r.ok ? "Renamed." : errorText(r.data), r.ok ? "" : "error");
    if (r.ok) load();
  }
  async function toggleArchive() {
    const r = await call(`/api/templates/${id}/${t.archived_at ? "restore" : "archive"}`, "POST");
    toast(r.ok ? (t.archived_at ? "Restored." : "Archived.") : errorText(r.data), r.ok ? "" : "error");
    if (r.ok) load();
  }
  function loadVersion(v) {
    setDraft({ subject: v.subject, body: v.body });
    toast(`Loaded v${v.version} into the editor. Save to make it the current version.`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  if (!t || !draft) return error ? <ErrorState>{error}</ErrorState> : <Loading what="template" />;
  const current = t.versions[0];
  const changed = draft.subject !== current.subject || draft.body !== current.body;

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href="/templates">← Templates</Link></p>
      <section className="card company-head">
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0 }}>{t.name}</h1>
          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            <Badge tone="accent">v{current.version}</Badge>{t.archived_at && <Badge tone="warning">archived</Badge>}
            {changed && <Badge tone="warning">unsaved changes</Badge>}
          </div>
        </div>
        <div className="head-actions">
          <input aria-label="Template name" value={name} onChange={(e) => setName(e.target.value)} />
          <button onClick={rename} disabled={name === t.name}>Rename</button>
          <button onClick={toggleArchive}>{t.archived_at ? "Restore" : "Archive"}</button>
        </div>
      </section>

      <div className="editor-grid" style={{ marginTop: 16 }}>
        <form className="card" onSubmit={saveVersion}>
          <TemplateFields value={draft} onChange={setDraft} />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button type="submit" className="btn-primary" disabled={!changed}>Save as new version</button>
            {changed && <button type="button" className="btn-ghost" onClick={() => setDraft({ subject: current.subject, body: current.body })}>Discard changes</button>}
          </div>
        </form>
        <LivePreview subject={draft.subject} body={draft.body} />
      </div>

      <h2>Version history</h2>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Version</th><th>Saved</th><th>Subject</th><th /></tr></thead>
          <tbody>
            {t.versions.map((v) => (
              <Fragment key={v.version}>
                <tr>
                  <td><span className="badge">v{v.version}</span>{v === current && <small style={{ color: "var(--muted)" }}> current</small>}</td>
                  <td><small>{new Date(v.created_at).toLocaleString()}</small></td>
                  <td className="clip" style={{ maxWidth: 360 }}>{v.subject}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button className="btn-sm btn-ghost" onClick={() => setOpen(open === v.version ? null : v.version)}>{open === v.version ? "Hide" : "View"}</button>{" "}
                    {v !== current && <button className="btn-sm" onClick={() => loadVersion(v)}>Use this version</button>}
                  </td>
                </tr>
                {open === v.version && (
                  <tr><td colSpan={4}><pre className="mail-body" style={{ background: "var(--surface-2)", padding: 10, borderRadius: 8 }}>{v.body}</pre></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel-grid" style={{ marginTop: 16 }}>
        <section className="card"><TasksPanel entityType="template" entityId={t.id} /></section>
        <section className="card"><NotesPanel entityType="template" entityId={t.id} /></section>
      </div>
    </main>
  );
}
