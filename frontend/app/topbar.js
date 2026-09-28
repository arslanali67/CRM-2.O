"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const DOT = { high: "crimson", normal: "steelblue", low: "#aaa" };

export async function openNotification(n, router) {
  await fetch(`/api/notifications/${n.id}/read`, { method: "POST" });
  router.push(n.link);
}

export function NotificationItem({ n, onOpen }) {
  return (
    <button onClick={onOpen} style={{ display: "block", width: "100%", textAlign: "left", background: n.read_at ? "white" : "#f3f7ff",
      border: "none", borderBottom: "1px solid #eee", padding: "6px 8px", cursor: "pointer" }}>
      <span style={{ color: DOT[n.priority] }}>●</span> <b style={{ fontWeight: n.read_at ? "normal" : "bold" }}>{n.title}</b>
      {n.body && <div><small style={{ color: "gray" }}>{n.body.slice(0, 120)}</small></div>}
      <div><small style={{ color: "gray" }}>{new Date(n.created_at).toLocaleString()}{n.company_name && ` · ${n.company_name}`}</small></div>
    </button>
  );
}

// M17: bell with unread count on every page (refreshed every 30 s). Hidden on the sign-in page.
export default function TopBar() {
  const path = usePathname();
  const router = useRouter();
  const [count, setCount] = useState(null);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);

  useEffect(() => {
    if (path === "/login") return;
    const load = () => fetch("/api/notifications/count").then((r) => r.ok && r.json()).then((d) => d && setCount(d));
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [path]);

  async function toggle() {
    if (!open) setItems(await fetch("/api/notifications?limit=10").then((r) => r.json()));
    setOpen(!open);
  }

  if (path === "/login" || !count) return null;
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #eee",
      marginBottom: 16, paddingBottom: 8, position: "relative" }}>
      <Link href="/"><b>Job Outreach CRM</b></Link>
      <button onClick={toggle} aria-label={`Notifications: ${count.unread} unread`} style={{ position: "relative" }}>
        🔔{count.unread > 0 && (
          <span style={{ background: count.high ? "crimson" : "steelblue", color: "white", borderRadius: 8, padding: "0 6px",
            marginLeft: 4, fontSize: 12 }}>{count.unread}</span>
        )}
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: 36, width: 360, maxHeight: 420, overflowY: "auto", background: "white",
          border: "1px solid #ccc", boxShadow: "0 4px 12px rgba(0,0,0,.15)", zIndex: 10 }}>
          {items.length === 0 && <p style={{ padding: 8 }}>No notifications.</p>}
          {items.map((n) => (
            <NotificationItem key={n.id} n={n} onOpen={() => { setOpen(false); openNotification(n, router); }} />
          ))}
          <div style={{ padding: 8 }}><Link href="/notifications" onClick={() => setOpen(false)}>All notifications →</Link></div>
        </div>
      )}
    </div>
  );
}
