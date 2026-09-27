"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const TEXT = [["full_name", "Full name"], ["email", "Email"], ["phone", "Phone"], ["location", "Location"], ["headline", "Headline"]];
const LINKS = [["linkedin_url", "LinkedIn URL"], ["github_url", "GitHub URL"], ["portfolio_url", "Portfolio URL"]];
const LISTS = [["skills", "Skills"], ["target_roles", "Target roles"], ["target_locations", "Target locations"]];
const EMPTY_JOB = { title: "", company: "", start: "", end: "", description: "" };

const full = { display: "block", width: "100%", boxSizing: "border-box" };
const section = { marginTop: 32 };

function errorText(body) {
  if (Array.isArray(body?.detail)) return body.detail.map((d) => `${d.loc.slice(1).join(".")}: ${d.msg}`).join("; ");
  return body?.detail || "Something went wrong";
}

export default function Profile() {
  const router = useRouter();
  const [p, setP] = useState(null);
  const [vars, setVars] = useState(null);
  const [cvs, setCvs] = useState([]);
  const [msg, setMsg] = useState("");
  const [cvMsg, setCvMsg] = useState("");

  const refreshVars = () => fetch("/api/profile/variables").then((r) => r.json()).then(setVars);
  const refreshCvs = () => fetch("/api/cv").then((r) => r.json()).then(setCvs);

  useEffect(() => {
    fetch("/api/profile").then(async (res) => {
      if (res.status === 401) return router.replace("/login");
      const data = await res.json();
      for (const [k] of LISTS) data[k] = data[k].join("\n");
      setP(data);
      refreshVars();
      refreshCvs();
    });
  }, [router]);

  const set = (k, v) => setP({ ...p, [k]: v });
  const setJob = (i, k, v) => set("experience", p.experience.map((e, j) => (j === i ? { ...e, [k]: v } : e)));

  async function save(e) {
    e.preventDefault();
    const body = { ...p };
    for (const [k] of LISTS) body[k] = p[k].split("\n");
    const res = await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setMsg(res.ok ? "Saved." : errorText(await res.json()));
    if (res.ok) refreshVars();
  }

  async function upload(e) {
    e.preventDefault();
    const file = e.target.file.files[0];
    const q = new URLSearchParams({ label: e.target.label.value, filename: file.name });
    const res = await fetch(`/api/cv?${q}`, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: file });
    setCvMsg(res.ok ? "Uploaded." : errorText(await res.json()));
    if (res.ok) {
      e.target.reset();
      refreshCvs();
      refreshVars();
    }
  }

  async function makeDefault(id) {
    await fetch(`/api/cv/${id}/default`, { method: "POST" });
    refreshCvs();
  }

  if (!p) return <p>Loading…</p>;

  return (
    <main>
      <p><Link href="/">← Home</Link></p>
      <h1>Profile & CV</h1>

      <form onSubmit={save} style={{ display: "grid", gap: 12 }}>
        {TEXT.map(([k, label]) => (
          <label key={k}>{label}<input value={p[k]} onChange={(e) => set(k, e.target.value)} style={full} /></label>
        ))}
        <label>Summary<textarea rows={4} value={p.summary} onChange={(e) => set("summary", e.target.value)} style={full} /></label>
        {LISTS.map(([k, label]) => (
          <label key={k}>{label} (one per line)<textarea rows={4} value={p[k]} onChange={(e) => set(k, e.target.value)} style={full} /></label>
        ))}
        {LINKS.map(([k, label]) => (
          <label key={k}>{label}<input type="url" placeholder="https://" value={p[k]} onChange={(e) => set(k, e.target.value)} style={full} /></label>
        ))}
        <label>Work mode
          <select value={p.work_mode} onChange={(e) => set("work_mode", e.target.value)} style={full}>
            {["any", "remote", "hybrid", "onsite"].map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label>Availability<input value={p.availability} onChange={(e) => set("availability", e.target.value)} style={full} /></label>

        <fieldset>
          <legend>Experience (leave End empty for your current job)</legend>
          {p.experience.map((job, i) => (
            <div key={i} style={{ display: "grid", gap: 6, marginBottom: 16 }}>
              <input placeholder="Title" value={job.title} onChange={(e) => setJob(i, "title", e.target.value)} />
              <input placeholder="Company" value={job.company} onChange={(e) => setJob(i, "company", e.target.value)} />
              <div style={{ display: "flex", gap: 6 }}>
                <input type="month" aria-label="Start" value={job.start} onChange={(e) => setJob(i, "start", e.target.value)} />
                <input type="month" aria-label="End" value={job.end} onChange={(e) => setJob(i, "end", e.target.value)} />
              </div>
              <textarea placeholder="Description" rows={2} value={job.description} onChange={(e) => setJob(i, "description", e.target.value)} />
              <button type="button" onClick={() => set("experience", p.experience.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" onClick={() => set("experience", [...p.experience, EMPTY_JOB])}>Add job</button>
        </fieldset>

        <button type="submit">Save profile</button>
        {msg && <p role="status">{msg}</p>}
      </form>

      <section style={section}>
        <h2>CV versions</h2>
        <form onSubmit={upload} style={{ display: "grid", gap: 8 }}>
          <input name="label" placeholder="Label, e.g. Backend CV 2026" required />
          <input name="file" type="file" accept="application/pdf" required />
          <button type="submit">Upload PDF (max 5 MB)</button>
          {cvMsg && <p role="status">{cvMsg}</p>}
        </form>
        <ul>
          {cvs.map((cv) => (
            <li key={cv.id}>
              <strong>{cv.label}</strong> ({cv.filename}, {Math.ceil(cv.size_bytes / 1024)} KB){" "}
              {cv.is_default ? <em>default</em> : <button onClick={() => makeDefault(cv.id)}>Make default</button>}{" "}
              <a href={`/api/cv/${cv.id}/file`}>Download</a>
            </li>
          ))}
        </ul>
      </section>

      <section style={section}>
        <h2>Template variables</h2>
        {vars && (
          <>
            <p>
              {vars.unresolved.length === 0 ? "All variables resolve." : `${vars.unresolved.length} unresolved.`}{" "}
              {vars.default_cv_set ? "Default CV set." : <span style={{ color: "crimson" }}>No default CV.</span>}
            </p>
            <table>
              <tbody>
                {Object.entries(vars.variables).map(([k, v]) => (
                  <tr key={k}>
                    <td><code>{`{{${k}}}`}</code></td>
                    <td style={{ color: v ? "inherit" : "crimson" }}>{v || "unresolved"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </main>
  );
}
