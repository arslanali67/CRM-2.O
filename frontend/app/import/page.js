"use client";
// F3: CSV import as a 3-step wizard: 1 Upload -> 2 Preview (nothing saved) -> 3 Import.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { errorText } from "../companies/shared";
import { Badge, ErrorState, PageHeader, Spinner } from "../ui";

const STATUS_TONE = { new: "success", duplicate: "", blocked: "danger", error: "danger" };
const STEPS = ["Upload", "Preview", "Import"];

function Steps({ at }) {
  return (
    <ol className="steps" aria-label="Import steps" style={{ listStyle: "none", padding: 0 }}>
      {STEPS.map((s, i) => (
        <li key={s} className={`step${i < at ? " done" : ""}`} aria-current={i === at ? "step" : undefined}>
          <span className="n">{i < at ? "✓" : i + 1}</span>{s}
        </li>
      ))}
    </ol>
  );
}

export default function Import() {
  const router = useRouter();
  const input = useRef(null);
  const [file, setFile] = useState(null);
  const [over, setOver] = useState(false);
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [result, setResult] = useState(null);
  const [imported, setImported] = useState(false);
  const [show, setShow] = useState("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(path) {
    setBusy(true);
    setError("");
    const q = new URLSearchParams({ filename: file.name, city, country });
    const res = await fetch(`/api/${path}?${q}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body: file });
    setBusy(false);
    if (res.status === 401) return router.replace("/login");
    const data = await res.json();
    if (!res.ok) return setError(errorText(data));
    setResult(data);
    return data;
  }

  const pick = (f) => { if (f) { setFile(f); setResult(null); setImported(false); setError(""); } };
  async function preview(e) { e.preventDefault(); if (!file) return setError("Choose a CSV file first."); setImported(false); await send("imports/preview"); }
  async function runImport() { if (await send("imports")) setImported(true); }
  function restart() { setFile(null); setResult(null); setImported(false); setShow("all"); if (input.current) input.current.value = ""; }
  function downloadRejected() {
    const url = URL.createObjectURL(new Blob([result.rejected_csv], { type: "text/csv" }));
    Object.assign(document.createElement("a"), { href: url, download: `rejected_${file.name}` }).click();
    URL.revokeObjectURL(url);
  }

  const s = result?.summary;
  const step = imported ? 2 : result ? 1 : 0;
  const rows = result ? result.rows.filter((r) => show === "all" || r.status === show) : [];
  const counts = s ? [["new", s.new, "New companies", "success"], ["duplicate", s.duplicate, "Duplicates", ""],
    ["blocked", s.blocked, "Blocked", "danger"], ["error", s.error, "Errors", "danger"]] : [];

  return (
    <main>
      <PageHeader title="Import companies" sub="An ai_companies CSV: columns company, website and all_emails are required." />
      <Steps at={step} />
      {error && <div style={{ marginBottom: 12 }}><ErrorState>{error}</ErrorState></div>}

      {step === 0 && (
        <form className="card" onSubmit={preview} style={{ maxWidth: 640 }}>
          <div className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0} aria-label="Choose a CSV file"
               onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
               onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
               onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}>
            {file ? <><b style={{ color: "var(--text)" }}>{file.name}</b><div><small>{Math.round(file.size / 1024)} KB · click to choose another</small></div></>
                  : <><b style={{ color: "var(--text)" }}>Drop your CSV here</b><div><small>or click to choose a file (max 5 MB, 5,000 rows)</small></div></>}
            <input ref={input} type="file" accept=".csv,text/csv" hidden onChange={(e) => pick(e.target.files[0])} />
          </div>
          <div className="filter-row" style={{ marginTop: 16 }}>
            <label className="field" style={{ flex: 1, margin: 0 }}><span>City for this batch</span>
              <input placeholder="Berlin" aria-label="City" value={city} onChange={(e) => setCity(e.target.value)} /></label>
            <label className="field" style={{ flex: 1, margin: 0 }}><span>Country for this batch</span>
              <input placeholder="Germany" aria-label="Country" value={country} onChange={(e) => setCountry(e.target.value)} /></label>
          </div>
          <div className="dialog-actions">
            <button type="submit" className="btn-primary" disabled={busy || !file}>{busy ? <Spinner /> : null}Preview (nothing is saved)</button>
          </div>
        </form>
      )}

      {step >= 1 && s && (
        <>
          {imported ? (
            <section className="card" style={{ borderColor: "var(--success)", background: "var(--success-bg)", marginBottom: 16 }}>
              <b style={{ color: "var(--success)" }}>Imported {s.new} companies and {s.contacts} contacts.</b>
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <Link className="btn btn-primary" href="/companies?source=csv_import">View imported leads</Link>
                <button onClick={restart}>Import another file</button>
                {s.total > s.new && <button onClick={downloadRejected}>Download rejected rows (CSV)</button>}
              </div>
            </section>
          ) : (
            <section className="card" style={{ marginBottom: 16 }}>
              <b>{file.name}</b>: {s.total} rows · {s.contacts} contacts to add · {s.skipped_emails} unusable addresses skipped.
              <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button className="btn-primary" onClick={runImport} disabled={busy || s.new === 0}>{busy ? <Spinner /> : null}Import {s.new} new companies</button>
                <button onClick={restart} disabled={busy}>Back</button>
                {s.total > s.new && <button onClick={downloadRejected}>Download rejected rows (CSV)</button>}
              </div>
            </section>
          )}

          <div className="kpi-grid" style={{ marginBottom: 16 }}>
            {counts.map(([k, n, label, tone]) => (
              <button key={k} className="stat" onClick={() => setShow(show === k ? "all" : k)} aria-pressed={show === k}
                      style={{ textAlign: "left", display: "block", minHeight: 0, padding: "12px 16px", borderColor: show === k ? "var(--accent)" : undefined }}>
                <div className="stat-label">{label}</div>
                <div className="stat-value" style={{ color: n && tone ? `var(--${tone})` : undefined }}>{n}</div>
              </button>
            ))}
          </div>

          <div className="table-wrap">
            <table>
              <thead><tr><th>Line</th><th>Company</th><th>Domain</th><th>Status</th><th>Contacts / skipped</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.line}>
                    <td>{r.line}</td>
                    <td>{r.company || <i>(none)</i>}</td>
                    <td>{r.domain || "—"}</td>
                    <td><Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>{r.reason && <div><small style={{ color: "var(--muted)" }}>{r.reason}</small></div>}</td>
                    <td>
                      {r.contacts.map((c, i) => <div key={i}><small>{c.email ? `${c.email} (${c.email_class})` : c.name}</small></div>)}
                      {r.skipped_emails.length > 0 && (
                        <details><summary><small>{r.skipped_emails.length} skipped</small></summary>
                          {r.skipped_emails.map((x, i) => <div key={i}><small style={{ color: "var(--muted)" }}>{x.email}: {x.reason}</small></div>)}
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {show !== "all" && <p><small>Showing {show} rows only · <button className="btn-sm btn-ghost" onClick={() => setShow("all")}>Show all</button></small></p>}
        </>
      )}
    </main>
  );
}
