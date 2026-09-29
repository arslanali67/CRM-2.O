"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { When } from "../opportunities/interviews";

const TABS = [["upcoming", "Upcoming"], ["past", "Past, done & cancelled"]];

export default function Interviews() {
  const router = useRouter();
  const [when, setWhen] = useState("upcoming");
  const [list, setList] = useState(null);

  useEffect(() => {
    fetch(`/api/interviews?when=${when}`).then(async (r) => (r.status === 401 ? router.replace("/login") : setList(await r.json())));
  }, [when, router]);

  return (
    <main>
      <p><Link href="/">← Dashboard</Link> · <Link href="/opportunities">Opportunities</Link></p>
      <h1>Interviews</h1>
      <p>{TABS.map(([k, label]) => (
        <button key={k} onClick={() => setWhen(k)} style={{ fontWeight: k === when ? "bold" : "normal", marginRight: 4 }}>{label}</button>
      ))}</p>
      {!list ? <p>Loading…</p> : list.length === 0 ? <p>No {when === "upcoming" ? "upcoming" : "past"} interviews. Record one on an opportunity.</p> : (
        <table cellPadding={6} style={{ borderCollapse: "collapse" }}>
          <tbody>
            {list.map((i) => (
              <tr key={i.id} style={{ borderBottom: "1px solid #eee", verticalAlign: "top" }}>
                <td><When i={i} /><br /><small>{i.duration_minutes} min · {i.kind} · {i.status}</small></td>
                <td><Link href={`/opportunities/${i.opportunity_id}#interview-${i.id}`}><b>{i.title}</b></Link>
                  <br /><small>{i.company_name} · {i.opportunity_title}</small></td>
                <td><a href={`/api/interviews/${i.id}/calendar.ics`}>.ics</a></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p><small style={{ color: "gray" }}>Reminders appear in the notifications bell 24 h and 1 h before (switchable in Settings).</small></p>
    </main>
  );
}
