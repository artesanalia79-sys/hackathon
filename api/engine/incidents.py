"""Incident records and their fingerprints.

`fingerprint_key` is what stops the same story from being opened twice: one open
incident per (scope, cause). The detector is the only writer.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from api.domain import Incident


def fingerprint(scope: dict[str, str], cause_type: str | None, kind: str = "conversion_drop") -> str:
    """One open incident per (scope, cause, kind).

    `kind` belongs in the key: a conversion drop and a data-integrity finding on the
    same provider are two different stories with two different fixes, and without it
    the second one lands on the first one's record and overwrites it.
    """
    payload = ("|".join(f"{k}={v}" for k, v in sorted(scope.items()))
               + f"#{cause_type or '?'}#{kind}")
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


@dataclass
class IncidentRecord:
    id: str
    fingerprint_key: str
    status: str                      # watching | confirmed | resolved | expired
    kind: str                        # conversion_drop | data_integrity | latency_spike | no_traffic
    scope: dict[str, str]
    cause_type: str | None
    started_at: datetime
    last_seen_at: datetime
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None
    expected_rate: float = 0.0
    observed_rate: float = 0.0
    excess_declines: float = 0.0
    cost_usd: float = 0.0
    cost_per_min_usd: float = 0.0
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    signature_before: dict[str, float] = field(default_factory=dict)
    signature_during: dict[str, float] = field(default_factory=dict)
    signature_json: dict = field(default_factory=dict)
    attribution_json: list = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    related_change_event_ids: list[str] = field(default_factory=list)
    acknowledged_by: str | None = None
    healthy_streak: int = 0
    last_streak_check: datetime | None = None
    # Money accrues on the clock, not on the detector re-firing. See Detector._accrue_cost.
    last_cost_at: datetime | None = None
    # The recent-history half of p0, measured before this incident started. Held still
    # while the incident is open so the expectation cannot drift down onto the failure.
    baseline_ewma: float | None = None
    last_attributed_at: datetime | None = None
    diagnosis: dict | None = None
    # Once an incident is over and its 30-minute tail has been recorded, its chart is
    # history: frozen here so it stops moving and cannot scroll out of the live buffer.
    frozen_series: list | None = None
    diagnosis_pending: bool = False
    # When the diagnosis agent's Slack alert for this incident actually landed.
    alerted_at: datetime | None = None
    alerted_by: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def duration_min(self) -> float:
        end = self.resolved_at or self.last_seen_at
        return max(0.0, (end - self.started_at).total_seconds() / 60.0)

    def to_model(self) -> Incident:
        return Incident(
            id=self.id, fingerprint_key=self.fingerprint_key, status=self.status,  # type: ignore[arg-type]
            scope=self.scope, cause_type=self.cause_type, kind=self.kind,  # type: ignore[arg-type]
            started_at=self.started_at, confirmed_at=self.confirmed_at,
            resolved_at=self.resolved_at, expected_rate=self.expected_rate,
            observed_rate=self.observed_rate, excess_declines=self.excess_declines,
            cost_usd=self.cost_usd, cost_per_min_usd=self.cost_per_min_usd,
            signature_before=self.signature_before, signature_during=self.signature_during,
            related_change_event_ids=self.related_change_event_ids,
            acknowledged_by=self.acknowledged_by,
            detail={
                "signature": self.signature_json,
                "attribution": self.attribution_json,
                "reasons": self.reasons,
                "confidence": round(self.confidence, 2),
                "cost_breakdown": self.cost_breakdown,
                "duration_min": round(self.duration_min, 1),
                "has_diagnosis": self.diagnosis is not None,
                "diagnosis_pending": self.diagnosis_pending,
                **self.detail,
            },
        )

    def to_json(self) -> dict:
        return self.to_model().model_dump(mode="json")


def new_id() -> str:
    return f"inc_{uuid.uuid4().hex[:10]}"
