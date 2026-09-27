"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { EventList } from "./describe";

const PAGE = 50;

export default function Activity() {
  const router = useRouter();
  const [events, setEvents] = useState(null);
  const [more, setMore] = useState(false);

  async function load(beforeId) {
    const q = new URLSearchParams({ limit: PAGE, ...(beforeId ? { before_id: beforeId } : {}) });
    const res = await fetch(`/api/activity?${q}`);
    if (res.status === 401) return router.replace("/login");
    const page = await res.json();
    setEvents((prev) => (beforeId ? [...prev, ...page] : page));
    setMore(page.length === PAGE);
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!events) return <p>Loading…</p>;

  return (
    <main>
      <p><Link href="/">← Home</Link></p>
      <h1>Activity</h1>
      <EventList events={events} />
      {more && <button onClick={() => load(events[events.length - 1].id)}>Load more</button>}
    </main>
  );
}
