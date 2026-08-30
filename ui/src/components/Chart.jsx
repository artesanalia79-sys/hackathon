import React from "react";

const hhmm = (iso) => (iso ? iso.slice(11, 16) : "");

/**
 * Conversion over time for one segment, against the band it was expected to sit in.
 *
 * The window is decided by the caller and stated in the caption, because "what am I
 * looking at" should never be a guess: a live incident runs to now, a finished one is
 * bounded and stops moving.
 */
export default function Chart({
  series = [],
  expected,
  alertThreshold,
  incidentFrom,
  incidentTo,
  caption,
  live = true,
  height = 250,
}) {
  const pts = series.filter((p) => p.rate !== null && p.rate !== undefined);
  if (pts.length < 2) {
    return <div className="empty small">Not enough data in this window yet.</div>;
  }

  const W = 900;
  const H = height;
  const M = { l: 50, r: 18, t: 14, b: 30 };
  const iw = W - M.l - M.r;
  const ih = H - M.t - M.b;

  const rates = pts.map((p) => p.rate);
  const candidates = [...rates, expected, alertThreshold].filter((v) => v != null);
  let lo = Math.min(...candidates);
  let hi = Math.max(...candidates);
  const pad = Math.max(0.02, (hi - lo) * 0.18);
  lo = Math.max(0, lo - pad);
  hi = Math.min(1, hi + pad);
  const span = Math.max(0.02, hi - lo);

  const t0 = new Date(pts[0].minute).getTime();
  const t1 = new Date(pts[pts.length - 1].minute).getTime();
  const tspan = Math.max(1, t1 - t0);
  const x = (iso) => M.l + ((new Date(iso).getTime() - t0) / tspan) * iw;
  const y = (r) => M.t + (1 - (r - lo) / span) * ih;

  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(p.minute).toFixed(1)},${y(p.rate).toFixed(1)}`).join(" ");
  const area = `${line} L${x(pts[pts.length - 1].minute).toFixed(1)},${M.t + ih} L${M.l},${M.t + ih} Z`;

  // y ticks at round percentages
  const ticks = [];
  const step = span > 0.4 ? 0.1 : span > 0.2 ? 0.05 : 0.02;
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);

  // x ticks, evenly spaced across the window
  const xticks = [];
  const n = Math.min(6, pts.length);
  for (let i = 0; i < n; i++) xticks.push(pts[Math.round((i * (pts.length - 1)) / (n - 1))]);

  const clampX = (v) => Math.max(M.l, Math.min(M.l + iw, v));
  const incFrom = incidentFrom ? clampX(x(incidentFrom)) : null;
  const incTo = incidentTo ? clampX(x(incidentTo)) : incidentFrom ? M.l + iw : null;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height} role="img">
        {/* the stretch of time the incident was open */}
        {incFrom !== null && incTo !== null && incTo > incFrom && (
          <rect x={incFrom} y={M.t} width={incTo - incFrom} height={ih}
                fill="#f87171" opacity="0.07" />
        )}

        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} y1={y(v)} x2={M.l + iw} y2={y(v)} stroke="#1c2635" strokeWidth="1" />
            <text x={M.l - 8} y={y(v) + 3.5} textAnchor="end" fontSize="10" fill="#6f83a0">
              {(v * 100).toFixed(0)}%
            </text>
          </g>
        ))}

        {alertThreshold != null && alertThreshold > lo && alertThreshold < hi && (
          <>
            <line x1={M.l} y1={y(alertThreshold)} x2={M.l + iw} y2={y(alertThreshold)}
                  stroke="#fbbf24" strokeWidth="1" strokeDasharray="3 5" opacity="0.8" />
            <text x={M.l + iw} y={y(alertThreshold) - 5} textAnchor="end" fontSize="9.5" fill="#fbbf24">
              alert threshold
            </text>
          </>
        )}

        {expected != null && (
          <>
            <line x1={M.l} y1={y(expected)} x2={M.l + iw} y2={y(expected)}
                  stroke="#34d399" strokeWidth="1.5" strokeDasharray="6 4" opacity="0.9" />
            <text x={M.l + iw} y={y(expected) - 6} textAnchor="end" fontSize="9.5" fill="#34d399">
              expected {(expected * 100).toFixed(1)}%
            </text>
          </>
        )}

        <path d={area} fill="#4da3ff" opacity="0.13" />
        <path d={line} fill="none" stroke="#4da3ff" strokeWidth="2" />

        {incFrom !== null && (
          <line x1={incFrom} y1={M.t} x2={incFrom} y2={M.t + ih}
                stroke="#f87171" strokeWidth="1.5" opacity="0.85" />
        )}
        {incidentTo && (
          <line x1={clampX(x(incidentTo))} y1={M.t} x2={clampX(x(incidentTo))} y2={M.t + ih}
                stroke="#34d399" strokeWidth="1.5" opacity="0.85" />
        )}

        <line x1={M.l} y1={M.t + ih} x2={M.l + iw} y2={M.t + ih} stroke="#2a3a52" strokeWidth="1" />
        {xticks.map((p, i) => (
          <text key={i} x={x(p.minute)} y={H - 10} textAnchor="middle" fontSize="10" fill="#6f83a0">
            {hhmm(p.minute)}
          </text>
        ))}
      </svg>

      <div className="chartlegend small">
        <span><i className="sw obs" /> observed conversion</span>
        <span><i className="sw exp" /> expected for this hour &amp; weekday</span>
        {alertThreshold != null && <span><i className="sw alert" /> fires below this</span>}
        {incidentFrom && <span><i className="sw inc" /> incident open</span>}
        <span className="spacer" />
        <span className={live ? "livetag" : "frozentag"}>{live ? "live" : "frozen — this incident is over"}</span>
      </div>
      {caption && <div className="small muted" style={{ marginTop: 5 }}>Window: {caption}.</div>}
    </div>
  );
}
