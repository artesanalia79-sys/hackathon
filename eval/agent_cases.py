"""Agent cases 19 and 20 — run against a stubbed Responses API.

These check the guarantees the design actually promises: a bad agent must never
reach the incident card. No API key, no network, no cost.
"""
from __future__ import annotations

import asyncio
import json
import time

from eval.cases import DEGRADED, FAIL, PASS, Result
from eval.harness import advance, build, inject


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload, self.status_code = payload, status
        self.text = json.dumps(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Replays a scripted sequence of Responses API payloads."""

    def __init__(self, script, delay: float = 0.0, **_kw) -> None:
        self.script, self.delay, self.i = script, delay, 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, _url, json=None, headers=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        step = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        if callable(step):
            step = step()
        return _FakeResponse(step)


def _call(name: str, args: dict, call_id: str) -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id,
            "arguments": json.dumps(args)}


def _out(*items) -> dict:
    return {"output": list(items)}


def _incident():
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"},
           severity=0.35)
    advance(run, 20)
    rec = next((r for r in run.open if r.scope.get("provider") == "dlocal"), None)
    return run, rec


def _run_with(script, delay: float = 0.0):
    """Run the agent loop against a scripted API, with a key pretended into place."""
    from api.agent import loop

    run, rec = _incident()
    real_client, real_key = loop.httpx.AsyncClient, loop.OPENAI_API_KEY
    loop.httpx.AsyncClient = lambda **kw: _FakeClient(script, delay=delay, **kw)
    loop.OPENAI_API_KEY = "sk-test-not-a-real-key"
    try:
        return asyncio.run(loop.run_agent(run.world.detector, rec, run.world.now)), run, rec
    finally:
        loop.httpx.AsyncClient, loop.OPENAI_API_KEY = real_client, real_key


VALID_CONCLUDE = {
    "root_cause_type": "provider_degraded",
    "root_cause_scope": {"provider": "dlocal", "country": "BR"},
    "confidence": 0.88,
    "evidence": [{"tool_call_id": "call_1", "claim": "dLocal in Brazil converts at 55% "
                                                     "against 89% expected"}],
    "recommended_action": "Reroute Brazilian traffic away from dLocal",
    "recommendation_rationale": "Adyen and Mercado Pago convert normally on the same issuers",
    "ops_explanation": "Technical declines on dLocal in Brazil, other providers healthy.",
    "exec_line": "Brazil is losing money through dLocal; reroute recommended.",
}


def case_19a_prose() -> Result:
    """The model answers in prose instead of calling a tool."""
    (diag, _run_obj), _run, _rec = _run_with([{"output": [
        {"type": "message", "content": [{"type": "output_text", "text": "It is probably dLocal."}]}]}])
    if diag.source != "deterministic_fallback":
        return FAIL, "prose answer was accepted"
    if not diag.fallback_reason:
        return DEGRADED, "fell back but did not say why"
    return PASS, f"fallback, labelled: {diag.fallback_reason[:80]}"


def case_19b_timeout() -> Result:
    """The model is too slow; the budget must win."""
    import api.config as cfg
    old = cfg.AGENT_TIMEOUT_S
    from api.agent import loop
    loop.AGENT_TIMEOUT_S = 0.4
    try:
        t0 = time.perf_counter()
        (diag, run_obj), _run, _rec = _run_with([_out(_call("get_incident_summary", {}, "call_1"))],
                                                delay=1.2)
        elapsed = time.perf_counter() - t0
    finally:
        loop.AGENT_TIMEOUT_S = old
        cfg.AGENT_TIMEOUT_S = old
    if diag.source != "deterministic_fallback":
        return FAIL, "a timed-out run produced an agent diagnosis"
    if not diag.ops_explanation:
        return FAIL, "fallback produced an empty diagnosis"
    return PASS, f"timed out in {elapsed:.1f}s, deterministic diagnosis shown ({run_obj.status})"


def case_19c_invalid_json() -> Result:
    """`conclude` with a payload that does not match the schema."""
    bad = dict(VALID_CONCLUDE, confidence=17.0)   # outside 0..1
    (diag, run_obj), _run, _rec = _run_with([
        _out(_call("get_incident_summary", {}, "call_1")),
        _out(_call("conclude", bad, "call_2")),
    ])
    if diag.source != "deterministic_fallback":
        return FAIL, "an out-of-range confidence was accepted"
    if run_obj.alert_decision is not None:
        return FAIL, "an invalid conclusion was treated as an alert decision"
    return PASS, f"rejected on schema ({run_obj.status}), deterministic diagnosis shown"


def case_20_unsupported_evidence() -> Result:
    """The agent cites a tool call it never made."""
    fabricated = dict(VALID_CONCLUDE,
                      evidence=[{"tool_call_id": "call_99",
                                 "claim": "the provider confirmed an outage on their status page"}])
    (diag, run_obj), _run, _rec = _run_with([
        _out(_call("get_incident_summary", {}, "call_1")),
        _out(_call("conclude", fabricated, "call_2")),
    ])
    if diag.source != "deterministic_fallback":
        return FAIL, "fabricated evidence reached the incident card"
    if run_obj.status != "rejected":
        return DEGRADED, f"fell back but status was {run_obj.status}"
    return PASS, "run rejected: cited call_99, which never happened"


def case_19d_happy_path() -> Result:
    """A well-behaved agent: its words are used, the engine's numbers are kept."""
    (diag, run_obj), _run, rec = _run_with([
        _out(_call("get_incident_summary", {}, "call_1")),
        _out(_call("compare_across", {"scope": {"country": "BR"}, "dimension": "provider"}, "call_2")),
        _out(_call("conclude", dict(VALID_CONCLUDE,
                                    evidence=[{"tool_call_id": "call_2",
                                               "claim": "only dLocal is below expectation in BR"}]),
                   "call_3")),
    ])
    if diag.source != "agent":
        return FAIL, f"a valid run was rejected: {diag.fallback_reason}"
    if abs(diag.affected.cost_per_min_usd - round(rec.cost_per_min_usd, 2)) > 0.01:
        return FAIL, "the agent's answer carried a number the engine did not compute"
    tools_used = [s["tool"] for s in run_obj.steps if s["kind"] == "tool_call"]
    return PASS, f"accepted after {tools_used}; money still comes from the engine"


def case_19e_uncertain_but_confident() -> Result:
    """`conclude(insufficient_evidence, confidence=0.95)` must not reach a card that way.

    The dedicated tool and this are the same answer through two doors; "I cannot tell,
    with 95% confidence" is not a reading anyone should be shown.
    """
    hedged = dict(VALID_CONCLUDE, root_cause_type="insufficient_evidence", confidence=0.95,
                  evidence=[{"tool_call_id": "call_1", "claim": "the segment is too small to split"}],
                  recommended_action="Reroute everything away from dLocal immediately")
    (diag, _run_obj), _run, _rec = _run_with([
        _out(_call("get_incident_summary", {}, "c1")),
        _out(_call("conclude", hedged, "c2")),
    ])
    if diag.confidence > 0.4:
        return FAIL, f"uncertainty reported at confidence {diag.confidence}"
    if "watching" not in diag.recommendation.action.lower():
        return FAIL, f"recommended an action anyway: {diag.recommendation.action}"
    return PASS, f"capped to {diag.confidence}, recommendation is to keep watching"


def case_19f_placeholder_scope() -> Result:
    """Models fill every dimension in the schema; "any"/"" must not reach the card."""
    noisy = dict(VALID_CONCLUDE,
                 root_cause_scope={"merchant": "any", "country": "BR", "method": "",
                                   "brand": "any", "issuer": "", "provider": "dlocal"},
                 evidence=[{"tool_call_id": "call_1", "claim": "dLocal in Brazil is below expectation"}])
    (diag, _run_obj), _run, _rec = _run_with([
        _out(_call("get_incident_summary", {}, "c1")),
        _out(_call("conclude", noisy, "c2")),
    ])
    scope = diag.root_cause.scope
    if scope != {"country": "BR", "provider": "dlocal"}:
        return FAIL, f"placeholder dimensions survived: {scope}"
    return PASS, f"scope cleaned to {scope}"


def case_29_agent_sends_slack() -> Result:
    """A confirmed incident is raised by the agent once, in its own words."""
    from api.notify import slack

    delivered: list[dict] = []
    real_url, real_send = slack.SLACK_WEBHOOK_URL, slack.send

    async def capture(payload: dict) -> bool:
        delivered.append(payload)
        return True

    # This is only a non-empty sentinel. `slack.send` is replaced by `capture` below,
    # so the test never performs a network request or uses a real webhook.
    slack.SLACK_WEBHOOK_URL = "https://example.invalid/slack-webhook"
    slack.send = capture
    try:
        (diag, run_obj), _run, rec = _run_with([
            _out(_call("get_incident_summary", {}, "call_1")),
            _out(_call("send_slack_alert", {
                "headline": "dLocal is degrading approvals in Brazil; reroute now",
                "urgency": "page",
            }, "call_2")),
            _out(_call("conclude", dict(VALID_CONCLUDE,
                                         evidence=[{"tool_call_id": "call_1",
                                                    "claim": "the incident is isolated to dLocal in Brazil"}]),
                       "call_3")),
        ])
    finally:
        slack.SLACK_WEBHOOK_URL, slack.send = real_url, real_send

    if diag.source != "agent":
        return FAIL, f"valid alerting run was rejected: {diag.fallback_reason}"
    if len(delivered) != 1:
        return FAIL, f"expected one direct Slack send, got {len(delivered)}"
    if rec.alerted_by != "agent" or run_obj.alert_decision != "sent":
        return FAIL, f"alert was not recorded as agent-raised: {rec.alerted_by}/{run_obj.alert_decision}"
    slack_steps = [s for s in run_obj.steps if s.get("tool") == "send_slack_alert"]
    if len(slack_steps) != 1 or slack_steps[0].get("alert_sent") is not True:
        return FAIL, "agent trace does not record Slack's successful delivery"
    if "Raised by the diagnosis agent" not in str(delivered[0].get("blocks")):
        return FAIL, "Slack payload does not identify the diagnosis agent"
    return PASS, "agent sent one Slack alert and the completed run recorded it"


AGENT_CASES = [
    ("19", "Agent answers in prose -> fallback", case_19a_prose),
    ("19b", "Agent times out -> fallback", case_19b_timeout),
    ("19c", "Agent returns invalid JSON -> fallback", case_19c_invalid_json),
    ("19d", "Well-behaved agent is accepted", case_19d_happy_path),
    ("19e", "Uncertainty reported with high confidence is capped", case_19e_uncertain_but_confident),
    ("19f", "Placeholder scope dimensions are stripped", case_19f_placeholder_scope),
    ("20", "Agent cites evidence it never gathered -> rejected", case_20_unsupported_evidence),
    ("29", "Agent raises one Slack alert for a confirmed incident", case_29_agent_sends_slack),
]
