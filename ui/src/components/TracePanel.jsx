import React from "react";

const indent = (depth) => "  ".repeat(Math.max(0, depth));

function formatPartialJson(source) {
  let formatted = "";
  let depth = 0;
  let inString = false;
  let escaped = false;

  for (const character of source) {
    if (inString) {
      formatted += character;
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === "\"") inString = false;
      continue;
    }

    if (character === "\"") {
      inString = true;
      formatted += character;
    } else if (character === "{" || character === "[") {
      depth += 1;
      formatted += `${character}\n${indent(depth)}`;
    } else if (character === "}" || character === "]") {
      depth = Math.max(0, depth - 1);
      formatted = formatted.trimEnd();
      formatted += `\n${indent(depth)}${character}`;
    } else if (character === ",") {
      formatted += `,\n${indent(depth)}`;
    } else if (character === ":") {
      formatted += ": ";
    } else if (!/\s/.test(character)) {
      formatted += character;
    }
  }

  return formatted.trim();
}

function formatJson(value) {
  if (typeof value !== "string") return JSON.stringify(value, null, 2);

  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    // Tool previews may end mid-object. Format the valid prefix structurally.
    return formatPartialJson(value);
  }
}

function JsonPreview({ value, truncated = false, className = "" }) {
  const formatted = formatJson(value);

  const lines = formatted.split("\n");

  return (
    <pre className={`json-preview${className ? ` ${className}` : ""}`}>
      {lines.map((line, index) => {
        const key = line.match(/^(\s*)("(?:\\.|[^"\\])*")(\s*:)(.*)$/);
        const newline = index < lines.length - 1 || truncated ? "\n" : "";

        return key ? (
          <React.Fragment key={index}>
            {key[1]}<span className="json-key">{key[2]}</span>{key[3]}{key[4]}{newline}
          </React.Fragment>
        ) : (
          <React.Fragment key={index}>{line}{newline}</React.Fragment>
        );
      })}
      {truncated ? <span className="json-truncated">…</span> : null}
    </pre>
  );
}

/**
 * Every tool call the agent made, in order, with what each one was for.
 *
 * An incident card is only trustworthy if you can see where each claim came from, and
 * the tool names alone do not tell a reader that — so each step says what it was doing.
 */
export default function TracePanel({ trace, liveSteps, diagnosis, onClose }) {
  const steps = (trace?.steps?.length ? trace.steps : liveSteps) || [];
  const source = diagnosis?.source;

  return (
    <aside className="col right trace-drawer" id="agent-trace-drawer" aria-label="Agent trace">
      <div className="colhead">
        Agent trace
        <span className="spacer" />
        {source === "agent" ? <span className="pill live">agent</span>
                            : <span className="pill off">deterministic</span>}
        <button className="drawer-close" type="button" aria-label="Hide agent trace" onClick={onClose}>
          <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
            <path d="m6 6 8 8M14 6l-8 8" />
          </svg>
        </button>
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
            <JsonPreview value={s.arguments} className="args" />
          )}
          {s.tool === "send_slack_alert" && (
            <div className={`slack-result ${s.alert_sent ? "sent" : "failed"}`}>
              {s.alert_sent ? "✓ Slack confirmó el envío de la alerta."
                            : "Slack no confirmó el envío de la alerta."}
              {s.alert_note && <span> {s.alert_note}</span>}
            </div>
          )}
          {s.result_preview && (
            <details>
              <summary className="small muted">what it returned</summary>
              <JsonPreview value={s.result_preview} truncated={s.truncated} />
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
    </aside>
  );
}
