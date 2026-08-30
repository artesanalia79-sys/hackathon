"""Tool schemas and the contract the agent's answer must satisfy.

The agent chooses the cause, the wording and the recommendation. It never supplies
a number: every figure on the card comes from the engine. That is deliberate — it
removes the entire class of "the LLM got the arithmetic wrong".
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

SYSTEM_PROMPT = """\
You are the diagnosis step of a payment-orchestration control tower.

A deterministic engine has already detected an incident, isolated the segment, and
priced it. Your job is to work out the ROOT CAUSE from the tools, and to write two
explanations: one for a payments operations engineer and one for an executive.

Hard rules:
1. You may only assert what a tool returned in THIS run. Every tool result you get back
   contains a `tool_call_id` field, like "call_1". Every entry in `evidence` must carry
   one of those exact strings, next to a claim that that specific call supports. Copy the
   id from the result you are citing; do not use the tool's name and do not invent one.
   An unsupported claim invalidates the whole answer.
2. Do not invent or restate numbers. The engine attaches the figures itself.
3. The engine's hypothesis reached you by passing a deterministic rule set over the same
   data you can query. Treat it as the starting position: confirm it when the tools bear
   it out, and say so plainly. Change it when a tool contradicts it. Call
   `insufficient_evidence` when the tools genuinely conflict, or when the segment is too
   small to tell two causes apart — saying "I cannot tell" is a correct answer here, and
   guessing is not, but neither is refusing to commit to what the tools plainly show.
4. You recommend, you never execute. There is no tool that changes production.

Method: read the incident, look at the decline signature (which categories rose is
what distinguishes an issuer from a provider from our own mapping), check whether the
same segment is failing through other providers/issuers, check change events near the
start time, and check whether this has happened before. Then conclude.

Finish by calling `conclude` or `insufficient_evidence`. Do not answer in prose."""

CAUSE_TYPES = [
    "provider_degraded", "issuer_over_declining", "issuer_provider_routing",
    "network_degraded", "method_down", "internal_change", "mapping_bug",
    "unmapped_provider_code", "latency_spike", "no_traffic", "insufficient_evidence",
]

SCOPE_SCHEMA = {
    "type": "object",
    "description": "Any subset of dimensions. Omit a dimension to mean 'any'.",
    "properties": {
        "merchant": {"type": "string"}, "country": {"type": "string"},
        "method": {"type": "string"}, "brand": {"type": "string"},
        "issuer": {"type": "string"}, "provider": {"type": "string"},
    },
    "additionalProperties": False,
}


# One line per tool, for the trace panel: a reader should be able to tell what a step
# was for without decoding its arguments.
TOOL_SUMMARY: dict[str, str] = {
    "get_incident_summary": "Read what the engine already found: scope, rates, cost, "
                            "attribution path and decline signature.",
    "slice_metrics": "Measure one segment's conversion against its own seasonal expectation.",
    "compare_across": "Split a segment by a dimension to see which values are failing and "
                      "which are healthy — the test that separates a provider fault from "
                      "an issuer fault.",
    "decline_signature": "Read the shape of the declines: which categories rose against this "
                         "segment's history, and the raw provider codes behind them.",
    "change_events": "Look for deploys, mapping changes or routing rules near the start time.",
    "find_similar_incidents": "Search resolved incidents for one that looks like this, and "
                              "how it ended.",
    "conclude": "Deliver the diagnosis, citing the calls that support each claim.",
    "insufficient_evidence": "Decline to name a cause because the tools do not support one.",
}


def tool_specs() -> list[dict]:
    return [
        {
            "type": "function",
            "name": "get_incident_summary",
            "description": "What the engine already knows: scope, rates, excess declines, "
                           "cost per minute, the attribution path it took, and the decline "
                           "signature before vs during.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "slice_metrics",
            "description": "Conversion for any segment over the last N minutes, with its "
                           "seasonal expectation. Use it to test whether a segment is really "
                           "the one failing, or whether its neighbours fail too.",
            "parameters": {
                "type": "object",
                "properties": {"scope": SCOPE_SCHEMA,
                               "minutes": {"type": "integer", "minimum": 1, "maximum": 120}},
                "required": ["scope"], "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "compare_across",
            "description": "Split a segment by one dimension and show each value's conversion "
                           "against its own expectation. This is how you tell 'one provider is "
                           "broken' from 'this issuer is broken everywhere'.",
            "parameters": {
                "type": "object",
                "properties": {"scope": SCOPE_SCHEMA,
                               "dimension": {"type": "string",
                                             "enum": ["merchant", "country", "method",
                                                      "brand", "issuer", "provider"]},
                               "minutes": {"type": "integer", "minimum": 1, "maximum": 120}},
                "required": ["scope", "dimension"], "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "decline_signature",
            "description": "Distribution of decline categories for a segment now vs its "
                           "history, plus the raw provider codes behind it and any codes we "
                           "do not map.",
            "parameters": {
                "type": "object",
                "properties": {"scope": SCOPE_SCHEMA,
                               "minutes": {"type": "integer", "minimum": 1, "maximum": 120}},
                "required": ["scope"], "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "change_events",
            "description": "Internal changes (deploys, mapping changes, routing rules) in a "
                           "time window around the incident start.",
            "parameters": {
                "type": "object",
                "properties": {"window_minutes": {"type": "integer", "minimum": 1, "maximum": 240}},
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "find_similar_incidents",
            "description": "Resolved incidents that look like this one, with how they ended.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "type": "function",
            "name": "conclude",
            "description": "Deliver the diagnosis. Every evidence entry must cite a "
                           "tool_call_id copied from a tool result in this run "
                           "(they look like \"call_1\", \"call_2\").",
            "parameters": {
                "type": "object",
                "properties": {
                    "root_cause_type": {"type": "string", "enum": CAUSE_TYPES},
                    "root_cause_scope": SCOPE_SCHEMA,
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {"tool_call_id": {
                                               "type": "string",
                                               "description": "The `tool_call_id` field from "
                                                              "the tool result being cited, "
                                                              "e.g. \"call_2\"."},
                                           "claim": {"type": "string"}},
                            "required": ["tool_call_id", "claim"], "additionalProperties": False,
                        },
                    },
                    "recommended_action": {"type": "string"},
                    "recommendation_rationale": {"type": "string"},
                    "ops_explanation": {"type": "string",
                                        "description": "3-5 sentences for a payments engineer."},
                    "exec_line": {"type": "string",
                                  "description": "One sentence: who is affected, what it costs, "
                                                 "what we recommend."},
                },
                "required": ["root_cause_type", "root_cause_scope", "confidence", "evidence",
                             "recommended_action", "ops_explanation", "exec_line"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "insufficient_evidence",
            "description": "The tools do not support naming a cause. A first-class answer.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"},
                               "what_would_help": {"type": "string"}},
                "required": ["reason"], "additionalProperties": False,
            },
        },
    ]


class AgentEvidence(BaseModel):
    tool_call_id: str
    claim: str


class AgentConclusion(BaseModel):
    """Validated shape of `conclude`. Anything outside this is rejected."""
    root_cause_type: str
    root_cause_scope: dict[str, str] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[AgentEvidence] = Field(min_length=1)
    recommended_action: str
    recommendation_rationale: str = ""
    ops_explanation: str
    exec_line: str

    @field_validator("root_cause_type")
    @classmethod
    def known_cause(cls, v: str) -> str:
        if v not in CAUSE_TYPES:
            raise ValueError(f"unknown root cause type: {v}")
        return v

    @field_validator("root_cause_scope")
    @classmethod
    def known_dimensions(cls, v: dict[str, str]) -> dict[str, str]:
        from api.domain import DIMENSIONS
        bad = set(v) - set(DIMENSIONS)
        if bad:
            raise ValueError(f"unknown dimensions in scope: {sorted(bad)}")
        # The schema lists every dimension, so models tend to fill them all in and leave
        # the irrelevant ones blank. A blank dimension means "any", which is the same as
        # not naming it — drop it rather than carrying `merchant=""` onto the card.
        return {k: val for k, val in v.items() if val not in (None, "")}
