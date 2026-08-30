import React from "react";

/** Observed conversion over time against the expected band. */
export default function Sparkline({ series, expected, height = 92 }) {
  const points = (series || []).filter((p) => p.rate !== null && p.rate !== undefined);
  if (points.length < 2) {
    return <div className="empty small">not enough history yet</div>;
  }
  const w = 640;
  const rates = points.map((p) => p.rate);
  const lo = Math.max(0, Math.min(...rates, expected ?? 1) - 0.06);
  const hi = Math.min(1, Math.max(...rates, expected ?? 0) + 0.04);
  const span = Math.max(0.02, hi - lo);
  const x = (i) => (i / (points.length - 1)) * w;
  const y = (r) => height - ((r - lo) / span) * height;

  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.rate).toFixed(1)}`).join(" ");
  const area = `${line} L${w},${height} L0,${height} Z`;
  const expY = expected != null ? y(expected) : null;

  return (
    <svg viewBox={`0 0 ${w} ${height}`} width="100%" height={height} preserveAspectRatio="none">
      <defs>
        <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4da3ff" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#4da3ff" stopOpacity="0" />
        </linearGradient>
      </defs>
      {expY !== null && (
        <>
          <rect x="0" y={Math.max(0, expY - 4)} width={w} height="8" fill="#34d399" opacity="0.10" />
          <line x1="0" y1={expY} x2={w} y2={expY} stroke="#34d399" strokeWidth="1"
                strokeDasharray="5 4" opacity="0.75" />
        </>
      )}
      <path d={area} fill="url(#fade)" />
      <path d={line} fill="none" stroke="#4da3ff" strokeWidth="1.8" />
    </svg>
  );
}
