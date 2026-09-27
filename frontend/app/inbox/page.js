"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, useEffect, useState } from "react";

const WHY = {
  reply_header: "replies to your email", thread: "in your thread", bounce: "bounce",
  contact: "from a contact", company_domain: "from a company domain",
};

function SyncStatus({ onSynced }) {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/inbox-sync").then((r) => r.ok && r.json()).then((d) => d && setS(d));
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  async function run() {
    setBusy(true);
    setMsg("Syncing (read-only)…");
    const r = await fetch("/api/inbox-sync/run", { method: "POST" }).then((x) => x.json());
    setBusy(false);
    setMsg(r.action === "synced" ? "Up to date." : r.action === "locked" ? "A sync is already running." : r.error || r.action);
    load();
    onSynced();
  }

  if (!s) return null;
  return (
    <div style={{ border: "1px solid #ccc", padding: 12, margin: "12px 0" }}>
      <b>Inbox sync</b> (read-only, every 2 minutes; nothing is marked read or changed){" "}
      <button onClick={run} disabled={busy || !s.account_ready}>Sync now</button>
      {!s.account_ready && <> · <Link href="/email-account">connect an email account</Link></>}
      <ul style={{ margin: "6px 0" }}>
        {s.mailboxes.map((b) => (
          <li key={b.mailbox} style={{ color: b.last_ok === false ? "crimson" : undefined }}>
            {b.imap_name || b.mailbox}: {b.last_sync_at ? `synced ${new Date(b.last_sync_at).toLocaleString()}` : "not synced yet"}
            {" · "}{b.seen_count} examined, {b.stored_count} relevant stored
            {b.last_error && ` · error: ${b.last_error}`}
          </li>
        ))}
      </ul>
      {msg && <small>{msg}</small>}
    </div>
  );
}

export default function Inbox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [msgs, setMsgs] = useState(null);
  const [open, setOpen] = useState(null);

  async function load(query = q) {
    const res = await fetch(`/api/inbox${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    if (res.status === 401) return router.replace("/login");
    setMsgs(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function show(id) {
    setOpen(open?.id === id ? null : await fetch(`/api/inbox/${id}`).then((r) => r.json()));
  }

  if (!msgs) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 900 }}>
      <p><Link href="/">← Home</Link> · <Link href="/history">History</Link></p>
      <h1>Inbox</h1>
      <p style={{ color: "gray" }}>Only outreach-related messages are stored. The system never replies on its own.</p>
      <SyncStatus onSynced={() => load()} />
      <form onSubmit={(e) => { e.preventDefault(); load(); }} style={{ display: "flex", gap: 6 }}>
        <input placeholder="Search sender or subject" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <button type="submit">Search</button>
      </form>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12 }}>
        <thead><tr><th align="left">From</th><th align="left">Subject</th><th align="left">Company</th><th align="left">Why</th><th align="left">Received</th></tr></thead>
        <tbody>
          {msgs.map((m) => (
            <Fragment key={m.id}>
              <tr style={{ borderTop: "1px solid #eee", cursor: "pointer" }} onClick={() => show(m.id)}>
                <td>{m.from_name || m.from_email}<div><small style={{ color: "gray" }}>{m.from_email}</small></div></td>
                <td>{m.subject}{m.mailbox === "spam" && <mark> spam</mark>}{m.attachment_names.length > 0 && " 📎"}
                  <div><small style={{ color: "gray" }}>{m.snippet}</small></div></td>
                <td>{m.company_id ? <Link href={`/companies/${m.company_id}`}>{m.company_name}</Link> : "—"}</td>
                <td><small>{WHY[m.relevance]}</small></td>
                <td><small>{m.received_at && new Date(m.received_at).toLocaleString()}</small></td>
              </tr>
              {open?.id === m.id && (
                <tr><td colSpan={5} style={{ background: "#fafafa", padding: 12 }}>
                  <div><small>To: {open.to_emails} · <Link href={`/threads/${open.thread_key}`}>open thread</Link>
                    {open.attachment_names.length > 0 && ` · attachments: ${open.attachment_names.join(", ")} (not stored)`}</small></div>
                  <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{open.body_text}{open.body_truncated && "\n[truncated]"}</pre>
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
      {msgs.length === 0 && <p>No relevant messages yet.</p>}
    </main>
  );
}
