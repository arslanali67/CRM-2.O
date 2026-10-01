"use client";
// F5: notifications grouped by day, unread/all switch, priority dot, Mark all read. Opening one marks it read and goes
// to its link. In-app only.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EmptyState, Loading, PageHeader, Tabs, useToast } from "../ui";
import { announceChange, openNotification } from "../topbar";

const DOT = { high: "var(--danger)", normal: "var(--accent)", low: "var(--muted)" };
const KIND = { reply: "↩", auto_reply: "⟲", bounce: "⚠", send_failed: "✕", send_cancelled: "⊘", sync_failing: "⟳", ai_failed: "✦", interview: "📅" };

function day(ts) {
  const d = new Date(ts), t = new Date();
  const same = (a, b) => a.toDateString() === b.toDateString();
  if (same(d, t)) return "Today";
  const y = new Date(t); y.setDate(t.getDate() - 1);
  return same(d, y) ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

export default function Notifications() {
  const router = useRouter();
  const toast = useToast();
  const [items, setItems] = useState(null);
  const [view, setView] = useState("all");

  async function load(v = view) {
    const res = await fetch(`/api/notifications?limit=200&unread_only=${v === "unread"}`);
    if (res.status === 401) return router.replace("/login");
    setItems(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function readAll() {
    const r = await fetch("/api/notifications/read-all", { method: "POST" }).then((x) => x.json());
    toast(r.marked ? `${r.marked} marked as read.` : "Nothing to mark.");
    announceChange();
    load();
  }

  const unread = items ? items.filter((n) => !n.read_at).length : 0;
  const groups = [];
  (items || []).forEach((n) => {
    const g = day(n.created_at);
    (groups.find((x) => x[0] === g) || (groups.push([g, []]), groups[groups.length - 1]))[1].push(n);
  });

  return (
    <main>
      <PageHeader title="Notifications" sub="In-app only. Unread first, then high → normal → low priority. The system never replies on its own."
                  actions={<button onClick={readAll} disabled={!unread}>Mark all read</button>} />
      <Tabs tabs={["all", "unread"]} value={view} onChange={(v) => { setView(v); load(v); }} />
      {!items ? <Loading what="notifications" /> : items.length === 0 ? (
        <EmptyState title={view === "unread" ? "You're all caught up" : "No notifications yet"}>Replies, bounces, sending problems and interview reminders appear here.</EmptyState>
      ) : groups.map(([g, list]) => (
        <section key={g} style={{ marginBottom: 16 }}>
          <h3 style={{ margin: "0 0 6px", color: "var(--muted)", fontSize: 13 }}>{g}</h3>
          <div className="card" style={{ padding: 0, overflow: "hidden" }}>
            {list.map((n) => (
              <button key={n.id} className="notif-row" data-unread={!n.read_at || undefined} onClick={() => openNotification(n, router)}>
                <span className="notif-dot" style={{ background: DOT[n.priority] }} aria-label={`${n.priority} priority`} />
                <span aria-hidden="true" style={{ width: 20, textAlign: "center" }}>{KIND[n.kind] || "•"}</span>
                <span style={{ minWidth: 0, flex: 1 }}>
                  <b style={{ fontWeight: n.read_at ? 400 : 700 }}>{n.title}</b>
                  {n.body && <small style={{ display: "block", color: "var(--muted)" }}>{n.body.slice(0, 140)}</small>}
                </span>
                <small style={{ color: "var(--muted)", whiteSpace: "nowrap" }}>{new Date(n.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}{n.company_name && ` · ${n.company_name}`}</small>
              </button>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}
