"use client";
// F2: a small hand-made SVG bar chart (no chart library). One bar per point, gridlines, date labels,
// a tooltip per bar (<title>) and a summary for screen readers.
const W = 800, H = 200, L = 34, B = 26, T = 10;

export function BarChart({ data, label, unit = "", empty = "Nothing yet." }) {
  const max = Math.max(0, ...data.map((d) => d.value));
  const total = data.reduce((s, d) => s + d.value, 0);
  if (!data.length || total === 0) return <div className="empty" style={{ padding: 24 }}>{empty}</div>;
  const top = Math.max(1, niceMax(max));
  const plotW = W - L - 6, plotH = H - B - T;
  const step = plotW / data.length;
  const barW = Math.max(1, Math.min(28, step * 0.7));
  const y = (v) => T + plotH - (v / top) * plotH;
  const ticks = [0, top / 2, top].filter((v, i, a) => a.indexOf(v) === i && Number.isInteger(v));
  const labelIdx = [...new Set([0, Math.floor((data.length - 1) / 2), data.length - 1])];
  const peak = data.reduce((a, d) => (d.value > a.value ? d : a), data[0]);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" data-bars={data.length} data-max={max}
         aria-label={`${label}: ${total} ${unit} over ${data.length} days; most on ${peak.label} (${peak.value}).`}
         style={{ display: "block", maxHeight: 240 }}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={L} x2={W - 6} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeDasharray={v ? "4 4" : undefined} />
          <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize="12" fill="var(--muted)">{v}</text>
        </g>
      ))}
      {data.map((d, i) => (
        <rect key={d.key} x={L + i * step + (step - barW) / 2} y={y(d.value)} width={barW} height={Math.max(0, y(0) - y(d.value))}
              rx={Math.min(3, barW / 3)} fill="var(--accent)" opacity={d.value ? 1 : 0}>
          <title>{`${d.label}: ${d.value} ${unit}`}</title>
        </rect>
      ))}
      {labelIdx.map((i) => (
        <text key={i} x={L + i * step + step / 2} y={H - 6} fontSize="12" fill="var(--muted)"
              textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}>{data[i].label}</text>
      ))}
    </svg>
  );
}

function niceMax(v) {
  if (v <= 4) return v % 2 ? v + 1 : v;
  const mag = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((c) => c >= v && Number.isInteger(c / 2)) || v;
}
