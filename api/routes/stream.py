"""SSE: the live board and the agent's trace as it happens."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from api.config import WINDOW_SENSITIVE_MIN
from api.engine.expectation import Expector
from api.runtime import get_world

router = APIRouter(tags=["stream"])


def _snapshot() -> dict:
    w = get_world()
    ex = Expector(w.cube)
    exp = ex.expect({}, w.now, WINDOW_SENSITIVE_MIN)
    openers = w.detector.open_incidents()
    return {
        "now": w.now.isoformat(),
        "sim_speed": w.sim_speed,
        "minutes_elapsed": w.minutes_elapsed,
        "tick_cost_ms": round(w.tick_cost_ms, 1),
        "global": {
            "attempts_per_min": round(exp.observed.attempts / WINDOW_SENSITIVE_MIN),
            "observed_rate": round(exp.observed.rate, 4) if exp.observed.rate is not None else None,
            "expected_rate": round(exp.p0, 4),
            "series": w.cube.series({}, w.now, 90),
        },
        "incidents": [r.to_json() for r in w.incidents_sorted()],
        "open_count": len(openers),
        "total_cost_per_min_usd": round(sum(r.cost_per_min_usd for r in openers), 2),
        "events": w.detector.events_log[-25:],
    }


@router.get("/stream")
async def stream() -> EventSourceResponse:
    w = get_world()

    async def gen():
        q = w.subscribe()
        try:
            yield {"event": "snapshot", "data": json.dumps(_snapshot(), default=str)}
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=2.0)
                except TimeoutError:
                    yield {"event": "snapshot", "data": json.dumps(_snapshot(), default=str)}
                    continue
                if msg.get("type") == "tick":
                    yield {"event": "snapshot", "data": json.dumps(_snapshot(), default=str)}
                else:
                    yield {"event": msg.get("type", "message"),
                           "data": json.dumps(msg, default=str)}
        finally:
            w.unsubscribe(q)

    return EventSourceResponse(gen())


@router.get("/snapshot")
def snapshot() -> dict:
    return _snapshot()
