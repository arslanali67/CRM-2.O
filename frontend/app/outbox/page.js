"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TABS = ["draft", "queued", "sending", "sent", "failed", "cancelled"];

function SendingSwitch() {
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/sending").then((r) => r.ok && r.json()).then((d) => d && setS(d));
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  async function toggle() {
    if (!s.enabled && !window.confirm(
      `Start sending?\n\nQueued emails (${s.queued}) will go out from ${s.account}, one at a time: ` +
      `at most ${s.daily_cap} per 24 hours, ${s.min_gap_seconds} s apart. Every safety check runs again before each send.`)) return;
    const res = await fetch(`/api/sending/${s.enabled ? "disable" : "enable"}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }),
    });
    const data = await res.json();
    setMsg(res.ok ? "" : data.detail);
    if (res.ok) setS(data);
  }

  if (!s) return null;
  return (
    <div style={{ border: `2px solid ${s.enabled ? "crimson" : "#999"}`, padding: 12, margin: "12px 0" }}>
      <b>Sending is {s.enabled ? "ON" : "OFF"}</b>{" "}
      <button onClick={toggle} disabled={!s.enabled && !s.account_ready} style={{ fontWeight: "bold" }}>
        {s.enabled ? "Stop sending" : "Enable sending"}
      </button>
      <div><small>
        {s.queued} queued · {s.sending} sending · {s.sent_24h}/{s.daily_cap} sent in the last 24 h
        {s.last_sent_at && ` · last sent ${new Date(s.last_sent_at).toLocaleString()}`}
        {!s.account_ready && <> · <Link href="/email-account">connect and test an email account</Link> to enable</>}
      </small></div>
      {msg && <p role="alert" style={{ color: "crimson" }}>{msg}</p>}
    </div>
  );
}

export default function Outbox() {
  const router = useRouter();
  const [status, setStatus] = useState("draft");
  const [data, setData] = useState(null);

  useEffect(() => {
    fetch(`/api/outbox?status=${status}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      setData(await res.json());
    });
  }, [status, router]);

  if (!data) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 900 }}>
      <p><Link href="/">← Home</Link> · <Link href="/compose">Compose list</Link></p>
      <h1>Outbox</h1>
      <SendingSwitch />
      <p style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => setStatus(t)} style={{ fontWeight: t === status ? "bold" : "normal" }}>
            {t} ({data.counts[t] || 0})
          </button>
        ))}
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr><th align="left">To</th><th align="left">Company</th><th align="left">Subject</th><th align="left">When</th></tr></thead>
        <tbody>
          {data.emails.map((e) => (
            <tr key={e.id} style={{ borderTop: "1px solid #eee" }}>
              <td><Link href={`/outbox/${e.id}`}>{e.to_email}</Link>{e.has_attachment && " 📎"}</td>
              <td>{e.company_name}</td>
              <td>{e.subject}{(e.cancel_reason || e.failure_reason) && <div style={{ color: "crimson" }}><small>{e.cancel_reason || e.failure_reason}</small></div>}</td>
              <td><small>{new Date(e.sent_at || e.approved_at || e.created_at).toLocaleString()}</small></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.emails.length === 0 && <p>No {status} emails.</p>}
    </main>
  );
}
