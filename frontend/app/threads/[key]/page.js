"use client";
// F5: a conversation as a chat-style timeline: your emails on one side, replies on the other. A notification deep link
// (#in-<id>) scrolls to and highlights that message. The system never replies on its own.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LabelBadge } from "../../inbox/label";
import { CreateOpportunity } from "../../opportunities/shared";
import { Badge, ErrorState, Loading, ago } from "../../ui";

const STATUS_TONE = { sent: "success", failed: "danger", cancelled: "", sending: "warning", queued: "accent", draft: "", approved: "accent" };

export default function Thread() {
  const { key } = useParams();
  const router = useRouter();
  const [t, setT] = useState(null);
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  const [opps, setOpps] = useState([]);

  useEffect(() => {
    fetch(`/api/threads/${encodeURIComponent(key)}`).then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      res.ok ? setT(data) : setError(data.detail);
    });
  }, [key, router]);

  // Deep link from a notification: /threads/<key>#in-<message id>
  useEffect(() => {
    if (!t) return;
    const id = window.location.hash.slice(1);
    setTarget(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [t]);

  const items = t ? [
    ...t.emails.map((e) => ({ ...e, kind: "out", when: e.sent_at || e.created_at })),
    ...t.inbound.map((m) => ({ ...m, kind: "in", when: m.received_at })),
  ].sort((a, b) => new Date(a.when) - new Date(b.when)) : [];
  const first = items[0];
  const companyId = first?.company_id;

  useEffect(() => {
    if (!companyId) return;
    fetch(`/api/companies/${companyId}/overview`).then((r) => r.ok && r.json()).then((o) => o && setOpps(o.opportunities));
  }, [companyId]);

  if (!t) return error ? <ErrorState>{error}</ErrorState> : <Loading what="conversation" />;
  const lastReply = [...items].reverse().find((x) => x.kind === "in" && x.label === "reply");

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href="/inbox">← Inbox</Link> · <Link href="/history">History</Link></p>
      <div className="page-header">
        <div><h1>{first.subject}</h1>
          <div className="sub">{t.gmail_thread ? "Gmail conversation" : "Not yet linked to a Gmail thread"} · {t.emails.length} sent, {t.inbound.length} received.
            The system never replies on its own.</div></div>
      </div>

      <div className="thread-grid">
        <div className="timeline" style={{ minWidth: 0 }}>
          {items.map((x) => {
            const id = `${x.kind}-${x.id}`;
            return (
              <article key={id} id={id} className={`bubble ${x.kind}${target === id ? " target" : ""}`} data-bubble={x.kind}>
                <header className="bubble-head">
                  {x.kind === "out" ? (
                    <span><b>You → {x.to_email}</b> <Badge tone={STATUS_TONE[x.status]}>{x.status}</Badge></span>
                  ) : (
                    <span><b>{x.from_name || x.from_email}</b> <LabelBadge m={x} />
                      {x.attachment_names?.length > 0 && <small style={{ color: "var(--muted)" }}> · 📎 {x.attachment_names.join(", ")}</small>}</span>
                  )}
                  <small style={{ color: "var(--muted)" }} title={x.when && new Date(x.when).toLocaleString()}>{ago(x.when)}</small>
                </header>
                <div className="bubble-subject">{x.subject}</div>
                <pre className="mail-body">{x.kind === "out" ? x.body : x.body_text}</pre>
                <footer style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {x.kind === "out" && <Link className="btn btn-sm" href={`/outbox/${x.id}`}>Open email</Link>}
                  {x.kind === "in" && <Link className="btn btn-sm" href={`/inbox?m=${x.id}`}>Open in inbox</Link>}
                  {x.kind === "in" && x.label === "reply" && x.company_id && (
                    <CreateOpportunity messageId={x.id} suggestedTitle={first.subject.replace(/^(re|aw|fw|wg):\s*/i, "")} />)}
                </footer>
              </article>
            );
          })}
        </div>

        <aside style={{ display: "grid", gap: 12, alignContent: "start" }}>
          <section className="card">
            <b>Company</b>
            <div style={{ marginTop: 4 }}>{companyId ? <Link href={`/companies/${companyId}`}>{first.company_name || "Open company"}</Link> : <span style={{ color: "var(--muted)" }}>not linked</span>}</div>
            {lastReply?.contact_id && <div><small><Link href={`/contacts/${lastReply.contact_id}`}>{lastReply.from_name || lastReply.from_email}</Link></small></div>}
          </section>
          <section className="card">
            <b>Opportunities</b>
            {opps.length === 0 ? <p style={{ margin: "4px 0 0", color: "var(--muted)" }}><small>None for this company yet.</small></p>
              : opps.map((o) => <div key={o.id} style={{ marginTop: 4 }}><Link href={o.link}>{o.title}</Link> <Badge>{o.stage}</Badge></div>)}
          </section>
        </aside>
      </div>
    </main>
  );
}
