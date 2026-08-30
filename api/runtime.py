"""The world: clock, generator, cube, detector, and the seam the API talks to.

One object owns the mutable state so there is exactly one writer per table, as the
architecture requires: ingest writes counters, the detector writes incidents, the
agent writes diagnoses.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from datetime import datetime, timedelta

from api.config import EWMA_HOURS, SEED, SIM_SPEED
from api.domain import ChangeEvent, Injection, Transaction
from api.engine.cube import Cube
from api.engine.detector import Detector
from api.engine.incidents import IncidentRecord
from api.sim.generator import Generator
from api.sim.injector import Injector

# A Wednesday at 14:00 — mid-week, mid-afternoon, healthy volume.
SIM_ORIGIN = datetime(2026, 8, 26, 14, 0, 0)
WARMUP_MINUTES = EWMA_HOURS * 60 + 40


class World:
    def __init__(self, seed: int = SEED, sim_speed: float = SIM_SPEED,
                 origin: datetime | None = None) -> None:
        self.seed = seed
        self.sim_speed = sim_speed
        self.origin = origin or SIM_ORIGIN
        self.injector = Injector()
        self.generator = Generator(self.injector, seed=seed)
        self.cube = Cube()
        self.detector = Detector(self.cube)
        self.now: datetime = self.origin
        self.recent_tx: deque[Transaction] = deque(maxlen=250)
        self.started_wall: float = time.monotonic()
        self.minutes_elapsed = 0
        self._task: asyncio.Task | None = None
        self._diagnoser: asyncio.Task | None = None
        self.agent_runs: dict[str, dict] = {}      # incident id -> serialised AgentRun
        self._lock = asyncio.Lock()
        self.listeners: set[asyncio.Queue] = set()
        self.tick_cost_ms: float = 0.0

    # --- setup -------------------------------------------------------------
    def warmup(self, minutes: int = WARMUP_MINUTES) -> None:
        """Build the seasonal baseline, then run enough clean minutes to fill the EWMA."""
        self.cube.set_baseline(self.generator.build_baseline())
        t = self.origin - timedelta(minutes=minutes)
        while t < self.origin:
            rows, _txs = self.generator.generate_minute(t)
            self.cube.put_minute(t, rows)
            t += timedelta(minutes=1)
        self.now = self.origin
        self.minutes_elapsed = 0
        self.seed_memory()

    def seed_memory(self) -> None:
        """A few incidents that already happened and were resolved.

        Without this, "we have seen this before" can only ever be false on demo day,
        and the memory tool would be untestable. These are marked as seeded.
        """
        from api.engine.incidents import fingerprint, new_id
        past = [
            (timedelta(days=2, hours=3), {"provider": "dlocal", "country": "BR"},
             "provider_degraded", 47.0, 1830.0, 38.0,
             "dLocal acquirer errors in Brazil; traffic was rerouted to adyen"),
            (timedelta(days=5, hours=6), {"issuer": "banorte"}, "issuer_over_declining",
             62.0, 940.0, 15.0, "Banorte tightened its risk rules; 3DS retry was enabled"),
            (timedelta(days=1, hours=9), {"provider": "stripe", "country": "CO"},
             "internal_change", 23.0, 610.0, 26.0,
             "Stripe was routed for Colombia by a routing rule; rolled back"),
        ]
        for ago, scope, cause, duration, cost, cost_min, note in past:
            started = self.origin - ago
            rec = IncidentRecord(
                id=new_id(), fingerprint_key=fingerprint(scope, cause, "conversion_drop"), status="resolved",
                kind="conversion_drop", scope=dict(scope), cause_type=cause,
                started_at=started, last_seen_at=started + timedelta(minutes=duration),
                confirmed_at=started + timedelta(minutes=8),
                resolved_at=started + timedelta(minutes=duration),
                expected_rate=0.90, observed_rate=0.62, excess_declines=cost_min * 2,
                cost_usd=cost, cost_per_min_usd=cost_min,
                signature_before={"none": 0.90, "soft_decline": 0.05, "technical": 0.02,
                                  "hard_decline": 0.03},
                signature_during={"none": 0.62, "soft_decline": 0.07, "technical": 0.27,
                                  "hard_decline": 0.04},
                reasons=[note], confidence=0.9, detail={"seeded": True, "resolution": note},
            )
            self.detector.incidents[rec.id] = rec

    # --- stepping ----------------------------------------------------------
    def step(self) -> None:
        """Advance one simulated minute: generate, count, detect."""
        t0 = time.perf_counter()
        self.now += timedelta(minutes=1)
        rows, txs = self.generator.generate_minute(self.now)
        self.cube.put_minute(self.now, rows)
        for tx in txs:
            self.recent_tx.appendleft(tx)
        self.detector.change_events = self.injector.change_events()
        self.detector.tick(self.now)
        self.minutes_elapsed += 1
        self.tick_cost_ms = (time.perf_counter() - t0) * 1000.0

    def run_minutes(self, n: int) -> None:
        for _ in range(n):
            self.step()

    # --- injections --------------------------------------------------------
    def set_speed(self, speed: float) -> float:
        """Change how fast simulated time runs. 0 pauses the world; the API stays up."""
        self.sim_speed = max(0.0, float(speed))
        self.publish({"type": "speed", "sim_speed": self.sim_speed})
        return self.sim_speed

    def stop_injection(self, injection_id: str) -> bool:
        """End one injection without resetting everything, so recovery can be watched."""
        for act in self.injector.all():
            if act.id == injection_id:
                if act.ends_at is not None and act.ends_at <= self.now:
                    return False
                act.ends_at = self.now
                return True
        return False

    def inject(self, inj: Injection) -> tuple[str, bool]:
        active, duplicate = self.injector.add(inj, self.now)
        self.detector.change_events = self.injector.change_events()
        return active.id, duplicate

    def add_change_event(self, ev: ChangeEvent) -> None:
        self.injector.add_change_event(ev)
        self.detector.change_events = self.injector.change_events()

    async def reset_async(self) -> None:
        """Reset under the simulation lock.

        Without the lock, a generation batch already in flight lands *after* the
        wipe and the detector re-opens the incident we just cleared — the ghosts
        rule 7 exists to prevent.
        """
        async with self._lock:
            await asyncio.to_thread(self.reset)

    def reset(self) -> None:
        """Back to a clean baseline: no injections, no incidents, no ghosts."""
        self.injector.reset()
        self.detector.reset()
        self.agent_runs.clear()
        self.cube.clear_live()
        self.recent_tx.clear()
        self.generator = Generator(self.injector, seed=self.seed)
        self.warmup()

    # --- notifications -----------------------------------------------------
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        self.listeners.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.listeners.discard(q)

    def publish(self, payload: dict) -> None:
        for q in list(self.listeners):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # --- async loop --------------------------------------------------------
    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
        if self._diagnoser is None:
            self._diagnoser = asyncio.create_task(self._diagnose_loop())

    async def stop(self) -> None:
        for attr in ("_task", "_diagnoser"):
            task = getattr(self, attr)
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                setattr(self, attr, None)

    async def _diagnose_loop(self) -> None:
        """Diagnose confirmed incidents, one at a time, and stream every tool call.

        Only confirmed incidents reach the model: that is what keeps the cost and the
        latency bounded, and it is why a five-minute blip never pays for an LLM call.
        """
        from api.agent.loop import run_agent

        while True:
            await asyncio.sleep(0.5)
            pending = [r for r in self.detector.incidents.values()
                       if r.diagnosis_pending and r.status == "confirmed"]
            for rec in pending:
                rec.diagnosis_pending = False

                def on_step(entry: dict, incident_id: str = rec.id) -> None:
                    self.publish({"type": "trace", "incident_id": incident_id, "step": entry})

                try:
                    diagnosis, run = await run_agent(self.detector, rec, self.now, on_step=on_step)
                except Exception as exc:  # the loop itself must never die
                    from api.engine.diagnose import deterministic_diagnosis
                    diagnosis = deterministic_diagnosis(self.detector, rec,
                                                        reason=f"{type(exc).__name__}: {exc}")
                    run = None
                rec.diagnosis = diagnosis.model_dump(mode="json")
                if run is not None:
                    self.agent_runs[rec.id] = run.to_json()
                self.publish({"type": "diagnosis", "incident_id": rec.id,
                              "source": diagnosis.source})

    async def _loop(self) -> None:
        """Wall clock -> simulated minutes. Generation runs off-thread so SSE stays smooth.

        `sim_speed` is a multiple of real time: 60 means one simulated minute per real
        second, so a 5-minute detection window takes 5 real seconds. Dividing by 60 is
        what makes that true — without it the number meant simulated *minutes* per real
        second and every label on the speed control was off by a factor of sixty.
        """
        tick_seconds = 0.25
        carry = 0.0
        while True:
            await asyncio.sleep(tick_seconds)
            carry += (self.sim_speed / 60.0) * tick_seconds
            steps = int(carry)
            carry -= steps
            if steps <= 0:
                continue
            steps = min(steps, 120)
            async with self._lock:
                await asyncio.to_thread(self.run_minutes, steps)
            self.publish({"type": "tick", "now": self.now.isoformat(),
                          "minutes": self.minutes_elapsed})

    # --- reads -------------------------------------------------------------
    def incident(self, incident_id: str) -> IncidentRecord | None:
        return self.detector.incidents.get(incident_id)

    def incidents_sorted(self) -> list[IncidentRecord]:
        def rank(r: IncidentRecord) -> tuple:
            status_rank = {"confirmed": 0, "watching": 1, "resolved": 2, "expired": 3}
            return (status_rank.get(r.status, 4), -r.cost_per_min_usd)
        return sorted(self.detector.incidents.values(), key=rank)


WORLD: World | None = None


def get_world() -> World:
    global WORLD
    if WORLD is None:
        WORLD = World()
        WORLD.warmup()
    return WORLD
