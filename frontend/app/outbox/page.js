"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TABS = ["draft", "queued", "sending", "sent", "failed", "cancelled"];

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
              <td>{e.subject}{e.cancel_reason && <div style={{ color: "crimson" }}><small>{e.cancel_reason}</small></div>}</td>
              <td><small>{new Date(e.sent_at || e.approved_at || e.created_at).toLocaleString()}</small></td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.emails.length === 0 && <p>No {status} emails.</p>}
    </main>
  );
}
