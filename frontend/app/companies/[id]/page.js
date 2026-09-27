"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "../../activity/describe";
import { COMPANY_FIELDS, CONTACT_FIELDS, EMAIL_CLASSES, errorText } from "../shared";

const EMPTY_CONTACT = Object.fromEntries(CONTACT_FIELDS.map(([k]) => [k, ""]));
const full = { display: "block", width: "100%" };

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
  const [form, setForm] = useState(null);
  const [newContact, setNewContact] = useState(EMPTY_CONTACT);
  const [editing, setEditing] = useState(null); // {id, ...fields}
  const [msg, setMsg] = useState("");
  const [timeline, setTimeline] = useState([]);

  async function load() {
    const r = await call(`/api/companies/${id}`, "GET");
    if (r.status === 401) return router.replace("/login");
    if (!r.ok) return setMsg(errorText(r.data));
    setCompany(r.data);
    call(`/api/companies/${id}/activity`, "GET").then((t) => t.ok && setTimeline(t.data));
    setForm(Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, r.data[k]])));
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
  const blockCompany = () => {
    const reason = window.prompt(`Why block ${company.name}? Blocks its domain and all its contacts.`);
    if (reason?.trim()) run(call("/api/suppressions", "POST", { kind: "company", company_id: company.id, reason }), "Company blocked.");
  };

  if (!company) return <p>{msg || "Loading…"}</p>;

  return (
    <main>
      <p><Link href="/companies">← Companies</Link></p>
      <h1>{company.name} {company.archived_at && <small>(archived)</small>}</h1>
      <p style={{ color: "gray" }}>
        Source: {company.source}
        {company.source_detail?.file && ` (${company.source_detail.file}, row ${company.source_detail.row})`}
        {" · "}created {new Date(company.created_at).toLocaleString()}
      </p>
      {company.block ? (
        <p style={{ color: "crimson" }}>
          Blocked: {company.block.reason} (<Link href="/do-not-contact">manage on Do-not-contact</Link>)
        </p>
      ) : (
        <p><button onClick={blockCompany}>Block company</button></p>
      )}
      {msg && <p role="status">{msg}</p>}

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

      <h2 style={{ marginTop: 32 }}>Contacts</h2>
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
                <strong>{c.name || c.email}</strong>{c.role && ` · ${c.role}`}
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

      <h2 style={{ marginTop: 32 }}>Timeline</h2>
      <EventList events={timeline} />
    </main>
  );
}
