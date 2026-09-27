"use client";
import { useEffect, useRef, useState } from "react";

const full = { display: "block", width: "100%", boxSizing: "border-box" };

// Subject + body fields with click-to-insert variables (inserted at the cursor of the last focused field).
export function TemplateFields({ value, onChange }) {
  const [vars, setVars] = useState(null);
  const refs = { subject: useRef(null), body: useRef(null) };
  const lastField = useRef("body");

  useEffect(() => { fetch("/api/templates/variables").then((r) => r.ok && r.json()).then(setVars); }, []);

  function insert(name) {
    const field = lastField.current;
    const el = refs[field].current;
    const token = `{{${name}}}`;
    const start = el?.selectionStart ?? value[field].length;
    const end = el?.selectionEnd ?? start;
    onChange({ ...value, [field]: value[field].slice(0, start) + token + value[field].slice(end) });
    requestAnimationFrame(() => { el?.focus(); el?.setSelectionRange(start + token.length, start + token.length); });
  }

  return (
    <>
      <label>Subject
        <input ref={refs.subject} required value={value.subject} style={full}
               onFocus={() => { lastField.current = "subject"; }}
               onChange={(e) => onChange({ ...value, subject: e.target.value })} />
      </label>
      <label>Body (plain text)
        <textarea ref={refs.body} required rows={12} value={value.body} style={{ ...full, fontFamily: "inherit" }}
                  onFocus={() => { lastField.current = "body"; }}
                  onChange={(e) => onChange({ ...value, body: e.target.value })} />
      </label>
      {vars && (
        <details>
          <summary>Insert a variable (use <code>{"{{name | fallback}}"}</code> for a fallback when empty)</summary>
          {Object.entries(vars).map(([group, names]) => (
            <p key={group} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              <strong style={{ width: 70 }}>{group}</strong>
              {names.map((n) => <button type="button" key={n} onClick={() => insert(n)}><code>{n}</code></button>)}
            </p>
          ))}
        </details>
      )}
    </>
  );
}
