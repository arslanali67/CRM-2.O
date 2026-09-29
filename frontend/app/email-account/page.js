"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";
import { useDialog } from "../ui";

async function call(url, method = "GET", body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

const Result = ({ label, r }) => r && (
  <li style={{ color: r.ok ? "var(--success)" : "var(--danger)" }}>{label}: {r.ok ? "✓" : "✗"} {r.detail}</li>
);

export default function EmailAccount() {
  const dialog = useDialog();
  const router = useRouter();
  const [acc, setAcc] = useState(null);
  const [form, setForm] = useState({ email_address: "", display_name: "", app_password: "" });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await call("/api/email-account");
    if (r.status === 401) return router.replace("/login");
    setAcc(r.data);
    if (r.data.configured) setForm((f) => ({ ...f, email_address: r.data.email_address, display_name: r.data.display_name }));
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function test() {
    setBusy(true);
    setMsg("Testing (logging in to Gmail; nothing is sent)…");
    const r = await call("/api/email-account/test", "POST");
    setBusy(false);
    setMsg(r.ok ? (r.data.connected ? "Connected." : "Test failed; see details below.") : errorText(r.data));
    load();
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    const r = await call("/api/email-account", "PUT", form);
    setBusy(false);
    setForm((f) => ({ ...f, app_password: "" }));  // never keep the password in the page
    if (!r.ok) return setMsg(errorText(r.data));
    await test();
  }

  async function disconnect() {
    if (!await dialog.confirm("Disconnect Gmail?", { body: "The stored app password is deleted. Sending and inbox sync stop until you connect again.", danger: true, confirmLabel: "Disconnect" })) return;
    await call("/api/email-account", "DELETE");
    setMsg("Disconnected; the app password was deleted.");
    load();
  }

  if (!acc) return <p>Loading…</p>;
  const d = acc.last_test_detail || {};

  return (
    <main style={{ maxWidth: 640 }}>
      <p><Link href="/">← Home</Link></p>
      <h1>Email account</h1>

      {acc.configured ? (
        <div style={{ border: "1px solid var(--border)", padding: 12 }}>
          <p>
            <b>{acc.email_address}</b>{" "}
            {acc.connected ? <mark style={{ background: "var(--success-bg)" }}>connected</mark>
              : acc.has_password ? <mark>not verified</mark> : <mark>disconnected</mark>}
          </p>
          <p style={{ color: "var(--muted)" }}><small>
            SMTP {acc.smtp_host}:{acc.smtp_port} (SSL) · IMAP {acc.imap_host}:{acc.imap_port} (SSL) ·
            app password {acc.has_password ? "stored encrypted" : "not stored"}
            {acc.last_test_at && ` · last tested ${new Date(acc.last_test_at).toLocaleString()}`}
          </small></p>
          <ul><Result label="SMTP (sending)" r={d.smtp} /><Result label="IMAP (inbox)" r={d.imap} /></ul>
          <p>
            <button onClick={test} disabled={busy || !acc.has_password}>Test connection</button>{" "}
            {acc.has_password && <button onClick={disconnect} disabled={busy}>Disconnect</button>}
          </p>
        </div>
      ) : <p>No account connected yet.</p>}
      {msg && <p role="status">{msg}</p>}

      <h2 style={{ marginTop: 24 }}>{acc.configured ? "Update account" : "Connect Gmail"}</h2>
      <ol style={{ color: "var(--muted)" }}>
        <li>Turn on 2-Step Verification for your Google account.</li>
        <li>Create an app password: Google Account → Security → App passwords.</li>
        <li>Paste it below. It is encrypted before it is stored and is never shown again.</li>
      </ol>
      <form onSubmit={save} style={{ display: "grid", gap: 8 }}>
        <input type="email" required placeholder="you@gmail.com" aria-label="Gmail address" autoComplete="off"
               value={form.email_address} onChange={(e) => setForm({ ...form, email_address: e.target.value })} />
        <input placeholder="Display name (optional)" aria-label="Display name" value={form.display_name}
               onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        <input type="password" required placeholder="App password (16 letters)" aria-label="App password"
               autoComplete="new-password" value={form.app_password}
               onChange={(e) => setForm({ ...form, app_password: e.target.value })} />
        <button type="submit" disabled={busy}>Save & test connection</button>
      </form>
    </main>
  );
}
