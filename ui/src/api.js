export const get = (path) => fetch(path).then((r) => r.json());

export const post = (path, body) =>
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => r.json());

export const pct = (v, digits = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;

export const usd = (v) =>
  v === null || v === undefined
    ? "—"
    : v >= 1000
      ? `$${Math.round(v).toLocaleString()}`
      : `$${v.toFixed(v < 10 ? 2 : 0)}`;

export const clock = (iso) => (iso ? iso.slice(11, 16) : "—");

export const scopeText = (scope) => {
  const order = ["provider", "issuer", "brand", "method", "country", "merchant"];
  const keys = Object.keys(scope || {});
  keys.sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return keys.length ? keys.map((k) => `${k}=${scope[k]}`).join(" · ") : "whole platform";
};

export const CAUSE_LABEL = {
  provider_degraded: "Provider degraded",
  issuer_over_declining: "Issuer over-declining",
  issuer_provider_routing: "Issuer ↔ provider routing",
  network_degraded: "Card network degraded",
  method_down: "Payment method down",
  internal_change: "Internal change",
  mapping_bug: "Mapping bug (internal)",
  unmapped_provider_code: "Unmapped provider code",
  latency_spike: "Latency spike",
  no_traffic: "No traffic",
  insufficient_evidence: "Insufficient evidence",
};
