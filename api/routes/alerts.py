"""Alert plumbing: check the wiring without waiting for something to break."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.config import PUBLIC_BASE_URL, SLACK_ALERT_MIN_COST_PER_MIN, SLACK_WEBHOOK_URL
from api.notify import slack
from api.runtime import get_world

router = APIRouter(tags=["alerts"])


@router.get("/alerts/status")
def status() -> dict:
    """Is alerting on, and what has it sent this session."""
    w = get_world()
    return {
        "slack": {
            "enabled": slack.enabled(),
            # Never return the webhook: it is a bearer credential, anyone holding it can
            # post to the channel. Say whether it is set, not what it is.
            "webhook_configured": bool(SLACK_WEBHOOK_URL),
            "min_cost_per_min_usd": SLACK_ALERT_MIN_COST_PER_MIN,
            "alerts_sent": len(w.slack_sent),
            "incident_ids": sorted(w.slack_sent),
        },
        "public_base_url": PUBLIC_BASE_URL or None,
    }


@router.post("/alerts/test")
async def test_alert(incident_id: str | None = None) -> dict:
    """Send one alert now, so a webhook can be verified before a real incident needs it.

    With no id it uses the most expensive incident on the board; with an id, that one.
    It ignores the "already sent" ledger on purpose — this is the button you press twice
    while you are still getting the channel right — but it does not write to it either,
    so a test never suppresses the real alert for that incident later.
    """
    if not slack.enabled():
        raise HTTPException(400, "SLACK_WEBHOOK_URL is not set; alerting is off")
    w = get_world()
    if incident_id:
        rec = w.incident(incident_id)
        if rec is None:
            raise HTTPException(404, f"no incident {incident_id}")
    else:
        candidates = sorted(w.detector.incidents.values(),
                            key=lambda r: -r.cost_per_min_usd)
        if not candidates:
            raise HTTPException(409, "no incidents yet — inject one first")
        rec = candidates[0]
    sent = await slack.send(slack.build_message(rec, rec.diagnosis, PUBLIC_BASE_URL))
    return {"sent": sent, "incident_id": rec.id,
            "note": "test send; the real alert for this incident is unaffected"}
