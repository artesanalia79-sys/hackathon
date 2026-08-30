"""What we should be seeing right now, for an arbitrary segment.

p0 = 0.7 * seasonal(same weekday & hour) + 0.3 * EWMA(recent live traffic).

The EWMA window deliberately *excludes* the window under test: if the current dip
fed the expectation, the expectation would chase the dip and the detector would go
blind exactly when it matters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from api.config import EWMA_HOURS, SEASONAL_WEIGHT
from api.engine.cube import Agg, Cube


@dataclass
class Expectation:
    p0: float
    seasonal_rate: float | None
    ewma_rate: float | None
    expected_approved: float
    excess_declines: float
    observed: Agg
    seasonal: Agg

    @property
    def observed_rate(self) -> float | None:
        return self.observed.rate


class Expector:
    """Caches aggregates within a single evaluation pass — attribution asks a lot."""

    def __init__(self, cube: Cube,
                 frozen_ewma: list[tuple[tuple, float]] | None = None) -> None:
        self.cube = cube
        self._obs: dict[tuple, Agg] = {}
        self._sea: dict[tuple, Agg] = {}
        # (scope items, rate) for scopes covered by an open incident. Most specific first,
        # so a scope inside two open incidents takes the narrower one's baseline.
        self._frozen = sorted(frozen_ewma or [], key=lambda f: -len(f[0]))

    @staticmethod
    def _key(scope: dict[str, str], end: datetime, minutes: int) -> tuple:
        return (tuple(sorted(scope.items())), end, minutes)

    def observed(self, scope: dict[str, str], end: datetime, minutes: int,
                 full: bool = False) -> Agg:
        k = self._key(scope, end, minutes) + (full,)
        hit = self._obs.get(k)
        if hit is None:
            hit = self.cube.aggregate(scope, end, minutes, full=full)
            self._obs[k] = hit
        return hit

    def seasonal(self, scope: dict[str, str], end: datetime, minutes: int) -> Agg:
        k = self._key(scope, end, minutes)
        hit = self._sea.get(k)
        if hit is None:
            hit = self.cube.seasonal(scope, end, minutes)
            self._sea[k] = hit
        return hit

    def ewma_rate(self, scope: dict[str, str], end: datetime, exclude_minutes: int) -> float | None:
        """Recent healthy level, measured strictly before the window under test.

        While an incident is open on this scope the value is held at what it was when
        the incident started. Left free, the 2-hour window swallows the incident itself:
        the expectation walks down onto the failure, the measured excess shrinks, and the
        money on the card falls without anything getting better. Measured over five
        simulated hours on an unchanged injection, $/min drifted down 41%.
        """
        for items, rate in self._frozen:
            if all(scope.get(k) == v for k, v in items):
                return rate
        cutoff = end - timedelta(minutes=exclude_minutes)
        agg = self.observed(scope, cutoff, EWMA_HOURS * 60)
        return agg.rate

    def expect(self, scope: dict[str, str], end: datetime, minutes: int) -> Expectation:
        obs = self.observed(scope, end, minutes)
        sea = self.seasonal(scope, end, minutes)
        seasonal_rate = sea.rate
        ewma = self.ewma_rate(scope, end, minutes)

        if seasonal_rate is None and ewma is None:
            p0 = obs.rate if obs.rate is not None else 0.0
        elif ewma is None:
            p0 = seasonal_rate  # type: ignore[assignment]
        elif seasonal_rate is None:
            p0 = ewma
        else:
            p0 = SEASONAL_WEIGHT * seasonal_rate + (1 - SEASONAL_WEIGHT) * ewma
        p0 = min(0.9995, max(0.0, p0))

        n = obs.operational_attempts
        expected_approved = p0 * n
        excess = max(0.0, expected_approved - obs.approved)
        return Expectation(p0=p0, seasonal_rate=seasonal_rate, ewma_rate=ewma,
                           expected_approved=expected_approved, excess_declines=excess,
                           observed=obs, seasonal=sea)
