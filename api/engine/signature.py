"""Decline-signature classification.

Attribution says *where*. The signature says *what kind*. A signature is the
distribution of decline categories in a segment compared with its own history:
a provider outage, an issuer tightening its rules and a broken mapping table all
drop the same conversion rate, and they look nothing alike here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from api.config import N_MIN
from api.domain import DIMENSIONS, ChangeEvent
from api.engine.cube import Agg
from api.engine.expectation import Expector
from api.engine.stats import js_divergence

# A category has "risen" once it gains this much share of all attempts.
RISE_ABS = 0.02
RISE_REL = 1.5
MISMATCH_RATE_ALERT = 0.02      # 2% of decisions contradicting the provider is already a bug
UNKNOWN_SHARE_ALERT = 0.02
CHANGE_WINDOW_MIN = 10

CAUSE_LABEL = {
    "mapping_bug": "internal: normalization mapping is wrong",
    "unmapped_provider_code": "internal: provider code we do not map",
    "internal_change": "internal: recent change (routing/config/mapping)",
    "network_degraded": "card network degraded",
    "provider_degraded": "provider degraded",
    "issuer_over_declining": "issuer over-declining",
    "issuer_provider_routing": "issuer <-> provider routing/config",
    "method_down": "payment method down in country",
    "latency_spike": "latency spike without decline increase",
    "no_traffic": "traffic stopped arriving",
    "insufficient_evidence": "insufficient evidence",
}

RECOMMENDATION = {
    "mapping_bug": ("Roll back the normalization change and re-process the affected window",
                    ("Approvals we reported are not confirmed by the provider; every downstream "
                    "number (settlement, retries, merchant reporting) is wrong until this is reverted.")),
    "unmapped_provider_code": ("Map the new provider code and re-classify the affected traffic",
                               ("The code is real and material; leaving it in `unknown` hides whatever "
                               "it actually means.")),
    "internal_change": ("Roll back or review the change listed in the evidence",
                        "The break starts inside the change window and inside the change's own scope."),
    "network_degraded": ("Do not reroute providers; inform merchants and prefer non-card methods",
                         ("The failure follows the brand across every provider and issuer, so moving "
                         "traffic between providers cannot help.")),
    "provider_degraded": ("Reroute the affected traffic away from this provider",
                          ("The failure is confined to one provider while the same issuers convert "
                          "normally elsewhere.")),
    "issuer_over_declining": ("Contact the issuer; enable retry with 3DS for this BIN range",
                              ("The issuer declines at the same elevated rate through every provider, "
                              "so it is their decisioning, not our routing.")),
    "issuer_provider_routing": ("Reroute this BIN range to another provider",
                                ("The same issuer converts normally through other providers, which "
                                "points at the pairing, not at either party alone.")),
    "method_down": ("Surface an alternative payment method for this country",
                    "The rail itself is failing; no provider choice recovers it."),
    "latency_spike": ("Check the provider's latency; watch for abandonment",
                      "Declines are normal, so the loss is people giving up, not issuers refusing."),
    "no_traffic": ("Check the merchant's checkout and our ingest, not the issuers",
                   "Attempts stopped arriving; conversion is undefined, not bad."),
    "insufficient_evidence": ("Keep watching; do not act yet",
                              "The excess does not concentrate anywhere with enough sample to name a cause."),
}


@dataclass
class Signature:
    before: dict[str, float]
    during: dict[str, float]
    risen: list[str] = field(default_factory=list)
    divergence: float = 0.0
    mismatch_rate: float = 0.0
    unknown_share: float = 0.0
    top_raw_codes: list[tuple[str, int]] = field(default_factory=list)
    unmapped_codes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "before": {k: round(v, 4) for k, v in self.before.items() if v > 0.0005},
            "during": {k: round(v, 4) for k, v in self.during.items() if v > 0.0005},
            "risen": self.risen,
            "divergence": round(self.divergence, 4),
            "raw_status_mismatch_rate": round(self.mismatch_rate, 4),
            "unknown_share": round(self.unknown_share, 4),
            "top_raw_codes": [{"raw_code": c, "count": n} for c, n in self.top_raw_codes],
            "unmapped_codes": self.unmapped_codes,
        }


def build_signature(observed: Agg, seasonal: Agg) -> Signature:
    before = seasonal.category_shares()
    during = observed.category_shares()
    risen = []
    for cat, now in during.items():
        if cat == "none":
            continue
        was = before.get(cat, 0.0)
        if now - was >= RISE_ABS and (was <= 0.001 or now / max(was, 1e-9) >= RISE_REL):
            risen.append(cat)
    risen.sort(key=lambda c: during[c] - before.get(c, 0.0), reverse=True)
    mismatch_rate = (observed.raw_status_mismatch / observed.attempts) if observed.attempts else 0.0
    top_codes = sorted(observed.by_raw_code.items(), key=lambda kv: kv[1], reverse=True)[:6]
    unmapped = [c for c, _n in top_codes if c.startswith("unmapped:")]
    if not unmapped:
        from api.sim.mapping import is_known
        provider = observed.scope.get("provider")
        if provider:
            unmapped = [c for c, _n in top_codes if not is_known(provider, c)]
    return Signature(before=before, during=during, risen=risen,
                     divergence=js_divergence(before, during),
                     mismatch_rate=mismatch_rate,
                     unknown_share=during.get("unknown", 0.0),
                     top_raw_codes=top_codes, unmapped_codes=unmapped)


def spread_across(ex: Expector, scope: dict[str, str], dimension: str,
                  end: datetime, minutes: int) -> float:
    """Fraction of a dimension's values inside `scope` that are themselves below expectation.

    "The same issuers convert fine through other providers" is a structural claim,
    and this is how we check it instead of asserting it.
    """
    values = ex.cube.values_of(dimension, scope)
    if len(values) < 2:
        return 0.0
    hurt = considered = 0
    for v in values:
        exp = ex.expect({**scope, dimension: v}, end, minutes)
        if exp.observed.operational_attempts < max(10, N_MIN // 4):
            continue
        considered += 1
        if exp.observed.rate is not None and exp.observed.rate < exp.p0 - 0.02:
            hurt += 1
    return (hurt / considered) if considered else 0.0


def related_change_events(events: list[ChangeEvent], scope: dict[str, str],
                          when: datetime) -> list[ChangeEvent]:
    """Change events near in time whose scope is compatible with the incident's scope."""
    out = []
    for ev in events:
        if abs((ev.ts - when).total_seconds()) > CHANGE_WINDOW_MIN * 60:
            continue
        compatible = all(scope.get(k) == v for k, v in ev.scope.items() if k in scope)
        overlaps = not ev.scope or any(scope.get(k) == v for k, v in ev.scope.items())
        if compatible or overlaps:
            out.append(ev)
    return out


def classify(scope: dict[str, str], sig: Signature, ex: Expector, end: datetime,
             minutes: int, change_events: list[ChangeEvent],
             started_at: datetime) -> tuple[str, float, list[str]]:
    """Rules, in priority order. Returns (cause_type, confidence, reasons)."""
    reasons: list[str] = []
    pinned = {d for d in DIMENSIONS if d in scope}
    risen = set(sig.risen)
    nearby = related_change_events(change_events, scope, started_at)

    # 1. We disagree with the provider about what happened. Nothing else matters first.
    if sig.mismatch_rate >= MISMATCH_RATE_ALERT:
        reasons.append(f"{sig.mismatch_rate:.1%} of decisions were stored with a status the "
                       f"provider did not return")
        if nearby:
            reasons.append(f"a {nearby[0].type} landed within {CHANGE_WINDOW_MIN} min: {nearby[0].description}")
        return "mapping_bug", 0.95 if nearby else 0.85, reasons

    # 2. Codes we do not map at all.
    if sig.unknown_share >= UNKNOWN_SHARE_ALERT and "unknown" in risen:
        codes = ", ".join(sig.unmapped_codes[:3]) or "an undocumented code"
        reasons.append(f"{sig.unknown_share:.1%} of attempts carry a code we do not map ({codes})")
        return "unmapped_provider_code", 0.8, reasons

    # 3. Something we changed, in the same scope, minutes before.
    if nearby and (risen & {"config", "unknown"} or nearby[0].type in ("routing_rule", "mapping_change")):
        ev = nearby[0]
        reasons.append(f"{ev.type} at {ev.ts:%H:%M} scoped to "
                       f"{ev.scope or 'all traffic'}: {ev.description}")
        if risen:
            reasons.append(f"{', '.join(sig.risen)} declines rose right after it")
        return "internal_change", 0.85, reasons

    tech = "technical" in risen
    soft = "soft_decline" in risen

    # 4. The brand carries it across every provider and issuer -> the network, not us.
    if tech and "brand" in pinned and "provider" not in pinned:
        prov_spread = spread_across(ex, scope, "provider", end, minutes)
        iss_spread = spread_across(ex, scope, "issuer", end, minutes)
        if prov_spread >= 0.6 and iss_spread >= 0.5:
            reasons.append(f"technical declines up on brand={scope['brand']} across "
                           f"{prov_spread:.0%} of providers and {iss_spread:.0%} of issuers")
            return "network_degraded", 0.85, reasons

    # 5. One provider, many issuers and merchants.
    if tech and "provider" in pinned:
        iss_spread = spread_across(ex, scope, "issuer", end, minutes)
        mer_spread = spread_across(ex, scope, "merchant", end, minutes)
        if "issuer" not in pinned and (iss_spread >= 0.5 or mer_spread >= 0.5):
            reasons.append(f"technical declines up on provider={scope['provider']}, hitting "
                           f"{iss_spread:.0%} of issuers and {mer_spread:.0%} of merchants")
            return "provider_degraded", 0.85, reasons

    # 6/7. Issuer stories: alone, or only through one provider.
    if soft or "risk_block" in risen:
        if "issuer" in pinned and "provider" in pinned:
            reasons.append(f"declines up only on issuer={scope['issuer']} via "
                           f"provider={scope['provider']}")
            return "issuer_provider_routing", 0.8, reasons
        if "issuer" in pinned:
            prov_spread = spread_across(ex, scope, "provider", end, minutes)
            if prov_spread >= 0.5:
                reasons.append(f"soft declines up on issuer={scope['issuer']} through "
                               f"{prov_spread:.0%} of providers")
                return "issuer_over_declining", 0.85, reasons
            reasons.append(f"soft declines up on issuer={scope['issuer']}, concentrated in "
                           f"{prov_spread:.0%} of providers")
            return "issuer_provider_routing", 0.7, reasons

    # 8. A rail is down in a country.
    if (tech or soft) and "method" in pinned and "provider" not in pinned:
        reasons.append(f"declines up on method={scope['method']}"
                       + (f" in {scope['country']}" if "country" in scope else "")
                       + ", independent of provider")
        return "method_down", 0.8, reasons

    # Fall through: a provider-pinned technical rise we could not corroborate structurally.
    if tech and "provider" in pinned:
        reasons.append(f"technical declines up on provider={scope['provider']}")
        return "provider_degraded", 0.6, reasons
    if soft and "provider" in pinned:
        reasons.append(f"soft declines up on provider={scope['provider']}")
        return "provider_degraded", 0.55, reasons

    # Attribution may well have isolated a scope; what failed is the *signature* — no rule
    # recognised the shape of the declines. Saying "the excess does not concentrate
    # anywhere" here contradicts the attribution panel sitting right above it on the card.
    if pinned:
        where = " · ".join(f"{d}={scope[d]}" for d in DIMENSIONS if d in scope)
        moved = ", ".join(sig.risen) if sig.risen else "no decline category"
        reasons.append(f"the excess does concentrate on {where}, but {moved} rose in a "
                       f"combination that matches none of the known failure patterns")
    else:
        reasons.append("no rule matched: the excess does not concentrate in a recognisable pattern")
    return "insufficient_evidence", 0.3, reasons
