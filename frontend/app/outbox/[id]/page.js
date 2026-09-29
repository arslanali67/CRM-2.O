"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { describe } from "../../activity/describe";
import { errorText } from "../../companies/shared";

async function call(url, method = "GET", body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

const box = { border: "1px solid #ccc", padding: 12, background: "#fafafa" };

export default function Email() {
  const { id } = useParams();
  const router = useRouter();
  const [e, setE] = useState(null);
  const [draft, setDraft] = useState(null);
  const [cvs, setCvs] = useState([]);
  const [msg, setMsg] = useState("");
  const [failedChecks, setFailedChecks] = useState(null);
  const [timeline, setTimeline] = useState([]);

  async function load() {
    const r = await call(`/api/outbound-emails/${id}`);
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setMsg(errorText(r.data));
    setE(r.data);
    call(`/api/outbound-emails/${id}/timeline`).then((t) => t.ok && setTimeline(t.data));
    setDraft({ subject: r.data.subject, body: r.data.body, cv_version_id: r.data.cv_version_id ? String(r.data.cv_version_id) : "" });
  }
  useEffect(() => { load(); call("/api/cv").then((r) => r.ok && setCvs(r.data)); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(ev) {
    ev.preventDefault();
    const r = await call(`/api/outbound-emails/${id}`, "PUT",
      { subject: draft.subject, body: draft.body, cv_version_id: draft.cv_version_id ? Number(draft.cv_version_id) : null });
    setMsg(r.ok ? "Saved. Review the preview again before approving." : errorText(r.data));
    if (r.ok) load();
  }

  async function approve() {
    // Sends the hash of exactly what is on screen; the server refuses if it changed since.
    const r = await call(`/api/outbound-emails/${id}/approve`, "POST", { content_hash: e.content_hash_hex });
    if (r.ok) { setFailedChecks(null); setMsg("Approved and queued."); return load(); }
    if (r.status === 422 && r.data.checks) { setFailedChecks(r.data.checks.filter((c) => !c.ok)); setMsg("Not approved."); }
    else setMsg(errorText(r.data));
    load();
  }

  async function action(name, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return;
    const r = await call(`/api/outbound-emails/${id}/${name}`, "POST");
    setMsg(r.ok ? `Now ${r.data.status}.` : errorText(r.data));
    load();
  }

  if (!e || !draft) return <p>{msg || "Loading…"}</p>;
  const isDraft = e.status === "draft";
  const edited = isDraft && (draft.subject !== e.subject || draft.body !== e.body ||
    (draft.cv_version_id || null) !== (e.cv_version_id ? String(e.cv_version_id) : null));
  const checks = e.checks?.results || [];
  const blocking = checks.filter((c) => !c.ok);

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/outbox">← Outbox</Link> · <Link href={`/companies/${e.company_id}`}>{e.company_name}</Link></p>
      <h1>Email #{e.id} <small>({e.status})</small></h1>
      {e.cancel_reason && <p style={{ color: "crimson" }}>Cancelled: {e.cancel_reason}</p>}
      {e.failure_reason && <p style={{ color: "crimson" }}>Failed: {e.failure_reason}</p>}
      {e.sent_at && <p style={{ color: "green" }}>Sent {new Date(e.sent_at).toLocaleString()} · Message-ID <code>{e.provider_message_id}</code></p>}

      <h2>Exact preview</h2>
      <div style={box}>
        <div><b>From:</b> {e.from.name || <i>(no name in profile)</i>} &lt;{e.from.email || "no address"}&gt;
          {!e.from.account_connected && <small style={{ color: "crimson" }}> (no Gmail connected: <Link href="/email-account">connect one</Link>)</small>}
        </div>
        <div><b>To:</b> {e.contact_name ? `${e.contact_name} ` : ""}&lt;{e.to_email}&gt; <mark>{e.email_class}</mark></div>
        <div><b>Subject:</b> {e.subject}</div>
        <div><b>Attachment:</b> {e.cv_version_id ? `${e.cv_filename} (${e.cv_label})` : "none"}</div>
        <hr />
        <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>{e.body}</pre>
      </div>
      {e.personalization?.sentences?.length > 0 && (
        <div style={{ border: "2px solid #d97706", borderRadius: 6, padding: 10, margin: "8px 0" }}>
          <b>AI-written sentences in this email</b> (check them before approving):
          {e.personalization.sentences.map((s, i) => (
            <div key={i} style={{ marginTop: 6 }}>
              <mark style={{ background: "#fde68a" }}>{s.text}</mark>
              {!e.body.includes(s.text) && <small style={{ color: "gray" }}> (edited or removed since)</small>}
              <ul style={{ margin: "2px 0" }}>{s.facts.map((f) => (
                <li key={f.id}><small>cites verified fact: “{f.fact}” · source: {/^https?:\/\//.test(f.source)
                  ? <a href={f.source} target="_blank" rel="noopener noreferrer">{f.source}</a> : f.source}</small></li>
              ))}</ul>
            </div>
          ))}
          {e.personalization.dropped?.length > 0 && <small style={{ color: "gray" }}>
            {e.personalization.dropped.length} AI sentence(s) were dropped as unproven and are not in the email.</small>}
        </div>
      )}
      <p style={{ color: "gray" }}><small>
        {e.template_name && `From template ${e.template_name} v${e.template_version} · `}fingerprint {e.content_hash_hex.slice(0, 12)}…
      </small></p>

      {checks.length > 0 && (
        <details open={blocking.length > 0}>
          <summary>Safety checks ({e.checks.stage}): {blocking.length ? `${blocking.length} failing` : "all passing"}</summary>
          <ol>
            {checks.map((c) => (
              <li key={c.id} style={{ color: c.ok ? (c.applies ? "green" : "gray") : "crimson" }}>
                {c.name}{!c.ok && `: ${c.detail}`}{!c.applies && " (checked at send)"}
              </li>
            ))}
          </ol>
        </details>
      )}

      {isDraft && (
        <p>
          <button onClick={approve} disabled={edited} style={{ fontWeight: "bold" }}>Approve & queue this email</button>{" "}
          {edited && <small>Save your edits first, then review the preview again.</small>}{" "}
          <button onClick={() => action("discard", "Discard this draft?")}>Discard</button>
        </p>
      )}
      {["approved", "queued"].includes(e.status) && (
        <p><button onClick={() => action("unqueue")}>Pull back to draft</button> <small>(clears the approval)</small></p>
      )}
      {msg && <p role="status">{msg}</p>}
      {failedChecks && (
        <ul style={{ color: "crimson" }}>{failedChecks.map((c) => <li key={c.id}>{c.id}. {c.name}: {c.detail}</li>)}</ul>
      )}

      <h2 style={{ marginTop: 32 }}>Status timeline</h2>
      <ol>
        {timeline.map((t) => (
          <li key={t.id}><small style={{ color: "gray" }}>{new Date(t.at).toLocaleString()} · {t.actor}</small> {describe(t)}</li>
        ))}
      </ol>
      <p style={{ color: "gray" }}><small>
        Message-ID <code>{e.provider_message_id || "not assigned yet"}</code>
        {" · "}Gmail message <code>{e.gmail_msgid || "unknown yet"}</code>
        {" · "}<Link href={`/threads/${e.thread_key}`}>Gmail thread {e.gmail_thrid || "(not linked yet)"}</Link>
      </small></p>

      {isDraft && (
        <>
          <h2 style={{ marginTop: 32 }}>Edit draft</h2>
          <form onSubmit={save} style={{ display: "grid", gap: 8 }}>
            <label>Subject<input value={draft.subject} onChange={(ev) => setDraft({ ...draft, subject: ev.target.value })} style={{ display: "block", width: "100%" }} /></label>
            <label>Body<textarea rows={12} value={draft.body} onChange={(ev) => setDraft({ ...draft, body: ev.target.value })} style={{ display: "block", width: "100%", fontFamily: "inherit" }} /></label>
            <label>Attachment{" "}
              <select value={draft.cv_version_id} onChange={(ev) => setDraft({ ...draft, cv_version_id: ev.target.value })}>
                <option value="">No attachment</option>
                {cvs.map((c) => <option key={c.id} value={c.id}>CV: {c.label}{c.is_default ? " (default)" : ""}</option>)}
              </select>
            </label>
            <button type="submit" disabled={!edited}>Save draft</button>
          </form>
        </>
      )}
    </main>
  );
}
