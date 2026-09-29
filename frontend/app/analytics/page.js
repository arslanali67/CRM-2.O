"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const PERIODS = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All time"]];
const SECTIONS = [["by_template_version", "Template version"], ["by_country", "Country"],
                  ["by_industry", "Industry"], ["by_source", "Source"]];
const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 1000) / 10}%`);

function Table({ title, rows }) {
  return (
    <section style={{ marginTop: 20 }}>
      <h3>By {title.toLowerCase()}</h3>
      {rows.length === 0 ? <p>No emails sent in this period.</p> : (
        <table cellPadding={5} style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "right" }}>
              <th align="left">{title}</th><th>Sent</th><th>Replied</th><th>Reply rate</th>
              <th>Bounced (hard / soft)</th><th>Bounce rate</th><th>Opportunities</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.group} style={{ borderTop: "1px solid var(--border)", textAlign: "right", color: g.few_data ? "var(--muted)" : undefined }}>
                <td align="left">{g.group}{g.few_data && <small title="fewer than 10 emails sent: don't read much into the rate"> · few data</small>}</td>
                <td>{g.sent}</td><td>{g.replied}</td><td><b>{pct(g.reply_rate)}</b></td>
                <td>{g.bounced_hard} / {g.bounced_soft}</td><td>{pct(g.bounce_rate)}</td><td>{g.opportunities}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function Analytics() {
  const router = useRouter();
  const [period, setPeriod] = useState("30");
  const [a, setA] = useState(null);

  useEffect(() => {
    fetch(`/api/analytics?period=${period}`).then(async (r) => (r.status === 401 ? router.replace("/login") : setA(await r.json())));
  }, [period, router]);

  const o = a?.overall;
  return (
    <main>
      <p><Link href="/">← Dashboard</Link></p>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
        <h1 style={{ margin: 0 }}>Analytics</h1>
        <span>{PERIODS.map(([v, label]) => (
          <button key={v} onClick={() => setPeriod(v)} style={{ fontWeight: v === period ? "bold" : "normal", marginLeft: 4 }}>{label}</button>
        ))}</span>
      </div>
      {!a ? <p>Loading…</p> : (
        <>
          <p style={{ fontSize: 18 }}>
            <b>{o.sent}</b> sent · <b>{o.replied}</b> replied (<b>{pct(o.reply_rate)}</b>) ·{" "}
            {o.bounced_hard + o.bounced_soft} bounced ({pct(o.bounce_rate)}) · {o.opportunities} opportunities
          </p>
          {SECTIONS.map(([k, title]) => <Table key={k} title={title} rows={a[k]} />)}
          <p style={{ color: "var(--muted)", marginTop: 24 }}><small>
            A reply is credited to the latest email sent to that company before it arrived; auto-replies and bounces never count.
            Companies with several industries count in each. Groups with fewer than {a.few_data_below} emails are marked
            "few data". Computed in {a.query_ms} ms.
          </small></p>
        </>
      )}
    </main>
  );
}
