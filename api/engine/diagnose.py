"""The deterministic diagnosis — the answer that always exists.

The agent narrates and recommends; this module is what runs when there is no agent,
when the agent times out, and when the agent says something its tools did not support.
It is not a stub: it is the fallback the whole design leans on.
"""
from __future__ import annotations

from api.domain import (
    Affected,
    Diagnosis,
    Evidence,
    Recommendation,
    RootCause,
    SignatureDiff,
    SimilarIncident,
)
from api.engine.incidents import IncidentRecord
from api.engine.memory import find_similar_incidents
from api.engine.playbook import build as build_playbook
from api.engine.signature import CAUSE_LABEL

MERCHANT_NAMES = {"m_fastcart": "FastCart", "m_streamly": "Streamly", "m_viajesya": "ViajesYa"}


def scope_phrase(scope: dict[str, str]) -> str:
    if not scope:
        return "the whole platform"
    order = ["provider", "issuer", "brand", "method", "country", "merchant"]
    parts = [f"{k}={scope[k]}" for k in order if k in scope]
    parts += [f"{k}={v}" for k, v in scope.items() if k not in order]
    return " · ".join(parts)


def affected_merchants(detector, rec: IncidentRecord) -> list[str]:
    if "merchant" in rec.scope:
        return [MERCHANT_NAMES.get(rec.scope["merchant"], rec.scope["merchant"])]
    leaves = detector.cube.matching_leaves(rec.scope)
    names = {detector.cube.leaf_by_key[lk]["merchant"] for lk in leaves}
    return sorted(MERCHANT_NAMES.get(n, n) for n in names)


def build_evidence(rec: IncidentRecord) -> list[Evidence]:
    """The engine's own steps, cited the same way the agent has to cite its tools."""
    ev = [Evidence(tool_call_id="engine.detector", claim=rec.reasons[0] if rec.reasons else
                   f"conversion {rec.observed_rate:.1%} against {rec.expected_rate:.1%} expected")]
    if rec.attribution_json:
        node = rec.attribution_json[0]
        path = " -> ".join(f"{p['dimension']}={p['value']} (EP {p['explanatory_power']:.0%}, "
                           f"lift {p.get('lift', 0):.1f}x)" for p in node.get("path", []))
        ev.append(Evidence(tool_call_id="engine.adtributor",
                           claim=f"excess isolated to {scope_phrase(rec.scope)}"
                                 + (f" via {path}" if path else "")
                                 + f"; stopped because {node.get('stop_reason', 'n/a')}"))
    risen = rec.signature_json.get("risen") or []
    if risen:
        during = rec.signature_during
        before = rec.signature_before
        shifts = ", ".join(f"{c} {before.get(c, 0):.1%} -> {during.get(c, 0):.1%}" for c in risen)
        ev.append(Evidence(tool_call_id="engine.signature",
                           claim=f"decline signature moved: {shifts}"))
    for reason in rec.reasons[1:]:
        ev.append(Evidence(tool_call_id="engine.classifier", claim=reason))
    ev.append(Evidence(tool_call_id="engine.cost",
                       claim=f"${rec.cost_per_min_usd:,.0f} per minute, "
                             f"${rec.cost_usd:,.0f} since {rec.started_at:%H:%M}"))
    return ev


def ops_text(rec: IncidentRecord, similar: list[dict]) -> str:
    risen = rec.signature_json.get("risen") or []
    bits = [(f"{CAUSE_LABEL.get(rec.cause_type or '', rec.cause_type or 'unknown')} on "
            f"{scope_phrase(rec.scope)}, since {rec.started_at:%H:%M}.")]
    if rec.kind == "conversion_drop":
        bits.append(f"Operational conversion is {rec.observed_rate:.1%} against "
                    f"{rec.expected_rate:.1%} expected for this hour and weekday, "
                    f"{rec.excess_declines:.0f} excess declines in the window.")
    if risen:
        during, before = rec.signature_during, rec.signature_before
        bits.append("Decline mix moved: " + ", ".join(
            f"{c} from {before.get(c, 0):.1%} to {during.get(c, 0):.1%}" for c in risen) + ".")
    for reason in rec.reasons[1:]:
        bits.append(reason[0].upper() + reason[1:] + ".")
    if similar:
        s = similar[0]
        bits.append(f"We have seen this before ({s['started_at'][:16].replace('T', ' ')}, "
                    f"{s['duration_min']:.0f} min, ${s['cost_usd']:,.0f}): {s['resolution']}.")
    return " ".join(bits)


def exec_text(rec: IncidentRecord, merchants: list[str]) -> str:
    who = ", ".join(merchants[:3]) if merchants else "the platform"
    label = CAUSE_LABEL.get(rec.cause_type or "", "an unresolved issue")
    if rec.kind == "no_traffic":
        return (f"{who} stopped sending traffic {rec.duration_min:.0f} minutes ago — "
                f"about ${rec.cost_per_min_usd:,.0f}/min of attempts not arriving. "
                f"Not a decline problem.")
    if rec.kind == "data_integrity":
        return (f"We are reporting approvals that {rec.scope.get('provider', 'a provider')} "
                f"never confirmed — roughly ${rec.cost_per_min_usd:,.0f}/min of revenue booked "
                f"that may not exist. Every downstream number is wrong until this is reverted.")
    return (f"{who}: losing about ${rec.cost_per_min_usd:,.0f} per minute "
            f"(${rec.cost_usd:,.0f} so far) to {label} on {scope_phrase(rec.scope)}. "
            f"Recommended action is ready; nothing has been changed automatically.")


def refresh_numbers(detector, rec: IncidentRecord, stored: dict) -> dict:
    """Re-attach the engine's *current* figures to a stored diagnosis.

    A diagnosis is written once, but the incident keeps costing money. Freezing the
    numbers at diagnosis time makes the headline disagree with the tile right above it
    a few minutes later. The agent's words are its own and stay put; every figure is
    the engine's and is recomputed on read — which is the same rule the agent runs
    under, applied all the way to the screen.

    A deterministic diagnosis is regenerated outright: its prose has the numbers
    written into it, so there is nothing to preserve.
    """
    if stored.get("source") != "agent":
        return deterministic_diagnosis(
            detector, rec, reason=stored.get("fallback_reason")).model_dump(mode="json")

    fresh = deterministic_diagnosis(detector, rec).model_dump(mode="json")
    out = dict(stored)
    for key in ("affected", "signature", "similar_past", "related_change_events"):
        out[key] = fresh[key]
    return out


def deterministic_diagnosis(detector, rec: IncidentRecord,
                            reason: str | None = None) -> Diagnosis:
    similar = find_similar_incidents(detector, rec)
    merchants = affected_merchants(detector, rec)
    action, rationale = build_playbook(detector, rec, rec.last_seen_at)
    events = [e for e in detector.change_events if e.id in set(rec.related_change_event_ids)]
    return Diagnosis(
        incident_id=rec.id,
        root_cause=RootCause(type=rec.cause_type or "insufficient_evidence", scope=rec.scope),
        since=rec.started_at,
        confidence=round(rec.confidence, 2),
        evidence=build_evidence(rec),
        affected=Affected(merchants=merchants,
                          excess_declines=round(rec.excess_declines, 1),
                          cost_per_min_usd=round(rec.cost_per_min_usd, 2)),
        signature=SignatureDiff(before=rec.signature_before, during=rec.signature_during,
                                risen=rec.signature_json.get("risen") or []),
        related_change_events=events,
        similar_past=[SimilarIncident(incident_id=s["incident_id"], started_at=s["started_at"],
                                      duration_min=s["duration_min"], cause_type=s["cause_type"],
                                      cost_usd=s["cost_usd"], similarity=s["similarity"])
                      for s in similar],
        recommendation=Recommendation(action=action, rationale=rationale),
        ops_explanation=ops_text(rec, similar),
        exec_line=exec_text(rec, merchants),
        source="deterministic_fallback",
        fallback_reason=reason,
    )
