"use client";
// F4: Outbox. Sending card (status, daily-cap bar, queue) and status tabs with counts. Starting sending still asks
// for an explicit confirmation; every email is approved on its own page.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, EmptyState, Loading, PageHeader, Tabs, ago, useDialog } from "../ui";

const TABS = ["draft", "queued", "sending", "sent", "failed", "cancelled"];

function SendingSwitch() {
  const dialog = useDialog();
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/sending").then((r) => r.ok && r.json()).then((d) => d && setS(d));
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, []);

  async function toggle() {
    if (!s.enabled && !await dialog.confirm("Start sending?", { danger: true, confirmLabel: "Start sending",
      body: `Queued emails (${s.queued}) will go out from ${s.account}, one at a time: ` +
            `at most ${s.daily_cap} per 24 hours, ${s.min_gap_seconds} s apart. Every safety check runs again before each send.` })) return;
    const res = await fetch(`/api/sending/${s.enabled ? "disable" : "enable"}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: true }),
    });
    const data = await res.json();
    setMsg(res.ok ? "" : data.detail);
    if (res.ok) setS(data);
  }

  if (!s) return <div className="card skeleton" style={{ minHeight: 110 }} />;
  const used = Math.min(100, Math.round((s.sent_24h / s.daily_cap) * 100));
  return (
    <section className="card sending-card" data-on={s.enabled || undefined} aria-label="Sending">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: s.enabled ? "var(--danger)" : undefined }}>Sending is {s.enabled ? "ON" : "OFF"}</div>
          <small style={{ color: "var(--muted)" }}>{s.enabled ? `Queued emails go out one at a time from ${s.account}.` : "Nothing is sent until you switch sending on."}</small>
        </div>
        <button onClick={toggle} disabled={!s.enabled && !s.account_ready} className={s.enabled ? "btn-danger" : "btn-primary"}>
          {s.enabled ? "Stop sending" : "Enable sending"}
        </button>
      </div>
      <div className="mini-stats" style={{ marginTop: 12 }}>
        <span><b>{s.queued}</b> queued</span><span><b>{s.sending}</b> sending</span>
        <span>gap <b>{s.min_gap_seconds} s</b></span>
        <span>last sent <b>{s.last_sent_at ? ago(s.last_sent_at) : "never"}</b></span>
      </div>
      <div style={{ marginTop: 10 }}>
        <small style={{ color: "var(--muted)" }}>{s.sent_24h} / {s.daily_cap} sent in the last 24 h</small>
        <div className="cap-bar" role="progressbar" aria-label="Daily cap used" aria-valuenow={s.sent_24h} aria-valuemin={0} aria-valuemax={s.daily_cap}>
          <span style={{ width: `${used}%`, background: used >= 100 ? "var(--danger)" : undefined }} /></div>
      </div>
      {!s.account_ready && <p style={{ margin: "10px 0 0" }}><small><Link href="/email-account">Connect and test an email account</Link> to enable sending.</small></p>}
      {msg && <p role="alert" className="error-box" style={{ marginTop: 10 }}>{msg}</p>}
    </section>
  );
}

export default function Outbox() {
  const router = useRouter();
  const [status, setStatus] = useState("draft");
  const [data, setData] = useState(null);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("status");
    if (TABS.includes(q)) setStatus(q);
  }, []);
  useEffect(() => {
    fetch(`/api/outbox?status=${status}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      setData(await res.json());
    });
  }, [status, router]);

  function pick(label) {
    const s = label.split(" ")[0];
    setStatus(s);
    window.history.replaceState(null, "", `/outbox?status=${s}`);
  }

  return (
    <main>
      <PageHeader title="Outbox" sub="Review each email and approve it on its own. Approved emails wait in the queue until sending is on."
                  actions={<Link className="btn" href="/compose">Compose</Link>} />
      <SendingSwitch />
      <div style={{ marginTop: 16 }}>
        <Tabs tabs={TABS.map((t) => `${t} (${data?.counts[t] || 0})`)} value={`${status} (${data?.counts[status] || 0})`} onChange={pick} />
      </div>
      {!data ? <Loading what="emails" /> : data.emails.length === 0 ? (
        <EmptyState title={`No ${status} emails`}>{status === "draft" ? <>Create drafts on the <Link href="/compose">Compose</Link> page.</> : null}</EmptyState>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>To</th><th>Company</th><th>Subject</th><th>When</th></tr></thead>
            <tbody>
              {data.emails.map((e) => (
                <tr key={e.id}>
                  <td><Link href={`/outbox/${e.id}`}>{e.to_email}</Link>
                    <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                      {e.has_attachment && <Badge>CV</Badge>}{e.personalized && <Badge tone="warning">AI-personalized</Badge>}</div></td>
                  <td>{e.company_id ? <Link href={`/companies/${e.company_id}`}>{e.company_name}</Link> : "—"}</td>
                  <td>{e.subject}{(e.cancel_reason || e.failure_reason) && <div><small style={{ color: "var(--danger)" }}>{e.cancel_reason || e.failure_reason}</small></div>}</td>
                  <td><small title={new Date(e.sent_at || e.approved_at || e.created_at).toLocaleString()}>{ago(e.sent_at || e.approved_at || e.created_at)}</small></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
