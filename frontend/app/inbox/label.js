const TONE = { reply: "success", auto_reply: "warning", bounce: "danger", unrelated: "" };

// Reply-detection label (M15); hover shows which rule matched.
export function LabelBadge({ m }) {
  if (!m.label) return null;
  const text = m.label === "bounce" ? `${m.bounce_type} bounce` : m.label.replace("_", "-");
  return <span className={`badge${TONE[m.label] ? ` badge-${TONE[m.label]}` : ""}`} title={m.label_rule}>{text}</span>;
}
