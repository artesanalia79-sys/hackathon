import React from "react";
import { CAUSE_LABEL, clock, pct, usd } from "../api.js";
import Baseline from "./Baseline.jsx";
import Chart from "./Chart.jsx";
import { ScopeChips, ScopeProse } from "./Scope.jsx";
import Signature from "./Signature.jsx";

function Tile({ k, v, s, tone }) {
  return (
    <div className="tile">
      <div className="k">{k}</div>
      <div className={`v ${tone || ""}`}>{v}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

export default function IncidentCard({ incident, diagnosis, onAck }) {
  if (!incident) {
    return (
      <div className="col">
        <div className="empty">
          <h3 style={{ marginBottom: 8 }}>Control Tower</h3>
          Select an incident, or inject one to see the system find it.
          <div className="small" style={{ marginTop: 10, maxWidth: 460, margin: "10px auto 0" }}>
            The engine watches every segment against its own seasonal baseline, isolates
            where an excess of declines concentrates, reads the shape of the decline codes
            to say what kind of failure it is, and prices it. Then it recommends — it never
            acts.
          </div>
        </div>
      </div>
    );
  }

  const d = diagnosis;
  const attribution = incident.detail?.attribution?.[0];
  const path = attribution?.path || [];
  const isDrop = incident.kind === "conversion_drop";
  const live = incident.status === "watching" || incident.status === "confirmed";

  return (
    <div className="col">
      <div className="card">
        <header className={`inchead ${incident.status}`}>
          <div className="inchead-tags">
            <span className={`badge ${incident.status}`}>
              {live && <i className="dot" />}
              {incident.status}
            </span>
            {!isDrop && <span className="badge kind">{incident.kind.replace(/_/g, " ")}</span>}
            {incident.acknowledged_by && (
              <span className="badge ack">ack · {incident.acknowledged_by}</span>
            )}
          </div>

          <h2>{CAUSE_LABEL[incident.cause_type] || incident.cause_type || "Unclassified incident"}</h2>

          <ScopeChips scope={incident.scope} />

          <div className="inchead-meta">
            <span>
              Started <b>{clock(incident.started_at)}</b>
            </span>
            <span>
              {live ? "Running for" : "Lasted"}{" "}
              <b>{Math.round(incident.detail?.duration_min ?? 0)} min</b>
            </span>
            <span className="bleed">
              <b>{usd(incident.cost_per_min_usd)}</b>/min
            </span>
          </div>
        </header>

        <div className="grid4">
          <Tile
            k={isDrop ? "Conversion now" : "Rate now"}
            v={pct(incident.baseline?.observed_rate ?? incident.observed_rate)}
            s={`expected ${pct(incident.baseline?.expected_rate ?? incident.expected_rate)}`}
            tone="bad"
          />
          <Tile
            k={incident.kind === "data_integrity" ? "Mis-stated" : "Excess declines"}
            v={Math.round(incident.excess_declines).toLocaleString()}
            s="in the 5-minute window"
            tone="warn"
          />
          <Tile k="Cost per minute" v={usd(incident.cost_per_min_usd)} s="weighted by recoverability" tone="warn" />
          <Tile k="Cost so far" v={usd(incident.cost_usd)} s={`since ${clock(incident.started_at)}`} />
        </div>

        {d?.exec_line && (
          <div className="section">
            <h3>For the executive</h3>
            <div className="box exec">
              <ScopeProse text={d.exec_line} />
            </div>
          </div>
        )}

        <div className="section">
          <h3>
            Conversion for this segment
            {incident.chart && !incident.chart.live && (
              <span className="tag frozen">finished — chart no longer moving</span>
            )}
          </h3>
          <div className="box">
            <Chart
              series={incident.series}
              expected={incident.baseline?.expected_rate ?? incident.expected_rate}
              alertThreshold={(incident.baseline?.expected_rate ?? incident.expected_rate) - 0.05}
              incidentFrom={incident.chart?.incident_from}
              incidentTo={incident.chart?.incident_to}
              caption={incident.chart?.caption}
              live={incident.chart?.live !== false}
            />
          </div>
        </div>

        <div className="section">
          <h3>Where “expected” comes from</h3>
          <div className="box">
            <Baseline b={incident.baseline} />
          </div>
        </div>

        {d?.ops_explanation && (
          <div className="section">
            <h3>For the operations engineer</h3>
            <div className="box ops">
              <ScopeProse text={d.ops_explanation} />
            </div>
          </div>
        )}

        {path.length > 0 && (
          <div className="section">
            <h3>How the segment was isolated</h3>
            <div className="box">
              <div className="path">
                <span className="step">all traffic</span>
                {path.map((p, i) => (
                  <React.Fragment key={i}>
                    <span className="arrow">→</span>
                    <span className="step">
                      <b>{p.dimension}={p.value}</b>{" "}
                      <em>
                        explains {pct(p.explanatory_power, 0)} · {p.lift}× its size ·{" "}
                        {pct(p.observed_rate)} vs {pct(p.expected_rate)}
                      </em>
                    </span>
                  </React.Fragment>
                ))}
              </div>
              <div className="small muted" style={{ marginTop: 9 }}>
                Stopped: <span className="mono">{attribution?.stop_reason}</span>
                {attribution?.stop_reason === "excess_spread_evenly" &&
                  " — below this, every value carries the excess in proportion to its size, so there is nothing left to blame."}
                {attribution?.stop_reason === "below_min_sample" &&
                  " — the next level down has too few attempts to say anything honest."}
              </div>
            </div>
          </div>
        )}

        <div className="section">
          <h3>Decline signature — what kind of failure this is</h3>
          <div className="box">
            <Signature
              before={incident.signature_before}
              during={incident.signature_during}
              risen={incident.detail?.signature?.risen || []}
            />
            {incident.detail?.signature?.top_raw_codes?.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <div className="small muted" style={{ marginBottom: 5 }}>Raw provider codes behind it</div>
                {incident.detail.signature.top_raw_codes.map((c) => (
                  <span className="chip" key={c.raw_code}>
                    {c.raw_code} × {c.count}
                  </span>
                ))}
              </div>
            )}
            {incident.detail?.signature?.raw_status_mismatch_rate > 0 && (
              <div className="small" style={{ marginTop: 9, color: "#f87171" }}>
                {pct(incident.detail.signature.raw_status_mismatch_rate)} of decisions carry a status
                the provider never returned.
              </div>
            )}
          </div>
        </div>

        {d?.evidence?.length > 0 && (
          <div className="section">
            <h3>Evidence — every claim traced to a call</h3>
            <div className="box">
              <ul className="evidence">
                {d.evidence.map((e, i) => (
                  <li key={i}>
                    <span className="tid">{e.tool_call_id}</span>
                    <span className="claim">{e.claim}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        {d?.related_change_events?.length > 0 && (
          <div className="section">
            <h3>Change events near the start</h3>
            <div className="box warnbox">
              {d.related_change_events.map((e) => (
                <div key={e.id} style={{ marginBottom: 5 }}>
                  <span className="chip">{e.type}</span>
                  <span className="mono small muted">{clock(e.ts)}</span>{" "}
                  {e.description}
                </div>
              ))}
            </div>
          </div>
        )}

        {d?.similar_past?.length > 0 && (
          <div className="section">
            <h3>We have seen this before</h3>
            <div className="box okbox">
              {d.similar_past.map((s) => (
                <div key={s.incident_id} style={{ marginBottom: 6 }}>
                  <span className="mono small">{s.started_at.slice(0, 16).replace("T", " ")}</span>{" "}
                  · {CAUSE_LABEL[s.cause_type] || s.cause_type} · {Math.round(s.duration_min)} min ·{" "}
                  {usd(s.cost_usd)} · similarity {s.similarity.toFixed(2)}
                </div>
              ))}
            </div>
          </div>
        )}

        {d?.recommendation && (
          <div className="section">
            <h3>Recommended action</h3>
            <div className="box exec">
              <div style={{ fontSize: 14, marginBottom: 5 }}>{d.recommendation.action}</div>
              {d.recommendation.rationale && (
                <div className="small muted">{d.recommendation.rationale}</div>
              )}
              <div className="small" style={{ marginTop: 9, color: "#fbbf24" }}>
                Not executed. A human decides — this system never touches production.
              </div>
              <div style={{ marginTop: 11 }}>
                <button className="btn" onClick={onAck} disabled={!!incident.acknowledged_by}>
                  {incident.acknowledged_by ? `Acknowledged by ${incident.acknowledged_by}` : "Acknowledge"}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="section">
          <h3>Confidence</h3>
          <div className="box small">
            {d ? `${(d.confidence * 100).toFixed(0)}%` : "—"} ·{" "}
            {d?.source === "agent" ? "diagnosed by the agent over tools" : "deterministic engine"}
            {d?.fallback_reason && <> · fell back because: {d.fallback_reason}</>}
          </div>
        </div>
      </div>
    </div>
  );
}
