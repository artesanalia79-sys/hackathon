"""Read tools for answering a question, as opposed to diagnosing one incident.

The diagnosis toolbox is bound to a single record: every call is implicitly "about this
incident". A person in a Slack channel is not. They ask "what is going on right now",
"is Brazil still bad", "what did we say about dLocal an hour ago" — so these tools take
the whole world as their subject and let the caller pick the scope.

Same cube, same expectations, same numbers as the incident card. Nothing here can write,
and nothing here can see the injector: what is *actually* wrong is the simulator's
secret, and an answer that leaked it would be an answer nobody could trust.
"""
from __future__ import annotations

from datetime import timedelta

from api.config import WINDOW_SENSITIVE_MIN
from api.domain import DIMENSIONS
from api.engine.cube import agg_to_json
from api.engine.expectation import Expector
from api.engine.playbook import build as build_playbook
from api.engine.signature import CAUSE_LABEL, build_signature

MERCHANT_NAMES = {"m_fastcart": "FastCart", "m_streamly": "Streamly", "m_viajesya": "ViajesYa"}
MAX_ROWS = 12
MAX_INCIDENTS = 15


class AskToolBox:
    """Every question anyone can ask the channel, answerable from live state."""

    def __init__(self, world) -> None:
        self.world = world
        self.detector = world.detector
        self.cube = world.cube
        self.now = world.now
        self.ex = Expector(self.cube)

    # --- helpers -----------------------------------------------------------
    def _clean_scope(self, scope: dict | None) -> dict[str, str]:
        """Keep only dimensions that exist and values the cube has actually seen.

        A model asking about `country=Brazil` or `provider=DLocal` is asking a real
        question with the wrong spelling; silently dropping the filter would answer a
        different question, so unknown values are reported back instead.
        """
        out: dict[str, str] = {}
        for k, v in (scope or {}).items():
            if k not in DIMENSIONS or not v:
                continue
            known = self.cube.index.get(k) or {}
            if v in known:
                out[k] = v
            else:
                match = next((c for c in known if c.lower() == str(v).lower()), None)
                if match:
                    out[k] = match
        return out

    def _minutes(self, minutes) -> int:
        try:
            m = int(minutes)
        except (TypeError, ValueError):
            return WINDOW_SENSITIVE_MIN
        return max(1, min(240, m))

    def _incident_brief(self, rec) -> dict:
        return {
            "incident_id": rec.id,
            "status": rec.status,
            "kind": rec.kind,
            "scope": rec.scope,
            "cause": rec.cause_type,
            "cause_label": CAUSE_LABEL.get(rec.cause_type or "", rec.cause_type),
            "cost_per_min_usd": round(rec.cost_per_min_usd, 2),
            "cost_so_far_usd": round(rec.cost_usd, 2),
            "observed_rate": round(rec.observed_rate, 4),
            "expected_rate": round(rec.expected_rate, 4),
            "started_at": rec.started_at.isoformat(),
            "minutes_open": round(rec.duration_min, 1),
            "confidence": round(rec.confidence, 2),
        }

    # --- tools -------------------------------------------------------------
    def system_status(self) -> dict:
        """The board right now: clock, what is open, what it is costing in total."""
        open_recs = self.detector.open_incidents()
        exp = self.ex.expect({}, self.now, WINDOW_SENSITIVE_MIN)
        return {
            "clock": self.now.isoformat(),
            "sim_speed": self.world.sim_speed,
            "platform_conversion_now": round(exp.observed_rate, 4) if exp.observed_rate else None,
            "platform_conversion_expected": round(exp.p0, 4),
            "attempts_last_5min": exp.observed.operational_attempts,
            "open_incidents": len(open_recs),
            "confirmed": sum(1 for r in open_recs if r.status == "confirmed"),
            "watching": sum(1 for r in open_recs if r.status == "watching"),
            "total_bleed_per_min_usd": round(sum(r.cost_per_min_usd for r in open_recs), 2),
            "incidents": [self._incident_brief(r) for r in
                          sorted(open_recs, key=lambda r: -r.cost_per_min_usd)[:MAX_INCIDENTS]],
        }

    def list_incidents(self, status: str | None = None, limit: int = 10) -> dict:
        """Incidents on the board, newest and most expensive first. `status` filters."""
        recs = list(self.detector.incidents.values())
        if status:
            recs = [r for r in recs if r.status == status]
        recs.sort(key=lambda r: (r.status != "confirmed", -r.cost_per_min_usd))
        limit = max(1, min(MAX_INCIDENTS, int(limit or 10)))
        return {"count": len(recs), "incidents": [self._incident_brief(r) for r in recs[:limit]],
                "note": "statuses are watching, confirmed, resolved, expired"}

    def incident_detail(self, incident_id: str) -> dict:
        """Everything on one incident's card, including what we recommended and why."""
        rec = self.detector.incidents.get(incident_id)
        if rec is None:
            return {"error": f"no incident {incident_id}",
                    "hint": "call list_incidents to see the ids that exist"}
        action, rationale = build_playbook(self.detector, rec, self.now)
        diag = rec.diagnosis or {}
        return {
            **self._incident_brief(rec),
            "engine_reasons": rec.reasons,
            "signature_before": {k: round(v, 4) for k, v in rec.signature_before.items() if v},
            "signature_during": {k: round(v, 4) for k, v in rec.signature_during.items() if v},
            "categories_that_rose": rec.signature_json.get("risen") or [],
            "attribution": rec.attribution_json,
            "cost_breakdown_per_min": rec.cost_breakdown,
            "recommended_action": action,
            "why": rationale,
            "diagnosis_source": diag.get("source"),
            "agent_explanation": diag.get("ops_explanation"),
            "alerted": rec.alerted_at.isoformat() if rec.alerted_at else None,
            "alerted_by": rec.alerted_by or None,
            "resolved_at": rec.resolved_at.isoformat() if rec.resolved_at else None,
        }

    def slice_metrics(self, scope: dict | None = None, minutes: int | None = None) -> dict:
        """Conversion for any segment against its own seasonal expectation."""
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        exp = self.ex.expect(sc, self.now, m)
        if exp.observed.attempts == 0:
            return {"scope": sc, "minutes": m, "attempts": 0,
                    "note": "no traffic matched this scope in the window"}
        obs = agg_to_json(exp.observed)
        # `rate` is too easy to misread as a share of volume — a model asked "how is
        # Brazil doing" answered "73% of its expected attempts are happening", which is
        # the conversion rate wearing the wrong noun. The field says what it is.
        obs["conversion_rate"] = obs.pop("rate", None)
        return {
            "scope": sc, "minutes": m,
            **obs,
            "expected_conversion_rate": round(exp.p0, 4),
            "excess_declines": round(exp.excess_declines, 1),
            "below_expectation": bool(exp.observed.rate is not None
                                      and exp.observed.rate < exp.p0 - 0.02),
            "units": ("conversion_rate and expected_conversion_rate are the share of "
                      "operational attempts that were approved, 0-1. attempts and "
                      "operational_attempts are counts of transactions."),
        }

    def compare_across(self, scope: dict | None = None, dimension: str = "provider",
                       minutes: int | None = None) -> dict:
        """Split a segment by a dimension: who is healthy and who is not."""
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        if dimension not in DIMENSIONS:
            return {"error": f"unknown dimension {dimension!r}", "valid": list(DIMENSIONS)}
        rows = []
        for v in self.cube.values_of(dimension, sc):
            if not v:
                continue
            exp = self.ex.expect({**sc, dimension: v}, self.now, m)
            if exp.observed.attempts == 0:
                continue
            rows.append({"value": v,
                         "operational_attempts": exp.observed.operational_attempts,
                         "conversion_rate": round(exp.observed.rate, 4) if exp.observed.rate else None,
                         "expected_conversion_rate": round(exp.p0, 4),
                         "excess_declines": round(exp.excess_declines, 1),
                         "below_expectation": bool(exp.observed.rate is not None
                                                   and exp.observed.rate < exp.p0 - 0.02)})
        rows.sort(key=lambda r: -r["excess_declines"])
        return {"scope": sc, "dimension": dimension, "minutes": m, "rows": rows[:MAX_ROWS],
                "units": "conversion_rate is approvals / operational attempts, 0-1."}

    def decline_signature(self, scope: dict | None = None, minutes: int | None = None) -> dict:
        """Which decline categories rose in a segment, and the raw codes behind them."""
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        obs = self.ex.observed(sc, self.now, m, full=True)
        sea = self.ex.seasonal(sc, self.now, m)
        if obs.attempts == 0:
            return {"scope": sc, "minutes": m, "note": "no traffic matched this scope"}
        sig = build_signature(obs, sea)
        return {"scope": sc, "minutes": m, **sig.to_json()}

    def change_events(self, window_minutes: int | None = 120) -> dict:
        """Deploys, routing rules and mapping changes we know about."""
        m = self._minutes(window_minutes)
        cutoff = self.now - timedelta(minutes=m)
        events = [e for e in self.detector.change_events if e.ts >= cutoff]
        events.sort(key=lambda e: e.ts, reverse=True)
        return {"window_minutes": m, "count": len(events),
                "events": [{"id": e.id, "type": e.type, "at": e.ts.isoformat(),
                            "scope": e.scope, "description": e.description}
                           for e in events[:MAX_ROWS]]}

    def history(self, hours: int = 6) -> dict:
        """Incidents that already closed, so "has this happened before" is answerable."""
        hours = max(1, min(72, int(hours or 6)))
        cutoff = self.now - timedelta(hours=hours)
        recs = [r for r in self.detector.incidents.values()
                if r.status in ("resolved", "expired") and r.last_seen_at >= cutoff]
        recs.sort(key=lambda r: r.last_seen_at, reverse=True)
        return {"hours": hours, "count": len(recs),
                "incidents": [{**self._incident_brief(r),
                               "resolution": r.detail.get("resolution") or (
                                   r.reasons[0] if r.reasons else "")}
                              for r in recs[:MAX_INCIDENTS]]}

    # --- dispatch ----------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        fn = {
            "system_status": lambda a: self.system_status(),
            "list_incidents": lambda a: self.list_incidents(a.get("status"), a.get("limit", 10)),
            "incident_detail": lambda a: self.incident_detail(a.get("incident_id", "")),
            "slice_metrics": lambda a: self.slice_metrics(a.get("scope"), a.get("minutes")),
            "compare_across": lambda a: self.compare_across(a.get("scope"),
                                                            a.get("dimension", "provider"),
                                                            a.get("minutes")),
            "decline_signature": lambda a: self.decline_signature(a.get("scope"),
                                                                  a.get("minutes")),
            "change_events": lambda a: self.change_events(a.get("window_minutes", 120)),
            "history": lambda a: self.history(a.get("hours", 6)),
        }.get(name)
        if fn is None:
            return {"error": f"unknown tool {name!r}"}
        try:
            return fn(args or {})
        except Exception as exc:                    # a bad argument is an answer, not a crash
            return {"error": f"{type(exc).__name__}: {exc}"}
