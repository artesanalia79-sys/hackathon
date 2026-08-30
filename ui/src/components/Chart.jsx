import React, { useLayoutEffect, useRef, useState } from "react";

const RANGE_OPTIONS = [
  { id: "hour", label: "Hour", minutes: 60 },
  { id: "day", label: "Day", minutes: 24 * 60 },
  { id: "week", label: "Week", minutes: 7 * 24 * 60 },
];

const hhmm = (iso) => (iso ? iso.slice(11, 16) : "");

const timestamp = (iso) => {
  if (!iso) return "";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
};

const percentage = (value) => (value == null ? "—" : `${(value * 100).toFixed(2)}%`);

function ChartTooltip({ svgRef, plotRef, x, y, point }) {
  const [position, setPosition] = useState(null);

  useLayoutEffect(() => {
    const svg = svgRef.current;
    const plot = plotRef.current;
    const matrix = svg?.getScreenCTM();
    if (!svg || !plot || !matrix) return;

    const svgPoint = svg.createSVGPoint();
    svgPoint.x = x;
    svgPoint.y = y;
    const pointOnScreen = svgPoint.matrixTransform(matrix);
    const plotRect = plot.getBoundingClientRect();
    const next = {
      x: pointOnScreen.x - plotRect.left,
      y: pointOnScreen.y - plotRect.top,
      alignRight: pointOnScreen.x - plotRect.left > plotRect.width * 0.72,
    };
    setPosition((current) => (
      current?.x === next.x && current?.y === next.y && current?.alignRight === next.alignRight
        ? current
        : next
    ));
  }, [plotRef, svgRef, x, y]);

  if (!position) return null;

  return (
    <div
      className={`charttooltip${position.alignRight ? " align-right" : ""}`}
      style={{ left: position.x, top: position.y }}
    >
      <strong>{timestamp(point.minute)}</strong>
      <span><b>{percentage(point.rate)}</b> conversion</span>
      <span>{point.attempts?.toLocaleString() ?? "—"} attempts</span>
      <span>{point.approved?.toLocaleString() ?? "—"} approved</span>
    </div>
  );
}

/**
 * Conversion over time for one segment, against the band it was expected to sit in.
 * Optional range controls filter the historical points already supplied by the caller.
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
  rangeFilter = false,
}) {
  const [range, setRange] = useState("hour");
  const [hoveredMinute, setHoveredMinute] = useState(null);
  const svgRef = useRef(null);
  const plotRef = useRef(null);
  const available = series.filter((p) => p.rate !== null && p.rate !== undefined);
  const selectedRange = RANGE_OPTIONS.find((option) => option.id === range) || RANGE_OPTIONS[0];
  const latestTime = available.length ? new Date(available[available.length - 1].minute).getTime() : 0;
  const rangeStart = latestTime - selectedRange.minutes * 60_000;
  const filtered = rangeFilter
    ? available.filter((point) => new Date(point.minute).getTime() >= rangeStart)
    : available;
  const pts = filtered.length >= 2 ? filtered : available;

  if (pts.length < 2) {
    return <div className="empty small">Not enough data in this window yet.</div>;
  }

  const W = 900;
  const H = height;
  const M = { l: 58, r: 20, t: 18, b: 34 };
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
  const y = (rate) => M.t + (1 - (rate - lo) / span) * ih;

  const line = pts
    .map((point, index) => `${index ? "L" : "M"}${x(point.minute).toFixed(1)},${y(point.rate).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${x(pts[pts.length - 1].minute).toFixed(1)},${M.t + ih} L${M.l},${M.t + ih} Z`;

  const ticks = [];
  const step = span > 0.4 ? 0.1 : span > 0.2 ? 0.05 : 0.02;
  for (let value = Math.ceil(lo / step) * step; value <= hi + 1e-9; value += step) {
    ticks.push(value);
  }

  const xticks = [];
  const tickCount = Math.min(6, pts.length);
  for (let index = 0; index < tickCount; index += 1) {
    xticks.push(pts[Math.round((index * (pts.length - 1)) / (tickCount - 1))]);
  }

  const clampX = (value) => Math.max(M.l, Math.min(M.l + iw, value));
  const incFrom = incidentFrom ? clampX(x(incidentFrom)) : null;
  const incTo = incidentTo ? clampX(x(incidentTo)) : incidentFrom ? M.l + iw : null;
  const hovered = hoveredMinute ? pts.find((point) => point.minute === hoveredMinute) : null;
  const hoverX = hovered ? x(hovered.minute) : null;
  const hoverY = hovered ? y(hovered.rate) : null;

  const handlePointerMove = (event) => {
    const svg = event.currentTarget;
    const matrix = svg.getScreenCTM();
    if (!matrix) return;

    const pointerOnScreen = svg.createSVGPoint();
    pointerOnScreen.x = event.clientX;
    pointerOnScreen.y = event.clientY;
    const pointer = pointerOnScreen.matrixTransform(matrix.inverse());
    const chartX = Math.max(M.l, Math.min(M.l + iw, pointer.x));
    const targetTime = t0 + ((chartX - M.l) / iw) * tspan;
    let nearest = pts[0];
    let distance = Math.abs(new Date(nearest.minute).getTime() - targetTime);
    for (let index = 1; index < pts.length; index += 1) {
      const nextDistance = Math.abs(new Date(pts[index].minute).getTime() - targetTime);
      if (nextDistance < distance) {
        nearest = pts[index];
        distance = nextDistance;
      }
    }
    setHoveredMinute(nearest.minute);
  };

  return (
    <div className="chart">
      {rangeFilter && (
        <div className="chartfilters" role="group" aria-label="Conversion chart range">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={`chartfilter${range === option.id ? " on" : ""}`}
              aria-pressed={range === option.id}
              onClick={() => {
                setRange(option.id);
                setHoveredMinute(null);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      <div className="chartplot" ref={plotRef}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          width="100%"
          height={height}
          role="img"
          aria-label="Conversion over time"
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoveredMinute(null)}
        >
          {incFrom !== null && incTo !== null && incTo > incFrom && (
            <rect x={incFrom} y={M.t} width={incTo - incFrom} height={ih}
                  fill="#f87171" opacity="0.07" />
          )}

          {ticks.map((value) => (
            <g key={value}>
              <line x1={M.l} y1={y(value)} x2={M.l + iw} y2={y(value)}
                    stroke="#1c2635" strokeWidth="1" />
              <text x={M.l - 10} y={y(value) + 4} textAnchor="end" fontSize="12" fill="#6f83a0">
                {(value * 100).toFixed(0)}%
              </text>
            </g>
          ))}

          {alertThreshold != null && alertThreshold > lo && alertThreshold < hi && (
            <>
              <line x1={M.l} y1={y(alertThreshold)} x2={M.l + iw} y2={y(alertThreshold)}
                    stroke="#fbbf24" strokeWidth="1" strokeDasharray="3 5" opacity="0.8" />
              <text x={M.l + iw} y={y(alertThreshold) - 7} textAnchor="end"
                    fontSize="11.5" fill="#fbbf24">
                alert threshold
              </text>
            </>
          )}

          {expected != null && (
            <>
              <line x1={M.l} y1={y(expected)} x2={M.l + iw} y2={y(expected)}
                    stroke="#34d399" strokeWidth="1.5" strokeDasharray="6 4" opacity="0.9" />
              <text x={M.l + iw} y={y(expected) - 7} textAnchor="end"
                    fontSize="11.5" fill="#34d399">
                expected {(expected * 100).toFixed(1)}%
              </text>
            </>
          )}

          <path d={area} fill="#4da3ff" opacity="0.09" />
          <path d={line} fill="none" stroke="#4da3ff" strokeWidth="2.5"
                strokeLinecap="round" strokeLinejoin="round" />

          {incFrom !== null && (
            <line x1={incFrom} y1={M.t} x2={incFrom} y2={M.t + ih}
                  stroke="#f87171" strokeWidth="1.5" opacity="0.85" />
          )}
          {incidentTo && (
            <line x1={clampX(x(incidentTo))} y1={M.t} x2={clampX(x(incidentTo))}
                  y2={M.t + ih} stroke="#34d399" strokeWidth="1.5" opacity="0.85" />
          )}

          {hovered && (
            <g className="charthover" aria-hidden="true">
              <line x1={hoverX} y1={M.t} x2={hoverX} y2={M.t + ih}
                    stroke="#3e4fe0" strokeWidth="1" strokeDasharray="3 4" />
              <circle cx={hoverX} cy={hoverY} r="7" fill="#ffffff" stroke="#3e4fe0" strokeWidth="2" />
              <circle cx={hoverX} cy={hoverY} r="3" fill="#3e4fe0" />
            </g>
          )}

          <line x1={M.l} y1={M.t + ih} x2={M.l + iw} y2={M.t + ih}
                stroke="#2a3a52" strokeWidth="1" />
          {xticks.map((point, index) => (
            <text key={index} x={x(point.minute)} y={H - 10} textAnchor="middle"
                  fontSize="12" fill="#6f83a0">
              {hhmm(point.minute)}
            </text>
          ))}
        </svg>

        {hovered && <ChartTooltip svgRef={svgRef} plotRef={plotRef} x={hoverX} y={hoverY} point={hovered} />}
      </div>

      <div className="chartlegend small">
        <span><i className="sw obs" /> observed conversion</span>
        <span><i className="sw exp" /> expected for this hour &amp; weekday</span>
        {alertThreshold != null && <span><i className="sw alert" /> fires below this</span>}
        {incidentFrom && <span><i className="sw inc" /> incident open</span>}
        <span className="spacer" />
        <span className={live ? "livetag" : "frozentag"}>
          {live ? "live" : "frozen, this incident is over"}
        </span>
      </div>
      {caption && <div className="small muted chartcaption">Window: {caption}.</div>}
    </div>
  );
}
