"""Detector and incident lifecycle. The only writer of incidents.

Runs once per simulated minute. Four independent questions, because they are four
different failures that a single "conversion is down" alert would blur together:
  - is the operational conversion rate below its own seasonal band?   (conversion_drop)
  - are we recording outcomes the provider never returned?            (data_integrity)
  - did the traffic itself stop?                                      (no_traffic)
  - are we slow without declining more?                               (latency_spike)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from api.config import (
    CHART_PAD_MIN,
    DELTA,
    N_MIN,
    NO_TRAFFIC_DROP,
    RESOLVE_WINDOWS,
    SCORE_FIRE,
    WATCHING_TTL_MIN,
    WINDOW_CONFIRM_MIN,
    WINDOW_SENSITIVE_MIN,
)
from api.domain import ChangeEvent
from api.engine.adtributor import Adtributor
from api.engine.cost import cost_per_minute
from api.engine.cube import Cube
from api.engine.expectation import Expector
from api.engine.incidents import IncidentRecord, fingerprint, new_id
from api.engine.signature import build_signature, classify, related_change_events
from api.engine.stats import prob_rate_below

FIRST_LEVEL = ("provider", "country", "method", "brand", "issuer")
LATENCY_SPIKE_FACTOR = 2.0
# A firing slice needs this much excess *outside* what we already explain to count
# as its own incident rather than a side effect of one.
UNEXPLAINED_SHARE = 0.5
MISMATCH_FIRE = 0.02


class Detector:
    def __init__(self, cube: Cube) -> None:
        self.cube = cube
        self.incidents: dict[str, IncidentRecord] = {}     # id -> record
        self.open_by_key: dict[str, str] = {}              # fingerprint -> incident id
        self.change_events: list[ChangeEvent] = []
        self.events_log: list[dict] = []

    # --- helpers -----------------------------------------------------------
    def open_incidents(self) -> list[IncidentRecord]:
        return [r for r in self.incidents.values() if r.status in ("watching", "confirmed")]

    def resolved_incidents(self) -> list[IncidentRecord]:
        return [r for r in self.incidents.values() if r.status == "resolved"]

    def reset(self) -> None:
        self.incidents.clear()
        self.open_by_key.clear()
        self.change_events.clear()
        self.events_log.clear()

    def _log(self, now: datetime, event: str, **fields) -> None:
        self.events_log.append({"ts": now.isoformat(), "event": event, **fields})
        if len(self.events_log) > 500:
            del self.events_log[:200]

    @staticmethod
    def _score(ex: Expector, scope: dict[str, str], end: datetime, minutes: int):
        exp = ex.expect(scope, end, minutes)
        n = exp.observed.operational_attempts
        if n <= 0:
            return 0.0, exp
        return prob_rate_below(exp.observed.approved, n, max(0.0, exp.p0 - DELTA)), exp

    # --- main tick ---------------------------------------------------------
    def tick(self, now: datetime) -> None:
        ex = Expector(self.cube)
        fired = self._scan_conversion(ex, now)
        if fired:
            self._attribute_and_upsert(ex, now, fired)
        self._scan_integrity(ex, now)
        self._scan_no_traffic(ex, now)
        self._scan_latency(ex, now)
        self._lifecycle(ex, now)

    # --- scans -------------------------------------------------------------
    def _scan_conversion(self, ex: Expector, now: datetime) -> list[dict[str, str]]:
        """Global plus every first-level slice, on the sensitive window."""
        roots: list[dict[str, str]] = []
        score, exp = self._score(ex, {}, now, WINDOW_SENSITIVE_MIN)
        if score > SCORE_FIRE and exp.observed.operational_attempts >= N_MIN:
            self._log(now, "fire", scope={}, score=round(score, 4),
                      observed=round(exp.observed.rate or 0, 4), expected=round(exp.p0, 4))
            return [{}]

        for dim in FIRST_LEVEL:
            for value in self.cube.values_of(dim, {}):
                scope = {dim: value}
                s, e = self._score(ex, scope, now, WINDOW_SENSITIVE_MIN)
                if s > SCORE_FIRE and e.observed.operational_attempts >= N_MIN:
                    roots.append(scope)
                    self._log(now, "fire", scope=scope, score=round(s, 4),
                              observed=round(e.observed.rate or 0, 4), expected=round(e.p0, 4))
        roots.sort(key=lambda sc: -ex.expect(sc, now, WINDOW_SENSITIVE_MIN).excess_declines)
        return roots[:6]

    def _scan_integrity(self, ex: Expector, now: datetime) -> None:
        """We wrote a status the provider never sent. Not a rate drop — a lie in the data."""
        for provider in self.cube.values_of("provider", {}):
            scope = {"provider": provider}
            agg = ex.observed(scope, now, WINDOW_SENSITIVE_MIN)
            if agg.attempts < N_MIN:
                continue
            rate = agg.raw_status_mismatch / agg.attempts
            if rate < MISMATCH_FIRE:
                continue
            seasonal = ex.seasonal(scope, now, WINDOW_SENSITIVE_MIN)
            # Raw codes only come off the leaf path, and the signature needs them.
            sig = build_signature(ex.observed(scope, now, WINDOW_SENSITIVE_MIN, full=True), seasonal)
            nearby = related_change_events(self.change_events, scope, now)
            reasons = [(f"{rate:.1%} of {provider} decisions were stored with a status the "
                       f"provider did not return ({agg.raw_status_mismatch} of {agg.attempts} attempts)")]
            if nearby:
                reasons.append(f"{nearby[0].type} at {nearby[0].ts:%H:%M}: {nearby[0].description}")
            # These are approvals we booked but never got: value at full risk.
            cost_min = (agg.raw_status_mismatch / WINDOW_SENSITIVE_MIN) * agg.avg_ticket
            self._upsert(now, scope=scope, cause_type="mapping_bug", kind="data_integrity",
                         expected_rate=seasonal.rate or 0.0, observed_rate=agg.rate or 0.0,
                         excess=float(agg.raw_status_mismatch), cost_min=cost_min,
                         cost_breakdown={"mis-stated approvals": round(cost_min, 2)},
                         sig=sig, reasons=reasons, confidence=0.95 if nearby else 0.85,
                         attribution=[{"scope": scope, "stop_reason": "integrity_check",
                                       "explanatory_power": 1.0, "path": [],
                                       "excess_declines": agg.raw_status_mismatch}],
                         change_ids=[e.id for e in nearby],
                         detail={"mismatch_rate": round(rate, 4),
                                 "mismatched_attempts": agg.raw_status_mismatch})

    def _scan_no_traffic(self, ex: Expector, now: datetime) -> None:
        """Attempts stopped arriving. Conversion is undefined here, not bad."""
        for merchant in self.cube.values_of("merchant", {}):
            scope = {"merchant": merchant}
            obs = ex.observed(scope, now, WINDOW_SENSITIVE_MIN)
            sea = ex.seasonal(scope, now, WINDOW_SENSITIVE_MIN)
            if sea.attempts < N_MIN:
                continue
            drop = 1.0 - (obs.attempts / sea.attempts if sea.attempts else 1.0)
            if drop < NO_TRAFFIC_DROP:
                continue
            sig = build_signature(obs, sea)
            lost_per_min = (sea.attempts - obs.attempts) / WINDOW_SENSITIVE_MIN
            ticket = sea.avg_ticket
            self._upsert(now, scope=scope, cause_type="no_traffic", kind="no_traffic",
                         expected_rate=sea.rate or 0.0, observed_rate=obs.rate or 0.0,
                         excess=float(sea.attempts - obs.attempts),
                         cost_min=lost_per_min * ticket * 0.5,
                         cost_breakdown={"lost attempts": round(lost_per_min * ticket * 0.5, 2)},
                         sig=sig,
                         reasons=[(f"attempts for {merchant} are {drop:.0%} below the seasonal "
                                  f"expectation ({obs.attempts} vs {sea.attempts:.0f} in "
                                  f"{WINDOW_SENSITIVE_MIN} min); declines look normal")],
                         confidence=0.8,
                         attribution=[{"scope": scope, "stop_reason": "volume_check",
                                       "explanatory_power": 1.0, "path": [],
                                       "excess_declines": 0}],
                         change_ids=[], detail={"volume_drop": round(drop, 3)})

    def _scan_latency(self, ex: Expector, now: datetime) -> None:
        """Slow but not declining: the loss is abandonment, so confidence stays low."""
        for provider in self.cube.values_of("provider", {}):
            scope = {"provider": provider}
            obs = ex.observed(scope, now, WINDOW_SENSITIVE_MIN)
            sea = ex.seasonal(scope, now, WINDOW_SENSITIVE_MIN)
            if obs.attempts < N_MIN or sea.attempts <= 0:
                continue
            base_lat, now_lat = sea.avg_latency, obs.avg_latency
            if base_lat <= 0 or now_lat < base_lat * LATENCY_SPIKE_FACTOR:
                continue
            score, exp = self._score(ex, scope, now, WINDOW_SENSITIVE_MIN)
            if score > SCORE_FIRE:
                continue  # it is declining too; the conversion path owns this story
            sig = build_signature(obs, sea)
            # Abandonment is a guess, and we say so: ~8% of shoppers per extra second.
            extra_s = (now_lat - base_lat) / 1000.0
            abandon = min(0.25, 0.08 * extra_s)
            cost_min = abandon * (obs.attempts / WINDOW_SENSITIVE_MIN) * obs.avg_ticket
            self._upsert(now, scope=scope, cause_type="latency_spike", kind="latency_spike",
                         expected_rate=exp.p0, observed_rate=obs.rate or 0.0,
                         excess=0.0, cost_min=cost_min,
                         cost_breakdown={"estimated abandonment": round(cost_min, 2)},
                         sig=sig,
                         reasons=[(f"{provider} p95 latency {now_lat:.0f}ms vs {base_lat:.0f}ms "
                                  f"expected, with no rise in declines"),
                                  (f"cost is an estimate: ~{abandon:.0%} abandonment at "
                                  f"+{extra_s:.1f}s, not measured")],
                         confidence=0.45,
                         attribution=[{"scope": scope, "stop_reason": "latency_check",
                                       "explanatory_power": 1.0, "path": [],
                                       "excess_declines": 0}],
                         change_ids=[], detail={"latency_ms": round(now_lat),
                                                "latency_baseline_ms": round(base_lat)})

    # --- attribution -------------------------------------------------------
    def _attribute_and_upsert(self, ex: Expector, now: datetime, roots: list[dict[str, str]]) -> None:
        """Attribute from the global scope first.

        Starting from every firing slice produced the same outage under a dozen
        different scopes ({country,provider} and {method,provider} and ...). One tree
        from the top yields one answer; the firing slices are only a fallback for a
        drop too small to show up in the global excess.
        """
        def useful(ns):
            return [n for n in ns if n.stop_reason not in ("no_signal", "no_excess")]

        adt = Adtributor(ex, now, WINDOW_SENSITIVE_MIN)
        nodes = useful(adt.run({}))

        # A second, smaller story does not survive the global tree: next to a $10k/min
        # outage its explanatory power never clears the branching threshold. So any slice
        # that fired on its own gets its own tree — but only if its excess is genuinely
        # its own. An issuer that routes through a broken provider is *below expectation*
        # too; it is not a second incident, it is the same one seen from another angle.
        for root in roots:
            if not root:
                continue
            if self._residual_share(ex, root, [n.scope for n in nodes], now) < UNEXPLAINED_SHARE:
                self._log(now, "slice_already_explained", scope=root)
                continue
            nodes.extend(useful(Adtributor(ex, now, WINDOW_SENSITIVE_MIN).run(root)))

        seen_scopes: set[tuple] = set()
        if True:
            for node in nodes:
                key = tuple(sorted(node.scope.items()))
                if key in seen_scopes:
                    continue
                seen_scopes.add(key)

                obs = ex.observed(node.scope, now, WINDOW_SENSITIVE_MIN)
                sea = ex.seasonal(node.scope, now, WINDOW_SENSITIVE_MIN)
                exp = ex.expect(node.scope, now, WINDOW_SENSITIVE_MIN)
                if obs.operational_attempts < N_MIN:
                    continue

                sig = build_signature(ex.observed(node.scope, now, WINDOW_SENSITIVE_MIN, full=True), sea)
                started = self._estimate_onset(ex, node.scope, now)
                cause, confidence, reasons = classify(node.scope, sig, ex, now,
                                                      WINDOW_SENSITIVE_MIN,
                                                      self.change_events, started)
                if node.stop_reason == "below_min_sample":
                    cause, confidence = "insufficient_evidence", min(confidence, 0.35)
                    reasons.append("cannot isolate further: sample below the minimum")

                cost_min, breakdown = cost_per_minute(obs, sea, node.excess_declines,
                                                      WINDOW_SENSITIVE_MIN)
                nearby = related_change_events(self.change_events, node.scope, started)
                reasons.insert(0, f"conversion {exp.observed_rate:.1%} vs {exp.p0:.1%} expected "
                                  f"on {obs.operational_attempts} operational attempts "
                                  f"in the last {WINDOW_SENSITIVE_MIN} min")
                self._upsert(now, scope=node.scope, cause_type=cause, kind="conversion_drop",
                             expected_rate=exp.p0, observed_rate=exp.observed_rate or 0.0,
                             excess=node.excess_declines, cost_min=cost_min,
                             cost_breakdown=breakdown, sig=sig, reasons=reasons,
                             confidence=confidence, attribution=[node.to_json()],
                             change_ids=[e.id for e in nearby], started_at=started,
                             detail={"explanatory_power": round(node.explanatory_power, 3)})

    def _residual_share(self, ex: Expector, scope: dict[str, str],
                        explained: list[dict[str, str]], now: datetime) -> float:
        """How much of this scope's excess is NOT already inside a scope we have explained."""
        mine = ex.expect(scope, now, WINDOW_SENSITIVE_MIN).excess_declines
        if mine <= 0:
            return 0.0
        overlap = 0.0
        for other in explained:
            if not other:
                return 0.0  # the global scope explains everything by definition
            combined = {**scope, **other}
            if any(scope.get(k) not in (None, v) for k, v in other.items()):
                continue  # contradictory scopes cannot overlap
            overlap = max(overlap, ex.expect(combined, now, WINDOW_SENSITIVE_MIN).excess_declines)
        return max(0.0, (mine - overlap) / mine)

    def _estimate_onset(self, ex: Expector, scope: dict[str, str], now: datetime) -> datetime:
        """Walk backwards until the segment was last inside its band.

        With a ramp this lands on the start of the ramp, which is what "since" should say.
        """
        exp_now = ex.expect(scope, now, WINDOW_SENSITIVE_MIN)
        band = exp_now.p0 - DELTA / 2
        onset = now
        for back in range(1, 90):
            t = now - timedelta(minutes=back)
            agg = self.cube.aggregate(scope, t, 3)
            if agg.operational_attempts < 10:
                continue
            if agg.rate is not None and agg.rate >= band:
                return onset
            onset = t
        return onset

    # --- write path --------------------------------------------------------
    def _upsert(self, now: datetime, *, scope: dict[str, str], cause_type: str, kind: str,
                expected_rate: float, observed_rate: float, excess: float, cost_min: float,
                cost_breakdown: dict, sig, reasons: list[str], confidence: float,
                attribution: list, change_ids: list[str],
                started_at: datetime | None = None, detail: dict | None = None) -> None:
        key = fingerprint(scope, cause_type)
        existing_id = self.open_by_key.get(key)

        # Attribution can land a notch deeper or shallower from one minute to the next as
        # noise moves, and each depth is a different fingerprint. Left alone that opens the
        # same story as half a dozen incidents which are then immediately superseded — all
        # bookkeeping, all visible. If an open incident with the same cause already covers
        # this scope, this is that incident, told with one more adjective.
        if existing_id is None:
            for other in self.open_incidents():
                if (other.cause_type == cause_type and other.kind == kind
                        and len(other.scope) < len(scope)
                        and all(scope.get(k) == v for k, v in other.scope.items())):
                    existing_id = other.id
                    key = other.fingerprint_key
                    break

        if existing_id and existing_id in self.incidents:
            rec = self.incidents[existing_id]
            elapsed = max(1.0, (now - rec.last_seen_at).total_seconds() / 60.0)
            rec.last_seen_at = now
            rec.expected_rate = expected_rate
            rec.observed_rate = observed_rate
            rec.excess_declines = excess
            rec.cost_per_min_usd = cost_min
            rec.cost_usd += cost_min * elapsed
            rec.cost_breakdown = cost_breakdown
            rec.signature_before = sig.before
            rec.signature_during = sig.during
            rec.signature_json = sig.to_json()
            rec.attribution_json = attribution
            rec.reasons = reasons
            rec.confidence = confidence
            rec.healthy_streak = 0
            if change_ids:
                rec.related_change_event_ids = sorted(set(rec.related_change_event_ids) | set(change_ids))
            if detail:
                rec.detail.update(detail)
            return

        rec = IncidentRecord(
            id=new_id(), fingerprint_key=key, status="watching", kind=kind, scope=dict(scope),
            cause_type=cause_type, started_at=started_at or now, last_seen_at=now,
            expected_rate=expected_rate, observed_rate=observed_rate, excess_declines=excess,
            cost_usd=0.0, cost_per_min_usd=cost_min, cost_breakdown=cost_breakdown,
            signature_before=sig.before, signature_during=sig.during, signature_json=sig.to_json(),
            attribution_json=attribution, reasons=reasons, confidence=confidence,
            related_change_event_ids=change_ids, detail=detail or {},
        )
        self.incidents[rec.id] = rec
        self.open_by_key[key] = rec.id
        self._log(now, "incident_opened", incident_id=rec.id, scope=scope,
                  cause=cause_type, incident_kind=kind)

    # --- lifecycle ---------------------------------------------------------
    def _dedupe_shadowed(self, ex: Expector, now: datetime) -> None:
        """Close incidents that are only a shadow of a bigger one.

        Two shapes of the same story: a narrower scope with the same cause (one extra
        adjective), and a *different* scope whose excess turns out to live almost
        entirely inside another incident's scope — an issuer that looks sick only
        because its traffic runs through a broken provider. Keeping either would
        double-count the money and bury the real incident in its own side effects.
        """
        openers = sorted([r for r in self.open_incidents() if r.kind == "conversion_drop"],
                         key=lambda r: -r.cost_per_min_usd)
        for i, narrow in enumerate(openers):
            if narrow.status != "confirmed" and narrow.status != "watching":
                continue
            for broad in openers[:i]:
                if broad.status not in ("watching", "confirmed") or narrow is broad:
                    continue
                nested = (narrow.cause_type == broad.cause_type
                          and len(narrow.scope) > len(broad.scope)
                          and all(narrow.scope.get(k) == v for k, v in broad.scope.items()))
                shadow = nested or self._residual_share(ex, narrow.scope, [broad.scope],
                                                        now) < UNEXPLAINED_SHARE
                if not shadow:
                    continue
                narrow.status = "expired"
                narrow.detail["superseded_by"] = broad.id
                self.open_by_key.pop(narrow.fingerprint_key, None)
                self._log(now, "incident_superseded", incident_id=narrow.id,
                          by=broad.id, scope=narrow.scope)
                break

    def chart_window(self, rec: IncidentRecord, now: datetime) -> tuple[datetime, datetime]:
        """The window an incident's chart should show.

        Open: from half an hour before it started up to now — it is still happening.
        Closed: the same start, out to half an hour past the end — a finished story with
        its recovery visible, and no reason to keep moving.
        """
        start = rec.started_at - timedelta(minutes=CHART_PAD_MIN)
        closed_at = rec.resolved_at or (rec.last_seen_at if rec.status == "expired" else None)
        if closed_at is None:
            return start, now
        return start, min(now, closed_at + timedelta(minutes=CHART_PAD_MIN))

    def _freeze_finished_charts(self, now: datetime) -> None:
        for rec in self.incidents.values():
            if rec.frozen_series is not None or rec.status in ("watching", "confirmed"):
                continue
            closed_at = rec.resolved_at or rec.last_seen_at
            if now < closed_at + timedelta(minutes=CHART_PAD_MIN):
                continue  # the tail is still being recorded
            start, end = self.chart_window(rec, now)
            minutes = max(1, int((end - start).total_seconds() // 60) + 1)
            rec.frozen_series = self.cube.series(rec.scope, end, minutes)

    def _lifecycle(self, ex: Expector, now: datetime) -> None:
        self._dedupe_shadowed(ex, now)
        self._freeze_finished_charts(now)
        for rec in list(self.incidents.values()):
            if rec.status not in ("watching", "confirmed"):
                continue

            if rec.kind == "conversion_drop":
                score30, exp30 = self._score(ex, rec.scope, now, WINDOW_CONFIRM_MIN)
                confirms = (score30 > SCORE_FIRE
                            and exp30.observed.operational_attempts >= N_MIN)
                healthy = self._is_healthy(ex, rec, now)
            else:
                confirms = self._non_conversion_confirms(ex, rec, now)
                healthy = not confirms and (now - rec.last_seen_at) >= timedelta(minutes=2)

            if rec.status == "watching":
                if confirms:
                    rec.status = "confirmed"
                    rec.confirmed_at = now
                    rec.diagnosis_pending = True
                    self._log(now, "incident_confirmed", incident_id=rec.id, scope=rec.scope,
                              cause=rec.cause_type)
                elif (now - rec.started_at) > timedelta(minutes=WATCHING_TTL_MIN):
                    rec.status = "expired"
                    self.open_by_key.pop(rec.fingerprint_key, None)
                    self._log(now, "incident_expired", incident_id=rec.id, scope=rec.scope)
                continue

            # confirmed: only resolution can move it now
            if rec.last_streak_check is None:
                rec.last_streak_check = now
            if (now - rec.last_streak_check) >= timedelta(minutes=WINDOW_SENSITIVE_MIN):
                rec.last_streak_check = now
                rec.healthy_streak = rec.healthy_streak + 1 if healthy else 0
                if rec.healthy_streak >= RESOLVE_WINDOWS:
                    rec.status = "resolved"
                    rec.resolved_at = now
                    self.open_by_key.pop(rec.fingerprint_key, None)
                    self._log(now, "incident_resolved", incident_id=rec.id, scope=rec.scope,
                              cause=rec.cause_type, duration_min=round(rec.duration_min, 1),
                              cost_usd=round(rec.cost_usd, 2))

    def _is_healthy(self, ex: Expector, rec: IncidentRecord, now: datetime) -> bool:
        exp = ex.expect(rec.scope, now, WINDOW_SENSITIVE_MIN)
        if exp.observed.operational_attempts < max(10, N_MIN // 2):
            return False
        return exp.observed_rate is not None and exp.observed_rate >= exp.p0 - DELTA / 2

    def _non_conversion_confirms(self, ex: Expector, rec: IncidentRecord, now: datetime) -> bool:
        obs = ex.observed(rec.scope, now, WINDOW_CONFIRM_MIN)
        if rec.kind == "data_integrity":
            return obs.attempts >= N_MIN and (obs.raw_status_mismatch / max(1, obs.attempts)) >= MISMATCH_FIRE
        if rec.kind == "no_traffic":
            sea = ex.seasonal(rec.scope, now, WINDOW_CONFIRM_MIN)
            if sea.attempts <= 0:
                return False
            return (1.0 - obs.attempts / sea.attempts) >= NO_TRAFFIC_DROP
        if rec.kind == "latency_spike":
            sea = ex.seasonal(rec.scope, now, WINDOW_CONFIRM_MIN)
            return (obs.attempts >= N_MIN and sea.avg_latency > 0
                    and obs.avg_latency >= sea.avg_latency * LATENCY_SPIKE_FACTOR)
        return False
