"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText } from "../companies/shared";

const STATUS_COLOR = { new: "green", duplicate: "gray", blocked: "crimson", error: "crimson" };

export default function Import() {
  const router = useRouter();
  const [file, setFile] = useState(null);
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [result, setResult] = useState(null);
  const [imported, setImported] = useState(false);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(path) {
    setBusy(true);
    setMsg("");
    const q = new URLSearchParams({ filename: file.name, city, country });
    const res = await fetch(`/api/${path}?${q}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body: file });
    setBusy(false);
    if (res.status === 401) return router.replace("/login");
    const data = await res.json();
    if (!res.ok) return setMsg(errorText(data));
    setResult(data);
    return data;
  }

  async function preview(e) {
    e.preventDefault();
    setImported(false);
    await send("imports/preview");
  }

  async function runImport() {
    const data = await send("imports");
    if (data) {
      setImported(true);
      setMsg(`Imported ${data.summary.new} companies and ${data.summary.contacts} contacts.`);
    }
  }

  function downloadRejected() {
    const url = URL.createObjectURL(new Blob([result.rejected_csv], { type: "text/csv" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `rejected_${file.name}` });
    a.click();
    URL.revokeObjectURL(url);
  }

  const s = result?.summary;

  return (
    <main style={{ maxWidth: 900 }}>
      <p><Link href="/">← Home</Link></p>
      <h1>Import companies (ai_companies CSV)</h1>

      <form onSubmit={preview} style={{ display: "grid", gap: 8, maxWidth: 480 }}>
        <input type="file" accept=".csv,text/csv" required onChange={(e) => { setFile(e.target.files[0]); setResult(null); }} />
        <input placeholder="City for this batch, e.g. Berlin" aria-label="City" value={city} onChange={(e) => setCity(e.target.value)} />
        <input placeholder="Country for this batch, e.g. Germany" aria-label="Country" value={country} onChange={(e) => setCountry(e.target.value)} />
        <button type="submit" disabled={busy}>Preview (nothing is saved)</button>
      </form>
      {msg && <p role="status">{msg}</p>}

      {s && (
        <>
          <h2>{imported ? "Import result" : "Preview"}</h2>
          <p>
            {s.total} rows: <b style={{ color: "green" }}>{s.new} new</b> · {s.duplicate} duplicate · {s.blocked} blocked ·{" "}
            {s.error} error · {s.contacts} contacts to add · {s.skipped_emails} emails skipped
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            {!imported && <button onClick={runImport} disabled={busy || s.new === 0}>Import {s.new} new companies</button>}
            {s.total > s.new && <button onClick={downloadRejected}>Download rejected rows (CSV)</button>}
          </div>

          <table style={{ width: "100%", marginTop: 16, borderCollapse: "collapse" }}>
            <thead>
              <tr><th align="left">Line</th><th align="left">Company</th><th align="left">Domain</th><th align="left">Status</th><th align="left">Contacts / skipped</th></tr>
            </thead>
            <tbody>
              {result.rows.map((r) => (
                <tr key={r.line} style={{ borderTop: "1px solid #eee", verticalAlign: "top" }}>
                  <td>{r.line}</td>
                  <td>{r.company || <i>(none)</i>}</td>
                  <td>{r.domain}</td>
                  <td style={{ color: STATUS_COLOR[r.status] }}>{r.status}{r.reason && `: ${r.reason}`}</td>
                  <td>
                    {r.contacts.map((c, i) => <div key={i}>{c.email ? `${c.email} (${c.email_class})` : c.name}</div>)}
                    {r.skipped_emails.length > 0 && (
                      <details>
                        <summary>{r.skipped_emails.length} skipped</summary>
                        {r.skipped_emails.map((x, i) => <div key={i} style={{ color: "gray" }}>{x.email}: {x.reason}</div>)}
                      </details>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
