"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { NotificationItem, openNotification } from "../topbar";

export default function Notifications() {
  const router = useRouter();
  const [items, setItems] = useState(null);
  const [unreadOnly, setUnreadOnly] = useState(false);

  async function load(u = unreadOnly) {
    const res = await fetch(`/api/notifications?limit=200&unread_only=${u}`);
    if (res.status === 401) return router.replace("/login");
    setItems(await res.json());
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function readAll() {
    await fetch("/api/notifications/read-all", { method: "POST" });
    load();
  }

  if (!items) return <p>Loading…</p>;
  return (
    <main style={{ maxWidth: 700 }}>
      <p><Link href="/">← Home</Link></p>
      <h1>Notifications</h1>
      <p style={{ color: "gray" }}><small>In-app only. Unread first, then high → normal → low priority. The system never replies on its own.</small></p>
      <p style={{ display: "flex", gap: 8 }}>
        <label><input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); load(e.target.checked); }} /> Unread only</label>
        <button onClick={readAll}>Mark all read</button>
      </p>
      <div style={{ border: "1px solid #eee" }}>
        {items.map((n) => <NotificationItem key={n.id} n={n} onOpen={() => openNotification(n, router)} />)}
      </div>
      {items.length === 0 && <p>Nothing here.</p>}
    </main>
  );
}
