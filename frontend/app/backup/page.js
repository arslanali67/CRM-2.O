"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, Loading } from "../ui";
import { errorText } from "../companies/shared";

const CSVS = [["companies", "Companies"], ["contacts", "Contacts"], ["sent_emails", "Sent emails"], ["replies", "Replies"]];
const size = (b) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export default function Backup() {
  const router = useRouter();
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await fetch("/api/backups");
    if (r.status === 401) return router.replace("/login");
    setS(await r.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function backupNow() {
    setBusy(true);
    setMsg("Backing up…");
    const r = await fetch("/api/backups", { method: "POST" });
    const data = await r.json();
    setBusy(false);
    setMsg(r.ok ? `Backup written: ${data.file} (${size(data.size)}).` : errorText(data));
    load();
  }

  if (!s) return <Loading what="backups" />;
  const last = s.backups[0];
  return (
    <main>
      <PageHeader title="Backup & export" />

      <section className="card">
      <h3 style={{ marginTop: 0 }}>Backups</h3>
      <p style={{ color: s.warn ? "var(--danger)" : undefined }}>
        {last ? `Last backup ${new Date(last.created_at).toLocaleString()} (${Math.round(s.age_hours)} h ago).` : "No backup yet."}
        {s.warn && ` Older than ${s.warn_hours} h: make one now.`}
      </p>
      <p><button onClick={backupNow} disabled={busy}>Back up now</button> {msg}</p>
      <p><small style={{ color: "var(--muted)" }}>
        A backup is made automatically once a day while the app is running (the last {s.keep} are kept) in the <code>backups</code> folder
        of the project. <code>.env</code> is not included: keep your own copy of it.
      </small></p>
      {s.backups.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th align="left">File</th><th align="left">Made</th><th align="right">Size</th><th align="right">Rows</th></tr></thead>
          <tbody>
            {s.backups.map((b) => (
              <tr key={b.file}><td><code>{b.file}</code></td><td>{new Date(b.created_at).toLocaleString()}</td>
                <td align="right">{size(b.size)}</td><td align="right">{b.rows}</td></tr>
            ))}
          </tbody>
        </table></div>
      )}
      <p><small>
        Restoring replaces <b>all</b> data, so it is only possible from a terminal: <code>make restore FILE=…</code>.
        After a restore, sending is OFF and emails that were approved or queued go back to draft for a fresh approval.
        Check a backup safely with <code>make restore-drill</code>.
      </small></p>

      </section>

      <section className="card" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Export</h3>
      <p>
        {CSVS.map(([k, label]) => <span key={k}><a href={`/api/export/${k}.csv`}>{label} (CSV)</a> · </span>)}
        <a href="/api/export/full.zip">Full export (ZIP: every table as JSON + CV PDFs)</a>
      </p>
      <p><small style={{ color: "var(--muted)" }}>The stored Gmail app password is never exported.</small></p>
      </section>
    </main>
  );
}
