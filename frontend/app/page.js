"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function Home() {
  const router = useRouter();
  const [email, setEmail] = useState(null);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    fetch("/api/auth/me").then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      setEmail((await res.json()).email);
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
      <h2>System status</h2>
      <ul>
        {health ? Object.entries(health).map(([k, v]) => <li key={k}>{k}: {v}</li>) : <li>Checking…</li>}
      </ul>
      <button onClick={logout}>Sign out</button>
    </main>
  );
}
