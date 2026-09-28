"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";

const REASON = { domain: "same domain", email: "contact email", linkedin: "same LinkedIn", name: "similar name" };

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return { ok: r.ok, data: await r.json() };
}

function Co({ id, name, domain }) {
  return <><Link href={`/companies/${id}`}>{name}</Link>{domain && <small style={{ color: "gray" }}> {domain}</small>}</>;
}

export default function Duplicates() {
  const router = useRouter();
  const [pairs, setPairs] = useState(null);
  const [merges, setMerges] = useState([]);
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await fetch("/api/duplicates");
    if (r.status === 401) return router.replace("/login");
    setPairs(await r.json());
    setMerges(await fetch("/api/duplicates/merges").then((x) => x.json()));
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(p, msgOk) {
    const r = await p;
    setMsg(r.ok ? msgOk : errorText(r.data));
    load();
  }

  function merge(keep, drop) {
    if (!window.confirm(`Keep "${keep.name}" and merge "${drop.name}" into it?\n\nAll of ${drop.name}'s contacts, emails, replies, opportunities, notes and tasks move to ${keep.name}; ${drop.name} is archived. You can undo this below.`)) return;
    act(post("/api/duplicates/merge", { survivor_id: keep.id, merged_id: drop.id }), `Merged "${drop.name}" into "${keep.name}".`);
  }

  if (!pairs) return <p>Loading…</p>;
  return (
    <main>
      <p><Link href="/companies">← Leads</Link></p>
      <h1>Duplicates</h1>
      <p><small>Suggestions only: nothing is merged unless you choose. Merges refuse while an email for either company is approved, queued or sending.</small></p>
      {msg && <p>{msg}</p>}

      {pairs.length === 0 && <p>No likely duplicates.</p>}
      <table cellPadding={6} style={{ borderCollapse: "collapse" }}>
        <tbody>
          {pairs.map((p) => {
            const a = { id: p.a, name: p.a_name, domain: p.a_domain }, b = { id: p.b, name: p.b_name, domain: p.b_domain };
            return (
              <tr key={`${p.a}-${p.b}`} style={{ borderBottom: "1px solid #eee", verticalAlign: "top" }}>
                <td><Co {...a} /><br /><Co {...b} /></td>
                <td>{p.reasons.map((r) => REASON[r]).join(", ")}<br /><small style={{ color: "gray" }}>{p.details.join(" · ")}</small></td>
                <td>
                  <button onClick={() => merge(a, b)}>Keep first</button>{" "}
                  <button onClick={() => merge(b, a)}>Keep second</button>{" "}
                  <button onClick={() => act(post("/api/duplicates/dismiss", { company_a: p.a, company_b: p.b }), "Marked as not a duplicate.")}>Not a duplicate</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Merge history</h3>
      {merges.length === 0 && <p>No merges yet.</p>}
      {merges.map((g) => (
        <div key={g.id} style={{ marginBottom: 6 }}>
          #{g.id} · {new Date(g.merged_at).toLocaleString()} · <Link href={`/companies/${g.merged_id}`}>{g.merged_name}</Link> →{" "}
          <Link href={`/companies/${g.survivor_id}`}>{g.survivor_name}</Link>{" "}
          {g.undone_at
            ? <small style={{ color: "gray" }}>undone {new Date(g.undone_at).toLocaleString()}</small>
            : <button onClick={() => window.confirm(`Undo merge #${g.id}? ${g.merged_name} is restored with the records the merge moved.`)
                                  && act(post(`/api/duplicates/merges/${g.id}/undo`), `Merge #${g.id} undone.`)}>Undo</button>}
        </div>
      ))}
    </main>
  );
}
