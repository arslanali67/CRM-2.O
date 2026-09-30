"use client";
// F1: the design system's components. Thin wrappers over the classes in globals.css.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export function Button({ variant = "secondary", size, className = "", ...props }) {
  const cls = ["btn", variant !== "secondary" && `btn-${variant}`, size === "sm" && "btn-sm", className].filter(Boolean).join(" ");
  return <button type="button" className={cls} {...props} />;
}

export function Field({ label, hint, error, children }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small className="hint">{hint}</small>}
      {error && <small className="err" role="alert">{error}</small>}
    </label>
  );
}

export const Card = ({ className = "", ...p }) => <div className={`card ${className}`} {...p} />;

export function Badge({ tone, children, ...p }) {
  return <span className={`badge${tone ? ` badge-${tone}` : ""}`} {...p}>{children}</span>;
}

export function PageHeader({ title, sub, actions }) {
  return (
    <div className="page-header">
      <div><h1>{title}</h1>{sub && <div className="sub">{sub}</div>}</div>
      {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub }) {
  return <div className="stat"><div className="stat-label">{label}</div><div className="stat-value">{value}</div>
    {sub && <small style={{ color: "var(--muted)" }}>{sub}</small>}</div>;
}

export function EmptyState({ title, children, action }) {
  return <div className="empty"><b>{title}</b>{children && <div>{children}</div>}{action && <div style={{ marginTop: 12 }}>{action}</div>}</div>;
}

export const Spinner = ({ label = "Loading" }) => <span className="spinner" role="status" aria-label={label} />;

export function Loading({ what = "" }) {
  return <p style={{ color: "var(--muted)" }}><Spinner /> Loading{what && ` ${what}`}…</p>;
}

export const ErrorState = ({ children }) => <div className="error-box" role="alert">{children}</div>;

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t} role="tab" aria-selected={t === value} onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  );
}

export function ago(ts) {
  if (!ts) return "";
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.round(s / 86400)} d ago`;
  return new Date(ts).toLocaleDateString();
}

export const TableWrap = ({ children }) => <div className="table-wrap">{children}</div>;

// A modal for forms (Add company, Edit contact…). Closes on Escape or a click outside.
export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title} style={{ width: wide ? "min(680px, 100%)" : undefined,
        maxHeight: "90vh", overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h2 style={{ margin: 0 }}>{title}</h2>
          <button className="btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ---------- dialogs: in-app confirm / prompt / alert (no browser pop-ups) ----------

const DialogCtx = createContext(null);

export function DialogProvider({ children }) {
  const [d, setD] = useState(null);
  const [value, setValue] = useState("");
  const input = useRef(null);

  const open = useCallback((opts) => new Promise((resolve) => {
    setValue(opts.defaultValue || "");
    setD({ ...opts, resolve });
  }), []);
  const close = (result) => { d?.resolve(result); setD(null); };

  useEffect(() => {
    if (!d) return;
    const onKey = (e) => e.key === "Escape" && close(d.kind === "prompt" ? null : false);
    window.addEventListener("keydown", onKey);
    setTimeout(() => (input.current || document.querySelector(".dialog .btn-primary, .dialog .btn-danger"))?.focus(), 0);
    return () => window.removeEventListener("keydown", onKey);
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps

  const api = {
    confirm: (title, opts = {}) => open({ kind: "confirm", title, ...opts }),
    prompt: (title, opts = {}) => open({ kind: "prompt", title, ...opts }),
    alert: (title, opts = {}) => open({ kind: "alert", title, ...opts }),
  };

  function submit(e) {
    e.preventDefault();
    if (d.kind === "prompt") {
      if (d.required && !value.trim()) return;
      return close(value);
    }
    close(true);
  }

  return (
    <DialogCtx.Provider value={api}>
      {children}
      {d && (
        <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close(d.kind === "prompt" ? null : false)}>
          <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onSubmit={submit}>
            <h2 id="dialog-title">{d.title}</h2>
            {d.body && <div className="body">{d.body}</div>}
            {d.kind === "prompt" && (
              <textarea ref={input} rows={3} aria-label={d.label || d.title} placeholder={d.placeholder || ""}
                        value={value} onChange={(e) => setValue(e.target.value)} required={!!d.required} />
            )}
            <div className="actions">
              {d.kind !== "alert" && <button type="button" onClick={() => close(d.kind === "prompt" ? null : false)}>
                {d.cancelLabel || "Cancel"}</button>}
              <button type="submit" className={d.danger ? "btn-danger" : "btn-primary"}>{d.confirmLabel || "OK"}</button>
            </div>
          </form>
        </div>
      )}
    </DialogCtx.Provider>
  );
}

export const useDialog = () => useContext(DialogCtx);

// ---------- toasts ----------

const ToastCtx = createContext(() => {});

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const show = useCallback((text, tone) => {
    const id = Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast${t.tone === "error" ? " toast-error" : ""}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
