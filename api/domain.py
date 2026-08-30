"""Data contracts. These mirror docs/ARCHITECTURE.md — keep them in sync."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Country = Literal["CO", "BR", "MX"]
Status = Literal["approved", "declined", "error"]
DeclineCategory = Literal[
    "hard_decline", "soft_decline", "risk_block", "technical",
    "config", "auth_required", "unknown", "none",
]
CATEGORIES: tuple[str, ...] = (
    "none", "hard_decline", "soft_decline", "risk_block",
    "technical", "config", "auth_required", "unknown",
)
# Categories excluded from the *operational* conversion rate: the shopper simply
# cannot pay, and no action of ours changes that.
HARD_CATEGORIES: frozenset[str] = frozenset({"hard_decline"})

DIMENSIONS: tuple[str, ...] = ("merchant", "country", "method", "brand", "issuer", "provider")


class Transaction(BaseModel):
    id: str
    ts: datetime
    merchant_id: str
    country: Country
    currency: str
    amount: float
    method: str
    provider: str
    brand: str | None = None
    issuer: str | None = None
    bin: str | None = None
    status: Status
    raw_code: str
    raw_message: str
    raw_status: str
    normalized_code: str
    # The anchor and the action: every card acquirer speaks ISO 8583, and `retriable`
    # is what turns a decline into a decision. Empty ISO means the canonical code has
    # no card-network equivalent (an alternative rail, or a Yuno-only code).
    iso_8583: str = ""
    retriable: str = "unknown"
    decline_category: DeclineCategory
    latency_ms: int
    attempt_no: int = 1


class ChangeEvent(BaseModel):
    id: str
    ts: datetime
    type: Literal["deploy", "mapping_change", "routing_rule", "provider_config"]
    scope: dict[str, str] = Field(default_factory=dict)
    description: str


InjectionType = Literal[
    "provider_degraded", "issuer_over_declining", "method_down",
    "network_degraded", "mapping_bug", "routing_change", "latency_spike",
    "hard_decline_spike", "merchant_outage", "unknown_code",
]


class Injection(BaseModel):
    type: InjectionType
    scope: dict[str, str] = Field(default_factory=dict)  # any subset of dimensions; missing = any
    severity: float = 0.3        # rate drop in points, or % of mis-mapped codes for mapping_bug
    ramp_minutes: int = 0        # 0 = abrupt
    start_in_minutes: int = 0
    duration_minutes: int | None = None  # None = until reset
    note: str = ""


class ActiveInjection(BaseModel):
    id: str
    injection: Injection
    created_at: datetime
    starts_at: datetime
    ends_at: datetime | None = None


class SegmentStat(BaseModel):
    scope: dict[str, str]
    attempts: int
    operational_attempts: int
    approved: int
    observed_rate: float | None
    expected_rate: float | None
    excess_declines: float
    by_category: dict[str, int] = Field(default_factory=dict)


class Incident(BaseModel):
    id: str
    fingerprint_key: str
    status: Literal["watching", "confirmed", "resolved", "expired"]
    scope: dict[str, str]
    cause_type: str | None = None
    kind: Literal["conversion_drop", "latency_spike", "no_traffic"] = "conversion_drop"
    started_at: datetime
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None
    expected_rate: float
    observed_rate: float
    excess_declines: float
    cost_usd: float
    cost_per_min_usd: float
    signature_before: dict[str, float] = Field(default_factory=dict)
    signature_during: dict[str, float] = Field(default_factory=dict)
    related_change_event_ids: list[str] = Field(default_factory=list)
    acknowledged_by: str | None = None
    detail: dict = Field(default_factory=dict)


class RootCause(BaseModel):
    type: str
    scope: dict[str, str]


class Evidence(BaseModel):
    tool_call_id: str
    claim: str


class Affected(BaseModel):
    merchants: list[str] = Field(default_factory=list)
    excess_declines: float
    cost_per_min_usd: float


class SignatureDiff(BaseModel):
    before: dict[str, float] = Field(default_factory=dict)
    during: dict[str, float] = Field(default_factory=dict)
    risen: list[str] = Field(default_factory=list)


class SimilarIncident(BaseModel):
    incident_id: str
    started_at: datetime
    duration_min: float
    cause_type: str | None
    cost_usd: float
    similarity: float


class Recommendation(BaseModel):
    action: str
    rationale: str = ""
    not_executed: Literal[True] = True


class Diagnosis(BaseModel):
    incident_id: str
    root_cause: RootCause
    since: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[Evidence] = Field(default_factory=list)
    affected: Affected
    signature: SignatureDiff
    related_change_events: list[ChangeEvent] = Field(default_factory=list)
    similar_past: list[SimilarIncident] = Field(default_factory=list)
    recommendation: Recommendation
    ops_explanation: str
    exec_line: str
    source: Literal["agent", "deterministic_fallback"] = "deterministic_fallback"
    fallback_reason: str | None = None
