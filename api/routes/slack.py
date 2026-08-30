"""The Slack Events endpoint: someone @-mentions us, we answer in the thread."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, Response

from api.agent import ask
from api.notify import slack_events
from api.runtime import get_world

log = logging.getLogger("control_tower.slack_events")
router = APIRouter(tags=["slack"])


@router.post("/slack/events")
async def events(request: Request) -> Response:
    """Slack's webhook. Verifies, acks in milliseconds, answers in the background.

    Slack retries anything it does not get a 200 for within three seconds, and answering
    a real question takes longer than that. Doing the work inline would not produce a
    late answer, it would produce several duplicate ones.
    """
    raw = await request.body()
    ok, why = slack_events.verify(raw, request.headers.get("x-slack-request-timestamp", ""),
                                  request.headers.get("x-slack-signature", ""))
    if not ok:
        log.warning("rejected a slack event: %s", why)
        # 401 and nothing else. Explaining *why* verification failed to an unverified
        # caller is how you help someone work out what to forge.
        return Response(status_code=401)

    payload = await request.json()

    # Slack proves it owns the URL by posting a challenge it expects echoed back.
    if payload.get("type") == "url_verification":
        return Response(content=payload.get("challenge", ""), media_type="text/plain")

    if payload.get("type") != "event_callback":
        return Response(status_code=200)

    event = payload.get("event") or {}
    if slack_events.already_handled(payload.get("event_id", "")):
        return Response(status_code=200)

    answerable, reason = slack_events.is_answerable(event)
    if not answerable:
        log.debug("ignoring slack event: %s", reason)
        return Response(status_code=200)

    # Fire and forget: the ack has to leave now.
    asyncio.create_task(_answer(event))
    return Response(status_code=200)


async def _answer(event: dict) -> None:
    """Do the actual work, off the request path. Never raises into the event loop."""
    try:
        channel = event.get("channel", "")
        # Reply in the thread the question was asked in; if it was asked in the channel,
        # start a thread on that message so the channel does not fill with answers.
        thread_ts = event.get("thread_ts") or event.get("ts")
        question = slack_events.clean_text(event.get("text", ""))

        world = get_world()
        context = slack_events.thread_context(thread_ts)
        result = await ask.answer(world, question, context)

        await slack_events.post_message(channel, result["text"], thread_ts)
        if not result.get("ok"):
            log.warning("answered with a failure notice: %s", result.get("error"))
    except Exception as exc:
        log.warning("slack answer task died: %s: %s", type(exc).__name__, exc)
