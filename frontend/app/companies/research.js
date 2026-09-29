"use client";
import { Fragment, useEffect, useState } from "react";
import { errorText } from "./shared";

const CATEGORIES = ["product", "mission", "technology", "hiring", "location", "size", "funding", "news", "other"];
const box = (color) => ({ border: `2px solid ${color}`, borderRadius: 6, padding: 12, marginTop: 16 });

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  return { ok: r.ok, data: await r.json() };
}

export function ResearchPanel({ companyId }) {
  const [d, setD] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [edit, setEdit] = useState({});             // claim id -> reworded text
  const [manual, setManual] = useState({ fact: "", category: "other", source: "" });

  const load = () => fetch(`/api/companies/${companyId}/research`).then((r) => r.json()).then(setD);
  useEffect(() => { load(); }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    setBusy(true);
    setMsg(`Reading ${d.domain}…`);
    const r = await post(`/api/companies/${companyId}/research`);
    setBusy(false);
    if (!r.ok) return setMsg(errorText(r.data));
    const x = r.data;
    setMsg(`Read ${x.pages} page(s)${x.fetch_errors.length ? ` (${x.fetch_errors.length} could not be read)` : ""}. ` +
           (x.ai === "done" ? `${x.claims} claim(s) to review${x.dropped ? `; ${x.dropped} dropped because their quote was not on the page` : ""}.` : `AI: ${x.ai}.`));
    load();
  }

  async function act(url, body, ok) {
    const r = await post(url, body);
    setMsg(r.ok ? ok : errorText(r.data));
    load();
  }

  if (!d) return <p>Loading…</p>;
  return (
    <div>
      <p>
        <button onClick={run} disabled={busy || !d.domain}>Research {d.domain || "(no domain)"}</button>{" "}
        <small style={{ color: "gray" }}>
          Reads up to 3 pages of the company&apos;s own website (home, about, careers) once, when you click.
          {d.ai.enabled ? ` The AI (${d.ai.model}) proposes claims; each must quote the page.` : " AI is off, so pages are only saved."}
        </small>
      </p>
      {msg && <p>{msg}</p>}

      <section style={box("#16a34a")}>
        <h3 style={{ marginTop: 0 }}>✔ Verified facts <small style={{ fontWeight: "normal" }}>(the only information personalized emails may use)</small></h3>
        {d.facts.length === 0 && <p>None yet. Verify an AI claim below or add a fact you know.</p>}
        {d.facts.map((f) => (
          <div key={f.id} style={{ marginBottom: 6 }}>
            <b>{f.category}</b>: {f.fact}{" "}
            <small style={{ color: "gray" }}>· source: {/^https?:\/\//.test(f.source)
              ? <a href={f.source} target="_blank" rel="noopener noreferrer">{f.source}</a> : f.source}
              {" "}· verified {new Date(f.verified_at).toLocaleDateString()}</small>{" "}
            <button onClick={() => window.confirm("Remove this fact?") && act(`/api/facts/${f.id}/remove`, {}, "Fact removed.")}>Remove</button>
          </div>
        ))}
        <form onSubmit={(e) => { e.preventDefault(); act(`/api/companies/${companyId}/facts`, manual, "Fact added."); setManual({ fact: "", category: "other", source: "" }); }}
              style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          <select aria-label="Category" value={manual.category} onChange={(e) => setManual({ ...manual, category: e.target.value })}>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select>
          <input required placeholder="A fact you know" aria-label="Fact" value={manual.fact} style={{ flex: 2 }}
                 onChange={(e) => setManual({ ...manual, fact: e.target.value })} />
          <input required placeholder="Source (link, or where you know it from)" aria-label="Source" value={manual.source} style={{ flex: 1 }}
                 onChange={(e) => setManual({ ...manual, source: e.target.value })} />
          <button type="submit">Add fact</button>
        </form>
      </section>

      <section style={box("#d97706")}>
        <h3 style={{ marginTop: 0 }}>AI claims <small style={{ fontWeight: "normal" }}>(unverified: check each quote before verifying)</small></h3>
        {d.claims.length === 0 && <p>No open claims.</p>}
        {d.claims.map((c) => (
          <div key={c.id} style={{ borderTop: "1px solid #eee", padding: "6px 0" }}>
            <b>{c.category}</b>:{" "}
            <input aria-label="Claim wording" value={edit[c.id] ?? c.claim} style={{ width: "70%" }}
                   onChange={(e) => setEdit({ ...edit, [c.id]: e.target.value })} />
            <div><small style={{ color: "gray" }}>Quote: “{c.evidence}” · <a href={c.source_url} target="_blank" rel="noopener noreferrer">{c.source_url}</a></small></div>
            <button onClick={() => act(`/api/claims/${c.id}/verify`, (edit[c.id] ?? c.claim) !== c.claim ? { fact: edit[c.id] } : {}, "Verified.")}>Verify</button>{" "}
            <button onClick={() => act(`/api/claims/${c.id}/reject`, {}, "Rejected.")}>Reject</button>
          </div>
        ))}
      </section>

      <section style={box("#9ca3af")}>
        <h3 style={{ marginTop: 0 }}>Scraped data <small style={{ fontWeight: "normal" }}>({d.scraped_source}; unverified)</small></h3>
        {Object.keys(d.scraped).length === 0 ? <p>Nothing scraped.</p> : (
          <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0 }}>
            {Object.entries(d.scraped).map(([k, v]) => <Fragment key={k}><dt>{k.replaceAll("_", " ")}</dt><dd style={{ margin: 0 }}>{String(v)}</dd></Fragment>)}
          </dl>
        )}
        {d.snapshots.length > 0 && <p><small style={{ color: "gray" }}>Pages read: {d.snapshots.map((s) =>
          `${s.url} (${s.error || `${s.chars} chars`}, ${new Date(s.fetched_at).toLocaleDateString()})`).join(" · ")}</small></p>}
      </section>
    </div>
  );
}
