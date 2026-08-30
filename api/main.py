"""FastAPI app. One process: simulation, engine, agent and the UI it serves."""
from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.agent.loop import agent_available
from api.config import OPENAI_MODEL, ROOT, SIM_SPEED
from api.routes import router
from api.runtime import get_world


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    world = get_world()
    await world.start()
    try:
        yield
    finally:
        await world.stop()


app = FastAPI(title="Control Tower", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/health")
def health() -> dict:
    world = get_world()
    return {
        "ok": True,
        "sim_now": world.now.isoformat(),
        "sim_speed": SIM_SPEED,
        "minutes_elapsed": world.minutes_elapsed,
        "tick_cost_ms": round(world.tick_cost_ms, 1),
        "agent": {"available": agent_available(), "model": OPENAI_MODEL if agent_available() else None},
        "open_incidents": len(world.detector.open_incidents()),
    }


DIST = Path(ROOT) / "ui" / "dist"
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(DIST / "index.html")
