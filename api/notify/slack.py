"""Slack alerts for confirmed incidents.

One message per incident, the moment it is confirmed and diagnosed. Not on `watching`:
a watching incident is a hypothesis, and paging a human for a hypothesis is how an alert
channel becomes a channel nobody reads.

Three rules this module keeps:

  - It never blocks the simulation. Sending happens on the diagnosis loop, already off
    the tick path, and any failure is swallowed and logged, never raised.
  - It never sends twice for the same incident. Slack dedupes nothing; we do.
  - It is off unless configured. No webhook, no attempt, no error - exactly how the
    agent behaves without an API key.

The payload deliberately carries the engine's numbers and the engine's recommendation,
not a re-description of them. What lands in the channel is what is on the card.
"""
from __future__ import annotations

import logging

import httpx

from api.config import SLACK_ALERT_MIN_COST_PER_MIN, SLACK_TIMEOUT_S, SLACK_WEBHOOK_URL
from api.engine.incidents import IncidentRecord

log = logging.getLogger("control_tower.slack")

MERCHANT_NAMES = {"m_fastcart": "FastCart", "m_streamly": "Streamly", "m_viajesya": "ViajesYa"}
# Slack rejects a payload over 3000 characters per text block; incident prose is well
# under that, but an agent explanation is free-form, so it gets trimmed.
MAX_BLOCK_CHARS = 2800


def enabled() -> bool:
    return bool(SLACK_WEBHOOK_URL)


def _scope_line(scope: dict[str, str]) -> str:
    if not scope:
        return "the whole platform"
    order = ["provider", "issuer", "brand", "method", "country", "merchant"]
    parts = [f"{k}=`{scope[k]}`" for k in order if k in scope]
    parts += [f"{k}=`{v}`" for k, v in scope.items() if k not in order]
    return " · ".join(parts)


def _trim(text: str, limit: int = MAX_BLOCK_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build_message(rec: IncidentRecord, diagnosis: dict | None, base_url: str = "") -> dict:
    """Block Kit payload. Pure function, so it can be tested without a network."""
    cause = (diagnosis or {}).get("root_cause", {}).get("type") or rec.cause_type or "unknown"
    confidence = (diagnosis or {}).get("confidence", rec.confidence)
    source = (diagnosis or {}).get("source", "engine")
    rec_block = (diagnosis or {}).get("recommendation") or {}
    action = rec_block.get("action") or "See the incident card."
    rationale = rec_block.get("rationale") or ""
    risen = ", ".join(rec.signature_json.get("risen") or []) or "—"

    headline = f"{cause.replace('_', ' ')} · {_scope_line(rec.scope)}"
    fields = [
        f"*Cost*\n${rec.cost_per_min_usd:,.0f}/min",
        f"*Conversion*\n{rec.observed_rate:.1%} vs {rec.expected_rate:.1%} expected",
        f"*Since*\n{rec.started_at:%H:%M} ({rec.duration_min:.0f} min)",
        f"*Confidence*\n{confidence:.0%} ({source})",
        f"*Declines up*\n{risen}",
        f"*Excess*\n{rec.excess_declines:,.0f} in 5 min",
    ]

    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"Confirmed incident — {headline}"[:150]}},
        {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields]},
        {"type": "section",
         "text": {"type": "mrkdwn", "text": f"*Recommended action*\n{_trim(action)}"}},
    ]
    if rationale:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": _trim(rationale, 1000)}]})
    # Said out loud in the channel, because an alert that looks like a bot with a switch
    # is an alert people stop trusting.
    blocks.append({"type": "context", "elements": [
        {"type": "mrkdwn", "text": ":lock: Control Tower recommends only — nothing was executed."}]})
    if base_url:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open incident"},
             "url": f"{base_url.rstrip('/')}/?incident={rec.id}"}]})

    return {"text": f"Confirmed incident: {headline} — ${rec.cost_per_min_usd:,.0f}/min",
            "blocks": blocks}


def should_alert(rec: IncidentRecord) -> bool:
    """Confirmed, and expensive enough to be worth a human's attention."""
    if rec.status != "confirmed":
        return False
    return rec.cost_per_min_usd >= SLACK_ALERT_MIN_COST_PER_MIN


async def send(payload: dict) -> bool:
    """POST to the webhook. Returns whether it landed; never raises."""
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(SLACK_TIMEOUT_S)) as client:
            resp = await client.post(SLACK_WEBHOOK_URL, json=payload)
        if resp.status_code >= 300:
            log.warning("slack rejected the alert: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as exc:
        log.warning("slack alert failed: %s: %s", type(exc).__name__, exc)  # break the loop
        return False
