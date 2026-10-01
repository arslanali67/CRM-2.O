"use client";
// F5: two-pane inbox. List (search, counted label tabs) on the left, reading pane on the right; the selected message
// lives in the URL (?m=<id>); arrow keys move through the list; on a phone the pane replaces the list with a Back button.
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CreateOpportunity } from "../opportunities/shared";
import { Badge, EmptyState, Loading, PageHeader, Tabs, ago } from "../ui";
import { Analysis } from "./analysis";
import { LabelBadge } from "./label";

const LABELS = [["", "all"], ["reply", "replies"], ["auto_reply", "auto-replies"], ["bounce", "bounces"], ["unrelated", "unrelated"]];

function SyncStrip({ onSynced }) {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const load = () => fetch("/api/inbox-sync").then((r) => r.ok && r.json()).then((d) => d && setS(d));
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, []);

  async function run() {
    setBusy(true); setMsg("Syncing (read-only)…");
    const r = await fetch("/api/inbox-sync/run", { method: "POST" }).then((x) => x.json());
    setBusy(false);
    setMsg(r.action === "synced" ? "Up to date." : r.action === "locked" ? "A sync is already running." : r.error || r.action);
    load(); onSynced();
  }
  if (!s) return null;
  const last = s.mailboxes.map((b) => b.last_sync_at).filter(Boolean).sort().pop();
  const failing = s.mailboxes.filter((b) => b.last_ok === false);
  return (
    <div className="card sync-strip" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: "8px 14px",
         borderColor: failing.length ? "var(--danger)" : undefined }}>
      <span><b>Inbox sync</b> <small style={{ color: "var(--muted)" }}>read-only · every 2 min · nothing is marked read or changed</small></span>
      <small style={{ color: failing.length ? "var(--danger)" : "var(--muted)" }}>
        {failing.length ? failing.map((b) => `${b.imap_name || b.mailbox}: ${b.last_error || "failing"}`).join(" · ")
          : last ? `synced ${ago(last)} · ${s.mailboxes.reduce((n, b) => n + b.seen_count, 0)} examined, ${s.stored_total} stored` : "not synced yet"}
      </small>
      <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
        {msg && <small>{msg}</small>}
        {!s.account_ready && <Link href="/email-account"><small>Connect an email account</small></Link>}
        <button className="btn-sm" onClick={run} disabled={busy || !s.account_ready}>Sync now</button>
      </span>
    </div>
  );
}

export default function Inbox() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [label, setLabel] = useState("");
  const [msgs, setMsgs] = useState(null);
  const [counts, setCounts] = useState({});
  const [sel, setSel] = useState(null);       // message id from the URL
  const [open, setOpen] = useState(null);     // full message
  const [ai, setAi] = useState(null);

  useEffect(() => {
    fetch("/api/ai/status").then((r) => r.ok && r.json()).then((d) => d && setAi(d));
    const p = new URLSearchParams(window.location.search);
    setQ(p.get("q") || ""); setLabel(p.get("label") || "");
    setSel(p.get("m") ? Number(p.get("m")) : null);
    loadList(p.get("q") || "", p.get("label") || "");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function loadList(query = q, lab = label) {
    const params = new URLSearchParams(Object.entries({ q: query, label: lab }).filter(([, v]) => v));
    const res = await fetch(`/api/inbox?${params}`);
    if (res.status === 401) return router.replace("/login");
    setMsgs(await res.json());
    // tab counts come from the unfiltered-by-label list
    const all = await fetch(`/api/inbox${query ? `?q=${encodeURIComponent(query)}` : ""}`).then((r) => r.json());
    setCounts({ "": all.length, ...Object.fromEntries(LABELS.slice(1).map(([k]) => [k, all.filter((m) => m.label === k).length])) });
  }

  const loadOne = useCallback(async (id) => {
    if (!id) return setOpen(null);
    const r = await fetch(`/api/inbox/${id}`);
    setOpen(r.ok ? await r.json() : null);
  }, []);
  useEffect(() => { loadOne(sel); }, [sel, loadOne]);

  function url(next) {
    const p = new URLSearchParams(Object.entries({ q: next.q ?? q, label: next.label ?? label, m: next.m === null ? "" : next.m ?? sel ?? "" }).filter(([, v]) => v));
    window.history.replaceState(null, "", p.toString() ? `/inbox?${p}` : "/inbox");
  }
  const select = (id) => { setSel(id); url({ m: id }); };
  const setLab = (lab) => { setLabel(lab); url({ label: lab }); loadList(q, lab); };

  function onKey(e) {
    if (!msgs?.length || !["ArrowDown", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const i = msgs.findIndex((m) => m.id === sel);
    const next = msgs[Math.min(msgs.length - 1, Math.max(0, i + (e.key === "ArrowDown" ? 1 : -1)))];
    if (next) { select(next.id); document.getElementById(`msg-${next.id}`)?.scrollIntoView({ block: "nearest" }); }
  }

  return (
    <main>
      <PageHeader title="Inbox" sub="Only outreach-related messages are stored. The system never replies on its own."
                  actions={ai && <small style={{ color: "var(--muted)" }}>AI ({ai.model}): {ai.enabled ? `on · ${ai.ok || 0} analysed, ${ai.pending} waiting${ai.error ? `, ${ai.error} errors` : ""}` : <>off · <Link href="/settings">Settings</Link></>}</small>} />
      <SyncStrip onSynced={() => loadList()} />
      <div style={{ marginTop: 12 }}>
        <Tabs tabs={LABELS.map(([k, name]) => `${name} (${counts[k] ?? 0})`)} value={`${LABELS.find(([k]) => k === label)?.[1]} (${counts[label] ?? 0})`}
              onChange={(t) => setLab(LABELS.find(([, n]) => t.startsWith(n + " "))?.[0] ?? "")} />
      </div>

      {!msgs ? <Loading what="messages" /> : (
        <div className={`inbox-grid${open ? " has-open" : ""}`}>
          <section className="inbox-list" aria-label="Messages" tabIndex={0} onKeyDown={onKey}>
            <form className="inbox-search" onSubmit={(e) => { e.preventDefault(); url({ q }); loadList(); }}>
              <input type="search" placeholder="Search sender or subject" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
            </form>
            {msgs.length === 0 ? (
              <EmptyState title={q || label ? "No messages match" : "No relevant messages yet"}>
                {q || label ? "Try another search or label." : "Replies, auto-replies and bounces to your emails appear here."}</EmptyState>
            ) : msgs.map((m) => (
              <button key={m.id} id={`msg-${m.id}`} className={`msg-row${m.id === sel ? " selected" : ""}${m.label === "reply" ? " is-reply" : ""}`}
                      onClick={() => select(m.id)} aria-current={m.id === sel ? "true" : undefined}>
                <span className="msg-top"><b className="clip-line">{m.from_name || m.from_email}</b><small>{ago(m.received_at)}</small></span>
                <span className="clip-line">{m.subject}{m.attachment_names.length > 0 && " 📎"}</span>
                <span className="clip-line msg-snippet">{m.snippet}</span>
                <span className="msg-badges"><LabelBadge m={m} />{m.ai_label && <Badge tone="accent">AI: {m.ai_label.replaceAll("_", " ")}</Badge>}
                  {m.mailbox === "spam" && <Badge tone="warning">spam</Badge>}{m.company_name && <small style={{ color: "var(--muted)" }}>{m.company_name}</small>}</span>
              </button>
            ))}
          </section>

          <section className="inbox-pane" aria-label="Message">
            {!open ? <div className="empty" style={{ marginTop: 0 }}><b>Select a message</b>Use the list or the up and down arrow keys.</div> : (
              <article>
                <button className="btn-sm back-btn" onClick={() => select(null)}>← Back to list</button>
                <h2 style={{ margin: "0 0 8px" }}>{open.subject}</h2>
                <div className="mail-head">
                  <div><small>From</small> {open.from_name ? `${open.from_name} ` : ""}&lt;{open.from_email}&gt; <LabelBadge m={open} /></div>
                  <div><small>To</small> {open.to_emails}</div>
                  <div><small>Received</small> {open.received_at && new Date(open.received_at).toLocaleString()}</div>
                  {open.attachment_names.length > 0 && <div><small>Files</small> {open.attachment_names.join(", ")} <small style={{ color: "var(--muted)" }}>(not stored)</small></div>}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "10px 0" }}>
                  <Link className="btn btn-sm" href={`/threads/${open.thread_key}#in-${open.id}`}>Open conversation</Link>
                  {open.company_id && <Link className="btn btn-sm" href={`/companies/${open.company_id}`}>{open.company_name || "Company"}</Link>}
                  {open.label === "reply" && open.company_id && <CreateOpportunity messageId={open.id} suggestedTitle={open.subject.replace(/^(re|aw|fw|wg):\s*/i, "")} />}
                </div>
                {open.label === "reply" && <Analysis messageId={open.id} analysis={open.analysis} aiEnabled={ai?.enabled}
                                                     onChange={() => { loadOne(open.id); loadList(); }} />}
                <pre className="mail-body" style={{ marginTop: 12 }}>{open.body_text}{open.body_truncated && "\n[truncated]"}</pre>
              </article>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
