"""Headless driver for the ugly cases: build a world, inject, run, inspect.

The engine never sees the injection — only the traffic it produces. That is the
whole point of `make eval`: it checks that we *found* the thing, not that we were told.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.domain import Injection
from api.engine.incidents import IncidentRecord
from api.runtime import World


@dataclass
class Run:
    world: World
    injections: list[str] = field(default_factory=list)

    @property
    def open(self) -> list[IncidentRecord]:
        return sorted(self.world.detector.open_incidents(),
                      key=lambda r: -r.cost_per_min_usd)

    @property
    def confirmed(self) -> list[IncidentRecord]:
        return [r for r in self.open if r.status == "confirmed"]

    def all_incidents(self, include_seeded: bool = False) -> list[IncidentRecord]:
        return [r for r in self.world.detector.incidents.values()
                if include_seeded or not r.detail.get("seeded")]

    def describe(self) -> str:
        lines = []
        for r in self.open:
            lines.append(f"  [{r.status:9}] {r.kind:15} {r.cause_type or '-':26} "
                         f"scope={r.scope} cost/min=${r.cost_per_min_usd:.0f} "
                         f"conf={r.confidence:.2f} rate={r.observed_rate:.3f}/{r.expected_rate:.3f}")
        return "\n".join(lines) or "  (no open incidents)"


def build(sim_minutes_before: int = 0, seed: int | None = None, origin=None) -> Run:
    from api.config import SEED
    w = World(seed=seed if seed is not None else SEED, origin=origin)
    w.warmup()
    if sim_minutes_before:
        w.run_minutes(sim_minutes_before)
    return Run(world=w)


def inject(run: Run, **kwargs) -> str:
    inj_id, _dup = run.world.inject(Injection(**kwargs))
    run.injections.append(inj_id)
    return inj_id


def advance(run: Run, minutes: int) -> None:
    run.world.run_minutes(minutes)


def matches_scope(rec: IncidentRecord, expected: dict[str, str]) -> bool:
    return all(rec.scope.get(k) == v for k, v in expected.items())


def find(run: Run, *, cause: str | None = None, scope: dict[str, str] | None = None,
         status: tuple[str, ...] = ("watching", "confirmed")) -> IncidentRecord | None:
    for r in sorted(run.world.detector.incidents.values(), key=lambda r: -r.cost_per_min_usd):
        if r.detail.get("seeded"):
            continue
        if r.status not in status:
            continue
        if cause and r.cause_type != cause:
            continue
        if scope and not matches_scope(r, scope):
            continue
        return r
    return None
