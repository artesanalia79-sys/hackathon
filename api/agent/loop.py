"""The agent loop: OpenAI Responses API, tool calling, hard timeout, strict validation.

Three things make this safe to put in front of judges:
  - it runs only on confirmed incidents, so cost and latency are bounded;
  - every claim it makes must cite a tool_call_id from its own run;
  - if anything at all goes wrong, the deterministic diagnosis is shown instead,
    labelled, and nobody has to notice at demo time.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any

import httpx

from api.agent.schema import SYSTEM_PROMPT, TOOL_SUMMARY, AgentConclusion, tool_specs
from api.agent.tools import ToolBox
from api.config import (
    AGENT_CONFIDENCE_HEADROOM,
    AGENT_MAX_STEPS,
    AGENT_TIMEOUT_S,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from api.domain import (
    Affected,
    Diagnosis,
    Evidence,
    Recommendation,
    RootCause,
    SignatureDiff,
    SimilarIncident,
)
from api.engine.diagnose import affected_merchants, deterministic_diagnosis, scope_phrase
from api.engine.incidents import IncidentRecord
from api.engine.memory import find_similar_incidents
from api.engine.playbook import build as build_playbook

RESULT_PREVIEW_CHARS = 900


class AgentRun:
    """Everything that happened, so the trace panel can show it and the UI can audit it."""

    def __init__(self, incident_id: str) -> None:
        self.incident_id = incident_id
        self.steps: list[dict] = []
        # Legible handles we hand the model ("call_1", "call_2", ...) plus the opaque
        # ids the API generated. Both identify a call that really happened; the model
        # is asked to cite the handle, because asking it to echo a 29-character opaque
        # string back is a guardrail that fails honest answers.
        self.call_ids: set[str] = set()
        self.handles: dict[str, str] = {}
        self.status = "running"
        self.error: str | None = None
        # The completed agent's explicit Slack decision, kept in the trace so the UI can
        # distinguish an alert it sent from one it deliberately chose not to send.
        self.alert_decision: str | None = None
        self.started = time.monotonic()

    def record(self, kind: str, **fields) -> dict:
        entry = {"seq": len(self.steps) + 1, "kind": kind,
                 "elapsed_ms": round((time.monotonic() - self.started) * 1000), **fields}
        self.steps.append(entry)
        return entry

    def handle_for(self, api_call_id: str) -> str:
        if api_call_id not in self.handles:
            self.handles[api_call_id] = f"call_{len(self.handles) + 1}"
        return self.handles[api_call_id]

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def to_json(self) -> dict:
        return {"incident_id": self.incident_id, "status": self.status,
                "error": self.error, "steps": self.steps,
                "alert_decision": self.alert_decision,
                "elapsed_ms": round(self.elapsed * 1000)}


def agent_available() -> bool:
    return bool(OPENAI_API_KEY)


def _extract_calls(payload: dict) -> tuple[list[dict], list[dict]]:
    """Pull function calls out of a Responses API payload, tolerantly."""
    output = payload.get("output") or []
    calls, others = [], []
    for item in output:
        if item.get("type") == "function_call":
            calls.append(item)
        else:
            others.append(item)
    return calls, others


async def run_agent(detector, rec: IncidentRecord, now: datetime,
                    on_step=None) -> tuple[Diagnosis, AgentRun]:
    """Diagnose with the model. Never raises: the fallback is part of the contract."""
    run = AgentRun(rec.id)
    if not agent_available():
        run.status = "skipped"
        run.error = "no OPENAI_API_KEY configured"
        run.record("fallback", reason=run.error)
        return deterministic_diagnosis(detector, rec, reason=run.error), run

    box = ToolBox(detector, rec, now)
    brief = (f"Incident {rec.id} is confirmed. The engine isolated it to "
             f"{scope_phrase(rec.scope) or 'the whole platform'} and its working hypothesis is "
             f"`{rec.cause_type}`. Verify or refute that, then conclude. "
             f"Start with get_incident_summary.")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": brief},
    ]
    tools = tool_specs()
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    def emit(entry: dict) -> None:
        if on_step:
            try:
                on_step(entry)
            except Exception:
                pass

    from api.notify import slack as _slack
    slack_on = _slack.enabled()
    alert_prompted = False

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(AGENT_TIMEOUT_S)) as client:
            for step in range(AGENT_MAX_STEPS):
                left = AGENT_MAX_STEPS - step
                if left <= 2:
                    # Running out of steps mid-investigation used to end as "did not
                    # conclude", which throws away real work. Tell it to land.
                    messages.append({"role": "user", "content":
                                     f"You have {left} step(s) left. Call `conclude` now with "
                                     f"what the tools have already shown you, or "
                                     f"`insufficient_evidence` if they genuinely conflict."})
                remaining = AGENT_TIMEOUT_S - run.elapsed
                if remaining <= 0:
                    raise TimeoutError(f"agent budget of {AGENT_TIMEOUT_S:.0f}s exhausted")
                # Cap the request at what is left, so one slow call cannot double the budget.
                client.timeout = httpx.Timeout(remaining)
                body = {"model": OPENAI_MODEL, "input": messages, "tools": tools,
                        "temperature": 0, "parallel_tool_calls": False,
                        "max_output_tokens": 1500}
                resp = await client.post(f"{OPENAI_BASE_URL}/responses", json=body, headers=headers)
                if resp.status_code >= 400:
                    raise RuntimeError(f"responses API {resp.status_code}: {resp.text[:200]}")
                payload = resp.json()
                calls, _others = _extract_calls(payload)
                if not calls:
                    raise ValueError("the model answered in prose instead of calling a tool")

                for call in calls:
                    name = call.get("name", "")
                    call_id = call.get("call_id") or call.get("id") or f"call_{step}"
                    try:
                        args = json.loads(call.get("arguments") or "{}")
                    except json.JSONDecodeError as exc:
                        args = {}
                        emit(run.record("tool_call", tool=name, tool_call_id=call_id,
                                        arguments={}, error=f"unparsable arguments: {exc}"))

                    if name == "conclude":
                        # Telling the model to alert before concluding is not enough on its
                        # own — it reads `conclude` as the finish line and goes straight
                        # there. So the decision is made structural: the first time it tries
                        # to land a nameable cause without having decided about the alert,
                        # it gets the turn back. Once. Concluding again *is* the decision
                        # not to alert, and we let it stand.
                        needs_alert_call = (slack_on and not box.alerted
                                            and not alert_prompted
                                            and args.get("root_cause_type")
                                            not in (None, "", "insufficient_evidence"))
                        if needs_alert_call:
                            alert_prompted = True
                            emit(run.record("alert_decision_requested", tool_call_id=call_id))
                            messages.append({"role": "user", "content":
                                             "Before you conclude: you have named a cause, and "
                                             "nobody outside this system knows about it yet. "
                                             "Call `send_slack_alert` if an operator should act "
                                             "on this now, then conclude. If this genuinely does "
                                             "not warrant interrupting anyone, just call "
                                             "`conclude` again and it will stand."})
                            continue
                        diagnosis, finished_run = _finish_conclude(
                            detector, rec, run, args, call_id, emit, now)
                        # A malformed or unsupported conclusion is a failed run, not a
                        # decision to suppress the safety-net alert. Record a decision
                        # only once its conclusion has passed all validation.
                        if finished_run.status in ("concluded", "insufficient_evidence"):
                            if slack_on:
                                finished_run.alert_decision = "sent" if box.alerted else "declined"
                                emit(finished_run.record("alert_decision",
                                                         decision=finished_run.alert_decision,
                                                         tool_call_id=call_id))
                            else:
                                finished_run.alert_decision = "not_configured"
                        return diagnosis, finished_run
                    if name == "insufficient_evidence":
                        # An agent that cannot support a cause has explicitly chosen not
                        # to interrupt a human. Do not turn that into a generic page later.
                        run.alert_decision = "declined" if slack_on else "not_configured"
                        emit(run.record("alert_decision", decision=run.alert_decision,
                                        tool_call_id=call_id))
                        return _finish_insufficient(detector, rec, run, args, call_id, emit)

                    # The one tool that reaches outside this process is awaited rather
                    # than run through the sync dispatcher, so a slow webhook cannot block
                    # the event loop the rest of the simulation is running on.
                    if name == "send_slack_alert":
                        result = await box.send_slack_alert(
                            headline=args.get("headline", ""),
                            urgency=args.get("urgency", "notify"))
                    else:
                        result = box.call(name, args)
                    handle = run.handle_for(call_id)
                    run.call_ids.add(handle)
                    run.call_ids.add(call_id)
                    # The handle travels back inside the result, so the model can read it
                    # off the tool output it is looking at when it writes its evidence.
                    blob = json.dumps({"tool_call_id": handle, "tool": name, "result": result},
                                      default=str)
                    emit(run.record("tool_call", tool=name, tool_call_id=handle, arguments=args,
                                    tool_description=TOOL_SUMMARY.get(name, ""),
                                    result_preview=blob[:RESULT_PREVIEW_CHARS],
                                    truncated=len(blob) > RESULT_PREVIEW_CHARS,
                                    # Keep the delivery result as a first-class trace field.
                                    # The UI should not have to parse a preview string to tell
                                    # an operator whether Slack actually accepted the alert.
                                    alert_sent=(result.get("sent") if name == "send_slack_alert"
                                                else None),
                                    alert_note=(result.get("note") or result.get("error"))
                                    if name == "send_slack_alert" else None))
                    messages.append(call)
                    messages.append({"type": "function_call_output", "call_id": call_id,
                                     "output": blob[:12000]})
            raise RuntimeError(f"agent did not conclude within {AGENT_MAX_STEPS} steps")

    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        run.status = "failed"
        run.error = reason
        emit(run.record("fallback", reason=reason))
        return deterministic_diagnosis(detector, rec, reason=reason), run


def _finish_insufficient(detector, rec, run: AgentRun, args: dict, call_id: str, emit) -> tuple:
    reason = str(args.get("reason") or "the agent could not separate the candidate causes")
    emit(run.record("insufficient_evidence", tool_call_id=call_id, reason=reason,
                    tool_description=TOOL_SUMMARY["insufficient_evidence"],
                    what_would_help=args.get("what_would_help")))
    run.status = "insufficient_evidence"
    diag = deterministic_diagnosis(detector, rec, reason=None)
    diag.source = "agent"
    diag.confidence = min(diag.confidence, 0.4)
    diag.root_cause = RootCause(type="insufficient_evidence", scope=rec.scope)
    diag.ops_explanation = (f"The agent declined to name a cause: {reason} "
                            f"The engine's own reading is kept below for context.\n\n"
                            + diag.ops_explanation)
    diag.recommendation = Recommendation(
        action="Keep watching; do not act on this yet",
        rationale=reason)
    return diag, run


def _clean_scope(detector, scope: dict[str, str]) -> dict[str, str]:
    """Keep only dimensions pinned to a value that actually exists in this world.

    The tool schema lists every dimension, so models fill them all in and mark the
    irrelevant ones "" or "any". Both mean "any", which is the same as not naming the
    dimension — and `merchant="any"` on an incident card would be nonsense.
    """
    out: dict[str, str] = {}
    for dim, val in (scope or {}).items():
        known = detector.cube.index.get(dim)
        if known and val in known:
            out[dim] = val
    return out


# The engine prices incidents; the agent narrates them. Any amount of money written in
# the agent's own prose is invented by definition — its tools do not carry money any more.
# This has already produced "costing over $1.2M so far" on a card, which contradicts a
# guarantee we make out loud in the pitch.
MONEY_IN_PROSE = re.compile(r"[$€£]\s*\d|\b\d[\d.,]*\s*(?:usd|dollars?|d[oó]lares)\b", re.IGNORECASE)


def _money_in_prose(concl) -> str | None:
    """The first field where the agent wrote a figure it was never given."""
    fields = {"exec_line": concl.exec_line,
              "ops_explanation": concl.ops_explanation,
              "recommendation_rationale": concl.recommendation_rationale,
              "recommended_action": concl.recommended_action}
    fields.update({f"evidence[{i}].claim": e.claim for i, e in enumerate(concl.evidence)})
    for name, text in fields.items():
        if text and MONEY_IN_PROSE.search(text):
            return f"{name}: {text.strip()[:120]}"
    return None


def _finish_conclude(detector, rec, run: AgentRun, args: dict, call_id: str, emit,
                     now: datetime) -> tuple:
    """Validate, then let the agent's words in — but never its numbers."""
    try:
        concl = AgentConclusion.model_validate(args)
    except Exception as exc:
        reason = f"conclude failed schema validation: {exc}"
        run.status = "rejected"
        run.error = reason
        emit(run.record("rejected", tool_call_id=call_id, reason=reason))
        return deterministic_diagnosis(detector, rec, reason=reason), run

    handles = sorted(run.handles.values())
    unsupported = [e.tool_call_id for e in concl.evidence if e.tool_call_id not in run.call_ids]
    if unsupported:
        reason = (f"cited tool calls that never happened: {unsupported}; "
                  f"actual calls were {handles}")
        run.status = "rejected"
        run.error = reason
        emit(run.record("rejected", tool_call_id=call_id, reason=reason))
        return deterministic_diagnosis(detector, rec, reason=reason), run

    offending = _money_in_prose(concl)
    if offending is not None:
        reason = (f"wrote money in its own prose, which no tool gave it -> {offending}. "
                  f"The engine is the only source of figures on the card.")
        run.status = "rejected"
        run.error = reason
        emit(run.record("rejected", tool_call_id=call_id, reason=reason))
        return deterministic_diagnosis(detector, rec, reason=reason), run

    emit(run.record("conclude", tool_call_id=run.handle_for(call_id),
                    root_cause=concl.root_cause_type,
                    tool_description=TOOL_SUMMARY["conclude"],
                    scope=concl.root_cause_scope, confidence=concl.confidence,
                    evidence_count=len(concl.evidence)))
    run.status = "concluded"

    # `conclude(root_cause="insufficient_evidence")` and the dedicated tool are the same
    # answer arriving by two doors. Route them to the same place: "I cannot tell, with 90%
    # confidence" is not a reading anyone should be shown on an incident card.
    # Same rule as money: the agent decides *what* is broken, the engine says what to do
    # about it. "Reroute away from this provider" is a sentence anyone can write; naming
    # the provider that is currently healthy enough to take the traffic, with its rate and
    # its sample, is a calculation — and the agent has no tool that returns it.
    action, rationale = build_playbook(detector, rec, now, cause=concl.root_cause_type)
    recommendation = Recommendation(action=action, rationale=rationale)
    confidence = round(concl.confidence, 2)
    # The agent reads the engine's evidence; it cannot be surer of the answer than the
    # engine that produced it. Without this ceiling the card showed a 1.0 sitting on top
    # of an engine reading of 0.45 — the agent's certainty, dressed as the system's.
    ceiling = round(min(1.0, rec.confidence + AGENT_CONFIDENCE_HEADROOM), 2)
    if confidence > ceiling:
        emit(run.record("confidence_capped", tool_call_id=run.handle_for(call_id),
                        claimed=confidence, capped_to=ceiling,
                        engine_confidence=round(rec.confidence, 2)))
        confidence = ceiling
    if concl.root_cause_type == "insufficient_evidence":
        run.status = "insufficient_evidence"
        confidence = min(confidence, 0.4)
        recommendation = Recommendation(
            action="Keep watching; do not act on this yet",
            rationale=concl.recommendation_rationale or concl.ops_explanation)

    similar = find_similar_incidents(detector, rec)
    merchants = affected_merchants(detector, rec)
    events = [e for e in detector.change_events if e.id in set(rec.related_change_event_ids)]
    return Diagnosis(
        incident_id=rec.id,
        root_cause=RootCause(type=concl.root_cause_type,
                             scope=_clean_scope(detector, concl.root_cause_scope) or rec.scope),
        since=rec.started_at,
        confidence=confidence,
        evidence=[Evidence(tool_call_id=e.tool_call_id, claim=e.claim) for e in concl.evidence],
        # Numbers come from the engine, always.
        affected=Affected(merchants=merchants, excess_declines=round(rec.excess_declines, 1),
                          cost_per_min_usd=round(rec.cost_per_min_usd, 2)),
        signature=SignatureDiff(before=rec.signature_before, during=rec.signature_during,
                                risen=rec.signature_json.get("risen") or []),
        related_change_events=events,
        similar_past=[SimilarIncident(incident_id=s["incident_id"], started_at=s["started_at"],
                                      duration_min=s["duration_min"], cause_type=s["cause_type"],
                                      cost_usd=s["cost_usd"], similarity=s["similarity"])
                      for s in similar],
        recommendation=recommendation,
        ops_explanation=concl.ops_explanation,
        exec_line=concl.exec_line,
        source="agent",
    ), run
