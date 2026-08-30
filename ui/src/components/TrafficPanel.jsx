import React, { useEffect, useState } from "react";
import { get, pct, usd } from "../api.js";
import Chart from "./Chart.jsx";
import TxFeed from "./TxFeed.jsx";

const DIMS = ["merchant", "country", "method", "brand", "issuer", "provider"];

/**
 * The live floor: platform conversion, an ad-hoc slice explorer, and the raw attempts.
 *
 * The slice explorer is deliberately here rather than on an incident: it is the manual
 * cross-filtering this whole system exists to replace, and having it side by side makes
 * the point better than a slide would.
 */
export default function TrafficPanel({ snap, catalog, now }) {
  const [scope, setScope] = useState({});
  const [seg, setSeg] = useState(null);
  const [tx, setTx] = useState([]);

  const dims = catalog?.dimensions || {};
  const country = scope.country;
  const options = {
    merchant: (dims.merchant || []).map((m) => m.id),
    country: dims.country || [],
    method: country ? catalog?.methods_by_country?.[country] || [] : dims.method || [],
    brand: dims.brand || [],
    issuer: country ? dims.issuer?.[country] || [] : Object.values(dims.issuer || {}).flat(),
    provider: dims.provider || [],
  };

  useEffect(() => {
    const p = new URLSearchParams({ minutes: "60" });
    Object.entries(scope).forEach(([k, v]) => v && p.set(k, v));
    get(`/api/segment?${p}`).then(setSeg);
  }, [scope, now]);

  useEffect(() => {
    get("/api/transactions?limit=30").then((d) => setTx(d.transactions));
  }, [now]);

  const setDim = (dim, value) => {
    const next = { ...scope };
    if (value) next[dim] = value; else delete next[dim];
    if (dim === "country") { delete next.method; delete next.issuer; delete next.provider; }
    setScope(next);
  };

  const g = snap?.global;

  return (
    <div className="scroll">
      <div className="card">
        <div className="section">
          <h3>Platform conversion — last 90 simulated minutes</h3>
          <div className="box">
            <Chart series={g?.series || []} expected={g?.expected_rate}
                   caption="the whole platform, rolling" height={190} />
          </div>
        </div>

        <div className="section">
          <h3>Slice it yourself — the manual work this system replaces</h3>
          <div className="box">
            <div className="scopegrid">
              {DIMS.map((dim) => (
                <select key={dim} value={scope[dim] || ""} onChange={(e) => setDim(dim, e.target.value)}>
                  <option value="">{dim}: any</option>
                  {(options[dim] || []).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              ))}
            </div>
            {seg && (
              <>
                <div className="grid4" style={{ marginTop: 13, marginBottom: 0 }}>
                  <div className="tile">
                    <div className="k">Attempts / min</div>
                    <div className="v">{seg.preview?.attempts_per_min?.toLocaleString() ?? "—"}</div>
                  </div>
                  <div className="tile">
                    <div className="k">Conversion</div>
                    <div className={`v ${seg.observed_rate < seg.expected_rate - 0.02 ? "bad" : "ok"}`}>
                      {pct(seg.observed_rate)}
                    </div>
                    <div className="s">expected {pct(seg.expected_rate)}</div>
                  </div>
                  <div className="tile">
                    <div className="k">Excess declines</div>
                    <div className="v">{Math.round(seg.excess_declines).toLocaleString()}</div>
                    <div className="s">in 60 min</div>
                  </div>
                  <div className="tile">
                    <div className="k">Segments</div>
                    <div className="v">{seg.preview?.segments_matched}</div>
                    <div className="s">of {seg.preview?.segments_total}</div>
                  </div>
                </div>
                <div style={{ marginTop: 14 }}>
                  <Chart series={seg.series || []} expected={seg.expected_rate}
                         caption="the slice above, last 60 simulated minutes" height={170} />
                </div>
              </>
            )}
          </div>
        </div>

        <div className="section">
          <h3>Live attempts — what the provider said, and what we stored</h3>
          <div className="box">
            <div className="small muted" style={{ marginBottom: 9 }}>
              These two columns should always agree. When they stop agreeing, our
              normalization is wrong and every number downstream is wrong with it — which
              is what the mapping-bug injection does.
            </div>
            <TxFeed transactions={tx} />
          </div>
        </div>
      </div>
    </div>
  );
}
