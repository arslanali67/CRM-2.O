"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function Thread() {
  const { key } = useParams();
  const router = useRouter();
  const [t, setT] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetch(`/api/threads/${encodeURIComponent(key)}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      res.ok ? setT(data) : setMsg(data.detail);
    });
  }, [key, router]);

  if (!t) return <p>{msg || "Loading…"}</p>;
  const first = t.emails[0];

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/history">← History</Link>{first.company_id && <> · <Link href={`/companies/${first.company_id}`}>{first.company_name}</Link></>}</p>
      <h1>{first.subject}</h1>
      <p style={{ color: "gray" }}><small>
        {t.gmail_thread ? `Gmail thread ${t.thread_key}` : "Not yet linked to a Gmail thread"} · {t.emails.length} message(s).
        Replies will appear here once inbox sync arrives (M14).
      </small></p>
      {t.emails.map((e) => (
        <article key={e.id} style={{ border: "1px solid #ddd", padding: 12, marginBottom: 12 }}>
          <div><b>To:</b> {e.to_email} · <Link href={`/outbox/${e.id}`}>{e.status}</Link>
            {e.sent_at && <> · sent {new Date(e.sent_at).toLocaleString()}</>}</div>
          <div><b>Subject:</b> {e.subject}</div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{e.body}</pre>
        </article>
      ))}
    </main>
  );
}
