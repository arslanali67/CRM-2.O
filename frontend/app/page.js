"use client";
// F2: dashboard. All numbers come from /api/dashboard (M18-M20); the attention strip from the status endpoints.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { describe } from "./activity/describe";
import { LabelBadge } from "./inbox/label";
import { localToday } from "./tasks/panels";
import { Badge, ErrorState, PageHeader, ago } from "./ui";
import { BarChart } from "./ui/chart";

const PERIODS = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All time"]];
const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 1000) / 10}%`);
const get = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);

// F8: first-run checklist; each step ticks itself from existing API data. Dismissal is remembered in this browser only.
function FirstRun() {
  const [steps, setSteps] = useState(null);
  const [hidden, setHidden] = useState(true);
  useEffect(() => {
    try { setHidden(localStorage.getItem("firstRunDismissed") === "1"); } catch { setHidden(false); }
    Promise.all(["/api/email-account", "/api/profile", "/api/cv", "/api/templates", "/api/leads?limit=1"].map(get)).then(([acc, prof, cvs, tpls, leads]) =>
      setSteps([["gmail", "Connect Gmail", "/email-account", !!acc?.connected], ["profile", "Fill in your profile", "/profile", !!prof?.full_name],
                ["cv", "Upload a CV", "/profile", !!cvs?.length], ["template", "Create a template", "/templates", !!tpls?.length],
                ["import", "Import companies", "/import", (leads?.total ?? leads?.leads?.length ?? 0) > 0]]));
  }, []);
  if (hidden || !steps || steps.every((x) => x[3])) return null;
  return (
    <section className="card" data-first-run style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
        <b>Getting started · {steps.filter((x) => x[3]).length} of {steps.length} done</b>
        <button className="btn-sm btn-ghost" onClick={() => { try { localStorage.setItem("firstRunDismissed", "1"); } catch {} setHidden(true); }}>Dismiss</button>
      </div>
      <ul className="checklist">{steps.map(([id, label, href, done]) => (
        <li key={id} data-step={id} className={done ? "done" : ""}><span className="tick" aria-hidden="true">{done ? "✓" : ""}</span>
          <Link href={href}>{label}</Link>{done && <span className="sr-only"> (done)</span>}</li>))}</ul>
    </section>
  );
}

function Kpi({ id, label, value, sub, href }) {
  return (
    <Link href={href} className="stat kpi" data-kpi={id} style={{ color: "inherit", textDecoration: "none", display: "block" }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value" data-value>{value}</div>
      {sub && <small style={{ color: "var(--muted)" }}>{sub}</small>}
    </Link>
  );
}

function Attention({ items }) {
  if (!items.length) return null;
  return (
    <div style={{ display: "grid", gap: 8, marginBottom: 16 }} aria-label="Needs attention">
      {items.map((a) => (
        <Link key={a.id} href={a.href} data-alert={a.id} className="card" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
          textDecoration: "none", color: "var(--text)", borderColor: `var(--${a.tone})`, background: `var(--${a.tone}-bg)` }}>
          <b style={{ color: `var(--${a.tone})` }}>{a.title}</b><span style={{ color: "var(--muted)" }}>{a.text}</span>
          <span style={{ marginLeft: "auto", color: `var(--${a.tone})` }}>{a.action} →</span>
        </Link>
      ))}
    </div>
  );
}

function Panel({ title, href, children }) {
  return (
    <section className="card" style={{ minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
        <h3 style={{ margin: 0 }}>{title}</h3>{href && <Link href={href}><small>View all</small></Link>}
      </div>
      {children}
    </section>
  );
}

const Row = ({ children }) => <div style={{ padding: "8px 0", borderTop: "1px solid var(--border)" }}>{children}</div>;

function zoned(ts, zone) {
  return new Date(ts).toLocaleString(undefined, { timeZone: zone, weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export default function Home() {
  const router = useRouter();
  const [period, setPeriod] = useState("30");
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState({});

  useEffect(() => {
    fetch(`/api/dashboard?period=${period}&today=${localToday()}`).then(async (r) => {
      if (r.status === 401) return router.replace("/login");
      if (!r.ok) return setError("The dashboard couldn't load. Check that the app is running (System status below).");
      setError("");
      setD(await r.json());
    }).catch(() => setError("The dashboard couldn't load."));
  }, [period, router]);

  useEffect(() => {
    Promise.all(["/api/health", "/api/backups", "/api/sending", "/api/email-account", "/api/inbox-sync", "/api/ai/status"].map(get))
      .then(([health, backups, sending, account, sync, ai]) => setStatus({ health, backups, sending, account, sync, ai }));
  }, []);

  const alerts = [];
  const { backups, sending, account, sync, ai, health } = status;
  if (backups?.warn) alerts.push({ id: "backup", tone: "warning", title: backups.backups.length ? "Backup is old." : "No backup yet.",
    text: backups.backups.length ? `The last one is ${Math.round(backups.age_hours)} h old.` : "Make one so your data is safe.", action: "Back up", href: "/backup" });
  if (sending?.enabled) alerts.push({ id: "sending", tone: "danger", title: "Sending is ON.",
    text: `${sending.queued} queued email(s) will go out, one at a time.`, action: "Outbox", href: "/outbox" });
  if (account && !account.connected) alerts.push({ id: "gmail", tone: "warning", title: "Gmail isn't connected.",
    text: account.configured ? "The last connection test failed." : "Replies can't be read and nothing can be sent.", action: "Connect", href: "/email-account" });
  if (sync?.mailboxes?.some((m) => m.failing_since)) alerts.push({ id: "sync", tone: "danger", title: "Inbox sync is failing.",
    text: "New replies aren't being read.", action: "Details", href: "/email-account" });
  if (ai && !ai.enabled) alerts.push({ id: "ai", tone: "accent", title: "AI analysis is off.",
    text: ai.key_present ? "It's switched off in Settings." : "No AI key in .env; replies aren't analysed.", action: "Settings", href: "/settings" });

  const k = d?.kpis;
  const next = k?.interviews?.next;
  return (
    <main>
      <PageHeader title="Dashboard" sub={d ? (period === "all" ? "All time" : `Last ${period} days`) : ""}
        actions={<div className="segmented" role="group" aria-label="Period">
          {PERIODS.map(([v, label]) => (
            <button key={v} onClick={() => setPeriod(v)} aria-pressed={v === period} className={v === period ? "btn-primary" : ""}>{label}</button>
          ))}
        </div>} />

      <FirstRun />
      <Attention items={alerts} />
      {error && <ErrorState>{error}</ErrorState>}

      {!k ? !error && <div className="kpi-grid">{Array.from({ length: 8 }, (_, i) => <div key={i} className="stat skeleton" />)}</div> : (
        <>
          <div className="kpi-grid">
            <Kpi id="leads" label="Leads" value={k.leads.total} href="/companies"
                 sub={Object.entries(k.leads.by_stage).map(([s, n]) => `${n} ${s.replace("_", " ")}`).join(" · ") || "none yet"} />
            <Kpi id="sent" label="Sent" value={k.sent} sub={`to ${k.companies_emailed} companies`} href="/history" />
            <Kpi id="reply_rate" label="Reply rate" value={pct(k.reply_rate)} href="/analytics"
                 sub={`${k.companies_replied} of ${k.companies_emailed} companies replied`} />
            <Kpi id="interested" label="Interested" value={k.interested} sub="AI: interested, interview, scheduling…" href="/inbox" />
            <Kpi id="offers" label="Offers" value={k.offers} sub="AI-labelled offers" href="/inbox" />
            <Kpi id="opportunities" label="Open opportunities" value={k.opportunities.open} href="/opportunities"
                 sub={Object.entries(k.opportunities.by_stage).map(([s, n]) => `${n} ${s}`).join(" · ") || "none yet"} />
            <Kpi id="interviews" label="Upcoming interviews" value={k.interviews.upcoming} href="/interviews"
                 sub={next ? `next: ${next.company_name}` : "none scheduled"} />
            <Kpi id="bounces" label="Bounces" value={k.bounces} sub={`${k.auto_replies} auto-replies`} href="/inbox" />
          </div>

          <section className="card" style={{ marginTop: 16 }}>
            <h3 style={{ marginTop: 0 }}>Emails sent per day</h3>
            <BarChart label="Emails sent per day" unit="sent" empty="No emails sent in this period."
                      data={d.sent_series.map((x) => ({ key: x.day, value: x.sent,
                        label: new Date(`${x.day}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) }))} />
          </section>

          <div className="panel-grid" style={{ marginTop: 16 }}>
            <Panel title="Latest replies" href="/inbox">
              {d.latest_replies.length === 0 && <p style={{ color: "var(--muted)", margin: 0 }}>No replies yet.</p>}
              {d.latest_replies.map((m) => (
                <Row key={m.id}>
                  <Link href={`/threads/${m.thread_key}#in-${m.id}`}><b>{m.from_name || m.from_email}</b></Link>{" "}
                  <LabelBadge m={m} />{m.ai_label && <> <Badge tone="accent">AI: {m.ai_label.replaceAll("_", " ")}</Badge></>}
                  <div><small style={{ color: "var(--muted)" }}>{m.company_name || "unknown company"} · {m.subject} · {ago(m.received_at)}</small></div>
                </Row>
              ))}
            </Panel>
            <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
              {next && (
                <Panel title="Next interview" href="/interviews">
                  <Link href={`/opportunities/${next.opportunity_id}#interview-${next.id}`}><b>{next.title}</b></Link>
                  <div>{next.company_name}</div>
                  <small style={{ color: "var(--muted)" }}>{zoned(next.starts_at, next.time_zone)} ({next.time_zone})
                    {next.time_zone !== Intl.DateTimeFormat().resolvedOptions().timeZone && <> · your time {new Date(next.starts_at).toLocaleString()}</>}</small>
                </Panel>
              )}
              <Panel title="Tasks due" href="/tasks">
                {d.tasks.length === 0 && <p style={{ color: "var(--muted)", margin: 0 }}>Nothing due this week.</p>}
                {d.tasks.map((t) => (
                  <Row key={t.id}><span style={{ color: t.overdue ? "var(--danger)" : undefined }}>{t.title}</span>
                    <div><small style={{ color: t.overdue ? "var(--danger)" : "var(--muted)" }}>{t.overdue ? "overdue · " : "due "}{t.due_date}</small></div></Row>
                ))}
              </Panel>
            </div>
            <Panel title="Recent activity" href="/activity">
              {d.activity.slice(0, 8).map((e) => (
                <Row key={e.id}><div style={{ overflowWrap: "anywhere" }}>{describe(e)}</div>
                  <small style={{ color: "var(--muted)" }}>{ago(e.at)} · {e.actor}</small></Row>
              ))}
            </Panel>
          </div>
        </>
      )}

      <p style={{ color: "var(--muted)", marginTop: 20, display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }} aria-label="System status">
        <small>System status:</small>
        {health ? Object.entries(health).map(([key, v]) => (
          <small key={key}><span style={{ color: v === "ok" ? "var(--success)" : "var(--danger)" }}>●</span> {key} {v === "ok" ? "ok" : v}</small>
        )) : <small>checking…</small>}
        {d && <small style={{ marginLeft: "auto" }}>computed in {d.query_ms} ms</small>}
      </p>
    </main>
  );
}
