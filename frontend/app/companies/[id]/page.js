"use client";
// F3: company page. Header card (stage, stats, actions), tabs with counts, contacts table with dialogs.
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "../../activity/describe";
import { LabelBadge } from "../../inbox/label";
import { CreateOpportunity, StageBadge } from "../../opportunities/shared";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { Badge, EmptyState, ErrorState, Loading, Modal, Tabs, ago, useDialog, useToast } from "../../ui";
import { ResearchPanel } from "../research";
import { COMPANY_FIELDS, CONTACT_FIELDS, CompanyFields, EMAIL_CLASSES, LeadStage, STAGES, errorText } from "../shared";

const EMPTY_CONTACT = { ...Object.fromEntries(CONTACT_FIELDS.map(([k]) => [k, ""])), email_class: "auto" };
const fmt = (d) => (d ? new Date(d).toLocaleDateString() : "never");
const CLASS_TONE = { careers: "success", personal: "accent", generic: "", unsuitable: "danger" };

async function call(url, method = "GET", body) {
  const res = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : undefined,
                                 body: body ? JSON.stringify(body) : undefined });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

function ContactDialog({ title, value, onSave, onClose }) {
  const [f, setF] = useState(value);
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); onSave(f); }}>
        {CONTACT_FIELDS.map(([k, label, type]) => (
          <label key={k} className="field"><span>{label}</span>
            <input type={type || "text"} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
        ))}
        <label className="field"><span>Email class</span>
          <select value={f.email_class} onChange={(e) => setF({ ...f, email_class: e.target.value })}>
            <option value="auto">auto (by the rules)</option>{EMAIL_CLASSES.map((x) => <option key={x}>{x}</option>)}
          </select>
          <small className="hint">Careers and personal addresses are preferred; unsuitable ones are never emailed.</small>
        </label>
        <div className="dialog-actions"><button type="button" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn-primary">Save contact</button></div>
      </form>
    </Modal>
  );
}

export default function Company() {
  const dialog = useDialog();
  const toast = useToast();
  const { id } = useParams();
  const router = useRouter();
  const [company, setCompany] = useState(null);
  const [overview, setOverview] = useState(null);
  const [form, setForm] = useState(null);
  const [contactDialog, setContactDialog] = useState(null); // {title, value, id?}
  const [error, setError] = useState("");
  const [timeline, setTimeline] = useState([]);
  const [emailThreads, setEmailThreads] = useState([]);
  const [tab, setTab] = useState("Overview");

  async function load() {
    const r = await call(`/api/companies/${id}`);
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setError(errorText(r.data));
    setCompany(r.data);
    setForm(Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, r.data[k]])));
    call(`/api/companies/${id}/overview`).then((t) => t.ok && setOverview(t.data));
    call(`/api/companies/${id}/activity`).then((t) => t.ok && setTimeline(t.data));
    call(`/api/companies/${id}/emails`).then((t) => t.ok && setEmailThreads(t.data));
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(promise, okMsg) {
    const r = await promise;
    toast(r.ok ? okMsg : errorText(r.data), r.ok ? "" : "error");
    if (r.ok) load();
    return r.ok;
  }

  const saveCompany = (e) => { e.preventDefault(); run(call(`/api/companies/${id}`, "PUT", form), "Company saved."); };
  async function archiveCompany() {
    const archive = !company.archived_at;
    if (archive && !await dialog.confirm(`Archive ${company.name}?`, { body: "It disappears from Leads but nothing is deleted; you can restore it.", confirmLabel: "Archive" })) return;
    run(call(`/api/companies/${id}/${archive ? "archive" : "restore"}`, "POST"), archive ? "Archived." : "Restored.");
  }
  async function saveContact(f) {
    const { id: cid, ...body } = f;
    if (await run(cid ? call(`/api/contacts/${cid}`, "PUT", body) : call(`/api/companies/${id}/contacts`, "POST", body),
                  cid ? "Contact saved." : "Contact added.")) setContactDialog(null);
  }
  const archiveContact = (c) => run(call(`/api/contacts/${c.id}/${c.archived_at ? "restore" : "archive"}`, "POST"), c.archived_at ? "Contact restored." : "Contact archived.");
  async function setStage(stage) {
    let close_reason = "";
    if (stage === "closed") {
      close_reason = (await dialog.prompt(`Close ${company.name}?`, { body: "A reason is required and kept in the history.", required: true, confirmLabel: "Close lead" })) || "";
      if (!close_reason.trim()) return;
    }
    run(call("/api/leads/stage", "POST", { company_ids: [company.id], stage, close_reason }), `Stage set to ${stage.replace("_", " ")}.`);
  }
  async function blockCompany() {
    const reason = await dialog.prompt(`Block ${company.name}?`, { body: "Blocks its domain and all its contacts. Pending emails are cancelled. A reason is required.", required: true, danger: true, confirmLabel: "Block company" });
    if (reason?.trim()) run(call("/api/suppressions", "POST", { kind: "company", company_id: company.id, reason }), "Company blocked.");
  }
  async function addToCompose() {
    const r = await call("/api/compose-list", "POST", { company_ids: [company.id] });
    if (!r.ok) return toast(errorText(r.data), "error");
    toast(r.data.added.length ? "Added to the compose list." : r.data.already.length ? "Already in the compose list."
      : `Not added: ${r.data.refused[0]?.reason || "no usable recipient"}.`, r.data.refused.length ? "error" : "");
  }

  if (!company) return error ? <ErrorState>{error}</ErrorState> : <Loading what="company" />;
  const o = overview;
  const active = company.contacts.filter((c) => !c.archived_at);
  const tabs = ["Overview", `Contacts (${active.length})`, `Emails & replies${o ? ` (${o.sent + o.replies})` : ""}`, "Notes",
                `Tasks${o ? ` (${o.open_tasks})` : ""}`, "Timeline", `Opportunities${o ? ` (${o.opportunities.length})` : ""}`, "Research"];
  const current = tabs.find((t) => t.startsWith(tab)) || tabs[0];

  return (
    <main>
      <p style={{ marginBottom: 8 }}><Link href="/companies">← Leads</Link></p>

      <section className="card company-head">
        <div style={{ minWidth: 0 }}>
          <h1 style={{ margin: 0 }}>{company.name}</h1>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
            <LeadStage stage={company.stage} />
            {company.domain && <a href={`https://${company.domain}`} target="_blank" rel="noopener noreferrer">{company.domain} ↗</a>}
            {o?.blocked && <Badge tone="danger">blocked</Badge>}
            {company.archived_at && <Badge tone="warning">archived</Badge>}
            {company.close_reason && <small style={{ color: "var(--muted)" }}>closed: {company.close_reason}</small>}
          </div>
          {o && (
            <div className="mini-stats">
              <span><b>{o.contacts}</b> contacts</span><span><b>{o.sent}</b> sent</span><span><b>{o.replies}</b> replies</span>
              <span><b>{o.open_tasks}</b> open tasks</span><span>last emailed <b>{fmt(o.last_emailed_at)}</b></span>
            </div>
          )}
        </div>
        <div className="head-actions">
          <select aria-label="Stage" value={company.stage} onChange={(e) => setStage(e.target.value)}>
            {STAGES.map((s) => <option key={s} value={s}>Stage: {s.replace("_", " ")}</option>)}
          </select>
          <button className="btn-primary" onClick={addToCompose}>Add to compose list</button>
          {!company.block && <button onClick={blockCompany}>Block</button>}
          <button onClick={archiveCompany}>{company.archived_at ? "Restore" : "Archive"}</button>
        </div>
      </section>

      <div style={{ marginTop: 16 }}>
        <Tabs tabs={tabs} value={current} onChange={(t) => setTab(t.replace(/ \(\d+\)$/, ""))} />
      </div>

      {tab === "Overview" && (
        <div className="panel-grid">
          <section className="card">
            <h3 style={{ marginTop: 0 }}>Details</h3>
            <form onSubmit={saveCompany}>
              <CompanyFields form={form} setForm={setForm} />
              <button type="submit" className="btn-primary">Save company</button>
            </form>
          </section>
          <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
            {o?.last_reply && (
              <section className="card">
                <h3 style={{ marginTop: 0 }}>Latest reply</h3>
                <Link href={o.last_reply.link}><b>{o.last_reply.subject}</b></Link> <LabelBadge m={o.last_reply} />
                <div><small style={{ color: "var(--muted)" }}>{o.last_reply.from_name || o.last_reply.from_email} · {ago(o.last_reply.received_at)}
                  {o.last_reply.ai_label && ` · AI: ${o.last_reply.ai_label.replaceAll("_", " ")}`}</small></div>
                {o.last_reply.ai_summary && <p style={{ margin: "8px 0 0" }}>{o.last_reply.ai_summary}</p>}
              </section>
            )}
            {company.block && (
              <section className="card" style={{ borderColor: "var(--danger)", background: "var(--danger-bg)" }}>
                <b style={{ color: "var(--danger)" }}>Blocked</b>
                <p style={{ margin: "4px 0" }}>{company.block.reason}</p>
                <Link href="/do-not-contact">Manage on Do-not-contact</Link>
              </section>
            )}
            <section className="card">
              <h3 style={{ marginTop: 0 }}>Source</h3>
              <dl className="dl">
                <dt>From</dt><dd>{company.source === "csv_import" ? "CSV import" : "added by hand"}</dd>
                {company.source_detail?.file && <><dt>File</dt><dd>{company.source_detail.file}, row {company.source_detail.row}</dd></>}
                <dt>Added</dt><dd>{new Date(company.created_at).toLocaleString()}</dd>
              </dl>
            </section>
          </div>
        </div>
      )}

      {tab === "Contacts" && (
        <>
          <p><button className="btn-primary" onClick={() => setContactDialog({ title: "Add contact", value: EMPTY_CONTACT })}>Add contact</button></p>
          {company.contacts.length === 0 ? <EmptyState title="No contacts yet">Add the person or address you want to write to.</EmptyState> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Class</th><th /></tr></thead>
                <tbody>
                  {company.contacts.map((c) => (
                    <tr key={c.id} style={{ opacity: c.archived_at ? 0.55 : 1 }}>
                      <td><Link href={`/contacts/${c.id}`}><b>{c.name || "—"}</b></Link>{c.archived_at && <Badge>archived</Badge>}</td>
                      <td>{c.email || "—"}{c.suppressed && <> <Badge tone="danger">blocked</Badge></>}</td>
                      <td>{c.role || "—"}</td>
                      <td>{c.email_class ? <Badge tone={CLASS_TONE[c.email_class]}>{c.email_class}{c.email_class_manual ? " (manual)" : ""}</Badge> : "—"}</td>
                      <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                        {!c.archived_at && <button className="btn-sm" onClick={() => setContactDialog({ title: `Edit ${c.name || c.email}`,
                          value: { id: c.id, ...Object.fromEntries(CONTACT_FIELDS.map(([k]) => [k, c[k]])), email_class: c.email_class_manual ? c.email_class : "auto" } })}>Edit</button>}{" "}
                        <button className="btn-sm btn-ghost" onClick={() => archiveContact(c)}>{c.archived_at ? "Restore" : "Archive"}</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "Emails & replies" && (
        emailThreads.length === 0 ? <EmptyState title="No emails yet">Drafts, sent emails and replies for this company appear here.</EmptyState> : (
          <div style={{ display: "grid", gap: 12 }}>
            {emailThreads.map((t) => (
              <section key={t.thread_key} className="card">
                <Link href={`/threads/${t.thread_key}`}><small>Conversation · {t.emails.length} sent, {t.inbound.length} received</small></Link>
                {t.emails.map((e) => (
                  <div key={`o${e.id}`} style={{ marginTop: 6 }}>→ <Link href={`/outbox/${e.id}`}>{e.subject}</Link>{" "}
                    <small style={{ color: "var(--muted)" }}>to {e.to_email} · {e.status}{e.sent_at && ` ${fmt(e.sent_at)}`}</small></div>
                ))}
                {t.inbound.map((m) => (
                  <div key={`i${m.id}`} style={{ marginTop: 6 }}>← <Link href={`/threads/${t.thread_key}#in-${m.id}`}>{m.subject}</Link> <LabelBadge m={m} />{" "}
                    <small style={{ color: "var(--muted)" }}>from {m.from_email}{m.received_at && ` ${fmt(m.received_at)}`}</small></div>
                ))}
              </section>
            ))}
          </div>
        )
      )}

      {tab === "Notes" && <NotesPanel entityType="company" entityId={company.id} />}
      {tab === "Tasks" && <TasksPanel entityType="company" entityId={company.id} />}
      {tab === "Timeline" && <EventList events={timeline} />}
      {tab === "Research" && <ResearchPanel companyId={company.id} />}
      {tab === "Opportunities" && (
        <>
          {o?.opportunities?.length === 0 && <EmptyState title="No opportunities yet">Create one from a reply, or by hand below.</EmptyState>}
          {o?.opportunities?.map((op) => (
            <div key={op.id} style={{ padding: "6px 0" }}><Link href={op.link}><b>{op.title}</b></Link> <StageBadge stage={op.stage} />
              <small style={{ color: "var(--muted)" }}> · since {fmt(op.stage_changed_at)}</small></div>
          ))}
          {o?.interviews?.length > 0 && <>
            <h3>Interviews</h3>
            {o.interviews.map((i) => (
              <div key={i.id}><Link href={i.link}>{i.title}</Link>{" "}
                <small style={{ color: "var(--muted)" }}>· {new Date(i.starts_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })} · {i.status}</small></div>
            ))}
          </>}
          <p style={{ marginTop: 12 }}><CreateOpportunity companyId={company.id} label="New opportunity" /></p>
        </>
      )}

      {contactDialog && <ContactDialog title={contactDialog.title} value={contactDialog.value} onSave={saveContact} onClose={() => setContactDialog(null)} />}
    </main>
  );
}
