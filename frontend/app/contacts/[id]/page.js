"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "../../activity/describe";
import { LabelBadge } from "../../inbox/label";
import { NotesPanel, TasksPanel } from "../../tasks/panels";

export default function Contact() {
  const { id } = useParams();
  const router = useRouter();
  const [d, setD] = useState(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    fetch(`/api/contacts/${id}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      res.ok ? setD(data) : setMsg(data.detail);
    });
  }, [id, router]);

  if (!d) return <p>{msg || "Loading…"}</p>;
  const c = d.contact;

  return (
    <main style={{ maxWidth: 800 }}>
      <p><Link href={d.company.link}>← {d.company.name}</Link></p>
      <h1 style={{ marginBottom: 4 }}>{c.name || c.email}</h1>
      <p style={{ margin: "4px 0" }}>
        {c.role && `${c.role} · `}{c.email || "no email"}{c.email_class && <> <mark>{c.email_class}{c.email_class_manual ? " (manual)" : ""}</mark></>}
        {d.suppressed && <> <mark style={{ background: "var(--danger)", color: "var(--surface)" }}>blocked</mark></>}
        {c.archived_at && " · archived"}
      </p>
      <p style={{ color: "var(--muted)" }}><small>
        {c.phone && `${c.phone} · `}{c.linkedin_url && <>{c.linkedin_url} · </>}source: {c.source}
        {c.source_detail?.file && ` (${c.source_detail.file}, row ${c.source_detail.row})`} · edit on the <Link href={d.company.link}>company page</Link>
      </small></p>

      <h2>Emails to {c.name || "this contact"} ({d.emails.length})</h2>
      {d.emails.length === 0 && <p>None.</p>}
      {d.emails.map((e) => (
        <div key={e.id}><Link href={e.link}>{e.subject}</Link> <small>· {e.status}{e.sent_at && ` ${new Date(e.sent_at).toLocaleDateString()}`}</small></div>
      ))}

      <h2>Replies ({d.replies.length})</h2>
      {d.replies.length === 0 && <p>None.</p>}
      {d.replies.map((m) => (
        <div key={m.id} style={{ marginBottom: 4 }}>
          <Link href={m.link}>{m.subject}</Link> <LabelBadge m={m} />
          {m.ai_label && <small> · AI: {m.ai_label.replaceAll("_", " ")}</small>}
          <small style={{ color: "var(--muted)" }}> · {m.received_at && new Date(m.received_at).toLocaleDateString()}</small>
          {m.ai_summary && <div><small style={{ color: "var(--muted)" }}>{m.ai_summary}</small></div>}
        </div>
      ))}

      <TasksPanel entityType="contact" entityId={c.id} />
      <NotesPanel entityType="contact" entityId={c.id} />

      <h2 style={{ marginTop: 32 }}>Timeline</h2>
      <EventList events={d.timeline} />
    </main>
  );
}
