"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Login() {
  const router = useRouter();
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setError("");
    const form = new FormData(e.target);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
    });
    if (res.ok) router.replace("/");
    else if (res.status === 401) setError("Invalid email or password");
    else if (res.status === 429) setError((await res.json()).detail);  // M30 lockout: says how long to wait
    else setError("Server error");
  }

  return (
    <div className="auth">
      <form onSubmit={submit} className="card" style={{ display: "grid", gap: 14 }}>
        <div className="brand" style={{ padding: 0 }}><span className="brand-mark">JO</span>Job Outreach</div>
        <h1 style={{ fontSize: 22, margin: 0 }}>Sign in</h1>
        <label className="field" style={{ margin: 0 }}>
          <span>Email</span>
          <input name="email" type="email" autoComplete="username" required />
        </label>
        <label className="field" style={{ margin: 0 }}>
          <span>Password</span>
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        <button type="submit" className="btn-primary" style={{ minHeight: 38 }}>Sign in</button>
        {error && <p role="alert" className="error-box" style={{ margin: 0 }}>{error}</p>}
      </form>
    </div>
  );
}
