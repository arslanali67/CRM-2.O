"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, Loading } from "../ui";
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
const FIELDS = [...NUMBERS.map(([k]) => k), "ai_enabled", "ai_provider", "ai_model", "notify_kinds"];

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

  if (!form) return <Loading what="settings" />;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const acc = s.email_account;

  return (
    <main>
      <PageHeader title="Settings" sub="Limits, AI and notifications. Changes apply immediately and are recorded in Activity." />
      <form onSubmit={save} className="card">
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
        <p><small>API keys in .env: OpenRouter {s.ai_keys.openrouter ? "present" : "missing"} · Gemini {s.ai_keys.gemini ? "present" : "missing"}. Keys are never shown or stored here.</small></p>
        <p><label>Provider{" "}
          <select value={form.ai_provider || ""} onChange={(e) => { set("ai_provider", e.target.value || null); set("ai_model", null); }}>
            <option value="">Automatic (OpenRouter if its key is present, else Gemini)</option>
            <option value="openrouter">OpenRouter</option>
            <option value="gemini">Gemini</option>
          </select></label>
          <br /><small style={{ color: "var(--muted)" }}>Free models may log or train on what is sent (reply text, company pages, verified facts; never your CV or contacts).</small></p>
        <p><label><input type="checkbox" checked={form.ai_enabled} onChange={(e) => set("ai_enabled", e.target.checked)} /> Analyse replies with AI</label></p>
        <p>
          <label>Model: <input list="ai-models" value={form.ai_model || ""} placeholder={`default: ${s.ai_defaults[form.ai_provider || s.ai_effective_provider]}`}
                               onChange={(e) => set("ai_model", e.target.value.trim() || null)} /></label>{" "}
          <button type="button" onClick={loadModels} disabled={!s.ai_keys[form.ai_provider || s.ai_effective_provider]}>Show available models</button>
          <datalist id="ai-models">{(models || []).map((m) => <option key={m} value={m} />)}</datalist>
          <br /><small style={{ color: "var(--muted)" }}>In use: {s.ai_effective_model} ({s.ai_effective_provider}). A new model is checked against Google&apos;s list before saving.</small>
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

      <section className="card" style={{ marginTop: 16 }}>
      <h3 style={{ marginTop: 0 }}>Email account</h3>
      {acc
        ? <p>{acc.display_name ? `${acc.display_name} <${acc.email_address}>` : acc.email_address} · {acc.connected ? (acc.last_test_ok ? "connected" : "test failed") : "disconnected"}</p>
        : <p>Not configured.</p>}
      <p><Link href="/email-account">Manage email account</Link></p>
      <p><small style={{ color: "var(--muted)" }}>Last changed {new Date(s.updated_at).toLocaleString()}. Every change is recorded in <Link href="/activity">Activity</Link>.</small></p>
      </section>
    </main>
  );
}
