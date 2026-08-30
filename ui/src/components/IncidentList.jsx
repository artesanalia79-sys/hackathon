import React from "react";
import { CAUSE_LABEL, clock, scopeText, usd } from "../api.js";

export default function IncidentList({ incidents, selected, onSelect, showClosed, onToggleClosed }) {
  const open = incidents.filter((i) => i.status === "watching" || i.status === "confirmed");
  const closed = incidents.filter((i) => i.status === "resolved" || i.status === "expired");
  const rows = showClosed ? [...open, ...closed] : open;

  return (
    <div className="col left">
      <div className="colhead">
        Incidents
        <span className="muted">· {open.length} open</span>
        <span className="spacer" />
        <button className="btn ghost small" style={{ padding: "2px 8px" }} onClick={onToggleClosed}>
          {showClosed ? "hide closed" : `closed (${closed.length})`}
        </button>
      </div>

      {!rows.length && (
        <div className="empty">
          Nothing is wrong.
          <div className="small" style={{ marginTop: 6 }}>
            The detector is watching every provider, country, method, brand and issuer
            against its own seasonal baseline.
          </div>
        </div>
      )}

      {rows.map((i) => {
        const isClosed = i.status === "resolved" || i.status === "expired";
        return (
          <div
            key={i.id}
            className={`inc${selected === i.id ? " sel" : ""}${isClosed ? " closed" : ""}`}
            onClick={() => onSelect(i.id)}
          >
            <div className="row1">
              <span className={`badge ${i.status}`}>{i.status}</span>
              {i.kind !== "conversion_drop" && <span className="badge kind">{i.kind.replace("_", " ")}</span>}
              <span className="money">{usd(i.cost_per_min_usd)}/min</span>
            </div>
            <div className="cause">{CAUSE_LABEL[i.cause_type] || i.cause_type || "unclassified"}</div>
            <div className="scope">{scopeText(i.scope)}</div>
            <div className="meta">
              <span>since {clock(i.started_at)}</span>
              <span>{Math.round(i.detail?.duration_min ?? 0)} min</span>
              <span>{usd(i.cost_usd)} total</span>
              {i.detail?.has_diagnosis && <span style={{ color: "#a78bfa" }}>diagnosed</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
