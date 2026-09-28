"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LabelBadge } from "../../inbox/label";

export default function Thread() {
  const { key } = useParams();
  const router = useRouter();
  const [t, setT] = useState(null);
  const [msg, setMsg] = useState("");

  const [target, setTarget] = useState("");

  useEffect(() => {
    fetch(`/api/threads/${encodeURIComponent(key)}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      res.ok ? setT(data) : setMsg(data.detail);
    });
  }, [key, router]);

  // Deep link from a notification: /threads/<key>#in-<message id> scrolls to and highlights that message.
  useEffect(() => {
    if (!t) return;
    const id = window.location.hash.slice(1);
    setTarget(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [t]);

  if (!t) return <p>{msg || "Loading…"}</p>;
  // One chronological conversation: our emails and inbound messages (M14).
  const items = [
    ...t.emails.map((e) => ({ ...e, kind: "out", when: e.sent_at || e.created_at })),
    ...t.inbound.map((m) => ({ ...m, kind: "in", when: m.received_at })),
  ].sort((a, b) => new Date(a.when) - new Date(b.when));
  const first = items[0];
  const companyId = first.company_id;

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href="/history">← History</Link> · <Link href="/inbox">Inbox</Link>
        {companyId && <> · <Link href={`/companies/${companyId}`}>{first.company_name || "company"}</Link></>}</p>
      <h1>{first.subject}</h1>
      <p style={{ color: "gray" }}><small>
        {t.gmail_thread ? `Gmail thread ${t.thread_key}` : "Not yet linked to a Gmail thread"} · {t.emails.length} sent,{" "}
        {t.inbound.length} received. The system never replies on its own.
      </small></p>
      {items.map((x) => (
        <article key={`${x.kind}-${x.id}`} id={`${x.kind}-${x.id}`}
                 style={{ border: "1px solid #ddd", borderLeft: `4px solid ${x.kind === "in" ? "seagreen" : "steelblue"}`, padding: 12, marginBottom: 12,
                          outline: target === `${x.kind}-${x.id}` ? "3px solid gold" : "none" }}>
          {x.kind === "out" ? (
            <div><b>You → {x.to_email}</b> · <Link href={`/outbox/${x.id}`}>{x.status}</Link>
              {x.sent_at && <> · {new Date(x.sent_at).toLocaleString()}</>}</div>
          ) : (
            <div><b>{x.from_name || x.from_email} → you</b> <LabelBadge m={x} /> · {x.when && new Date(x.when).toLocaleString()}
              {x.attachment_names?.length > 0 && <small> · attachments: {x.attachment_names.join(", ")}</small>}</div>
          )}
          <div><b>Subject:</b> {x.subject}</div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{x.kind === "out" ? x.body : x.body_text}</pre>
        </article>
      ))}
    </main>
  );
}
