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
    <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
      <h1>Sign in</h1>
      <label>
        Email
        <input name="email" type="email" autoComplete="username" required style={{ display: "block", width: "100%" }} />
      </label>
      <label>
        Password
        <input name="password" type="password" autoComplete="current-password" required style={{ display: "block", width: "100%" }} />
      </label>
      <button type="submit">Sign in</button>
      {error && <p role="alert" style={{ color: "crimson" }}>{error}</p>}
    </form>
  );
}
