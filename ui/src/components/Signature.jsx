import React from "react";
import { pct } from "../api.js";

const ORDER = ["none", "hard_decline", "soft_decline", "technical", "risk_block",
               "config", "auth_required", "unknown"];

/**
 * The decline signature: each category's share of attempts, history vs now.
 * This is the picture that separates an issuer problem from a provider outage.
 */
export default function Signature({ before, during, risen = [] }) {
  const keys = ORDER.filter((k) => (before?.[k] || 0) > 0.0005 || (during?.[k] || 0) > 0.0005);
  if (!keys.length) return <div className="empty small">no signature recorded</div>;
  const max = Math.max(...keys.map((k) => Math.max(before?.[k] || 0, during?.[k] || 0)));
  return (
    <div className="sig">
      <div className="sigrow small muted">
        <span />
        <span>
          <span style={{ color: "#2b3b52" }}>▬</span> normal for this segment&nbsp;&nbsp;
          <span style={{ color: "#f87171" }}>▬</span> now
        </span>
        <span className="nums">before → now</span>
      </div>
      {keys.map((k) => (
        <div className={`sigrow${risen.includes(k) ? " risen" : ""}`} key={k}>
          <span className="name">{k}{risen.includes(k) ? " ↑" : ""}</span>
          <span className="bars">
            <span className="bar before" style={{ width: `${((before?.[k] || 0) / max) * 100}%` }} />
            <span className="bar during" style={{ width: `${((during?.[k] || 0) / max) * 100}%` }} />
          </span>
          <span className="nums">{pct(before?.[k] || 0)} → {pct(during?.[k] || 0)}</span>
        </div>
      ))}
    </div>
  );
}
