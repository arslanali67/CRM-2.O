"use client";
// F7: the Research tab. Three kinds of information stay strictly apart: verified facts (the only kind personalization may
// use), AI claims (unverified; each quotes the page it came from) and scraped data (from the CSV, unverified).
import { Fragment, useEffect, useState } from "react";
import { Badge, EmptyState, Loading, Modal, Spinner, ago, useDialog, useToast } from "../ui";
import { errorText } from "./shared";

const CATEGORIES = ["product", "mission", "technology", "hiring", "location", "size", "funding", "news", "other"];
const get = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const link = (u) => (/^https?:\/\//.test(u) ? <a href={u} target="_blank" rel="noopener noreferrer">{u}</a> : u);

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return { ok: r.ok, data: await r.json() };
}

function Section({ tone, title, count, rule, children, actions }) {
  return (
    <section className="card research-section" data-section={title} style={{ borderColor: `var(--${tone})`, marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "baseline" }}>
        <h3 style={{ margin: 0 }}>{title} <Badge tone={tone === "border-strong" ? "" : tone}>{count}</Badge></h3>
        {actions}
      </div>
      <p style={{ margin: "2px 0 10px", color: "var(--muted)" }}><small>{rule}</small></p>
      {children}
    </section>
  );
}

export function ResearchPanel({ companyId }) {
  const dialog = useDialog();
  const toast = useToast();
  const [d, setD] = useState(null);
  const [last, setLast] = useState(null);            // the latest "company researched" audit event
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState({});               // claim id -> reworded text
  const [adding, setAdding] = useState(null);

  async function load() {
    setD(await get(`/api/companies/${companyId}/research`));
    const events = await get(`/api/companies/${companyId}/activity`);
    setLast((events || []).find((e) => e.action === "company.researched") || null);
  }
  useEffect(() => { load(); }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    setBusy(true);
    const r = await post(`/api/companies/${companyId}/research`);
    setBusy(false);
    if (!r.ok) toast(errorText(r.data), "error");
    else toast(r.data.ai === "done" ? `Read ${r.data.pages} page(s); ${r.data.claims} claim(s) to review.` : `Read ${r.data.pages} page(s). AI: ${r.data.ai}.`);
    load();
  }
  async function act(url, body, ok) {
    const r = await post(url, body);
    toast(r.ok ? ok : errorText(r.data), r.ok ? "" : "error");
    load();
    return r.ok;
  }
  async function removeFact(f) {
    if (await dialog.confirm("Remove this fact?", { body: "It will no longer be used for personalization.", danger: true, confirmLabel: "Remove" }))
      act(`/api/facts/${f.id}/remove`, {}, "Fact removed.");
  }
  async function addFact(e) {
    e.preventDefault();
    if (await act(`/api/companies/${companyId}/facts`, adding, "Fact added.")) setAdding(null);
  }

  if (!d) return <Loading what="research" />;
  const status = () => {
    if (!last && d.snapshots.length === 0) return "Not researched yet.";
    const x = last?.data || {};
    const when = ago(last?.at || d.snapshots[0]?.fetched_at);
    return `Researched ${when}: ${x.pages ?? d.snapshots.filter((s) => !s.error).length} page(s) read, ${x.claims ?? d.claims.length} claim(s)` +
           (x.ai && x.ai !== "done" ? ` · AI: ${x.ai}` : "") + (x.fetch_errors?.length ? ` · ${x.fetch_errors.length} page(s) couldn't be read` : "") + ".";
  };
  const byCategory = CATEGORIES.map((c) => [c, d.claims.filter((x) => x.category === c)]).filter(([, l]) => l.length);

  return (
    <div>
      <section className="card" style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ minWidth: 0 }}>
          <b>Research</b>
          <div data-research-status style={{ color: "var(--muted)" }}>{status()}</div>
          <small style={{ color: "var(--muted)" }}>Reads up to 3 pages of the company&apos;s own website (home, about, careers) once, when you click.
            {d.ai.enabled ? ` The AI (${d.ai.model}) proposes claims; each must quote the page.` : " AI is off, so pages are only saved."}</small>
        </div>
        <button className="btn-primary" onClick={run} disabled={busy || !d.domain}>{busy && <Spinner />}Research {d.domain || "(no domain)"}</button>
      </section>

      <Section tone="success" title="Verified facts" count={d.facts.length} rule="The only information personalized emails may use. Each keeps its source."
               actions={<button onClick={() => setAdding({ fact: "", category: "other", source: "" })}>Add a fact</button>}>
        {d.facts.length === 0 ? <p style={{ margin: 0, color: "var(--muted)" }}>None yet. Verify an AI claim below or add a fact you know.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Category</th><th>Fact</th><th>Source</th><th>Verified</th><th /></tr></thead>
            <tbody>{d.facts.map((f) => (
              <tr key={f.id} data-fact={f.id}>
                <td><Badge tone="success">{f.category}</Badge></td><td>{f.fact}</td>
                <td className="clip" style={{ maxWidth: 240 }}><small>{link(f.source)}</small></td>
                <td><small>{new Date(f.verified_at).toLocaleDateString()}</small></td>
                <td style={{ textAlign: "right" }}><button className="btn-sm btn-ghost" onClick={() => removeFact(f)}>Remove</button></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Section>

      <Section tone="warning" title="AI claims" count={d.claims.length} rule="Unverified. Check each quote on its page before verifying; you can reword a claim first.">
        {d.claims.length === 0 ? <p style={{ margin: 0, color: "var(--muted)" }}>No open claims.</p> : byCategory.map(([cat, list]) => (
          <Fragment key={cat}>
            <div style={{ margin: "8px 0 4px" }}><Badge tone="warning">{cat}</Badge></div>
            {list.map((c) => (
              <div key={c.id} className="claim-card" data-claim={c.id}>
                <textarea rows={2} aria-label={`Claim wording ${c.id}`} value={edit[c.id] ?? c.claim} onChange={(e) => setEdit({ ...edit, [c.id]: e.target.value })} />
                <small style={{ color: "var(--muted)" }}>Quote: “{c.evidence}” · {link(c.source_url)}</small>
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn-primary btn-sm" onClick={() => act(`/api/claims/${c.id}/verify`, (edit[c.id] ?? c.claim) !== c.claim ? { fact: edit[c.id] } : {}, "Verified.")}>Verify</button>
                  <button className="btn-sm" onClick={() => act(`/api/claims/${c.id}/reject`, {}, "Rejected.")}>Reject</button>
                </div>
              </div>
            ))}
          </Fragment>
        ))}
      </Section>

      <Section tone="border-strong" title="Scraped data" count={Object.keys(d.scraped).length} rule={`From ${d.scraped_source}. Unverified: it never reaches personalization.`}>
        {Object.keys(d.scraped).length === 0 ? <p style={{ margin: 0, color: "var(--muted)" }}>Nothing scraped.</p> : (
          <dl className="dl">{Object.entries(d.scraped).map(([k, v]) => <Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd>{String(v)}</dd></Fragment>)}</dl>
        )}
        <h4 style={{ margin: "14px 0 6px" }}>Pages read</h4>
        {d.snapshots.length === 0 ? <small style={{ color: "var(--muted)" }}>None yet.</small> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Page</th><th>Result</th><th>Size</th><th>When</th></tr></thead>
            <tbody>{d.snapshots.map((s) => (
              <tr key={s.id}><td className="clip" style={{ maxWidth: 280 }}><small>{s.url}</small></td>
                <td>{s.error ? <Badge tone="danger">{s.error}</Badge> : <Badge tone="success">read</Badge>}</td>
                <td><small>{s.chars ? `${Math.round(s.chars / 1000)} k chars` : "—"}</small></td>
                <td><small>{ago(s.fetched_at)}</small></td></tr>))}</tbody>
          </table></div>
        )}
      </Section>

      {adding && (
        <Modal title="Add a fact" onClose={() => setAdding(null)}>
          <form onSubmit={addFact}>
            <label className="field"><span>Category</span>
              <select value={adding.category} onChange={(e) => setAdding({ ...adding, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
            <label className="field"><span>Fact</span>
              <textarea required rows={3} value={adding.fact} onChange={(e) => setAdding({ ...adding, fact: e.target.value })} placeholder="Something you know to be true about the company" /></label>
            <label className="field"><span>Source</span>
              <input required value={adding.source} onChange={(e) => setAdding({ ...adding, source: e.target.value })} placeholder="A link, or where you know it from" /></label>
            <small className="hint">Every fact keeps its source.</small>
            <div className="dialog-actions"><button type="button" onClick={() => setAdding(null)}>Cancel</button>
              <button type="submit" className="btn-primary">Add fact</button></div>
          </form>
        </Modal>
      )}
    </div>
  );
}
