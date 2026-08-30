"""Reading the board: incidents, diagnoses, traces, and the numbers behind them."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.config import (
    EWMA_HOURS,
    HISTORY_DAYS,
    N_MIN,
    SEASONAL_WEIGHT,
    WINDOW_SENSITIVE_MIN,
)
from api.engine.diagnose import deterministic_diagnosis, refresh_numbers
from api.engine.expectation import Expector
from api.engine.memory import find_similar_incidents
from api.runtime import get_world

router = APIRouter(tags=["incidents"])


@router.get("/incidents")
def list_incidents(include_closed: bool = Query(True),
                   include_superseded: bool = Query(False)) -> dict:
    """Superseded records are hidden by default.

    They are the same story at a different depth, already folded into a broader incident;
    showing them would put the same outage on the board several times.
    """
    w = get_world()
    rows = [r for r in w.incidents_sorted()
            if (include_closed or r.status in ("watching", "confirmed"))
            and (include_superseded or not r.detail.get("superseded_by"))]
    return {
        "now": w.now.isoformat(),
        "incidents": [r.to_json() for r in rows],
        "open_count": len(w.detector.open_incidents()),
        "total_cost_per_min_usd": round(
            sum(r.cost_per_min_usd for r in w.detector.open_incidents()), 2),
    }


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> dict:
    w = get_world()
    rec = w.incident(incident_id)
    if rec is None:
        raise HTTPException(404, "no such incident")
    ex = Expector(w.cube)
    exp = ex.expect(rec.scope, w.now, WINDOW_SENSITIVE_MIN)

    # A live incident's chart follows it; a finished one is history and stops moving.
    start, end = w.detector.chart_window(rec, w.now)
    live_chart = rec.status in ("watching", "confirmed")
    if rec.frozen_series is not None:
        series = rec.frozen_series
    else:
        minutes = max(1, int((end - start).total_seconds() // 60) + 1)
        series = w.cube.series(rec.scope, end, minutes)

    n = exp.observed.operational_attempts
    return {
        **rec.to_json(),
        "series": series,
        "chart": {
            "from": start.isoformat(), "to": end.isoformat(),
            "live": live_chart, "frozen": rec.frozen_series is not None,
            "incident_from": rec.started_at.isoformat(),
            "incident_to": (rec.resolved_at or (rec.last_seen_at if rec.status == "expired"
                                                else None)),
            "caption": ("30 min before it started, up to now"
                        if live_chart else "30 min before it started to 30 min after it ended"),
        },
        # Everything a reader needs to check the expectation instead of trusting it.
        "baseline": {
            "window_minutes": WINDOW_SENSITIVE_MIN,
            "expected_rate": round(exp.p0, 4),
            "seasonal_rate": round(exp.seasonal_rate, 4) if exp.seasonal_rate is not None else None,
            "seasonal_weight": SEASONAL_WEIGHT,
            "recent_rate": round(exp.ewma_rate, 4) if exp.ewma_rate is not None else None,
            "recent_weight": round(1 - SEASONAL_WEIGHT, 2),
            "recent_hours": EWMA_HOURS,
            "history_days": HISTORY_DAYS,
            "observed_rate": round(exp.observed.rate, 4) if exp.observed.rate is not None else None,
            "attempts": exp.observed.attempts,
            "operational_attempts": n,
            "hard_declines_excluded": exp.observed.hard_declines,
            "observed_approved": exp.observed.approved,
            "expected_approved": round(exp.expected_approved),
            "excess_declines": round(exp.excess_declines, 1),
            "min_sample": N_MIN,
            "enough_sample": n >= N_MIN,
        },
        "similar_past": find_similar_incidents(w.detector, rec),
        "change_events": [e.model_dump(mode="json") for e in w.detector.change_events
                          if e.id in set(rec.related_change_event_ids)],
    }


@router.get("/incidents/{incident_id}/diagnosis")
def get_diagnosis(incident_id: str) -> dict:
    """The diagnosis, or the deterministic one computed on the spot if none exists yet.

    An incident is never left without an explanation, agent or no agent.
    """
    w = get_world()
    rec = w.incident(incident_id)
    if rec is None:
        raise HTTPException(404, "no such incident")
    if rec.diagnosis:
        return {"diagnosis": refresh_numbers(w.detector, rec, rec.diagnosis),
                "pending": rec.diagnosis_pending}
    diag = deterministic_diagnosis(w.detector, rec,
                                   reason="agent has not run for this incident yet")
    return {"diagnosis": diag.model_dump(mode="json"), "pending": rec.diagnosis_pending}


@router.get("/incidents/{incident_id}/trace")
def get_trace(incident_id: str) -> dict:
    """Every tool call the agent made. This is what makes a claim auditable."""
    w = get_world()
    rec = w.incident(incident_id)
    if rec is None:
        raise HTTPException(404, "no such incident")
    return w.agent_runs.get(incident_id) or {
        "incident_id": incident_id, "status": "not_run", "steps": [],
        "error": "no agent run for this incident (it may not be confirmed yet, "
                 "or no OPENAI_API_KEY is configured)",
    }


@router.post("/incidents/{incident_id}/ack")
def acknowledge(incident_id: str, by: str = Query("ops")) -> dict:
    """Humans acknowledge; only the detector ever closes an incident."""
    w = get_world()
    rec = w.incident(incident_id)
    if rec is None:
        raise HTTPException(404, "no such incident")
    rec.acknowledged_by = by
    return {"ok": True, "incident": rec.to_json()}


@router.get("/segment")
def segment(minutes: int = Query(30, ge=1, le=240), merchant: str | None = None,
            country: str | None = None, method: str | None = None, brand: str | None = None,
            issuer: str | None = None, provider: str | None = None) -> dict:
    """Ad-hoc slice — the manual cross-filtering this system exists to replace.

    Also backs the injection form's preview: before you inject into a scope, it tells you
    how much traffic that scope actually carries, so "nothing happened" is never a mystery.
    """
    w = get_world()
    scope = {k: v for k, v in {"merchant": merchant, "country": country, "method": method,
                               "brand": brand, "issuer": issuer, "provider": provider}.items() if v}
    ex = Expector(w.cube)
    exp = ex.expect(scope, w.now, minutes)
    leaves = len(w.cube.matching_leaves(scope))
    per_min = exp.observed.attempts / minutes if minutes else 0
    in_window = per_min * WINDOW_SENSITIVE_MIN
    if leaves == 0:
        verdict = "No segment matches this combination — nothing would happen."
    elif in_window < N_MIN:
        verdict = (f"Only ~{in_window:.0f} attempts per {WINDOW_SENSITIVE_MIN}-min window, "
                   f"below the minimum of {N_MIN}. Expect 'insufficient evidence' rather "
                   f"than a named cause — which is the correct answer here.")
    elif in_window < N_MIN * 4:
        verdict = (f"~{in_window:.0f} attempts per window: detectable, but it may take "
                   f"longer to confirm and the cause may stay low-confidence.")
    else:
        verdict = f"~{in_window:.0f} attempts per window — comfortably detectable."
    return {
        "scope": scope, "minutes": minutes,
        "attempts": exp.observed.attempts,
        "operational_attempts": exp.observed.operational_attempts,
        "observed_rate": round(exp.observed.rate, 4) if exp.observed.rate is not None else None,
        "expected_rate": round(exp.p0, 4),
        "excess_declines": round(exp.excess_declines, 1),
        "by_category": {k: v for k, v in exp.observed.by_category.items() if v},
        "series": w.cube.series(scope, w.now, minutes),
        "preview": {
            "segments_matched": leaves,
            "segments_total": len(w.cube.leaves),
            "attempts_per_min": round(per_min),
            "attempts_per_window": round(in_window),
            "min_sample": N_MIN,
            "detectable": leaves > 0 and in_window >= N_MIN,
            "verdict": verdict,
        },
    }
