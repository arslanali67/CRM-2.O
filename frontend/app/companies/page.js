"use client";
// F3: Leads. Filters live in the URL (reload / bookmark keep them); sorting and paging happen in the browser on
// the up-to-500 rows the API returns; a bulk bar appears when rows are selected.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, Loading, Modal, PageHeader, useDialog, useToast } from "../ui";
import { COMPANY_FIELDS, CompanyFields, LeadStage, STAGES, errorText } from "./shared";

const EMPTY_COMPANY = Object.fromEntries(COMPANY_FIELDS.map(([k]) => [k, ""]));
const NO_FILTERS = { q: "", stage: "", country: "", city: "", industry: "", source: "", has_email: "", has_careers: "",
                     replied: "", ai_label: "", template_id: "", emailed_from: "", emailed_to: "", replied_from: "",
                     replied_to: "", added_from: "", added_to: "", include_blocked: false, archived: false };
const AI_LABELS = ["interview_request", "interested", "needs_info", "scheduling", "application_redirect", "referral",
                   "keep_on_file", "not_hiring", "rejection", "offer", "unsubscribe_request", "other"];
const PAGE = 50;
const COLUMNS = [["name", "Name"], ["stage", "Stage"], ["place", "Location"], ["industry", "Industry"],
                 ["usable_emails", "Emails"], ["last_emailed_at", "Last emailed"], ["last_reply_at", "Last reply"]];
const LABELS = { q: "Name/domain", stage: "Stage", country: "Country", city: "City", industry: "Industry", source: "Source",
                 has_email: "Usable email", has_careers: "Careers email", replied: "Reply", ai_label: "AI label",
                 template_id: "Template", emailed_from: "Emailed from", emailed_to: "Emailed to", replied_from: "Reply from",
                 replied_to: "Reply to", added_from: "Added from", added_to: "Added to", include_blocked: "Incl. blocked",
                 archived: "Archived" };

const fromUrl = () => {
  const p = new URLSearchParams(window.location.search);
  return Object.fromEntries(Object.entries(NO_FILTERS).map(([k, v]) => [k, typeof v === "boolean" ? p.get(k) === "true" : p.get(k) ?? ""]));
};
const query = (f) => new URLSearchParams(Object.entries(f).filter(([, v]) => v !== "" && v !== false)).toString();
const sortValue = (l, key) => key === "place" ? `${l.country} ${l.city}`.trim().toLowerCase()
  : key === "name" ? l.name.toLowerCase() : key === "stage" ? STAGES.indexOf(l.stage) : l[key] ?? "";
const date = (d) => (d ? new Date(d).toLocaleDateString() : "—");

export default function Leads() {
  const dialog = useDialog();
  const toast = useToast();
  const router = useRouter();
  const [filters, setFilters] = useState(null);
  const [draft, setDraft] = useState(NO_FILTERS);
  const [more, setMore] = useState(false);
  const [data, setData] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [sort, setSort] = useState(["name", 1]);
  const [page, setPage] = useState(0);
  const [adding, setAdding] = useState(null);

  useEffect(() => {
    const f = fromUrl();
    setFilters(f); setDraft(f);
    setMore(["replied", "ai_label", "template_id", "emailed_from", "emailed_to", "replied_from", "replied_to", "added_from", "added_to", "source"]
      .some((k) => f[k]));
    fetch("/api/templates").then((r) => r.ok && r.json()).then((t) => t && setTemplates(t));
  }, []);

  async function load(f = filters) {
    const res = await fetch(`/api/leads?${query(f)}`);
    if (res.status === 401) return router.replace("/login");
    setData(await res.json());
    setSelected(new Set());
  }
  useEffect(() => { if (filters) load(filters); }, [filters]); // eslint-disable-line react-hooks/exhaustive-deps

  function apply(f) {
    const q = query(f);
    window.history.replaceState(null, "", q ? `/companies?${q}` : "/companies");
    setFilters(f); setDraft(f); setPage(0);
  }
  const setD = (k, v) => setDraft({ ...draft, [k]: v });

  const rows = useMemo(() => {
    const [key, dir] = sort;
    return [...(data?.leads || [])].sort((a, b) => {
      const x = sortValue(a, key), y = sortValue(b, key);
      if (x === y) return a.id - b.id;
      if (x === "" || x === null) return 1;
      if (y === "" || y === null) return -1;
      return (x > y ? 1 : -1) * dir;
    });
  }, [data, sort]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const allSelected = shown.length > 0 && shown.every((l) => selected.has(l.id));

  const toggle = (id) => { const s = new Set(selected); s.has(id) ? s.delete(id) : s.add(id); setSelected(s); };
  const toggleAll = () => { const s = new Set(selected); shown.forEach((l) => (allSelected ? s.delete(l.id) : s.add(l.id))); setSelected(s); };
  const sortBy = (key) => setSort(([k, d]) => [key, k === key ? -d : 1]);

  async function post(url, body) {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return { ok: res.ok, data: await res.json() };
  }

  async function setStage(stage) {
    let close_reason = "";
    if (stage === "closed") {
      close_reason = (await dialog.prompt(`Close ${selected.size} lead(s)?`, { body: "A reason is required and kept in the history.", required: true, confirmLabel: "Close leads" })) || "";
      if (!close_reason.trim()) return;
    }
    const r = await post("/api/leads/stage", { company_ids: [...selected], stage, close_reason });
    toast(r.ok ? `${r.data.changed} lead(s) moved to ${stage.replace("_", " ")}.` : errorText(r.data), r.ok ? "" : "error");
    if (r.ok) load();
  }

  async function handOff() {
    const r = await post("/api/compose-list", { company_ids: [...selected] });
    if (!r.ok) return toast(errorText(r.data), "error");
    const refused = r.data.refused.map((x) => `${x.name} (${x.reason})`).join(", ");
    toast(`${r.data.added.length} added to the compose list` + (r.data.already.length ? `, ${r.data.already.length} already there` : "")
      + (refused ? `. Not added: ${refused}.` : "."));
    load();
  }

  async function addCompany(e) {
    e.preventDefault();
    const r = await post("/api/companies", adding);
    if (!r.ok) return toast(errorText(r.data), "error");
    toast(`${r.data.name} added.`);
    setAdding(null);
    router.push(`/companies/${r.data.id}`);
  }

  if (!filters) return <Loading what="leads" />;
  const chips = Object.entries(filters).filter(([, v]) => v !== "" && v !== false);
  const text = (k, label, type = "text") => <input type={type} placeholder={label} aria-label={label} value={draft[k]} onChange={(e) => setD(k, e.target.value)} />;
  const yesNo = (k, label) => (
    <select aria-label={label} value={draft[k]} onChange={(e) => setD(k, e.target.value)}>
      <option value="">{label}: any</option><option value="true">{label}: yes</option><option value="false">{label}: no</option>
    </select>
  );

  return (
    <main>
      <PageHeader title="Leads" sub={data ? `${rows.length}${data.truncated ? "+" : ""} companies` : ""}
        actions={<>
          <Link className="btn" href="/import">Import CSV</Link>
          <button className="btn-primary" onClick={() => setAdding(EMPTY_COMPANY)}>Add company</button>
        </>} />

      <form className="card filters" onSubmit={(e) => { e.preventDefault(); apply(draft); }}>
        <div className="filter-row">
          {text("q", "Name or domain contains")}
          <select aria-label="Stage" value={draft.stage} onChange={(e) => setD("stage", e.target.value)}>
            <option value="">Stage: any</option>{STAGES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
          {text("country", "Country")}{text("city", "City")}{text("industry", "Industry contains")}
          {yesNo("has_email", "Usable email")}{yesNo("has_careers", "Careers email")}
        </div>
        {more && (
          <div className="filter-row">
            <select aria-label="Source" value={draft.source} onChange={(e) => setD("source", e.target.value)}>
              <option value="">Source: any</option><option value="manual">manual</option><option value="csv_import">CSV import</option>
            </select>
            <select aria-label="Reply" value={draft.replied} onChange={(e) => setD("replied", e.target.value)}>
              <option value="">Reply: any</option><option value="true">replied</option><option value="false">not replied</option>
            </select>
            <select aria-label="AI label" value={draft.ai_label} onChange={(e) => setD("ai_label", e.target.value)}>
              <option value="">AI label: any</option>{AI_LABELS.map((l) => <option key={l} value={l}>{l.replaceAll("_", " ")}</option>)}
            </select>
            <select aria-label="Template" value={draft.template_id} onChange={(e) => setD("template_id", e.target.value)}>
              <option value="">Template: any</option>{templates.map((t) => <option key={t.id} value={t.id}>emailed with {t.name}</option>)}
            </select>
            {[["emailed", "Last emailed"], ["replied", "Last reply"], ["added", "Added"]].map(([k, label]) => (
              <span key={k} className="range"><small>{label}</small>
                <input type="date" aria-label={`${label} from`} value={draft[`${k}_from`]} onChange={(e) => setD(`${k}_from`, e.target.value)} />
                <small>–</small>
                <input type="date" aria-label={`${label} to`} value={draft[`${k}_to`]} onChange={(e) => setD(`${k}_to`, e.target.value)} />
              </span>
            ))}
            <label><input type="checkbox" checked={draft.include_blocked} onChange={(e) => setD("include_blocked", e.target.checked)} /> include blocked</label>
            <label><input type="checkbox" checked={draft.archived} onChange={(e) => setD("archived", e.target.checked)} /> archived only</label>
          </div>
        )}
        <div className="filter-row" style={{ marginBottom: 0 }}>
          <button type="submit" className="btn-primary">Filter</button>
          <button type="button" className="btn-ghost" onClick={() => setMore(!more)} aria-expanded={more}>{more ? "Fewer filters" : "More filters"}</button>
          {chips.length > 0 && <button type="button" className="btn-ghost" onClick={() => apply(NO_FILTERS)}>Clear all</button>}
        </div>
      </form>

      {chips.length > 0 && (
        <div className="chips" aria-label="Active filters">
          {chips.map(([k, v]) => (
            <span key={k} className="badge badge-accent chip">
              {LABELS[k]}{v === true ? "" : `: ${k === "template_id" ? templates.find((t) => String(t.id) === v)?.name || v : v === "true" ? "yes" : v === "false" ? "no" : v}`}
              <button type="button" aria-label={`Remove filter ${LABELS[k]}`} onClick={() => apply({ ...filters, [k]: NO_FILTERS[k] })}>✕</button>
            </span>
          ))}
        </div>
      )}

      {!data ? <Loading what="leads" /> : rows.length === 0 ? (
        <EmptyState title={chips.length ? "No leads match these filters" : "No leads yet"}
                    action={chips.length ? <button onClick={() => apply(NO_FILTERS)}>Clear filters</button> : <Link className="btn btn-primary" href="/import">Import a CSV</Link>}>
          {chips.length ? "Try removing a filter." : "Import your companies or add one by hand."}
        </EmptyState>
      ) : (
        <>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 36 }}><input type="checkbox" aria-label="Select all shown" checked={allSelected} onChange={toggleAll} /></th>
                  {COLUMNS.map(([key, label]) => (
                    <th key={key} aria-sort={sort[0] === key ? (sort[1] === 1 ? "ascending" : "descending") : "none"}>
                      <button type="button" className="th-sort" onClick={() => sortBy(key)}>
                        {label}{sort[0] === key ? (sort[1] === 1 ? " ▲" : " ▼") : ""}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((l) => (
                  <tr key={l.id} className={selected.has(l.id) ? "selected" : ""}>
                    <td><input type="checkbox" aria-label={`Select ${l.name}`} checked={selected.has(l.id)} onChange={() => toggle(l.id)} /></td>
                    <td><Link href={`/companies/${l.id}`}><b>{l.name}</b></Link>
                      <div><small style={{ color: "var(--muted)" }}>{l.domain}</small>
                        {l.blocked && <span className="badge badge-danger" style={{ marginLeft: 6 }}>blocked</span>}
                        {l.in_compose_list && <span className="badge" style={{ marginLeft: 6 }}>in compose list</span>}</div></td>
                    <td><LeadStage stage={l.stage} />{l.close_reason && <div><small style={{ color: "var(--muted)" }}>{l.close_reason}</small></div>}</td>
                    <td>{[l.city, l.country].filter(Boolean).join(", ") || "—"}</td>
                    <td className="clip" title={l.industry}><small>{l.industry || "—"}</small></td>
                    <td>{l.usable_emails}{l.careers_emails > 0 && <span className="badge badge-success" style={{ marginLeft: 6 }}>careers</span>}</td>
                    <td><small>{date(l.last_emailed_at)}</small></td>
                    <td><small>{date(l.last_reply_at)}</small></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pager">
            <small style={{ color: "var(--muted)" }}>
              {page * PAGE + 1}–{Math.min(rows.length, page * PAGE + PAGE)} of {rows.length}
              {data.truncated && " · only the first 500 matches are loaded: narrow the filters to see the rest"}
            </small>
            <span>
              <button disabled={page === 0} onClick={() => setPage(page - 1)} aria-label="Previous page">‹ Prev</button>{" "}
              <small>Page {page + 1} of {pages}</small>{" "}
              <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)} aria-label="Next page">Next ›</button>
            </span>
          </div>
        </>
      )}

      {selected.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Bulk actions">
          <b>{selected.size} selected</b>
          <select aria-label="New stage" defaultValue="" onChange={(e) => { const v = e.target.value; e.target.value = ""; if (v) setStage(v); }}>
            <option value="" disabled>Set stage…</option>
            {STAGES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
          <button className="btn-primary" onClick={handOff}>Add to compose list</button>
          <button className="btn-ghost" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

      {adding && (
        <Modal title="Add company" onClose={() => setAdding(null)}>
          <form onSubmit={addCompany}>
            <CompanyFields form={adding} setForm={setAdding} />
            <div className="dialog-actions"><button type="button" onClick={() => setAdding(null)}>Cancel</button>
              <button type="submit" className="btn-primary">Add company</button></div>
          </form>
        </Modal>
      )}
    </main>
  );
}
