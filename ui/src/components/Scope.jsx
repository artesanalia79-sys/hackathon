import React from "react";
import { scopePart, scopeParts } from "../api.js";

/** The scope of an incident as labelled chips — a flag for the country, names for the rest. */
export function ScopeChips({ scope, compact }) {
  const parts = scopeParts(scope);

  if (!parts.length) {
    return (
      <div className={`scopechips${compact ? " compact" : ""}`}>
        <span className="scopechip wide">
          <span className="flag">🌐</span>
          <span className="body">
            {!compact && <span className="k">Blast radius</span>}
            <span className="v">Whole platform</span>
          </span>
        </span>
      </div>
    );
  }

  return (
    <div className={`scopechips${compact ? " compact" : ""}`}>
      {parts.map((p) => (
        <span className={`scopechip ${p.dimension}`} key={p.dimension} title={`${p.label}: ${p.text}`}>
          {p.flag && <span className="flag">{p.flag}</span>}
          <span className="body">
            {!compact && <span className="k">{p.label}</span>}
            <span className="v">{p.text}</span>
          </span>
        </span>
      ))}
    </div>
  );
}

const TOKEN = /\b(provider|issuer|brand|method|country|merchant)=([A-Za-z0-9_-]+)/g;

/**
 * Diagnosis prose with its `country=CO` fragments lifted into inline chips.
 * The engine writes one string; the reader should not have to parse it.
 */
export function ScopeProse({ text }) {
  if (!text) return null;
  const out = [];
  let last = 0;
  let m;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const p = scopePart(m[1], m[2]);
    out.push(
      <span className="inlinescope" key={`${m.index}-${p.value}`} title={`${p.label}: ${p.text}`}>
        {p.flag && <span className="flag">{p.flag}</span>}
        {p.text}
      </span>,
    );
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

export default ScopeChips;
