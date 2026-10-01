"use client";
// F6: interviews. Upcoming grouped by day (in the owner's time zone) with each card in the interview's own zone and
// the owner's; a Past tab with outcome notes. Recording an interview stays on the opportunity page.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, EmptyState, Loading, PageHeader, Tabs } from "../ui";

const KIND = { video: "Video call", phone: "Phone", onsite: "On-site" };
const myZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const dayKey = (ts) => new Date(ts).toLocaleDateString("en-CA");  // yyyy-mm-dd in the owner's zone

function dayLabel(ts) {
  const d = new Date(ts), t = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  if (same(d, t)) return "Today";
  const tm = new Date(t); tm.setDate(t.getDate() + 1);
  if (same(d, tm)) return "Tomorrow";
  const y = new Date(t); y.setDate(t.getDate() - 1);
  if (same(d, y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: d.getFullYear() === t.getFullYear() ? undefined : "numeric" });
}
const clock = (ts, zone) => new Date(ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: zone });

function Card({ i }) {
  const mine = myZone();
  const link = /^https?:\/\//i.test(i.location);
  return (
    <article className="card interview-card" id={`interview-${i.id}`} data-interview={i.id}>
      <div className="iv-time">
        <b>{clock(i.starts_at, i.time_zone)}</b>
        <small>{i.time_zone}</small>
        {i.time_zone !== mine && <small data-your-time style={{ color: "var(--muted)" }}>your time {clock(i.starts_at, mine)}</small>}
      </div>
      <div style={{ minWidth: 0 }}>
        <Link href={`/opportunities/${i.opportunity_id}#interview-${i.id}`}><b>{i.title}</b></Link>
        <div><small>{i.company_name} · {i.opportunity_title}</small></div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4, alignItems: "center" }}>
          <Badge>{i.duration_minutes} min</Badge><Badge>{KIND[i.kind] || i.kind}</Badge>
          {i.status !== "scheduled" && <Badge tone={i.status === "done" ? "success" : "danger"}>{i.status}</Badge>}
          <a href={`/api/interviews/${i.id}/calendar.ics`}><small>Add to calendar (.ics)</small></a>
        </div>
        {i.location && <div style={{ overflowWrap: "anywhere", marginTop: 4 }}><small>{link ? <>Meeting link (copy to open): <code>{i.location}</code></> : i.location}</small></div>}
        {i.interviewers && <div><small style={{ color: "var(--muted)" }}>With {i.interviewers}</small></div>}
        {i.outcome && <div style={{ marginTop: 4 }}><small>Outcome: {i.outcome}</small></div>}
      </div>
    </article>
  );
}

export default function Interviews() {
  const router = useRouter();
  const [when, setWhen] = useState("upcoming");
  const [list, setList] = useState(null);

  useEffect(() => {
    setList(null);
    fetch(`/api/interviews?when=${when}`).then(async (r) => (r.status === 401 ? router.replace("/login") : setList(await r.json())));
  }, [when, router]);

  const groups = [];
  (list || []).forEach((i) => {
    const k = dayKey(i.starts_at);
    (groups.find((g) => g.k === k) || (groups.push({ k, label: dayLabel(i.starts_at), items: [] }), groups[groups.length - 1])).items.push(i);
  });

  return (
    <main>
      <PageHeader title="Interviews" sub="Times are shown in each interview's own time zone and in yours. Record an interview on its opportunity; nothing is ever emailed." />
      <Tabs tabs={["Upcoming", "Past"]} value={when === "upcoming" ? "Upcoming" : "Past"} onChange={(t) => setWhen(t.toLowerCase())} />
      {!list ? <Loading what="interviews" /> : list.length === 0 ? (
        <EmptyState title={when === "upcoming" ? "No upcoming interviews" : "No past interviews"}
                    action={<Link className="btn" href="/opportunities">Open opportunities</Link>}>
          {when === "upcoming" ? "Open an opportunity and click “Record an interview”." : "Done and cancelled interviews appear here, with their outcome."}
        </EmptyState>
      ) : groups.map((g) => (
        <section key={g.k} style={{ marginBottom: 16 }} data-day={g.label}>
          <h3 style={{ margin: "0 0 6px", color: "var(--muted)", fontSize: 13 }}>{g.label}</h3>
          <div style={{ display: "grid", gap: 8 }}>{g.items.map((i) => <Card key={i.id} i={i} />)}</div>
        </section>
      ))}
      <p><small style={{ color: "var(--muted)" }}>Reminders appear in the notifications bell 24 h and 1 h before (switchable in Settings).</small></p>
    </main>
  );
}
