"""Recommendations an on-call operator can act on without a second question.

The cause tells you what broke. This module turns that into an instruction with the
nouns filled in: which provider, moving to which other provider, carrying how much
traffic, and what to look at afterwards to know it worked.

A generic string ("reroute the affected traffic away from this provider") makes the
reader do the work the engine already did — it knows which provider, it knows which
alternatives are healthy right now, and it knows how much money is on the line. Saying
it is not extra intelligence; it is refusing to throw away what we already computed.

Nothing here executes anything. Every string ends up behind `not_executed: True`.
"""
from __future__ import annotations

from api.config import N_MIN, WINDOW_SENSITIVE_MIN
from api.engine.expectation import Expector
from api.engine.incidents import IncidentRecord

MERCHANT_NAMES = {"m_fastcart": "FastCart", "m_streamly": "Streamly", "m_viajesya": "ViajesYa"}
# Rails that do not touch the card networks, per country, for when cards are the problem.
NON_CARD_RAILS = {
    "CO": "PSE, Nequi or Bre-B",
    "BR": "PIX or boleto",
    "MX": "SPEI or OXXO",
}


def _pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "n/a"


def _money(x: float) -> str:
    return f"${x:,.0f}"


def alternatives(ex: Expector, rec: IncidentRecord, dimension: str, end,
                 minutes: int = WINDOW_SENSITIVE_MIN) -> list[tuple[str, float, int]]:
    """Healthy values of `dimension` serving the same traffic as the broken one.

    The comparison drops the broken value from the scope and keeps everything else, so
    "somewhere else to send BR card traffic" does not quietly become "somewhere else to
    send all traffic". Sorted best first; only values with enough sample to trust.
    """
    if dimension not in rec.scope:
        return []
    base = {k: v for k, v in rec.scope.items() if k != dimension}
    out: list[tuple[str, float, int]] = []
    for value in ex.cube.values_of(dimension, base):
        if value == rec.scope[dimension] or not value:
            continue
        exp = ex.expect({**base, dimension: value}, end, minutes)
        n = exp.observed.operational_attempts
        if n < N_MIN or exp.observed.rate is None:
            continue
        if exp.observed.rate < exp.p0 - 0.02:
            continue  # also below its own expectation: not somewhere to send traffic
        out.append((value, exp.observed.rate, n))
    out.sort(key=lambda t: -t[1])
    return out


def _reroute_clause(alts: list[tuple[str, float, int]], broken_rate: float | None) -> str:
    if not alts:
        return ("no alternative in this segment is currently healthy enough to take the "
                "traffic — hold, and escalate to the provider instead of rerouting")
    best, rate, n = alts[0]
    tail = f" ({len(alts) - 1} other healthy option{'s' if len(alts) > 2 else ''})" if len(alts) > 1 else ""
    return (f"move it to {best}, converting {_pct(rate)} on {n:,} attempts in the same "
            f"segment right now against {_pct(broken_rate)} here{tail}")


def build(detector, rec: IncidentRecord, now,
          cause: str | None = None) -> tuple[str, str]:
    """(action, rationale) for this specific incident. Never a template with blanks.

    `cause` overrides the engine's own hypothesis, for when the agent concluded something
    different after checking it — the instruction has to follow the conclusion on the card.
    """
    ex = Expector(detector.cube)
    cause = cause or rec.cause_type or "insufficient_evidence"
    scope = rec.scope
    merchants = sorted(MERCHANT_NAMES.get(m, m) for m in _merchants_in(detector, rec))
    who = ", ".join(merchants) if merchants else "the affected merchants"
    bleed = f"{_money(rec.cost_per_min_usd)}/min"
    risen = ", ".join(rec.signature_json.get("risen") or []) or "declines"

    if cause == "provider_degraded":
        prov = scope.get("provider", "this provider")
        alts = alternatives(ex, rec, "provider", now)
        where = _reroute_clause(alts, rec.observed_rate)
        return (f"Reroute {_segment(detector, scope)} away from {prov}: {where}.",
                (f"{risen} rose on {prov} while the same issuers convert normally elsewhere, so "
                 f"this is {prov}'s side, not ours and not the issuers'. It is costing {bleed} "
                 f"and it hits {who}. After the switch, watch this segment's conversion for "
                 f"5 minutes: if it does not recover, the cause is wider than the provider."))

    if cause == "issuer_provider_routing":
        iss, prov = scope.get("issuer", "this BIN range"), scope.get("provider", "this provider")
        alts = alternatives(ex, rec, "provider", now)
        return (f"Reroute {iss} away from {prov}: {_reroute_clause(alts, rec.observed_rate)}.",
                (f"{iss} converts normally through other providers, so neither party is broken "
                 f"on its own — it is the pairing. Costing {bleed}. Do not open a ticket with "
                 f"the issuer yet; the routing change is the test."))

    if cause == "issuer_over_declining":
        iss = scope.get("issuer", "this issuer")
        return ((f"Contact {iss} with the BIN ranges and this window, and enable 3DS retry "
                 f"for them meanwhile — do not reroute."),
                (f"{iss} declines at the same elevated rate through every provider, so it is "
                 f"their decisioning and moving traffic between providers will not change it. "
                 f"Costing {bleed} across {who}. 3DS retry is the only lever on our side."))

    if cause == "network_degraded":
        brand = scope.get("brand", "this network")
        rail = NON_CARD_RAILS.get(_only_value(detector, scope, "country") or "", "a non-card rail")
        return ((f"Do not reroute providers. Tell {who} now, and push checkout toward "
                 f"{rail} while {brand} is degraded."),
                (f"The failure follows {brand} across every provider and issuer, which is the "
                 f"signature of the network itself. Every provider reaches {brand} the same way, "
                 f"so switching providers moves the traffic and not the problem. {bleed}."))

    if cause == "method_down":
        method = scope.get("method", "this rail")
        country = _only_value(detector, scope, "country") or ""
        rail = NON_CARD_RAILS.get(country, "another rail")
        return ((f"Surface an alternative at checkout for {method}"
                 f"{f' in {country}' if country else ''} — {rail} — and tell {who}."),
                (f"{method} fails independently of provider, so the rail itself is down and no "
                 f"routing choice recovers it. {bleed}. This is a checkout change, not an "
                 f"infrastructure one: nothing on our side is broken."))

    if cause == "mapping_bug":
        prov = scope.get("provider", "this provider")
        n = rec.detail.get("mismatched_attempts", int(rec.excess_declines))
        return ((f"Roll back the normalization change for {prov} and re-process the "
                 f"{n:,} affected transactions from {rec.started_at:%H:%M} onward."),
                (f"We recorded approvals {prov} never returned, so settlement, retries and "
                 f"merchant reporting are all wrong for that window — and they stay wrong after "
                 f"the bug is fixed unless the window is re-processed. Revert first, reconcile "
                 f"second; do not touch routing, the provider is fine."))

    if cause == "unmapped_provider_code":
        prov = scope.get("provider", "this provider")
        codes = ", ".join((rec.signature_json.get("unmapped_codes") or [])[:3]) or "the new codes"
        return (f"Add {codes} to the {prov} mapping table, then re-classify this window.",
                (f"{prov} is answering with codes we have no entry for, so every one of them is "
                 f"counted as a generic failure and whatever it actually means is invisible. "
                 f"Nothing was deployed wrong — the table is incomplete, so there is nothing to "
                 f"roll back. Ask {prov} what the code means before guessing at the category."))

    if cause == "internal_change":
        ev = next((e for e in detector.change_events
                   if e.id in set(rec.related_change_event_ids)), None)
        what = f"the {ev.type} at {ev.ts:%H:%M} ({ev.description})" if ev else "the change in the evidence"
        return (f"Roll back {what} and confirm this segment recovers within 5 minutes.",
                (f"The break starts inside that change's window and inside its own scope, which "
                 f"is the strongest evidence we can produce short of reverting it. {bleed}. "
                 f"If rolling back does not recover it, the change is a coincidence and this is "
                 f"a provider problem — re-run the diagnosis then."))

    if cause == "latency_spike":
        ms = rec.detail.get("latency_ms")
        base = rec.detail.get("latency_baseline_ms")
        prov = scope.get("provider", "this provider")
        return ((f"Open a latency ticket with {prov} ({ms}ms against {base}ms normal) and "
                 f"watch checkout abandonment — do not reroute yet."),
                ("Declines are normal here, so nobody is refusing the payments: people are "
                 "giving up while they wait. The cost figure is an estimate from abandonment, "
                 "not measured losses, so treat it as an upper bound and confirm on the funnel "
                 "before moving traffic."))

    if cause == "no_traffic":
        merch = MERCHANT_NAMES.get(scope.get("merchant", ""), scope.get("merchant", "this merchant"))
        drop = rec.detail.get("volume_drop")
        return ((f"Check {merch}'s checkout and our ingest — attempts fell "
                 f"{f'{drop:.0%}' if drop else 'sharply'} and the declines look normal."),
                ("Conversion is undefined here, not bad: the transactions are not arriving at "
                 "all. Look upstream — their checkout, their integration, or our ingest — and "
                 "do not touch providers or issuers, none of them have seen this traffic."))

    if cause == "insufficient_evidence":
        return ("Keep watching; do not act yet.",
                (f"The excess is real ({_pct(rec.observed_rate)} against {_pct(rec.expected_rate)} "
                 f"expected) but it does not concentrate anywhere with enough sample to name a "
                 f"cause. Acting now means guessing. If it holds, the segment will grow until it "
                 f"clears the minimum sample and the diagnosis will sharpen on its own."))

    return ("Keep watching; do not act yet.", "No playbook for this cause.")


def _only_value(detector, scope: dict[str, str], dimension: str) -> str | None:
    """The single value of `dimension` this scope actually touches, if there is only one.

    PIX is Brazil whether or not the incident scope says so, and an instruction that says
    "in BR" is worth more to the person reading it than one that says "another rail".
    """
    if dimension in scope:
        return scope[dimension]
    leaves = detector.cube.matching_leaves(scope)
    values = {detector.cube.leaf_by_key[lk][dimension] for lk in leaves}
    values.discard("")
    return values.pop() if len(values) == 1 else None


def _segment(detector, scope: dict[str, str]) -> str:
    """The traffic an instruction is talking about, in the words an operator uses."""
    method = scope.get("method")
    country = _only_value(detector, scope, "country")
    if method and country:
        return f"{method} traffic in {country}"
    if method:
        return f"{method} traffic"
    if country:
        return f"{country} traffic"
    return "the affected traffic"


def _merchants_in(detector, rec: IncidentRecord) -> set[str]:
    if "merchant" in rec.scope:
        return {rec.scope["merchant"]}
    leaves = detector.cube.matching_leaves(rec.scope)
    return {detector.cube.leaf_by_key[lk]["merchant"] for lk in leaves}
