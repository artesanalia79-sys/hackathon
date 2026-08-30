"""Injections: the judges' input surface.

Rules from the spec: no magic IDs, any subset of dimensions is a valid scope,
missing dimension = "any". An injection never names an incident — it perturbs the
world, and the engine has to find it on its own.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from api.domain import ActiveInjection, ChangeEvent, Injection

# Which decline category each failure mode pushes traffic into. This is the
# ground truth the signature classifier has to recover without being told.
EFFECT_CATEGORY = {
    "provider_degraded": "technical",
    "issuer_over_declining": "soft_decline",
    "method_down": "technical",
    "network_degraded": "technical",
    "routing_change": "config",
    "hard_decline_spike": "hard_decline",
    "unknown_code": "unknown",
}

# Injections that are, by nature, caused by something we did to ourselves.
INTERNAL_TYPES = {"mapping_bug", "routing_change"}

# How long an identical payload is treated as the same click.
DEDUP_WINDOW_S = 5.0

CHANGE_EVENT_FOR = {
    "mapping_bug": ("mapping_change", "Deployed normalization table v{v}: {n} provider codes remapped"),
    "routing_change": ("routing_rule", "Routing rule updated: traffic re-pointed for {scope}"),
}


@dataclass
class Effect:
    """What the injections do to one leaf in one minute, already combined."""
    approval_delta: float = 0.0                      # points removed from approval prob
    category_push: dict[str, float] = field(default_factory=dict)  # extra weight per decline category
    volume_factor: float = 1.0
    latency_factor: float = 1.0
    mismap_fraction: float = 0.0                     # declines silently recorded as approved
    novel_code_fraction: float = 0.0                 # declines carrying an unseen raw code
    sources: list[str] = field(default_factory=list) # injection ids that touched this leaf


def _payload_hash(inj: Injection) -> str:
    blob = json.dumps(inj.model_dump(), sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


class Injector:
    """Holds active injections and answers "what is wrong with this leaf right now"."""

    def __init__(self) -> None:
        self._active: list[ActiveInjection] = []
        # payload hash -> (wall-clock monotonic seconds, injection id). Wall clock, not
        # simulated time: this window exists for a human double-clicking a button, and
        # the simulation runs 60x faster than they do.
        self._recent: dict[str, tuple[float, str]] = {}
        self._change_events: list[ChangeEvent] = []
        self._mapping_version = 1

    # --- lifecycle ---------------------------------------------------------
    def add(self, inj: Injection, now: datetime) -> tuple[ActiveInjection, bool]:
        """Register an injection. Idempotent: an identical payload within 5 s reuses the id."""
        key = _payload_hash(inj)
        wall = time.monotonic()
        prior = self._recent.get(key)
        if prior and (wall - prior[0]) <= DEDUP_WINDOW_S:
            existing = next((a for a in self._active if a.id == prior[1]), None)
            if existing is not None:
                return existing, True

        starts = now + timedelta(minutes=inj.start_in_minutes)
        ends = starts + timedelta(minutes=inj.duration_minutes) if inj.duration_minutes else None
        active = ActiveInjection(id=f"inj_{uuid.uuid4().hex[:10]}", injection=inj,
                                 created_at=now, starts_at=starts, ends_at=ends)
        self._active.append(active)
        self._recent[key] = (wall, active.id)

        if inj.type in CHANGE_EVENT_FOR:
            kind, template = CHANGE_EVENT_FOR[inj.type]
            self._mapping_version += 1
            scope_txt = ", ".join(f"{k}={v}" for k, v in inj.scope.items()) or "all traffic"
            self._change_events.append(ChangeEvent(
                id=f"chg_{uuid.uuid4().hex[:8]}",
                ts=starts,
                type=kind,  # type: ignore[arg-type]
                scope=dict(inj.scope),
                description=template.format(v=self._mapping_version,
                                            n=max(1, int(inj.severity * 40)),
                                            scope=scope_txt),
            ))
        return active, False

    def reset(self) -> None:
        self._active.clear()
        self._recent.clear()
        self._change_events.clear()
        self._mapping_version = 1

    def active(self, now: datetime) -> list[ActiveInjection]:
        return [a for a in self._active if a.starts_at <= now and (a.ends_at is None or now < a.ends_at)]

    def all(self) -> list[ActiveInjection]:
        return list(self._active)

    def change_events(self) -> list[ChangeEvent]:
        return list(self._change_events)

    def add_change_event(self, ev: ChangeEvent) -> None:
        self._change_events.append(ev)

    # --- evaluation --------------------------------------------------------
    @staticmethod
    def _matches(scope: dict[str, str], leaf: dict[str, str]) -> bool:
        """A missing dimension means 'any'. An empty leaf value never matches a demand."""
        for dim, want in scope.items():
            if dim not in leaf:
                return False
            if leaf[dim] != want:
                return False
        return True

    @staticmethod
    def _ramp(active: ActiveInjection, now: datetime) -> float:
        ramp = active.injection.ramp_minutes
        if ramp <= 0:
            return 1.0
        elapsed = (now - active.starts_at).total_seconds() / 60.0
        return max(0.0, min(1.0, elapsed / ramp))

    def effect_for(self, leaf: dict[str, str], now: datetime) -> Effect:
        eff = Effect()
        for act in self.active(now):
            inj = act.injection
            if not self._matches(inj.scope, leaf):
                continue
            k = self._ramp(act, now)
            if k <= 0:
                continue
            sev = inj.severity * k
            eff.sources.append(act.id)

            if inj.type == "latency_spike":
                eff.latency_factor *= 1.0 + 4.0 * sev
            elif inj.type == "merchant_outage":
                eff.volume_factor *= max(0.0, 1.0 - min(1.0, sev if sev > 0 else 1.0))
            elif inj.type == "mapping_bug":
                eff.mismap_fraction = min(0.95, eff.mismap_fraction + sev)
            elif inj.type == "unknown_code":
                eff.novel_code_fraction = min(0.95, eff.novel_code_fraction + sev)
                eff.approval_delta += sev * 0.25
                eff.category_push["unknown"] = eff.category_push.get("unknown", 0.0) + sev
            else:
                category = EFFECT_CATEGORY.get(inj.type, "soft_decline")
                eff.approval_delta += sev
                eff.category_push[category] = eff.category_push.get(category, 0.0) + sev
        return eff

    def ground_truth(self, now: datetime) -> list[dict]:
        """What is actually broken right now. Used by `make eval`, never by the engine."""
        out = []
        for act in self.active(now):
            out.append({"injection_id": act.id, "type": act.injection.type,
                        "scope": act.injection.scope, "severity": act.injection.severity,
                        "starts_at": act.starts_at.isoformat()})
        return out
