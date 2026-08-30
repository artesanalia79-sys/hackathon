"""The other direction: Slack talking to us.

An incoming webhook can only fire messages one way. To answer someone you need a bot
token and `chat.postMessage`, and to know they asked you need the Events API pointed at
a public URL of ours. That URL is on the internet, so the first thing this module does
is refuse anything it cannot prove came from Slack.

Three things worth knowing about the shape of this:

  - Slack retries any event it does not get a 200 for within 3 seconds. Answering a
    question takes longer than that, so the endpoint acks immediately and the work runs
    in the background. Doing it inline would produce duplicate answers, not late ones.
  - Slack also retries on *its* own timeouts, so the same event can arrive twice with
    the same `event_id`. We remember the ids we have handled.
  - The bot hears its own messages. Answering them is an infinite loop with a billing
    department, so anything with a `bot_id` is dropped before anything else happens.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from collections import OrderedDict

import httpx

from api.config import (
    SLACK_API_BASE,
    SLACK_BOT_TOKEN,
    SLACK_SIGNING_SECRET,
    SLACK_TIMEOUT_S,
)

log = logging.getLogger("control_tower.slack_events")

# Slack considers anything older than five minutes a replay attempt, and so do we.
MAX_SKEW_S = 60 * 5
_seen_events: OrderedDict[str, float] = OrderedDict()
MAX_SEEN = 500

# `<@U123ABC>` — the mention of us that we strip before reading the question.
MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
# Slack wraps bare urls and channels in angle brackets; the model does not need them.
LINK_RE = re.compile(r"<(?:https?://)?([^|>]+)(?:\|[^>]*)?>")


def can_reply() -> bool:
    return bool(SLACK_BOT_TOKEN)


def verify(body: bytes, timestamp: str, signature: str) -> tuple[bool, str]:
    """Is this really Slack? Returns (ok, why not).

    Without a signing secret configured we cannot answer that question at all, and the
    honest response to "I cannot verify you" is to refuse, not to assume yes.
    """
    if not SLACK_SIGNING_SECRET:
        return False, "SLACK_SIGNING_SECRET is not configured; refusing unverifiable events"
    if not timestamp or not signature:
        return False, "missing signature headers"
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False, "unparsable timestamp"
    if age > MAX_SKEW_S:
        return False, f"timestamp is {age:.0f}s off; treating as a replay"
    base = b"v0:" + timestamp.encode() + b":" + body
    expected = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    # compare_digest, not ==, so the comparison does not leak the secret through timing.
    if not hmac.compare_digest(expected, signature):
        return False, "signature mismatch"
    return True, ""


def already_handled(event_id: str) -> bool:
    """Slack retries; a retry must not produce a second answer."""
    if not event_id:
        return False
    if event_id in _seen_events:
        return True
    _seen_events[event_id] = time.time()
    while len(_seen_events) > MAX_SEEN:
        _seen_events.popitem(last=False)
    return False


def clean_text(text: str) -> str:
    """The question, without the mention of us and without Slack's link syntax."""
    text = MENTION_RE.sub("", text or "")
    text = LINK_RE.sub(r"\1", text)
    return " ".join(text.split()).strip()


async def post_message(channel: str, text: str, thread_ts: str | None = None,
                       blocks: list | None = None) -> dict:
    """`chat.postMessage`. Returns the API payload; never raises.

    Slack answers 200 with `{"ok": false, "error": ...}` for application errors, so the
    status code alone is not the result — the body is.
    """
    if not SLACK_BOT_TOKEN:
        return {"ok": False, "error": "no bot token configured"}
    body: dict = {"channel": channel, "text": text}
    if thread_ts:
        body["thread_ts"] = thread_ts
    if blocks:
        body["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(SLACK_TIMEOUT_S)) as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/chat.postMessage", json=body,
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                         "Content-Type": "application/json; charset=utf-8"})
        out = resp.json()
        if not out.get("ok"):
            log.warning("chat.postMessage refused: %s", out.get("error"))
        return out
    except Exception as exc:
        log.warning("chat.postMessage failed: %s: %s", type(exc).__name__, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# Which incident a thread is about, for when someone replies under an alert we posted.
# Process-local, like the retry ledger: losing it on restart costs a little context on
# old threads, never an answer.
_thread_incidents: OrderedDict[str, str] = OrderedDict()
MAX_THREADS = 300


def remember_thread(ts: str, incident_id: str) -> None:
    if not ts or not incident_id:
        return
    _thread_incidents[ts] = incident_id
    while len(_thread_incidents) > MAX_THREADS:
        _thread_incidents.popitem(last=False)


def thread_context(thread_ts: str | None) -> str:
    """What the asker is standing in front of, phrased for the model.

    A question in the thread of an alert almost always means "this one" — "is it fixed?",
    "did we reroute?" — with no incident named anywhere in the sentence. Without this the
    answer would be a confident summary of the wrong thing.
    """
    incident_id = _thread_incidents.get(thread_ts or "")
    if not incident_id:
        return ""
    return (f"This question was asked in the Slack thread of incident {incident_id}. "
            f"Unless the question clearly asks about something else, it is about that "
            f"incident — call incident_detail on it before answering.")


def is_answerable(event: dict) -> tuple[bool, str]:
    """Should we answer this event at all?"""
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return False, "our own message, or another bot's"
    if event.get("type") not in ("app_mention", "message"):
        return False, f"event type {event.get('type')!r} is not a question"
    if not clean_text(event.get("text", "")):
        return False, "mention with no question in it"
    return True, ""
