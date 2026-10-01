"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, Loading } from "../ui";
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

  if (!events) return <Loading what="activity" />;

  return (
    <main>
      <PageHeader title="Activity" sub="Everything that changed, newest first." />
      <EventList events={events} />
      {more && <button onClick={() => load(events[events.length - 1].id)}>Load more</button>}
    </main>
  );
}
