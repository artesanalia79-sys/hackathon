import React from "react";
import { pct } from "../api.js";

/**
 * What "expected" actually means, in numbers you can check.
 *
 * "Conversion is below expectation" is worth nothing if the reader cannot see what the
 * expectation was built from, so this shows the formula, both inputs, and the counts
 * behind the rates.
 */
export default function Baseline({ b }) {
  if (!b) return null;
  const rows = [
    ["Attempts in the window", b.attempts?.toLocaleString(),
     `last ${b.window_minutes} simulated minutes`],
    ["Hard declines excluded", b.hard_declines_excluded?.toLocaleString(),
     "no card, no funds, wrong data — nothing we do changes these"],
    ["Operational attempts", b.operational_attempts?.toLocaleString(),
     `the denominator of the rate${b.enough_sample ? "" : ` — below the minimum of ${b.min_sample}`}`],
    ["Approved", b.observed_approved?.toLocaleString(), `observed rate ${pct(b.observed_rate)}`],
    ["Expected approved", b.expected_approved?.toLocaleString(),
     `at ${pct(b.expected_rate)}, the expectation below`],
    ["Excess declines", Math.round(b.excess_declines ?? 0).toLocaleString(),
     "approvals we should have had and did not"],
  ];
  return (
    <div>
      <div className="formula">
        <span className="fpart">
          <b>{pct(b.expected_rate)}</b> expected
        </span>
        <span className="feq">=</span>
        <span className="fpart">
          {b.seasonal_weight} × <b>{pct(b.seasonal_rate)}</b>
          <em>seasonal — same weekday and hour, averaged over {b.history_days} days of history</em>
        </span>
        <span className="feq">+</span>
        <span className="fpart">
          {b.recent_weight} × <b>{pct(b.recent_rate)}</b>
          <em>recent — this segment's own last {b.recent_hours}h, ending before the window under test</em>
        </span>
      </div>
      <table className="kv">
        <tbody>
          {rows.map(([k, v, note]) => (
            <tr key={k}>
              <td className="k">{k}</td>
              <td className="v">{v ?? "—"}</td>
              <td className="n">{note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!b.enough_sample && (
        <div className="small warn" style={{ marginTop: 8 }}>
          Below the minimum sample of {b.min_sample}. The honest answer for a segment this
          small is "insufficient evidence", not a named cause.
        </div>
      )}
    </div>
  );
}
