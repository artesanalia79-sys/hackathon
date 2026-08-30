import React, { useState } from "react";
import { post } from "../api.js";

const DIMS = ["merchant", "country", "method", "brand", "issuer", "provider"];

/**
 * The judges' input surface. Any subset of dimensions is a valid scope; an empty
 * dimension means "any". Nothing here names an incident — the engine has to find it.
 */
export default function Injector({ catalog, onClose, onDone }) {
  const [type, setType] = useState("provider_degraded");
  const [scope, setScope] = useState({});
  const [severity, setSeverity] = useState(0.35);
  const [ramp, setRamp] = useState(0);
  const [duration, setDuration] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const dims = catalog?.dimensions || {};
  const country = scope.country;
  const methods = country ? catalog?.methods_by_country?.[country] || [] : dims.method || [];
  const issuers = country
    ? dims.issuer?.[country] || []
    : Object.values(dims.issuer || {}).flat();
  const providers =
    country && scope.method
      ? catalog?.providers_by_method?.[`${country}|${scope.method}`] || []
      : dims.provider || [];

  const options = { merchant: (dims.merchant || []).map((m) => m.id), country: dims.country || [],
                    method: methods, brand: dims.brand || [], issuer: issuers, provider: providers };
  const info = (catalog?.injection_types || []).find((t) => t.id === type);

  const setDim = (dim, value) => {
    const next = { ...scope };
    if (value) next[dim] = value;
    else delete next[dim];
    // Changing country invalidates the values that only exist inside it.
    if (dim === "country") { delete next.method; delete next.issuer; delete next.provider; }
    if (dim === "method") delete next.provider;
    setScope(next);
  };

  const submit = async () => {
    setBusy(true);
    try {
      const body = {
        type, scope, severity: Number(severity), ramp_minutes: Number(ramp) || 0,
        note, ...(duration ? { duration_minutes: Number(duration) } : {}),
      };
      const r = await post("/api/inject", body);
      setResult(r);
      onDone?.();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="drawer" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel">
        <div style={{ display: "flex", alignItems: "center", marginBottom: 4 }}>
          <h3>Inject a failure</h3>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="btn ghost" onClick={onClose}>close</button>
        </div>
        <div className="small muted" style={{ marginBottom: 16 }}>
          Any combination of dimensions works. Leave a dimension empty to mean “any”.
          The engine is not told what you injected.
        </div>

        <div className="field">
          <label>What breaks</label>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {(catalog?.injection_types || []).map((t) => (
              <option key={t.id} value={t.id}>{t.label}</option>
            ))}
          </select>
          {info && <div className="hint">{info.hint}</div>}
        </div>

        <div className="field">
          <label>Scope</label>
          <div className="scopegrid">
            {DIMS.map((dim) => (
              <select key={dim} value={scope[dim] || ""} onChange={(e) => setDim(dim, e.target.value)}>
                <option value="">{dim}: any</option>
                {(options[dim] || []).map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            ))}
          </div>
          <div className="hint">
            {Object.keys(scope).length
              ? Object.entries(scope).map(([k, v]) => `${k}=${v}`).join(" · ")
              : "the whole platform"}
          </div>
        </div>

        <div className="row">
          <div className="field">
            <label>Severity {Number(severity).toFixed(2)}</label>
            <input type="range" min="0.05" max="0.95" step="0.05" value={severity}
                   onChange={(e) => setSeverity(e.target.value)} />
            <div className="hint">
              {type === "mapping_bug" ? "share of decisions mis-mapped"
                : type === "merchant_outage" ? "share of traffic that disappears"
                : type === "latency_spike" ? "latency multiplier"
                : "conversion points removed"}
            </div>
          </div>
          <div className="field">
            <label>Ramp (min)</label>
            <input type="number" min="0" max="60" value={ramp} onChange={(e) => setRamp(e.target.value)} />
            <div className="hint">0 = abrupt</div>
          </div>
          <div className="field">
            <label>Duration (min)</label>
            <input type="number" min="1" placeholder="until reset" value={duration}
                   onChange={(e) => setDuration(e.target.value)} />
            <div className="hint">blank = until reset</div>
          </div>
        </div>

        <div className="field">
          <label>Note (free text, any language)</label>
          <input value={note} onChange={(e) => setNote(e.target.value)}
                 placeholder="e.g. dLocal está fallando en Brasil" />
          <div className="hint">Recorded with the injection. The engine never reads it.</div>
        </div>

        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 6 }}>
          <button className="btn primary" onClick={submit} disabled={busy}>
            {busy ? "injecting…" : "Inject"}
          </button>
          {result && (
            <span className="small muted">
              {result.duplicate
                ? `duplicate ignored — still ${result.injection_id}`
                : `injected ${result.injection_id}`}
              {" · detection takes ~5 simulated minutes"}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
