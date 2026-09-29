"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { COMPANY_FIELDS, STAGES, errorText } from "./shared";
import { useDialog } from "../ui";

const EMPTY_COMPANY = Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, ""]));
const NO_FILTERS = { q: "", stage: "", country: "", city: "", industry: "", source: "", has_email: "", has_careers: "",
                     replied: "", ai_label: "", template_id: "", emailed_from: "", emailed_to: "", replied_from: "",
                     replied_to: "", added_from: "", added_to: "", include_blocked: false, archived: false };
const AI_LABELS = ["interview_request", "interested", "needs_info", "scheduling", "application_redirect", "referral",
                   "keep_on_file", "not_hiring", "rejection", "offer", "unsubscribe_request", "other"];

export default function Leads() {
  const dialog = useDialog();
  const router = useRouter();
  const [filters, setFilters] = useState(NO_FILTERS);
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [bulkStage, setBulkStage] = useState("qualified");
  const [form, setForm] = useState(EMPTY_COMPANY);
  const [msg, setMsg] = useState("");

  async function load(f = filters) {
    const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v !== false));
    const res = await fetch(`/api/leads?${q}`);
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
    setSelected(new Set());
  }
  const [templates, setTemplates] = useState([]);
  useEffect(() => {
    load();
    fetch("/api/templates").then((r) => r.ok && r.json()).then((t) => t && setTemplates(t));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setFilter = (k, v) => setFilters({ ...filters, [k]: v });
  const applyFilters = (e) => { e.preventDefault(); load(); };
  const clearFilters = () => { setFilters(NO_FILTERS); load(NO_FILTERS); };

  const leads = data?.leads || [];
  const allSelected = leads.length > 0 && leads.every((l) => selected.has(l.id));
  const toggle = (id) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(leads.map((l) => l.id)));

  async function post(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return { ok: res.ok, data: await res.json() };
  }

  async function applyStage() {
    let close_reason = "";
    if (bulkStage === "closed") {
      close_reason = (await dialog.prompt(`Close ${selected.size} lead(s)?`, { body: "A reason is required and kept in the history.", required: true, confirmLabel: "Close leads" })) || "";
      if (!close_reason.trim()) return;
    }
    const r = await post("/api/leads/stage", { company_ids: [...selected], stage: bulkStage, close_reason });
    setMsg(r.ok ? `${r.data.changed} lead(s) moved to ${bulkStage}.` : errorText(r.data));
    if (r.ok) load();
  }

  async function handOff() {
    const r = await post("/api/compose-list", { company_ids: [...selected] });
    if (!r.ok) return setMsg(errorText(r.data));
    const refused = r.data.refused.map((x) => `${x.name} (${x.reason})`).join(", ");
    setMsg(`${r.data.added.length} added to the compose list` +
      (r.data.already.length ? `, ${r.data.already.length} already there` : "") +
      (refused ? `. Not added: ${refused}.` : "."));
    load();
  }

  async function addCompany(e) {
    e.preventDefault();
    const r = await post("/api/companies", form);
    setMsg(r.ok ? "Company added." : errorText(r.data));
    if (r.ok) { setForm(EMPTY_COMPANY); load(); }
  }

  if (!data) return <p>Loading…</p>;

  const input = (k, placeholder) => (
    <input placeholder={placeholder} aria-label={placeholder} value={filters[k]} onChange={(e) => setFilter(k, e.target.value)} />
  );
  const yesNo = (k, label) => (
    <select aria-label={label} value={filters[k]} onChange={(e) => setFilter(k, e.target.value)}>
      <option value="">{label}: any</option><option value="true">{label}: yes</option><option value="false">{label}: no</option>
    </select>
  );

  return (
    <main style={{ maxWidth: 1000 }}>
      <p><Link href="/">← Home</Link> · <Link href="/compose">Compose list</Link> · <Link href="/duplicates">Duplicates</Link></p>
      <h1>Leads</h1>

      <form onSubmit={applyFilters} style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
        <select aria-label="Stage" value={filters.stage} onChange={(e) => setFilter("stage", e.target.value)}>
          <option value="">Stage: any</option>
          {STAGES.map((s) => <option key={s}>{s}</option>)}
        </select>
        {input("country", "Country")}
        {input("city", "City")}
        {input("industry", "Industry contains")}
        <select aria-label="Source" value={filters.source} onChange={(e) => setFilter("source", e.target.value)}>
          <option value="">Source: any</option><option value="manual">manual</option><option value="csv_import">csv_import</option>
        </select>
        {yesNo("has_email", "Usable email")}
        {yesNo("has_careers", "Careers email")}
        <label><input type="checkbox" checked={filters.include_blocked} onChange={(e) => setFilter("include_blocked", e.target.checked)} /> blocked</label>
        <label><input type="checkbox" checked={filters.archived} onChange={(e) => setFilter("archived", e.target.checked)} /> archived</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, width: "100%" }}>
          {input("q", "Name or domain contains")}
          <select aria-label="Reply" value={filters.replied} onChange={(e) => setFilter("replied", e.target.value)}>
            <option value="">Reply: any</option><option value="true">replied</option><option value="false">not replied</option>
          </select>
          <select aria-label="AI label" value={filters.ai_label} onChange={(e) => setFilter("ai_label", e.target.value)}>
            <option value="">AI label: any</option>
            {AI_LABELS.map((l) => <option key={l} value={l}>{l.replaceAll("_", " ")}</option>)}
          </select>
          <select aria-label="Template" value={filters.template_id} onChange={(e) => setFilter("template_id", e.target.value)}>
            <option value="">Template: any</option>
            {templates.map((t) => <option key={t.id} value={t.id}>emailed with {t.name}</option>)}
          </select>
          {[["emailed", "Last emailed"], ["replied", "Last reply"], ["added", "Added"]].map(([k, label]) => (
            <span key={k}><small>{label}</small>{" "}
              <input type="date" aria-label={`${label} from`} value={filters[`${k}_from`]} onChange={(e) => setFilter(`${k}_from`, e.target.value)} />
              <small>–</small>
              <input type="date" aria-label={`${label} to`} value={filters[`${k}_to`]} onChange={(e) => setFilter(`${k}_to`, e.target.value)} />
            </span>
          ))}
        </div>
        <button type="submit">Filter</button>
        <button type="button" onClick={clearFilters}>Clear</button>
      </form>

      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0", flexWrap: "wrap" }}>
        <strong>{selected.size} selected</strong>
        <select aria-label="New stage" value={bulkStage} onChange={(e) => setBulkStage(e.target.value)}>
          {STAGES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <button disabled={!selected.size} onClick={applyStage}>Set stage</button>
        <button disabled={!selected.size} onClick={handOff}>Add to compose list</button>
      </div>
      {msg && <p role="status">{msg}</p>}

      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th><input type="checkbox" aria-label="Select all shown" checked={allSelected} onChange={toggleAll} /></th>
            <th align="left">Name</th><th align="left">Stage</th><th align="left">City</th><th align="left">Industry</th>
            <th align="right">Emails</th><th align="left">Last emailed</th><th align="left">Last reply</th><th />
          </tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr key={l.id} style={{ borderTop: "1px solid var(--border)" }}>
              <td><input type="checkbox" aria-label={`Select ${l.name}`} checked={selected.has(l.id)} onChange={() => toggle(l.id)} /></td>
              <td><Link href={`/companies/${l.id}`}>{l.name}</Link> <small style={{ color: "var(--muted)" }}>{l.domain}</small></td>
              <td>{l.stage}{l.close_reason && <small style={{ color: "var(--muted)" }}> ({l.close_reason})</small>}</td>
              <td>{l.city}</td>
              <td><small>{l.industry}</small></td>
              <td align="right">{l.usable_emails}{l.careers_emails > 0 && <mark title="has a careers email"> careers</mark>}</td>
              <td><small>{l.last_emailed_at ? new Date(l.last_emailed_at).toLocaleDateString() : "—"}</small></td>
              <td><small>{l.last_reply_at ? new Date(l.last_reply_at).toLocaleDateString() : "—"}</small></td>
              <td>
                {l.blocked && <mark style={{ background: "var(--danger)", color: "var(--surface)" }}>blocked</mark>}
                {l.in_compose_list && <mark> in list</mark>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>{leads.length} shown{data.truncated && " (first 500; narrow the filters to see the rest)"}</p>

      <details style={{ marginTop: 24 }}>
        <summary>Add company manually</summary>
        <form onSubmit={addCompany} style={{ display: "grid", gap: 8, maxWidth: 480 }}>
          {COMPANY_FIELDS.map(([k, label, type]) => (
            <label key={k}>{label}
              {type === "textarea"
                ? <textarea rows={3} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={{ display: "block", width: "100%" }} />
                : <input type={type || "text"} required={k === "name"} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} style={{ display: "block", width: "100%" }} />}
            </label>
          ))}
          <button type="submit">Add company</button>
        </form>
      </details>
    </main>
  );
}
