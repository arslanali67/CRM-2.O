"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function ComposeList() {
  const router = useRouter();
  const [items, setItems] = useState(null);

  async function load() {
    const res = await fetch("/api/compose-list");
    if (res.status === 401) return router.replace("/login");
    setItems(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function remove(id) {
    await fetch(`/api/compose-list/${id}`, { method: "DELETE" });
    load();
  }

  if (!items) return <p>Loading…</p>;

  return (
    <main style={{ maxWidth: 900 }}>
      <p><Link href="/">← Home</Link> · <Link href="/companies">Leads</Link></p>
      <h1>Compose list</h1>
      <p style={{ color: "gray" }}>
        Leads handed off for outreach, each with the best recipient (careers → personal → generic; blocked and
        unsuitable addresses are never picked). Writing and approving emails arrives with the composer (M10).
      </p>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead><tr><th align="left">Company</th><th align="left">Stage</th><th align="left">Recipient</th><th /></tr></thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.company_id} style={{ borderTop: "1px solid #eee" }}>
              <td><Link href={`/companies/${i.company_id}`}>{i.name}</Link></td>
              <td>{i.stage}</td>
              <td>
                {i.recipient
                  ? <>{i.recipient.email} <mark>{i.recipient.email_class}</mark>{i.recipient.name && ` · ${i.recipient.name}`}</>
                  : <span style={{ color: "crimson" }}>{i.problem}</span>}
              </td>
              <td><button onClick={() => remove(i.company_id)}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p>Empty. Select leads on the <Link href="/companies">Leads</Link> page and add them here.</p>}
    </main>
  );
}
