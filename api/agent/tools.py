"""Tool implementations. Every one reads the same cube the engine decided on.

Exactly one tool has an effect outside this process: `send_slack_alert`, which raises
the incident in the on-call channel. It notifies people; it does not touch payments.
The agent still cannot change routing, cannot close an incident and cannot reach a
provider — by construction, not by prompt. That boundary is the point: interrupting a
human is reversible by the human, moving live traffic is not.
"""
from __future__ import annotations

import re
from datetime import timedelta

from api.config import WINDOW_SENSITIVE_MIN
from api.engine.cube import agg_to_json
from api.engine.expectation import Expector
from api.engine.incidents import IncidentRecord
from api.engine.memory import find_similar_incidents
from api.engine.playbook import build as build_playbook
from api.engine.signature import build_signature

MAX_ROWS = 12


# The agent may narrate an alert; it may not price one. Same rule as the incident card.
MONEY_IN_HEADLINE = re.compile(r"[$€£]\s*\d|\b\d[\d.,]*\s*(?:usd|dollars?|d[oó]lares)\b",
                               re.IGNORECASE)


class ToolBox:
    def __init__(self, detector, rec: IncidentRecord, now) -> None:
        self.alerted = False
        self.detector = detector
        self.cube = detector.cube
        self.rec = rec
        self.now = now
        self.ex = Expector(self.cube)

    # --- helpers -----------------------------------------------------------
    def _clean_scope(self, scope: dict | None) -> dict[str, str]:
        """Keep only dimensions pinned to a value that exists in this world.

        The schema lists all six dimensions, so models fill them all in and mark the
        irrelevant ones "", "any" or "all". Every one of those means "any", which is the
        same as not naming the dimension. Passing them through as literal values matched
        zero leaves and handed the agent an empty answer from every tool — which it then
        correctly refused to draw a conclusion from.
        """
        out: dict[str, str] = {}
        for dim, val in (scope or {}).items():
            known = self.cube.index.get(dim)
            if known and val is not None and str(val) in known:
                out[dim] = str(val)
        return out

    def _minutes(self, minutes) -> int:
        try:
            m = int(minutes)
        except (TypeError, ValueError):
            m = WINDOW_SENSITIVE_MIN
        return max(1, min(120, m))

    # --- tools -------------------------------------------------------------
    def get_incident_summary(self) -> dict:
        rec = self.rec
        return {
            "incident_id": rec.id,
            "kind": rec.kind,
            "scope_isolated_by_engine": rec.scope,
            "status": rec.status,
            "started_at": rec.started_at.isoformat(),
            "minutes_running": round((self.now - rec.started_at).total_seconds() / 60.0, 1),
            "observed_rate": round(rec.observed_rate, 4),
            "expected_rate": round(rec.expected_rate, 4),
            "excess_declines_in_window": round(rec.excess_declines, 1),
            "attribution": rec.attribution_json,
            "signature": rec.signature_json,
            "engine_hypothesis": rec.cause_type,
            "engine_reasons": rec.reasons,
            "note": "The engine's hypothesis is a starting point, not an answer. "
                    "Check it against the other tools. Money is deliberately not in "
                    "this payload: the engine prices the incident and the card shows "
                    "that figure. Never state an amount of money in your own words.",
        }

    def slice_metrics(self, scope: dict | None = None, minutes: int | None = None) -> dict:
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        exp = self.ex.expect(sc, self.now, m)
        if exp.observed.attempts == 0:
            return {"scope": sc, "minutes": m, "attempts": 0,
                    "note": "no traffic matched this scope in the window"}
        observed = agg_to_json(exp.observed)
        observed.pop("avg_ticket_usd", None)   # the agent has no business quoting money
        return {
            "scope": sc, "minutes": m,
            **observed,
            "expected_rate": round(exp.p0, 4),
            "seasonal_rate": round(exp.seasonal_rate, 4) if exp.seasonal_rate is not None else None,
            "recent_baseline_rate": round(exp.ewma_rate, 4) if exp.ewma_rate is not None else None,
            "excess_declines": round(exp.excess_declines, 1),
            "below_expectation": bool(exp.observed.rate is not None and exp.observed.rate < exp.p0 - 0.02),
        }

    def compare_across(self, scope: dict | None = None, dimension: str = "provider",
                       minutes: int | None = None) -> dict:
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        from api.domain import DIMENSIONS
        if dimension not in DIMENSIONS:
            return {"error": f"unknown dimension {dimension!r}; valid: {list(DIMENSIONS)}"}
        if not self.cube.matching_leaves(sc):
            return {"scope": sc, "dimension": dimension, "rows": [],
                    "note": "no segment matches that scope"}
        values = self.cube.values_of(dimension, sc)
        if not values:
            return {"scope": sc, "dimension": dimension, "rows": [],
                    "note": f"{dimension} does not apply inside that scope "
                            "(alternative payment methods have no brand or issuer)"}
        rows = []
        for v in values:
            exp = self.ex.expect({**sc, dimension: v}, self.now, m)
            if exp.observed.attempts == 0:
                continue
            rows.append({
                "value": v,
                "operational_attempts": exp.observed.operational_attempts,
                "observed_rate": round(exp.observed.rate, 4) if exp.observed.rate is not None else None,
                "expected_rate": round(exp.p0, 4),
                "excess_declines": round(exp.excess_declines, 1),
                "below_expectation": bool(exp.observed.rate is not None
                                          and exp.observed.rate < exp.p0 - 0.02),
                "enough_sample": exp.observed.operational_attempts >= 40,
            })
        rows.sort(key=lambda r: -r["excess_declines"])
        hurt = [r["value"] for r in rows if r["below_expectation"] and r["enough_sample"]]
        healthy = [r["value"] for r in rows if not r["below_expectation"] and r["enough_sample"]]
        return {"scope": sc, "dimension": dimension, "minutes": m, "rows": rows[:MAX_ROWS],
                "below_expectation": hurt, "healthy": healthy}

    def decline_signature(self, scope: dict | None = None, minutes: int | None = None) -> dict:
        sc = self._clean_scope(scope)
        m = self._minutes(minutes)
        obs = self.ex.observed(sc, self.now, m, full=True)
        sea = self.ex.seasonal(sc, self.now, m)
        if obs.attempts == 0:
            return {"scope": sc, "minutes": m, "note": "no traffic matched this scope"}
        sig = build_signature(obs, sea)
        return {"scope": sc, "minutes": m, "attempts": obs.attempts, **sig.to_json(),
                "reading": "shares are of all attempts, approvals included; "
                           "`risen` lists the categories that grew against this segment's own history"}

    def change_events(self, window_minutes: int | None = None) -> dict:
        w = max(1, min(240, int(window_minutes or 30)))
        centre = self.rec.started_at
        lo, hi = centre - timedelta(minutes=w), centre + timedelta(minutes=w)
        rows = [{"id": e.id, "ts": e.ts.isoformat(), "type": e.type, "scope": e.scope,
                 "description": e.description,
                 "minutes_from_incident_start": round((e.ts - centre).total_seconds() / 60.0, 1)}
                for e in self.detector.change_events if lo <= e.ts <= hi]
        rows.sort(key=lambda r: abs(r["minutes_from_incident_start"]))
        return {"window_minutes": w, "around": centre.isoformat(), "events": rows[:MAX_ROWS],
                "count": len(rows)}

    async def send_slack_alert(self, headline: str = "", urgency: str = "notify") -> dict:
        """Raise this incident in the on-call channel. The one tool with an outside effect.

        The agent decides whether an incident is worth interrupting a human for, and says
        why in its own words. It still cannot write figures: the alert carries the
        engine's numbers and the engine's recommended action, and a headline containing an
        amount of money is refused rather than quietly stripped, so the model learns the
        rule from the tool result instead of being silently overruled.
        """
        from api.config import PUBLIC_BASE_URL
        from api.notify import slack

        if self.rec.status != "confirmed":
            return {"sent": False,
                    "error": "only confirmed incidents may be raised in Slack"}
        if not slack.enabled():
            return {"sent": False,
                    "error": "alerting is not configured on this deployment (no webhook). "
                             "Continue and conclude; the incident card is unaffected."}
        if self.rec.alerted_at is not None:
            return {"sent": False,
                    "error": "this incident was already raised; one alert is enough"}
        if self.alerted:
            return {"sent": False,
                    "error": "you already alerted on this incident in this run; one is enough"}
        if not slack.should_alert(self.rec):
            return {"sent": False,
                    "error": "this confirmed incident is below the configured alert threshold; "
                             "continue and conclude without paging"}
        headline = (headline or "").strip()
        if not headline:
            return {"sent": False, "error": "headline is required: say what is wrong in one line"}
        if MONEY_IN_HEADLINE.search(headline):
            return {"sent": False,
                    "error": "the headline states an amount of money. The engine attaches the "
                             "cost itself — rewrite the headline without figures and call again."}
        if urgency not in ("page", "notify", "fyi"):
            urgency = "notify"

        # The diagnosis does not exist yet — this call happens before `conclude` — so the
        # recommendation is computed here rather than left as "see the incident card".
        action, rationale = build_playbook(self.detector, self.rec, self.now)
        payload = slack.build_agent_message(self.rec, headline, urgency,
                                            self.rec.diagnosis, PUBLIC_BASE_URL,
                                            action, rationale)
        sent = await slack.deliver(payload, self.rec.id)
        if sent:
            self.alerted = True
            self.rec.alerted_at = self.now
            self.rec.alerted_by = "agent"
        return {"sent": sent, "urgency": urgency, "channel": "slack",
                "note": ("delivered to the on-call channel with the engine's figures attached"
                         if sent else "the webhook rejected it; the incident card is unaffected")}

    def find_similar_incidents(self) -> dict:
        matches = [{k: v for k, v in m.items() if k != "cost_usd"}
                   for m in find_similar_incidents(self.detector, self.rec)]
        return {"matches": matches, "count": len(matches),
                "note": "similarity is 0.5 scope + 0.3 same cause + 0.2 same decline signature"}

    # --- dispatch ----------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        fn = {
            "get_incident_summary": lambda a: self.get_incident_summary(),
            "slice_metrics": lambda a: self.slice_metrics(a.get("scope"), a.get("minutes")),
            "compare_across": lambda a: self.compare_across(a.get("scope"),
                                                            a.get("dimension", "provider"),
                                                            a.get("minutes")),
            "decline_signature": lambda a: self.decline_signature(a.get("scope"), a.get("minutes")),
            "change_events": lambda a: self.change_events(a.get("window_minutes")),
            "find_similar_incidents": lambda a: self.find_similar_incidents(),
        }.get(name)
        if fn is None:
            return {"error": f"no such tool: {name}"}
        try:
            return fn(args or {})
        except Exception as exc:  # a bad argument must not kill the run
            return {"error": f"{type(exc).__name__}: {exc}"}
