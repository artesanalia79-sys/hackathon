"""Incident memory: resolved incidents, scored against the one in front of us.

"This already happened on Tuesday, it was dLocal, and rerouting fixed it in 40
minutes" is worth more to an on-call human than any amount of fresh analysis.
"""
from __future__ import annotations

from api.config import SIMILARITY_THRESHOLD
from api.engine.incidents import IncidentRecord
from api.engine.stats import jaccard, js_divergence


def similarity(a: IncidentRecord, b: IncidentRecord) -> float:
    """0.5 scope + 0.3 same cause + 0.2 same decline signature."""
    scope_score = jaccard(a.scope, b.scope)
    cause_score = 1.0 if (a.cause_type and a.cause_type == b.cause_type) else 0.0
    sig_score = 1.0 - js_divergence(a.signature_during, b.signature_during)
    return 0.5 * scope_score + 0.3 * cause_score + 0.2 * sig_score


def find_similar_incidents(detector, incident: IncidentRecord,
                           threshold: float = SIMILARITY_THRESHOLD,
                           limit: int = 3) -> list[dict]:
    out = []
    for past in detector.incidents.values():
        if past.id == incident.id or past.status != "resolved":
            continue
        score = similarity(incident, past)
        if score < threshold:
            continue
        out.append({
            "incident_id": past.id,
            "started_at": past.started_at.isoformat(),
            "duration_min": round(past.duration_min, 1),
            "cause_type": past.cause_type,
            "scope": past.scope,
            "cost_usd": round(past.cost_usd, 2),
            "similarity": round(score, 3),
            "resolution": past.detail.get("resolution") or (past.reasons[0] if past.reasons else ""),
        })
    out.sort(key=lambda d: d["similarity"], reverse=True)
    return out[:limit]
