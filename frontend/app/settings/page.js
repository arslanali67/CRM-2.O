"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { errorText } from "../companies/shared";

const NUMBERS = [
  ["daily_cap", "Daily sending cap (emails/day)", 1, 100],
  ["min_gap_seconds", "Minimum gap between emails (seconds)", 30, 3600],
  ["approval_max_age_days", "Approval valid for (days)", 1, 30],
  ["recipient_cooldown_days", "Recipient cooldown (days)", 0, 365],
  ["company_cooldown_days", "Company cooldown (days)", 0, 365],
];
const KINDS = [["reply", "Replies"], ["auto_reply", "Auto-replies"], ["bounce", "Bounces"],
               ["sending", "Sending problems (failed / not sent)"], ["system", "System (sync failing, AI failed)"],
               ["interview", "Interview reminders (24 h and 1 h before)"]];
const FIELDS = [...NUMBERS.map(([k]) => k), "ai_enabled", "ai_model", "notify_kinds"];

export default function Settings() {
  const router = useRouter();
  const [s, setS] = useState(null);
  const [form, setForm] = useState(null);
  const [models, setModels] = useState(null);
  const [msg, setMsg] = useState("");

  function show(data) {
    setS(data);
    setForm(Object.fromEntries(FIELDS.map((k) => [k, data[k]])));
  }
  useEffect(() => {
    fetch("/api/settings").then(async (r) => (r.status === 401 ? router.replace("/login") : show(await r.json())));
  }, [router]);

  async function loadModels() {
    setMsg("Loading models…");
    const r = await fetch("/api/settings/ai-models");
    const data = await r.json();
    setMsg(r.ok ? "" : errorText(data));
    if (r.ok) setModels(data.models);
  }

  async function save(e) {
    e.preventDefault();
    const r = await fetch("/api/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
    });
    const data = await r.json();
    if (!r.ok) return setMsg(errorText(data));
    show(data);
    setMsg(data.changed.length ? `Saved: ${data.changed.join(", ").replaceAll("_", " ")}. Applies immediately.` : "Nothing changed.");
  }

  if (!form) return <p>Loading…</p>;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const acc = s.email_account;

  return (
    <main>
      <p><Link href="/">← Dashboard</Link></p>
      <h1>Settings</h1>
      <form onSubmit={save}>
        <h3>Sending limits and cooldowns</h3>
        <p><small>Sending is currently <b>{s.sending_enabled ? "ON" : "OFF"}</b>. Switch it on or off on the <Link href="/outbox">Outbox</Link>.</small></p>
        {NUMBERS.map(([k, label, min, max]) => (
          <p key={k}>
            <label>{label}: <input type="number" required min={min} max={max} value={form[k]}
                                   onChange={(e) => set(k, e.target.value === "" ? "" : Number(e.target.value))} /></label>
            <small style={{ color: "var(--muted)" }}> ({min}–{max})</small>
          </p>
        ))}

        <h3>AI analysis</h3>
        <p><small>API key: {s.ai_key_present ? "present in .env" : "missing (add GEMINI_API_KEY to .env)"}. The key is never shown or stored here.</small></p>
        <p><label><input type="checkbox" checked={form.ai_enabled} onChange={(e) => set("ai_enabled", e.target.checked)} /> Analyse replies with AI</label></p>
        <p>
          <label>Model: <input list="ai-models" value={form.ai_model || ""} placeholder={`default: ${s.ai_default_model}`}
                               onChange={(e) => set("ai_model", e.target.value.trim() || null)} /></label>{" "}
          <button type="button" onClick={loadModels} disabled={!s.ai_key_present}>Show available models</button>
          <datalist id="ai-models">{(models || []).map((m) => <option key={m} value={m} />)}</datalist>
          <br /><small style={{ color: "var(--muted)" }}>In use: {s.ai_effective_model}. A new model is checked against Google&apos;s list before saving.</small>
        </p>

        <h3>Notifications</h3>
        {KINDS.map(([k, label]) => (
          <div key={k}>
            <label><input type="checkbox" checked={form.notify_kinds.includes(k)}
                          onChange={(e) => set("notify_kinds", e.target.checked ? [...form.notify_kinds, k] : form.notify_kinds.filter((x) => x !== k))} /> {label}</label>
          </div>
        ))}

        <p><button type="submit">Save settings</button> {msg && <span>{msg}</span>}</p>
      </form>

      <h3>Email account</h3>
      {acc
        ? <p>{acc.display_name ? `${acc.display_name} <${acc.email_address}>` : acc.email_address} · {acc.connected ? (acc.last_test_ok ? "connected" : "test failed") : "disconnected"}</p>
        : <p>Not configured.</p>}
      <p><Link href="/email-account">Manage email account</Link></p>
      <p><small style={{ color: "var(--muted)" }}>Last changed {new Date(s.updated_at).toLocaleString()}. Every change is recorded in <Link href="/activity">Activity</Link>.</small></p>
    </main>
  );
}
