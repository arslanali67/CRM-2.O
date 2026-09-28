"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "../../activity/describe";
import { LabelBadge } from "../../inbox/label";
import { NotesPanel, TasksPanel } from "../../tasks/panels";
import { CreateOpportunity, StageBadge } from "../../opportunities/shared";
import { COMPANY_FIELDS, CONTACT_FIELDS, EMAIL_CLASSES, STAGES, errorText } from "../shared";

const EMPTY_CONTACT = Object.fromEntries(CONTACT_FIELDS.map(([k]) => [k, ""]));
const full = { display: "block", width: "100%" };
const TABS = ["Overview", "Contacts", "Emails & replies", "Notes", "Tasks", "Timeline", "Opportunity"];
const fmt = (d) => (d ? new Date(d).toLocaleDateString() : "never");

async function call(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  return { ok: res.ok, status: res.status, data: await res.json() };
}

export default function Company() {
  const { id } = useParams();
  const router = useRouter();
  const [company, setCompany] = useState(null);
  const [overview, setOverview] = useState(null);
  const [form, setForm] = useState(null);
  const [newContact, setNewContact] = useState(EMPTY_CONTACT);
  const [editing, setEditing] = useState(null); // {id, ...fields}
  const [msg, setMsg] = useState("");
  const [timeline, setTimeline] = useState([]);
  const [emailThreads, setEmailThreads] = useState([]);
  const [tab, setTab] = useState("Overview");

  async function load() {
    const r = await call(`/api/companies/${id}`, "GET");
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setMsg(errorText(r.data));
    setCompany(r.data);
    setForm(Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, r.data[k]])));
    call(`/api/companies/${id}/overview`, "GET").then((t) => t.ok && setOverview(t.data));
    call(`/api/companies/${id}/activity`, "GET").then((t) => t.ok && setTimeline(t.data));
    call(`/api/companies/${id}/emails`, "GET").then((t) => t.ok && setEmailThreads(t.data));
  }
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run(promise, okMsg) {
    const r = await promise;
    setMsg(r.ok ? okMsg : errorText(r.data));
    if (r.ok) load();
    return r.ok;
  }

  const saveCompany = (e) => { e.preventDefault(); run(call(`/api/companies/${id}`, "PUT", form), "Company saved."); };
  const archiveCompany = (archive) => run(call(`/api/companies/${id}/${archive ? "archive" : "restore"}`, "POST"), archive ? "Archived." : "Restored.");
  const addContact = async (e) => {
    e.preventDefault();
    if (await run(call(`/api/companies/${id}/contacts`, "POST", newContact), "Contact added.")) setNewContact(EMPTY_CONTACT);
  };
  const saveContact = async (e) => {
    e.preventDefault();
    const { id: cid, ...body } = editing;
    if (await run(call(`/api/contacts/${cid}`, "PUT", body), "Contact saved.")) setEditing(null);
  };
  const archiveContact = (cid, archive) => run(call(`/api/contacts/${cid}/${archive ? "archive" : "restore"}`, "POST"), archive ? "Contact archived." : "Contact restored.");
  const setStage = (stage) => {
    let close_reason = "";
    if (stage === "closed") {
      close_reason = window.prompt(`Why close ${company.name}?`) || "";
      if (!close_reason.trim()) return;
    }
    run(call("/api/leads/stage", "POST", { company_ids: [company.id], stage, close_reason }), `Stage set to ${stage}.`);
  };
  const blockCompany = () => {
    const reason = window.prompt(`Why block ${company.name}? Blocks its domain and all its contacts.`);
    if (reason?.trim()) run(call("/api/suppressions", "POST", { kind: "company", company_id: company.id, reason }), "Company blocked.");
  };

  if (!company) return <p>{msg || "Loading…"}</p>;
  const o = overview;

  return (
    <main>
      <p><Link href="/companies">← Leads</Link></p>
      <h1 style={{ marginBottom: 4 }}>{company.name} {company.archived_at && <small>(archived)</small>}</h1>

      {/* Summary header */}
      <p style={{ margin: "4px 0" }}>
        <b>{company.stage.replace("_", " ")}</b>{company.domain && ` · ${company.domain}`}
        {o?.blocked && <> · <mark style={{ background: "crimson", color: "white" }}>blocked</mark></>}
        {o && <> · last emailed {fmt(o.last_emailed_at)}</>}
      </p>
      {o && (
        <p style={{ color: "gray", margin: "4px 0" }}><small>
          {o.contacts} contacts · {o.sent} sent · {o.replies} replies · {o.open_tasks} open tasks
          {o.last_reply && <> · last reply {fmt(o.last_reply.received_at)} from {o.last_reply.from_name || o.last_reply.from_email}
            {o.last_reply.ai_label && ` (AI: ${o.last_reply.ai_label.replaceAll("_", " ")})`}</>}
        </small></p>
      )}
      {msg && <p role="status">{msg}</p>}

      <nav style={{ display: "flex", gap: 4, flexWrap: "wrap", borderBottom: "1px solid #ddd", margin: "12px 0" }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  style={{ border: "none", borderBottom: t === tab ? "3px solid steelblue" : "3px solid transparent",
                           background: "none", padding: "6px 10px", fontWeight: t === tab ? "bold" : "normal", cursor: "pointer" }}>
            {t}
          </button>
        ))}
      </nav>

      {tab === "Overview" && (
        <>
          {o?.last_reply && (
            <div style={{ border: "1px solid #ddd", padding: 8, marginBottom: 12 }}>
              <b>Latest reply</b> <LabelBadge m={o.last_reply} /> · <Link href={o.last_reply.link}>{o.last_reply.subject}</Link>
              {o.last_reply.ai_summary && <div><small>{o.last_reply.ai_summary}</small></div>}
            </div>
          )}
          <p style={{ color: "gray" }}>
            Source: {company.source}
            {company.source_detail?.file && ` (${company.source_detail.file}, row ${company.source_detail.row})`}
            {" · "}created {new Date(company.created_at).toLocaleString()}
          </p>
          <p>
            <label>Stage{" "}
              <select value={company.stage} onChange={(e) => setStage(e.target.value)}>
                {STAGES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
            {company.close_reason && <small style={{ color: "gray" }}> closed: {company.close_reason}</small>}
          </p>
          {company.block ? (
            <p style={{ color: "crimson" }}>Blocked: {company.block.reason} (<Link href="/do-not-contact">manage on Do-not-contact</Link>)</p>
          ) : (
            <p><button onClick={blockCompany}>Block company</button></p>
          )}
          <form onSubmit={saveCompany} style={{ display: "grid", gap: 8 }}>
            {COMPANY_FIELDS.map(([k, label, type]) => (
              <label key={k}>{label}
                {type === "textarea"
                  ? <textarea rows={3} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={full} />
                  : <input type={type || "text"} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={full} />}
              </label>
            ))}
            <div style={{ display: "flex", gap: 8 }}>
              <button type="submit">Save company</button>
              <button type="button" onClick={() => archiveCompany(!company.archived_at)}>
                {company.archived_at ? "Restore company" : "Archive company"}
              </button>
            </div>
          </form>
        </>
      )}

      {tab === "Contacts" && (
        <>
          <ul style={{ paddingLeft: 16 }}>
            {company.contacts.map((c) => (
              <li key={c.id} style={{ marginBottom: 12, opacity: c.archived_at ? 0.5 : 1 }}>
                {editing?.id === c.id ? (
                  <form onSubmit={saveContact} style={{ display: "grid", gap: 6 }}>
                    {CONTACT_FIELDS.map(([k, label, type]) => (
                      <input key={k} type={type || "text"} placeholder={label} aria-label={label} value={editing[k]}
                             onChange={(e) => setEditing({ ...editing, [k]: e.target.value })} />
                    ))}
                    <label>Email class
                      <select value={editing.email_class} onChange={(e) => setEditing({ ...editing, email_class: e.target.value })}>
                        <option value="auto">auto (rules)</option>
                        {EMAIL_CLASSES.map((x) => <option key={x}>{x}</option>)}
                      </select>
                    </label>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button type="submit">Save</button>
                      <button type="button" onClick={() => setEditing(null)}>Cancel</button>
                    </div>
                  </form>
                ) : (
                  <>
                    <Link href={`/contacts/${c.id}`}><strong>{c.name || c.email}</strong></Link>{c.role && ` · ${c.role}`}
                    {c.email && <> · {c.email} <mark>{c.email_class}{c.email_class_manual ? " (manual)" : ""}</mark></>}
                    {c.suppressed && <> <mark style={{ background: "crimson", color: "white" }}>blocked</mark></>}
                    {c.archived_at && " · archived"}{" "}
                    {!c.archived_at && (
                      <button onClick={() => setEditing({
                        id: c.id,
                        ...Object.fromEntries(CONTACT_FIELDS.map(([k]) => [k, c[k]])),
                        email_class: c.email_class_manual ? c.email_class : "auto",
                      })}>Edit</button>
                    )}{" "}
                    <button onClick={() => archiveContact(c.id, !c.archived_at)}>{c.archived_at ? "Restore" : "Archive"}</button>
                  </>
                )}
              </li>
            ))}
          </ul>
          {company.contacts.length === 0 && <p>No contacts yet.</p>}
          <h3>Add contact</h3>
          <form onSubmit={addContact} style={{ display: "grid", gap: 6 }}>
            {CONTACT_FIELDS.map(([k, label, type]) => (
              <input key={k} type={type || "text"} placeholder={label} aria-label={label} value={newContact[k]}
                     onChange={(e) => setNewContact({ ...newContact, [k]: e.target.value })} />
            ))}
            <button type="submit">Add contact</button>
          </form>
        </>
      )}

      {tab === "Emails & replies" && (
        <>
          {emailThreads.length === 0 && <p>No emails yet.</p>}
          {emailThreads.map((t) => (
            <div key={t.thread_key} style={{ borderLeft: "3px solid #ddd", paddingLeft: 8, margin: "8px 0" }}>
              <Link href={`/threads/${t.thread_key}`}><small>thread ({t.emails.length} sent, {t.inbound.length} received)</small></Link>
              {t.emails.map((e) => (
                <div key={`o${e.id}`}>
                  <Link href={`/outbox/${e.id}`}>{e.subject}</Link> <small>→ {e.to_email} · {e.status}
                    {e.sent_at && ` ${new Date(e.sent_at).toLocaleDateString()}`}</small>
                </div>
              ))}
              {t.inbound.map((m) => (
                <div key={`i${m.id}`}>
                  <Link href={`/threads/${t.thread_key}#in-${m.id}`}>{m.subject}</Link> <LabelBadge m={m} /> <small>← {m.from_email}
                    {m.received_at && ` ${new Date(m.received_at).toLocaleDateString()}`}</small>
                </div>
              ))}
            </div>
          ))}
        </>
      )}

      {tab === "Notes" && <NotesPanel entityType="company" entityId={company.id} />}
      {tab === "Tasks" && <TasksPanel entityType="company" entityId={company.id} />}
      {tab === "Timeline" && <EventList events={timeline} />}
      {tab === "Opportunity" && (
        <>
          {o?.opportunities?.length === 0 && <p>No opportunities yet. Create one from a reply, or manually:</p>}
          {o?.opportunities?.map((op) => (
            <div key={op.id}><Link href={op.link}><b>{op.title}</b></Link> <StageBadge stage={op.stage} />
              <small style={{ color: "gray" }}> · since {new Date(op.stage_changed_at).toLocaleDateString()}</small></div>
          ))}
          <p><CreateOpportunity companyId={company.id} label="New opportunity (manual)" /></p>
        </>
      )}
    </main>
  );
}
