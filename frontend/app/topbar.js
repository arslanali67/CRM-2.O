"use client";
// F1: app shell. Sidebar (grouped navigation with live counts), top bar (search, sending pill, bell, theme,
// account), mobile drawer. The sign-in page renders without the shell.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

// ---------- icons (inline SVG, 24x24 stroke paths) ----------
const P = {
  home: "M3 11l9-7 9 7M5 10v10h14V10",
  building: "M4 21V5a2 2 0 012-2h8a2 2 0 012 2v16M16 9h2a2 2 0 012 2v10M8 7h4M8 11h4M8 15h4M3 21h18",
  pen: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  send: "M4 12l16-8-6 16-3-7-7-1z",
  inbox: "M3 13h5l1 3h6l1-3h5M5 5h14l2 8v6H3v-6z",
  target: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 16a4 4 0 100-8 4 4 0 000 8zM12 12h.01",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  check: "M4 5h16v14H4zM8 12l3 3 5-6",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  history: "M3 12a9 9 0 103-6.7L3 8M3 3v5h5M12 7v5l3 2",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  template: "M4 4h16v6H4zM4 14h7v6H4zM15 14h5v6h-5z",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  ban: "M12 21a9 9 0 100-18 9 9 0 000 18zM5.6 5.6l12.8 12.8",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  mail: "M3 5h18v14H3zM3 6l9 7 9-7",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-2.9 1.2V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-2.9-1.2l-.1.1a2 2 0 11-2.8-2.8l.1-.1A1.7 1.7 0 003 15H3a2 2 0 110-4h.1a1.7 1.7 0 001.2-2.9l-.1-.1a2 2 0 112.8-2.8l.1.1A1.7 1.7 0 0010 3.1V3a2 2 0 114 0v.1a1.7 1.7 0 002.9 1.2l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 001.2 2.9H21a2 2 0 110 4h-.1z",
  archive: "M3 4h18v4H3zM5 8v12h14V8M10 12h4",
  bell: "M6 8a6 6 0 1112 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 003.4 0",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  menu: "M4 6h16M4 12h16M4 18h16",
};
export const Icon = ({ name }) => <svg viewBox="0 0 24 24" aria-hidden="true"><path d={P[name]} /></svg>;

const NAV = [
  ["Work", [["/", "Dashboard", "home"], ["/companies", "Leads", "building"], ["/compose", "Compose", "pen"],
            ["/outbox", "Outbox", "send", "queued"], ["/inbox", "Inbox", "inbox", "unread"],
            ["/opportunities", "Opportunities", "target"], ["/interviews", "Interviews", "calendar"],
            ["/tasks", "Tasks", "check", "tasks"]]],
  ["Insights", [["/analytics", "Analytics", "chart"], ["/history", "History", "history"], ["/activity", "Activity", "activity"]]],
  ["Setup", [["/templates", "Templates", "template"], ["/import", "Import", "upload"], ["/duplicates", "Duplicates", "copy"],
             ["/do-not-contact", "Do-not-contact", "ban"], ["/profile", "Profile & CV", "user"],
             ["/email-account", "Email account", "mail"], ["/settings", "Settings", "settings"],
             ["/backup", "Backup & export", "archive"]]],
];

const active = (path, href) => (href === "/" ? path === "/" : path === href || path.startsWith(href + "/"));

// ---------- notifications (also used by the Notifications page) ----------
const DOT = { high: "var(--danger)", normal: "var(--accent)", low: "var(--muted)" };

export async function openNotification(n, router) {
  await fetch(`/api/notifications/${n.id}/read`, { method: "POST" });
  router.push(n.link);
}

export function NotificationItem({ n, onOpen }) {
  return (
    <button onClick={onOpen} className="menu-item" style={{ display: "block", minHeight: 0, whiteSpace: "normal", lineHeight: 1.4,
      background: n.read_at ? "transparent" : "var(--accent-bg)", borderRadius: 8, marginBottom: 2 }}>
      <span style={{ color: DOT[n.priority] }}>●</span> <b style={{ fontWeight: n.read_at ? 400 : 600 }}>{n.title}</b>
      {n.body && <div><small style={{ color: "var(--muted)" }}>{n.body.slice(0, 120)}</small></div>}
      <div><small style={{ color: "var(--muted)" }}>{new Date(n.created_at).toLocaleString()}{n.company_name && ` · ${n.company_name}`}</small></div>
    </button>
  );
}

// ---------- search (M22) ----------
const KINDS = [["companies", "Companies"], ["contacts", "Contacts"], ["emails", "Sent emails"], ["replies", "Replies"],
               ["templates", "Templates"], ["notes", "Notes"]];

function GlobalSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);

  useEffect(() => {
    if (q.trim().length < 2) { setRes(null); return; }
    const t = setTimeout(() => {
      fetch(`/api/search?q=${encodeURIComponent(q.trim())}`).then((r) => r.ok && r.json()).then((d) => d && setRes(d));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  const go = (link) => { setQ(""); setRes(null); router.push(link); };
  const empty = res && KINDS.every(([k]) => res[k].length === 0);

  return (
    <div style={{ position: "relative", flex: "1 1 360px", maxWidth: 520 }}>
      <input type="search" placeholder="Search companies, contacts, emails, replies…" aria-label="Search" value={q}
             onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Escape" && setQ("")} style={{ width: "100%" }} />
      {res && (
        <div className="menu" style={{ left: 0, right: 0, maxHeight: 460, overflowY: "auto" }}>
          {empty && <p style={{ padding: 8, margin: 0, color: "var(--muted)" }}>Nothing found for “{res.q}”.</p>}
          {KINDS.filter(([k]) => res[k].length).map(([k, label]) => (
            <div key={k}>
              <div className="nav-group" style={{ padding: "6px 10px 2px" }}>{label}</div>
              {res[k].map((x) => (
                <button key={`${k}-${x.id}`} className="menu-item" onClick={() => go(x.link)}>
                  {x.title} {x.detail && <small style={{ color: "var(--muted)" }}>· {x.detail}</small>}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- small hooks ----------
function useClickAway(ref, onAway) {
  useEffect(() => {
    const h = (e) => ref.current && !ref.current.contains(e.target) && onAway();
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [ref, onAway]);
}

function usePoll(url, ms, path) {
  const [data, setData] = useState(null);
  useEffect(() => {
    const load = () => fetch(url).then((r) => (r.ok ? r.json() : null)).then(setData).catch(() => {});
    load();
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  }, [url, ms, path]);
  return data;
}

// ---------- top bar pieces ----------
function Bell({ count }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const ref = useRef(null);
  useClickAway(ref, () => setOpen(false));

  async function toggle() {
    if (!open) setItems(await fetch("/api/notifications?limit=10").then((r) => r.json()));
    setOpen(!open);
  }
  const unread = count?.unread || 0;
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="icon-btn" onClick={toggle} aria-label={`Notifications: ${unread} unread`}>
        <Icon name="bell" />{unread > 0 && <span className="dot-count">{unread}</span>}
      </button>
      {open && (
        <div className="menu" style={{ width: 380, maxHeight: 460, overflowY: "auto" }}>
          {items.length === 0 && <p style={{ padding: 8, margin: 0, color: "var(--muted)" }}>No notifications.</p>}
          {items.map((n) => <NotificationItem key={n.id} n={n} onOpen={() => { setOpen(false); openNotification(n, router); }} />)}
          <div style={{ padding: 8 }}><Link href="/notifications" onClick={() => setOpen(false)}>All notifications →</Link></div>
        </div>
      )}
    </div>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const t = document.documentElement.dataset.theme;
    setDark(t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches);
  }, []);
  function toggle() {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch {}
    setDark(!dark);
  }
  return (
    <button className="icon-btn" onClick={toggle} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}>
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}

function Account() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const ref = useRef(null);
  useClickAway(ref, () => setOpen(false));
  useEffect(() => { fetch("/api/auth/me").then((r) => r.ok && r.json()).then((d) => d && setEmail(d.email)); }, []);
  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
  }
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="icon-btn" onClick={() => setOpen(!open)} aria-label="Account menu" aria-expanded={open}
              style={{ borderRadius: "50%", background: "var(--accent-bg)", color: "var(--accent)", fontWeight: 700 }}>
        {(email[0] || "?").toUpperCase()}
      </button>
      {open && (
        <div className="menu">
          <div style={{ padding: "6px 10px", color: "var(--muted)" }}><small>Signed in as</small><div style={{ color: "var(--text)" }}>{email}</div></div>
          <hr style={{ margin: "6px 0" }} />
          <Link className="menu-item" href="/profile" onClick={() => setOpen(false)}>Profile & CV</Link>
          <Link className="menu-item" href="/settings" onClick={() => setOpen(false)}>Settings</Link>
          <button className="menu-item" onClick={signOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

// ---------- the shell ----------
export default function Shell({ children }) {
  const path = usePathname();
  const [navOpen, setNavOpen] = useState(false);
  const bare = path === "/login";
  const sending = usePoll("/api/sending", 15000, path);
  const notif = usePoll("/api/notifications/count", 30000, path);
  const tasks = usePoll("/api/tasks/counts", 60000, path);
  useEffect(() => setNavOpen(false), [path]);

  if (bare) return children;
  const counts = { queued: sending?.queued, unread: notif?.unread, tasks: tasks ? tasks.overdue + tasks.due_today : 0 };
  const tone = { queued: "badge-warning", unread: "badge-accent", tasks: "badge-danger" };

  return (
    <div className={`shell${navOpen ? " nav-open" : ""}`}>
      <nav className="sidebar" aria-label="Main">
        <Link href="/" className="brand"><span className="brand-mark">JO</span>Job Outreach</Link>
        {NAV.map(([group, links]) => (
          <div key={group}>
            <div className="nav-group">{group}</div>
            {links.map(([href, label, icon, count]) => (
              <Link key={href} href={href} className="nav-link" aria-current={active(path, href) ? "page" : undefined}>
                <Icon name={icon} />{label}
                {count && counts[count] > 0 && <span className={`badge ${tone[count]} count`}>{counts[count]}</span>}
              </Link>
            ))}
          </div>
        ))}
      </nav>
      <div className="scrim" onClick={() => setNavOpen(false)} />
      <div className="main">
        <header className="topbar">
          <button className="icon-btn hamburger" onClick={() => setNavOpen(true)} aria-label="Open menu"><Icon name="menu" /></button>
          <GlobalSearch />
          <div className="grow" />
          {sending && (
            <Link href="/outbox" className={`pill${sending.enabled ? " pill-on" : ""}`}
                  title={sending.enabled ? "Queued emails are being sent" : "Nothing is sent until you switch sending on"}>
              <span className="dot" />Sending {sending.enabled ? "ON" : "off"}
            </Link>
          )}
          <Bell count={notif} />
          <ThemeToggle />
          <Account />
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  );
}
