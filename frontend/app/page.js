"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { describe } from "./activity/describe";
import { LabelBadge } from "./inbox/label";
import { localToday } from "./tasks/panels";

const PERIODS = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All time"]];
const tile = { border: "1px solid #ddd", borderRadius: 6, padding: "10px 12px", minWidth: 120, flex: "1 1 120px" };

function Tile({ label, value, sub, href }) {
  const body = (
    <div style={tile}>
      <div style={{ fontSize: 26, fontWeight: 600 }}>{value}</div>
      <div>{label}</div>
      {sub && <small style={{ color: "gray" }}>{sub}</small>}
    </div>
  );
  return href ? <Link href={href} style={{ color: "inherit", textDecoration: "none", display: "contents" }}>{body}</Link> : body;
}

function Series({ data }) {
  const max = Math.max(1, ...data.map((d) => d.sent));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 60, borderBottom: "1px solid #ccc" }}
         aria-label="Emails sent per day">
      {data.map((d) => (
        <div key={d.day} title={`${d.day}: ${d.sent} sent`}
             style={{ flex: 1, height: `${(d.sent / max) * 100}%`, minHeight: d.sent ? 2 : 0, background: "steelblue" }} />
      ))}
    </div>
  );
}

export default function Home() {
  const router = useRouter();
  const [email, setEmail] = useState(null);
  const [health, setHealth] = useState(null);
  const [period, setPeriod] = useState("30");
  const [d, setD] = useState(null);

  useEffect(() => {
    fetch("/api/auth/me").then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      setEmail((await res.json()).email);
      setHealth(await fetch("/api/health").then((r) => r.json()));
    });
  }, [router]);

  useEffect(() => {
    if (!email) return;
    fetch(`/api/dashboard?period=${period}&today=${localToday()}`).then((r) => r.ok && r.json()).then((x) => x && setD(x));
  }, [email, period]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!email) return <p>Loading…</p>;
  const k = d?.kpis;
  const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 1000) / 10}%`);

  return (
    <main>
      <p>
        <Link href="/companies">Leads</Link> · <Link href="/opportunities">Opportunities</Link> · <Link href="/compose">Compose list</Link> · <Link href="/outbox">Outbox</Link> · <Link href="/history">History</Link> · <Link href="/inbox">Inbox</Link> ·{" "}
        <Link href="/templates">Templates</Link> · <Link href="/import">Import CSV</Link> · <Link href="/duplicates">Duplicates</Link> ·{" "}
        <Link href="/profile">Profile & CV</Link> · <Link href="/email-account">Email account</Link> · <Link href="/do-not-contact">Do-not-contact</Link> ·{" "}
        <Link href="/tasks">Tasks</Link> · <Link href="/notifications">Notifications</Link> · <Link href="/activity">Activity</Link> · <Link href="/settings">Settings</Link>
      </p>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h1 style={{ margin: 0 }}>Dashboard</h1>
        <span>
          {PERIODS.map(([v, label]) => (
            <button key={v} onClick={() => setPeriod(v)} style={{ fontWeight: v === period ? "bold" : "normal", marginLeft: 4 }}>{label}</button>
          ))}
        </span>
      </div>

      {!k ? <p>Loading dashboard…</p> : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0" }}>
            <Tile label="Leads" value={k.leads.total} href="/companies"
                  sub={Object.entries(k.leads.by_stage).map(([s, n]) => `${n} ${s.replace("_", " ")}`).join(" · ")} />
            <Tile label="Sent" value={k.sent} sub={`to ${k.companies_emailed} companies`} href="/history" />
            <Tile label="Replies" value={k.replies} sub={`from ${k.companies_replied} companies`} href="/inbox" />
            <Tile label="Reply rate" value={pct(k.reply_rate)} sub="companies that replied after being emailed" />
            <Tile label="Interested" value={k.interested} sub="AI: interested, interview, scheduling, questions, offer" />
            <Tile label="Offers" value={k.offers} />
            <Tile label="Open opportunities" value={k.opportunities.open} href="/opportunities"
                  sub={Object.entries(k.opportunities.by_stage).map(([s, n]) => `${n} ${s}`).join(" · ") || "none yet"} />
            <Tile label="Interviews" value="—" sub={`available after ${k.interviews.after}`} />
            <Tile label="Bounces" value={k.bounces} sub={`${k.auto_replies} auto-replies`} />
          </div>

          <h3>Emails sent per day</h3>
          <Series data={d.sent_series} />

          <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginTop: 24 }}>
            <section style={{ flex: "1 1 300px" }}>
              <h3>Latest replies</h3>
              {d.latest_replies.length === 0 && <p>None yet.</p>}
              {d.latest_replies.map((m) => (
                <div key={m.id} style={{ marginBottom: 6 }}>
                  <Link href={`/threads/${m.thread_key}#in-${m.id}`}>{m.from_name || m.from_email}</Link> <LabelBadge m={m} />
                  {m.ai_label && <small> · AI: {m.ai_label.replaceAll("_", " ")}</small>}
                  <div><small style={{ color: "gray" }}>{m.company_name} · {m.subject}</small></div>
                </div>
              ))}
            </section>
            <section style={{ flex: "1 1 220px" }}>
              <h3><Link href="/tasks">Tasks due</Link></h3>
              {d.tasks.length === 0 && <p>Nothing due this week.</p>}
              {d.tasks.map((t) => (
                <div key={t.id} style={{ color: t.overdue ? "crimson" : undefined }}>{t.due_date} · {t.title}</div>
              ))}
            </section>
            <section style={{ flex: "1 1 300px" }}>
              <h3><Link href="/activity">Recent activity</Link></h3>
              {d.activity.map((e) => (
                <div key={e.id}><small style={{ color: "gray" }}>{new Date(e.at).toLocaleString()}</small> {describe(e)}</div>
              ))}
            </section>
          </div>
          <p style={{ color: "gray" }}><small>Computed in {d.query_ms} ms.</small></p>
        </>
      )}

      <h3>System status</h3>
      <p>{health ? Object.entries(health).map(([key, v]) => `${key}: ${v}`).join(" · ") : "Checking…"}</p>
      <p><small>Signed in as {email}</small> <button onClick={logout}>Sign out</button></p>
    </main>
  );
}
