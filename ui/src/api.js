// Where the simulator lives. Empty means "same origin", which is what `make run`
// and `vite dev` both serve — set VITE_API_BASE only when the UI is hosted apart
// from the API, as it is on a static host like Vercel.
export const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/+$/, "");

export const apiUrl = (path) => `${API_BASE}${path}`;

export const get = (path) => fetch(apiUrl(path)).then((r) => r.json());

export const post = (path, body) =>
  fetch(apiUrl(path), {
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

// --- how a scope is spoken out loud ----------------------------------------
// The engine speaks in `country=CO`; a human reads a flag and a country name.
export const COUNTRY = {
  CO: { flag: "🇨🇴", name: "Colombia" },
  BR: { flag: "🇧🇷", name: "Brazil" },
  MX: { flag: "🇲🇽", name: "Mexico" },
};

export const MERCHANT_NAME = {
  m_fastcart: "FastCart",
  m_streamly: "Streamly",
  m_viajesya: "ViajesYa",
};

export const DIMENSION_LABEL = {
  provider: "Provider",
  issuer: "Issuer",
  brand: "Brand",
  method: "Method",
  country: "Country",
  merchant: "Merchant",
};

const SCOPE_ORDER = ["country", "provider", "issuer", "brand", "method", "merchant"];

const titleCase = (s) =>
  String(s).replace(/_/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase());

const UPPER = new Set(["pse", "pix", "spei", "codi", "oxxo", "breb"]);

/** One scope entry, ready to render: `{ dimension, label, value, text, flag }`. */
export const scopePart = (dimension, value) => {
  const part = {
    dimension,
    label: DIMENSION_LABEL[dimension] || titleCase(dimension),
    value,
    text: String(value),
    flag: null,
  };
  if (dimension === "country") {
    const c = COUNTRY[value];
    part.flag = c?.flag ?? null;
    part.text = c?.name ?? String(value);
  } else if (dimension === "merchant") {
    part.text = MERCHANT_NAME[value] || titleCase(String(value).replace(/^m_/, ""));
  } else if (UPPER.has(String(value))) {
    part.text = String(value).toUpperCase();
  } else {
    part.text = titleCase(value);
  }
  return part;
};

/** A scope object as an ordered list of renderable parts. Empty = whole platform. */
export const scopeParts = (scope) => {
  const keys = Object.keys(scope || {});
  keys.sort((a, b) => {
    const ia = SCOPE_ORDER.indexOf(a), ib = SCOPE_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return keys.map((k) => scopePart(k, scope[k]));
};
