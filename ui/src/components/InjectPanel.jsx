import React, { useEffect, useMemo, useState } from "react";
import { get, post, pct, scopeText } from "../api.js";

const DIMS = ["merchant", "country", "method", "brand", "issuer", "provider"];

/** Fills the form only — no code path keys off these. A judge can change every field. */
const PRESETS = [
  { name: "Provider down in one country", type: "provider_degraded",
    scope: { provider: "dlocal", country: "BR" }, severity: 0.35 },
  { name: "Issuer over-declining everywhere", type: "issuer_over_declining",
    scope: { issuer: "itau" }, severity: 0.35 },
  { name: "Issuer bad through one provider", type: "issuer_over_declining",
    scope: { issuer: "itau", provider: "adyen" }, severity: 0.45 },
  { name: "Card network wobbling", type: "network_degraded",
    scope: { brand: "visa" }, severity: 0.30 },
  { name: "Our own mapping is wrong", type: "mapping_bug",
    scope: { provider: "dlocal" }, severity: 0.35 },
  { name: "Rail down in a country", type: "method_down",
    scope: { method: "pix", country: "BR" }, severity: 0.45 },
  { name: "Should NOT alert: hard declines", type: "hard_decline_spike",
    scope: { country: "CO" }, severity: 0.25 },
  { name: "Should NOT alert: merchant offline", type: "merchant_outage",
    scope: { merchant: "m_streamly" }, severity: 0.95 },
];

const SEVERITY_UNIT = {
  mapping_bug: "of decisions get mis-mapped",
  merchant_outage: "of this merchant's traffic disappears",
  latency_spike: "→ latency multiplier",
  unknown_code: "of declines carry a code we do not map",
};

export default function InjectPanel({ catalog, now, onInjected }) {
  const [type, setType] = useState("provider_degraded");
  const [scope, setScope] = useState({ provider: "dlocal", country: "BR" });
  const [severity, setSeverity] = useState(0.35);
  const [ramp, setRamp] = useState(0);
  const [startIn, setStartIn] = useState(0);
  const [duration, setDuration] = useState("");
  const [note, setNote] = useState("");
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [active, setActive] = useState([]);

  const dims = catalog?.dimensions || {};
  const country = scope.country;
  const methods = country ? catalog?.methods_by_country?.[country] || [] : dims.method || [];
  const issuers = country ? dims.issuer?.[country] || [] : Object.values(dims.issuer || {}).flat();
  const providers = country && scope.method
    ? catalog?.providers_by_method?.[`${country}|${scope.method}`] || []
    : dims.provider || [];
  const options = {
    merchant: (dims.merchant || []).map((m) => m.id), country: dims.country || [],
    method: methods, brand: dims.brand || [], issuer: issuers, provider: providers,
  };
  const info = (catalog?.injection_types || []).find((t) => t.id === type);

  const qs = useMemo(() => {
    const p = new URLSearchParams({ minutes: "10" });
    Object.entries(scope).forEach(([k, v]) => v && p.set(k, v));
    return p.toString();
  }, [scope]);

  // Tell the judge what this scope actually carries *before* they inject into it,
  // so "nothing happened" is never a mystery.
  useEffect(() => {
    let dead = false;
    get(`/api/segment?${qs}`).then((d) => !dead && setPreview(d));
    return () => { dead = true; };
  }, [qs, now]);

  const loadActive = () => get("/api/injections").then((d) => setActive(d.active || []));
  useEffect(() => { loadActive(); }, [now]);

  const setDim = (dim, value) => {
    const next = { ...scope };
    if (value) next[dim] = value; else delete next[dim];
    if (dim === "country") { delete next.method; delete next.issuer; delete next.provider; }
    if (dim === "method") delete next.provider;
    setScope(next);
  };

  const applyPreset = (p) => {
    setType(p.type); setScope({ ...p.scope }); setSeverity(p.severity);
    setRamp(0); setStartIn(0); setDuration(""); setResult(null);
  };

  const submit = async () => {
    setBusy(true);
    try {
      const r = await post("/api/inject", {
        type, scope, severity: Number(severity), ramp_minutes: Number(ramp) || 0,
        start_in_minutes: Number(startIn) || 0, note,
        ...(duration ? { duration_minutes: Number(duration) } : {}),
      });
      setResult(r); loadActive(); onInjected?.();
    } finally { setBusy(false); }
  };

  const stop = async (id) => { await post(`/api/injections/${id}/stop`); loadActive(); };

  const p = preview?.preview;
  const tone = !p ? "" : !p.detectable ? "bad" : p.attempts_per_window < p.min_sample * 4 ? "warn" : "ok";

  return (
    <div className="panelwrap">
      <div className="pcol">
        <div className="section">
          <h3>Start from a known shape (then change anything)</h3>
          <div className="presets">
            {PRESETS.map((pr) => (
              <button key={pr.name} className="preset" onClick={() => applyPreset(pr)}>
                {pr.name}
              </button>
            ))}
          </div>
        </div>

        <div className="section">
          <h3>What breaks</h3>
          <div className="box">
            <div className="field">
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {(catalog?.injection_types || []).map((t) => (
                  <option key={t.id} value={t.id}>{t.label}</option>
                ))}
              </select>
              {info && <div className="hint">{info.hint}</div>}
            </div>

            <div className="field">
              <label>Where — leave a dimension on “any” to widen the blast radius</label>
              <div className="scopegrid">
                {DIMS.map((dim) => (
                  <select key={dim} value={scope[dim] || ""} onChange={(e) => setDim(dim, e.target.value)}>
                    <option value="">{dim}: any</option>
                    {(options[dim] || []).map((v) => <option key={v} value={v}>{v}</option>)}
                  </select>
                ))}
              </div>
              <div className="hint mono">{scopeText(scope)}</div>
            </div>

            <div className="field">
              <label>
                How hard — {(severity * 100).toFixed(0)}%{" "}
                <span className="muted">
                  {SEVERITY_UNIT[type] || "conversion points removed"}
                </span>
              </label>
              <input type="range" min="0.05" max="0.95" step="0.05" value={severity}
                     onChange={(e) => setSeverity(e.target.value)} />
            </div>

            <div className="row">
              <div className="field">
                <label>Starts in (min)</label>
                <input type="number" min="0" value={startIn} onChange={(e) => setStartIn(e.target.value)} />
                <div className="hint">simulated minutes from now</div>
              </div>
              <div className="field">
                <label>Ramp (min)</label>
                <input type="number" min="0" max="60" value={ramp} onChange={(e) => setRamp(e.target.value)} />
                <div className="hint">0 = a cliff; 20 = a slow slide</div>
              </div>
              <div className="field">
                <label>Lasts (min)</label>
                <input type="number" min="1" placeholder="until stopped" value={duration}
                       onChange={(e) => setDuration(e.target.value)} />
                <div className="hint">blank = until you stop it</div>
              </div>
            </div>

            <div className="field">
              <label>Note — free text, any language</label>
              <input value={note} onChange={(e) => setNote(e.target.value)}
                     placeholder="e.g. dLocal está fallando en Brasil" />
              <div className="hint">Recorded with the injection. The engine never reads it.</div>
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <button className="btn primary" onClick={submit} disabled={busy || (p && !p.detectable)}>
                {busy ? "injecting…" : "Inject"}
              </button>
              {result && (
                <span className="small muted">
                  {result.duplicate ? `duplicate ignored — still ${result.injection_id}`
                                    : `injected ${result.injection_id}`}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="pcol">
        <div className="section">
          <h3>What this scope actually carries, right now</h3>
          <div className={`box ${tone === "bad" ? "badbox" : tone === "warn" ? "warnbox" : "okbox"}`}>
            {!p ? <div className="small muted">measuring…</div> : (
              <>
                <div className="grid2">
                  <div className="tile">
                    <div className="k">Segments matched</div>
                    <div className="v">{p.segments_matched}<span className="s"> / {p.segments_total}</span></div>
                  </div>
                  <div className="tile">
                    <div className="k">Attempts per 5-min window</div>
                    <div className={`v ${tone}`}>{p.attempts_per_window.toLocaleString()}</div>
                    <div className="s">minimum to judge: {p.min_sample}</div>
                  </div>
                </div>
                <div className="small" style={{ marginTop: 10 }}>{p.verdict}</div>
                <div className="small muted" style={{ marginTop: 8 }}>
                  Currently converting at {pct(preview.observed_rate)} against{" "}
                  {pct(preview.expected_rate)} expected.
                </div>
              </>
            )}
          </div>
        </div>

        <div className="section">
          <h3>Running now ({active.length})</h3>
          <div className="box">
            {!active.length && <div className="small muted">Nothing injected. The world is healthy.</div>}
            {active.map((a) => (
              <div className="activeinj" key={a.injection_id}>
                <div>
                  <div className="mono small">{a.type}</div>
                  <div className="small muted">{scopeText(a.scope)} · severity {(a.severity * 100).toFixed(0)}%</div>
                </div>
                <button className="btn ghost small" onClick={() => stop(a.injection_id)}>stop</button>
              </div>
            ))}
            {active.length > 0 && (
              <div className="small muted" style={{ marginTop: 9 }}>
                Stopping one leaves the others running — that is how you watch a single
                incident recover and close on its own.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
