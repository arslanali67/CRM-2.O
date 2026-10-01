"use client";
// F4: one email. Left: the exact message as the recipient will see it (AI sentences highlighted). Right: status, the
// 12 safety checks as a checklist, and the actions. Approval is unchanged: one email, bound to the exact content shown.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { describe } from "../../activity/describe";
import { errorText } from "../../companies/shared";
import { Badge, ErrorState, Loading, Modal, useDialog, useToast } from "../../ui";

async function call(url, method = "GET", body) {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined,
                                 body: body ? JSON.stringify(body) : undefined });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

const TONE = { draft: "", approved: "accent", queued: "accent", sending: "warning", sent: "success", failed: "danger", cancelled: "danger" };

// The body with AI-written sentences highlighted (only those still present in the text).
function Body({ text, sentences = [] }) {
  const marks = sentences.map((s) => s.text).filter((t) => text.includes(t));
  if (!marks.length) return <pre className="mail-body">{text}</pre>;
  const parts = [];
  let rest = text;
  while (rest) {
    const hits = marks.map((m) => [rest.indexOf(m), m]).filter(([i]) => i >= 0).sort((a, b) => a[0] - b[0]);
    if (!hits.length) { parts.push(rest); break; }
    const [i, m] = hits[0];
    parts.push(rest.slice(0, i), <mark key={parts.length} data-ai>{m}</mark>);
    rest = rest.slice(i + m.length);
  }
  return <pre className="mail-body">{parts}</pre>;
}

export default function Email() {
  const dialog = useDialog();
  const toast = useToast();
  const { id } = useParams();
  const router = useRouter();
  const [e, setE] = useState(null);
  const [draft, setDraft] = useState(null);
  const [editing, setEditing] = useState(false);
  const [cvs, setCvs] = useState([]);
  const [failed, setFailed] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [error, setError] = useState("");

  async function load() {
    const r = await call(`/api/outbound-emails/${id}`);
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setError(errorText(r.data));
    setE(r.data);
    call(`/api/outbound-emails/${id}/timeline`).then((t) => t.ok && setTimeline(t.data));
    setDraft({ subject: r.data.subject, body: r.data.body, cv_version_id: r.data.cv_version_id ? String(r.data.cv_version_id) : "" });
  }
  useEffect(() => { load(); call("/api/cv").then((r) => r.ok && setCvs(r.data)); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(ev) {
    ev.preventDefault();
    const r = await call(`/api/outbound-emails/${id}`, "PUT", { subject: draft.subject, body: draft.body, cv_version_id: draft.cv_version_id ? Number(draft.cv_version_id) : null });
    toast(r.ok ? "Saved. Review the preview again before approving." : errorText(r.data), r.ok ? "" : "error");
    if (r.ok) { setEditing(false); load(); }
  }

  async function approve() {
    // Sends the hash of exactly what is on screen; the server refuses if it changed since.
    const r = await call(`/api/outbound-emails/${id}/approve`, "POST", { content_hash: e.content_hash_hex });
    if (r.ok) { setFailed(null); toast("Approved and queued."); return load(); }
    if (r.status === 422 && r.data.checks) { setFailed(r.data.checks.filter((c) => !c.ok)); toast("Not approved.", "error"); }
    else toast(errorText(r.data), "error");
    load();
  }

  async function action(name, title, opts = {}) {
    if (title && !await dialog.confirm(title, { confirmLabel: "Yes", ...opts })) return;
    const r = await call(`/api/outbound-emails/${id}/${name}`, "POST");
    toast(r.ok ? `Now ${r.data.status}.` : errorText(r.data), r.ok ? "" : "error");
    load();
  }

  if (!e || !draft) return error ? <ErrorState>{error}</ErrorState> : <Loading what="email" />;
  const isDraft = e.status === "draft";
  const edited = isDraft && (draft.subject !== e.subject || draft.body !== e.body ||
    (draft.cv_version_id || null) !== (e.cv_version_id ? String(e.cv_version_id) : null));
  const checks = e.checks?.results || [];
  const blocking = checks.filter((c) => !c.ok);

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href="/outbox">← Outbox</Link>{e.company_id && <> · <Link href={`/companies/${e.company_id}`}>{e.company_name}</Link></>}</p>
      <div className="page-header">
        <div><h1>Email #{e.id}</h1>
          <div className="sub" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <Badge tone={TONE[e.status]}>{e.status}</Badge>
            {e.cv_version_id && <Badge>CV</Badge>}{e.personalization?.sentences?.length > 0 && <Badge tone="warning">AI-personalized</Badge>}
            {e.sent_at && <span style={{ color: "var(--success)" }}>sent {new Date(e.sent_at).toLocaleString()}</span>}
          </div>
        </div>
      </div>
      {e.cancel_reason && <p className="error-box">Cancelled: {e.cancel_reason}</p>}
      {e.failure_reason && <p className="error-box">Failed: {e.failure_reason}</p>}

      <div className="email-grid">
        <div style={{ minWidth: 0 }}>
          <h2 style={{ marginTop: 0 }}>Exact preview</h2>
          <section className="card">
            <div className="mail-head">
              <div><small>From</small> {e.from.name || <i>(no name in profile)</i>} &lt;{e.from.email || "no address"}&gt;
                {!e.from.account_connected && <small style={{ color: "var(--danger)" }}> (no Gmail connected: <Link href="/email-account">connect one</Link>)</small>}</div>
              <div><small>To</small> {e.contact_name ? `${e.contact_name} ` : ""}&lt;{e.to_email}&gt; <Badge tone="accent">{e.email_class}</Badge></div>
              <div><small>Subject</small> <b>{e.subject}</b></div>
              <div><small>Attachment</small> {e.cv_version_id ? `${e.cv_filename} (${e.cv_label})` : "none"}</div>
            </div>
            <Body text={e.body} sentences={e.personalization?.sentences} />
          </section>
          <p style={{ color: "var(--muted)" }}><small>
            {e.template_name && `From template ${e.template_name} v${e.template_version} · `}fingerprint {e.content_hash_hex.slice(0, 12)}…
          </small></p>

          {e.personalization?.sentences?.length > 0 && (
            <section className="card" style={{ borderColor: "var(--warning)" }}>
              <b>AI-written sentences in this email</b> <small style={{ color: "var(--muted)" }}>(highlighted above; check them before approving)</small>
              {e.personalization.sentences.map((s, i) => (
                <div key={i} style={{ marginTop: 8 }}>
                  <mark>{s.text}</mark>{!e.body.includes(s.text) && <small style={{ color: "var(--muted)" }}> (edited or removed since)</small>}
                  <ul style={{ margin: "4px 0 0" }}>{s.facts.map((f) => (
                    <li key={f.id}><small>cites verified fact: “{f.fact}” · source: {/^https?:\/\//.test(f.source)
                      ? <a href={f.source} target="_blank" rel="noopener noreferrer">{f.source}</a> : f.source}</small></li>
                  ))}</ul>
                </div>
              ))}
              {e.personalization.dropped?.length > 0 && <p style={{ margin: "8px 0 0" }}><small style={{ color: "var(--muted)" }}>
                {e.personalization.dropped.length} AI sentence(s) were dropped as unproven and are not in the email.</small></p>}
            </section>
          )}
        </div>

        <aside style={{ display: "grid", gap: 12, alignContent: "start", minWidth: 0 }}>
          <section className="card" aria-label="Actions">
            {isDraft && (<>
              <button className="btn-primary" style={{ width: "100%" }} onClick={approve} disabled={edited}>Approve & queue this email</button>
              {edited && <p style={{ margin: "6px 0 0" }}><small>Save your edits first, then review the preview again.</small></p>}
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button style={{ flex: 1 }} onClick={() => setEditing(true)}>Edit draft</button>
                <button style={{ flex: 1 }} onClick={() => action("discard", "Discard this draft?", { danger: true, confirmLabel: "Discard" })}>Discard</button>
              </div>
            </>)}
            {["approved", "queued"].includes(e.status) && (<>
              <button style={{ width: "100%" }} onClick={() => action("unqueue")}>Pull back to draft</button>
              <p style={{ margin: "6px 0 0" }}><small>Clears the approval. The email waits in the queue until sending is on.</small></p>
            </>)}
            {!isDraft && !["approved", "queued"].includes(e.status) && <p style={{ margin: 0, color: "var(--muted)" }}>This email is {e.status}; no actions are available.</p>}
            {failed && <ul style={{ color: "var(--danger)", margin: "10px 0 0", paddingLeft: 18 }}>{failed.map((c) => <li key={c.id}>{c.id}. {c.name}: {c.detail}</li>)}</ul>}
          </section>

          {checks.length > 0 && (
            <section className="card" aria-label="Safety checks" data-checks={checks.length}>
              <b>Safety checks <small style={{ fontWeight: 400, color: "var(--muted)" }}>({e.checks.stage})</small></b>
              <p style={{ margin: "2px 0 8px", color: blocking.length ? "var(--danger)" : "var(--success)" }}>
                {blocking.length ? `${blocking.length} failing` : "all passing"}</p>
              <ul className="check-list">
                {checks.map((c) => (
                  <li key={c.id} data-check={c.id} data-ok={c.ok}>
                    <span style={{ color: c.ok ? (c.applies ? "var(--success)" : "var(--muted)") : "var(--danger)", fontWeight: 700 }} aria-hidden="true">{c.ok ? (c.applies ? "✓" : "–") : "✕"}</span>
                    <span><span className="sr-only">{c.ok ? "passed: " : "failed: "}</span>{c.name}
                      {!c.ok && <small style={{ display: "block", color: "var(--danger)" }}>{c.detail}</small>}
                      {!c.applies && <small style={{ display: "block", color: "var(--muted)" }}>checked at send</small>}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card">
            <b>Status timeline</b>
            <ol style={{ margin: "8px 0 0", paddingLeft: 18 }}>
              {timeline.map((t) => (
                <li key={t.id}><small style={{ color: "var(--muted)" }}>{new Date(t.at).toLocaleString()} · {t.actor}</small><div>{describe(t)}</div></li>
              ))}
            </ol>
            <p style={{ margin: "10px 0 0", color: "var(--muted)", overflowWrap: "anywhere" }}><small>
              Message-ID <code>{e.provider_message_id || "not assigned yet"}</code> · Gmail message <code>{e.gmail_msgid || "unknown yet"}</code> ·{" "}
              <Link href={`/threads/${e.thread_key}`}>Gmail thread {e.gmail_thrid || "(not linked yet)"}</Link></small></p>
          </section>
        </aside>
      </div>

      {editing && (
        <Modal title="Edit draft" wide onClose={() => { setEditing(false); setDraft({ subject: e.subject, body: e.body, cv_version_id: e.cv_version_id ? String(e.cv_version_id) : "" }); }}>
          <form onSubmit={save}>
            <label className="field"><span>Subject</span><input value={draft.subject} onChange={(ev) => setDraft({ ...draft, subject: ev.target.value })} /></label>
            <label className="field"><span>Body</span><textarea rows={12} value={draft.body} onChange={(ev) => setDraft({ ...draft, body: ev.target.value })} /></label>
            <label className="field"><span>Attachment</span>
              <select value={draft.cv_version_id} onChange={(ev) => setDraft({ ...draft, cv_version_id: ev.target.value })}>
                <option value="">No attachment</option>
                {cvs.map((c) => <option key={c.id} value={c.id}>CV: {c.label}{c.is_default ? " (default)" : ""}</option>)}
              </select></label>
            <p style={{ color: "var(--muted)" }}><small>Editing clears nothing by itself: the email stays a draft and needs a fresh approval.</small></p>
            <div className="dialog-actions"><button type="button" onClick={() => { setEditing(false); setDraft({ subject: e.subject, body: e.body, cv_version_id: e.cv_version_id ? String(e.cv_version_id) : "" }); }}>Cancel</button>
              <button type="submit" className="btn-primary" disabled={!edited}>Save draft</button></div>
          </form>
        </Modal>
      )}
    </main>
  );
}
