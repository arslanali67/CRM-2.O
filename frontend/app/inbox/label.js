const LABEL_STYLE = {
  reply: { background: "#c8f7c5" }, auto_reply: { background: "#fff3c4" },
  bounce: { background: "crimson", color: "white" }, unrelated: { background: "#eee" },
};

// Reply-detection label (M15); hover shows which rule matched.
export function LabelBadge({ m }) {
  if (!m.label) return null;
  const text = m.label === "bounce" ? `${m.bounce_type} bounce` : m.label.replace("_", "-");
  return <mark title={m.label_rule} style={LABEL_STYLE[m.label]}>{text}</mark>;
}
