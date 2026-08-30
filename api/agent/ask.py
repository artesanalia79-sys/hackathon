"""Answer a question about live state, in prose, for a chat channel.

This is the diagnosis agent's sibling, and the differences are deliberate.

The diagnosis agent must end in a structured verdict, so prose is an error there. Here
prose *is* the deliverable: somebody asked a question in Slack and wants a sentence
back, not JSON. So the loop is inverted — tool calls continue it, text ends it.

It also cannot conclude, cannot alert, and cannot change anything. It reads. The worst
thing a wrong answer here can do is mislead one person who can ask a follow-up, which is
why this one is allowed to be chatty where the diagnosis agent is not.
"""
from __future__ import annotations

import json
import time

import httpx

from api.agent.ask_tools import AskToolBox
from api.config import (
    ASK_MAX_STEPS,
    ASK_TIMEOUT_S,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)
from api.domain import DIMENSIONS

SYSTEM_PROMPT = """You are Control Tower, answering a payments operations team in Slack.

You watch a payment orchestrator in real time: attempts are counted per minute across
merchant, country, method, brand (card network), issuer and provider, compared against
what that same segment normally does at this hour on this weekday, and anything that
drops below its band becomes an incident with a cause, a cost and a recommended action.

Answer the question you were asked. Use the tools first — you have no memory of the
system between questions and the numbers move every minute, so anything you state about
right now has to come from a call you just made.

How to answer:
- Lead with the answer. The person is on their phone, possibly at 3am.
- A conversion rate is approvals divided by operational attempts. It is never a share
  of volume: "conversion is 73%" is right, "73% of expected attempts happened" is a
  different claim and usually a wrong one. Report rates as percentages.
- Numbers come from tool results, never from your head. If a tool did not return it, you
  do not know it, and saying so is a good answer.
- Slack markdown: *bold* with single asterisks, `code` for scopes and ids. No headers,
  no tables. Keep it under about 12 lines unless asked for detail.
- Name the incident id when you talk about a specific incident, so the person can open it.
- If the question is vague ("what's going on?"), call system_status and summarise what is
  open, worst first, with what it is costing.
- If nothing is wrong, say so plainly. "Everything is inside its band right now" is a
  complete answer and a good one.
- You may be asked things outside this system. Say what you do not have access to instead
  of guessing, and offer what you can see that is closest.

What you cannot do: change anything. You cannot reroute traffic, edit a mapping, close an
incident or send an alert. If someone asks you to act, say what you would do and that a
human has to do it. You also cannot see what is "actually" broken behind the scenes —
only what the counters show, exactly like the engine."""


def available() -> bool:
    return bool(OPENAI_API_KEY)


def tool_specs() -> list[dict]:
    scope_schema = {
        "type": "object",
        "description": "Filter, e.g. {\"provider\": \"dlocal\", \"country\": \"BR\"}. "
                       "Omit or leave empty for the whole platform.",
        "properties": {d: {"type": "string"} for d in DIMENSIONS},
        "additionalProperties": False,
    }
    minutes = {"type": "integer", "description": "Window in minutes (default 5, max 240)."}
    return [
        {"type": "function", "name": "system_status",
         "description": "The board right now: clock, platform conversion, every open "
                        "incident with its cost. Start here for a general question.",
         "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"type": "function", "name": "list_incidents",
         "description": "Incidents on the board, optionally filtered by status.",
         "parameters": {"type": "object",
                        "properties": {"status": {"type": "string",
                                                  "enum": ["watching", "confirmed",
                                                           "resolved", "expired"]},
                                       "limit": {"type": "integer"}},
                        "additionalProperties": False}},
        {"type": "function", "name": "incident_detail",
         "description": "One incident in full: cause, signature, attribution, cost "
                        "breakdown, recommended action and why.",
         "parameters": {"type": "object",
                        "properties": {"incident_id": {"type": "string"}},
                        "required": ["incident_id"], "additionalProperties": False}},
        {"type": "function", "name": "slice_metrics",
         "description": "Conversion for any segment against its own seasonal expectation.",
         "parameters": {"type": "object",
                        "properties": {"scope": scope_schema, "minutes": minutes},
                        "additionalProperties": False}},
        {"type": "function", "name": "compare_across",
         "description": "Split a segment by a dimension to see who is healthy and who is "
                        "not — the test that separates a provider fault from an issuer one.",
         "parameters": {"type": "object",
                        "properties": {"scope": scope_schema,
                                       "dimension": {"type": "string",
                                                     "enum": list(DIMENSIONS)},
                                       "minutes": minutes},
                        "additionalProperties": False}},
        {"type": "function", "name": "decline_signature",
         "description": "Which decline categories rose in a segment against its history, "
                        "and the raw provider codes behind them.",
         "parameters": {"type": "object",
                        "properties": {"scope": scope_schema, "minutes": minutes},
                        "additionalProperties": False}},
        {"type": "function", "name": "change_events",
         "description": "Deploys, routing rules and mapping changes in a recent window.",
         "parameters": {"type": "object",
                        "properties": {"window_minutes": {"type": "integer"}},
                        "additionalProperties": False}},
        {"type": "function", "name": "history",
         "description": "Incidents that already closed, for 'has this happened before'.",
         "parameters": {"type": "object", "properties": {"hours": {"type": "integer"}},
                        "additionalProperties": False}},
    ]


def _extract(payload: dict) -> tuple[list[dict], str]:
    """(function calls, assistant text) out of a Responses API payload."""
    calls, text = [], []
    for item in payload.get("output") or []:
        if item.get("type") == "function_call":
            calls.append(item)
        elif item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") in ("output_text", "text") and part.get("text"):
                    text.append(part["text"])
    return calls, "\n".join(text).strip()


async def answer(world, question: str, context: str = "") -> dict:
    """Answer `question` about `world`. Never raises — a chat reply always happens.

    `context` is what the caller already knows about where the question came from, such
    as the incident whose thread it was asked in. It goes in as a user message rather
    than into the prompt, because it is data about this question, not a standing rule.
    """
    started = time.monotonic()
    if not available():
        return {"ok": False, "text": "I have no model configured, so I cannot answer "
                                     "questions right now. The dashboard still has "
                                     "everything: incidents, causes and recommendations.",
                "tools_used": [], "elapsed_s": 0.0}

    box = AskToolBox(world)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "user", "content": context})
    messages.append({"role": "user", "content": question})

    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    tools = tool_specs()
    used: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(ASK_TIMEOUT_S)) as client:
            for step in range(ASK_MAX_STEPS):
                remaining = ASK_TIMEOUT_S - (time.monotonic() - started)
                if remaining <= 1:
                    raise TimeoutError("out of time")
                client.timeout = httpx.Timeout(remaining)
                if step == ASK_MAX_STEPS - 1:
                    messages.append({"role": "user",
                                     "content": "Answer now, in text, with what you have."})
                resp = await client.post(
                    f"{OPENAI_BASE_URL}/responses",
                    json={"model": OPENAI_MODEL, "input": messages, "tools": tools,
                          "temperature": 0, "parallel_tool_calls": False,
                          "max_output_tokens": 900},
                    headers=headers)
                if resp.status_code >= 400:
                    raise RuntimeError(f"responses API {resp.status_code}: {resp.text[:200]}")
                payload = resp.json()
                calls, text = _extract(payload)

                if not calls:
                    # Text with no tool calls is the answer: this loop ends in prose.
                    if not text:
                        raise ValueError("the model returned neither a tool call nor text")
                    return {"ok": True, "text": text, "tools_used": used,
                            "elapsed_s": round(time.monotonic() - started, 2)}

                for call in calls:
                    name = call.get("name", "")
                    call_id = call.get("call_id") or call.get("id") or f"call_{step}"
                    try:
                        args = json.loads(call.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = box.call(name, args)
                    used.append(name)
                    messages.append({"type": "function_call", "call_id": call_id,
                                     "name": name, "arguments": call.get("arguments") or "{}"})
                    messages.append({"type": "function_call_output", "call_id": call_id,
                                     "output": json.dumps(result, default=str)[:12000]})
        raise TimeoutError("step budget exhausted without an answer")
    except Exception as exc:
        # A question that cannot be answered still gets a reply. Silence in a chat channel
        # reads as "the system is down", which is worse than an honest failure.
        return {"ok": False,
                "text": (f"I could not finish that one ({type(exc).__name__}). "
                         f"The dashboard has the current state, and asking again "
                         f"usually works."),
                "tools_used": used, "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.monotonic() - started, 2)}
