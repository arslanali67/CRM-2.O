"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { localToday } from "./tasks/panels";

export default function Home() {
  const router = useRouter();
  const [email, setEmail] = useState(null);
  const [health, setHealth] = useState(null);
  const [due, setDue] = useState(null);

  useEffect(() => {
    fetch("/api/auth/me").then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      setEmail((await res.json()).email);
      fetch(`/api/tasks/counts?today=${localToday()}`).then((r) => r.json()).then(setDue);
      setHealth(await fetch("/api/health").then((r) => r.json()));
    });
  }, [router]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!email) return <p>Loading…</p>;

  return (
    <main>
      <h1>Job Outreach CRM</h1>
      <p>Signed in as {email}</p>
      <p>
        <Link href="/companies">Leads</Link> · <Link href="/compose">Compose list</Link> · <Link href="/outbox">Outbox</Link> ·{" "}
        <Link href="/templates">Templates</Link> · <Link href="/import">Import CSV</Link> ·{" "}
        <Link href="/profile">Profile & CV</Link> · <Link href="/email-account">Email account</Link> · <Link href="/do-not-contact">Do-not-contact</Link> ·{" "}
        <Link href="/tasks">Tasks</Link> · <Link href="/activity">Activity</Link>
      </p>
      {due && (
        <p>
          <Link href="/tasks">
            <span style={{ color: due.overdue ? "crimson" : undefined }}>{due.overdue} overdue</span> · {due.due_today} due today
          </Link>
        </p>
      )}
      <h2>System status</h2>
      <ul>
        {health ? Object.entries(health).map(([k, v]) => <li key={k}>{k}: {v}</li>) : <li>Checking…</li>}
      </ul>
      <button onClick={logout}>Sign out</button>
    </main>
  );
}
