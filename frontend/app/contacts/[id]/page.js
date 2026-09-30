"use client";
// F3: contact page. Header card, then emails, replies, tasks, notes and timeline.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "../../activity/describe";
import { LabelBadge } from "../../inbox/label";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { Badge, EmptyState, ErrorState, Loading, ago } from "../../ui";

const CLASS_TONE = { careers: "success", personal: "accent", generic: "", unsuitable: "danger" };

export default function Contact() {
  const { id } = useParams();
  const router = useRouter();
  const [d, setD] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch(`/api/contacts/${id}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      res.ok ? setD(data) : setError(data.detail);
    });
  }, [id, router]);

  if (!d) return error ? <ErrorState>{error}</ErrorState> : <Loading what="contact" />;
  const c = d.contact;

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href={d.company.link}>← {d.company.name}</Link></p>
      <section className="card company-head">
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0 }}>{c.name || c.email}</h1>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
            {c.role && <span>{c.role}</span>}
            <span>{c.email || "no email"}</span>
            {c.email_class && <Badge tone={CLASS_TONE[c.email_class]}>{c.email_class}{c.email_class_manual ? " (manual)" : ""}</Badge>}
            {d.suppressed && <Badge tone="danger">blocked</Badge>}
            {c.archived_at && <Badge tone="warning">archived</Badge>}
          </div>
          <div className="mini-stats">
            <span>at <Link href={d.company.link}><b>{d.company.name}</b></Link></span>
            {c.phone && <span>{c.phone}</span>}
            {c.linkedin_url && <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer">LinkedIn ↗</a>}
            <span><b>{d.emails.length}</b> emails · <b>{d.replies.length}</b> replies</span>
            <span>source: {c.source === "csv_import" ? `CSV${c.source_detail?.file ? ` (${c.source_detail.file}, row ${c.source_detail.row})` : ""}` : "added by hand"}</span>
          </div>
        </div>
        <div className="head-actions"><Link className="btn" href={d.company.link}>Edit on company page</Link></div>
      </section>

      <div className="panel-grid" style={{ marginTop: 16 }}>
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Emails to {c.name || "this contact"}</h3>
          {d.emails.length === 0 && <p style={{ color: "var(--muted)", margin: 0 }}>None yet.</p>}
          {d.emails.map((e) => (
            <div key={e.id} style={{ padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <Link href={e.link}>{e.subject}</Link>
              <div><small style={{ color: "var(--muted)" }}>{e.status}{e.sent_at && ` · ${new Date(e.sent_at).toLocaleDateString()}`}</small></div>
            </div>
          ))}
        </section>
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Replies</h3>
          {d.replies.length === 0 && <p style={{ color: "var(--muted)", margin: 0 }}>None yet.</p>}
          {d.replies.map((m) => (
            <div key={m.id} style={{ padding: "6px 0", borderTop: "1px solid var(--border)" }}>
              <Link href={m.link}>{m.subject}</Link> <LabelBadge m={m} />{m.ai_label && <> <Badge tone="accent">AI: {m.ai_label.replaceAll("_", " ")}</Badge></>}
              <div><small style={{ color: "var(--muted)" }}>{ago(m.received_at)}</small></div>
              {m.ai_summary && <small style={{ color: "var(--muted)" }}>{m.ai_summary}</small>}
            </div>
          ))}
        </section>
      </div>

      <div className="panel-grid" style={{ marginTop: 16 }}>
        <section className="card"><TasksPanel entityType="contact" entityId={c.id} /></section>
        <section className="card"><NotesPanel entityType="contact" entityId={c.id} /></section>
      </div>

      <section className="card" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Timeline</h3>
        {d.timeline.length ? <EventList events={d.timeline} /> : <EmptyState title="No activity yet" />}
      </section>
    </main>
  );
}
