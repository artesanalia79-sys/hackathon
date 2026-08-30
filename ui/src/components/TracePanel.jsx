import React from "react";

/**
 * Every tool call the agent made, in order, with what each one was for.
 *
 * An incident card is only trustworthy if you can see where each claim came from, and
 * the tool names alone do not tell a reader that — so each step says what it was doing.
 */
export default function TracePanel({ trace, liveSteps, diagnosis }) {
  const steps = (trace?.steps?.length ? trace.steps : liveSteps) || [];
  const source = diagnosis?.source;

  return (
    <div className="col right">
      <div className="colhead">
        Agent trace
        <span className="spacer" />
        {source === "agent" ? <span className="pill live">agent</span>
                            : <span className="pill off">deterministic</span>}
      </div>

      {source === "deterministic_fallback" && diagnosis?.fallback_reason && (
        <div className="trace fallback">
          <div className="th"><span className="tool">no agent run</span></div>
          <div className="small muted" style={{ marginTop: 5 }}>{diagnosis.fallback_reason}</div>
          <div className="small muted" style={{ marginTop: 7 }}>
            The deterministic engine answered instead. Its own steps are cited on the card as
            <span className="chip" style={{ marginLeft: 5 }}>engine.*</span>
          </div>
        </div>
      )}

      {!steps.length && source !== "deterministic_fallback" && (
        <div className="empty small">
          No agent run yet. The agent starts once an incident is confirmed, on top of a card
          the engine has already filled in.
        </div>
      )}

      {steps.map((s) => (
        <div className={`trace ${s.kind}`} key={`${s.seq}-${s.kind}`}>
          <div className="th">
            <span className="seq">{String(s.seq).padStart(2, "0")}</span>
            <span className="tool">{s.tool || s.kind.replace(/_/g, " ")}</span>
            <span className="ms">{s.elapsed_ms}ms</span>
          </div>
          {s.tool_description && <div className="tdesc">{s.tool_description}</div>}
          {s.tool_call_id && <div style={{ marginTop: 5 }}><span className="chip">{s.tool_call_id}</span></div>}
          {s.arguments && Object.keys(s.arguments).length > 0 && (
            <pre className="args">{JSON.stringify(s.arguments)}</pre>
          )}
          {s.result_preview && (
            <details>
              <summary className="small muted">what it returned</summary>
              <pre>{s.result_preview}{s.truncated ? "\n…" : ""}</pre>
            </details>
          )}
          {s.reason && <div className="small muted" style={{ marginTop: 5 }}>{s.reason}</div>}
          {s.kind === "conclude" && (
            <div className="small" style={{ marginTop: 5, color: "#34d399" }}>
              {s.root_cause} · confidence {s.confidence} · {s.evidence_count} cited claims
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
