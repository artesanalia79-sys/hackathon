"""The counter cube: a rolling per-minute window plus the seasonal baseline.

One read path. The detector, the attributor and the agent's tools all query this
object, so what the agent sees is exactly what the engine decided on.

Baseline note (differs from a naive reading of ARCHITECTURE.md): history is stored
pre-aggregated by (day-of-week, hour, leaf) instead of as 3 weeks of raw minutes.
It is the same sum the spec asks for — "sum the leaf counters that match the filter
over the same hour x weekday" — computed once at boot instead of on every query.
57k rows instead of 10M, identical semantics.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from api.domain import CATEGORIES, DIMENSIONS, HARD_CATEGORIES
from api.sim.catalog import leaf_cuboids, leaf_key

LeafKey = tuple[str, str, str, str, str, str]

WINDOW_MINUTES = 260  # keep ~4h of live minutes in memory


@dataclass
class LeafMinute:
    attempts: int = 0
    approved: int = 0
    hard_declines: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_raw_code: dict[str, int] = field(default_factory=dict)
    raw_status_mismatch: int = 0
    amount_sum: float = 0.0
    latency_sum: float = 0.0
    latency_p95: int = 0


@dataclass
class Agg:
    """An aggregate over a scope and a time window, in the shape the engine reasons about."""
    scope: dict[str, str] = field(default_factory=dict)
    attempts: int = 0
    approved: int = 0
    hard_declines: int = 0
    by_category: dict[str, int] = field(default_factory=lambda: {c: 0 for c in CATEGORIES})
    by_raw_code: dict[str, int] = field(default_factory=dict)
    raw_status_mismatch: int = 0
    amount_sum: float = 0.0
    latency_weighted: float = 0.0
    latency_p95: int = 0

    @property
    def operational_attempts(self) -> int:
        """Attempts that our conversion rate is actually accountable for."""
        return max(0, self.attempts - self.hard_declines)

    @property
    def rate(self) -> float | None:
        n = self.operational_attempts
        return (self.approved / n) if n > 0 else None

    @property
    def avg_ticket(self) -> float:
        return (self.amount_sum / self.attempts) if self.attempts > 0 else 0.0

    @property
    def avg_latency(self) -> float:
        return (self.latency_weighted / self.attempts) if self.attempts > 0 else 0.0

    def category_shares(self) -> dict[str, float]:
        """The signature: share of *outcomes* per category, approvals included."""
        total = self.attempts
        if total <= 0:
            return {c: 0.0 for c in CATEGORIES}
        shares = {c: self.by_category.get(c, 0) / total for c in CATEGORIES}
        shares["none"] = self.approved / total
        return shares

    def merge(self, other: Agg) -> None:
        self.attempts += other.attempts
        self.approved += other.approved
        self.hard_declines += other.hard_declines
        for c, v in other.by_category.items():
            self.by_category[c] = self.by_category.get(c, 0) + v
        for c, v in other.by_raw_code.items():
            self.by_raw_code[c] = self.by_raw_code.get(c, 0) + v
        self.raw_status_mismatch += other.raw_status_mismatch
        self.amount_sum += other.amount_sum
        self.latency_weighted += other.latency_weighted
        self.latency_p95 = max(self.latency_p95, other.latency_p95)


class Cube:
    def __init__(self) -> None:
        self.leaves: list[dict[str, str]] = leaf_cuboids()
        self.leaf_keys: list[LeafKey] = [leaf_key(le) for le in self.leaves]
        self.leaf_by_key: dict[LeafKey, dict[str, str]] = dict(zip(self.leaf_keys, self.leaves))
        # dimension -> value -> set of leaf keys, so scope filtering is a set intersection
        self.index: dict[str, dict[str, set[LeafKey]]] = {d: defaultdict(set) for d in DIMENSIONS}
        for lk, le in zip(self.leaf_keys, self.leaves):
            for d in DIMENSIONS:
                self.index[d][le[d]].add(lk)
        self._all: set[LeafKey] = set(self.leaf_keys)

        self.minutes: deque[datetime] = deque()
        self.live: dict[datetime, dict[LeafKey, LeafMinute]] = {}
        # (dow, hour) -> leaf -> LeafMinute, already averaged to a per-minute rate
        self.baseline: dict[tuple[int, int], dict[LeafKey, LeafMinute]] = {}
        # Pre-summed rollups for the global total and every single-dimension slice.
        # These are the scopes the detector hammers every minute (and the 2h EWMA
        # window especially), so summing 342 leaves x 120 minutes for each of them
        # is the difference between a 95 ms tick and a 5 ms one.
        self.roll_live: dict[datetime, dict[tuple[str, str], LeafMinute]] = {}
        self.roll_base: dict[tuple[int, int], dict[tuple[str, str], LeafMinute]] = {}

    GLOBAL: tuple[str, str] = ("", "")

    def _rollup(self, rows: dict[LeafKey, LeafMinute]) -> dict[tuple[str, str], LeafMinute]:
        out: dict[tuple[str, str], LeafMinute] = {}

        def bucket(key: tuple[str, str]) -> LeafMinute:
            hit = out.get(key)
            if hit is None:
                hit = LeafMinute(by_category={}, by_raw_code={})
                out[key] = hit
            return hit

        for lk, r in rows.items():
            leaf = self.leaf_by_key.get(lk)
            if leaf is None:
                continue
            targets = [bucket(self.GLOBAL)]
            for d in DIMENSIONS:
                v = leaf[d]
                if v:
                    targets.append(bucket((d, v)))
            for b in targets:
                b.attempts += r.attempts
                b.approved += r.approved
                b.hard_declines += r.hard_declines
                for c, v in r.by_category.items():
                    if v:
                        b.by_category[c] = b.by_category.get(c, 0) + v
                b.raw_status_mismatch += r.raw_status_mismatch
                b.amount_sum += r.amount_sum
                b.latency_sum += r.latency_sum
                b.latency_p95 = max(b.latency_p95, r.latency_p95)
        return out

    @staticmethod
    def _roll_key(scope: dict[str, str]) -> tuple[str, str] | None:
        """A scope is rollup-answerable when it pins at most one dimension."""
        if not scope:
            return Cube.GLOBAL
        if len(scope) == 1:
            dim, val = next(iter(scope.items()))
            if dim in DIMENSIONS and val:
                return (dim, val)
        return None

    # --- writes ------------------------------------------------------------
    def put_minute(self, minute: datetime, rows: dict[LeafKey, LeafMinute]) -> None:
        self.live[minute] = rows
        self.roll_live[minute] = self._rollup(rows)
        self.minutes.append(minute)
        while len(self.minutes) > WINDOW_MINUTES:
            old = self.minutes.popleft()
            self.live.pop(old, None)
            self.roll_live.pop(old, None)

    def set_baseline(self, baseline: dict[tuple[int, int], dict[LeafKey, LeafMinute]]) -> None:
        self.baseline = baseline
        self.roll_base = {slot: self._rollup(rows) for slot, rows in baseline.items()}

    def clear_live(self) -> None:
        self.minutes.clear()
        self.live.clear()
        self.roll_live.clear()

    # --- scope resolution --------------------------------------------------
    def matching_leaves(self, scope: dict[str, str]) -> set[LeafKey]:
        """Leaf keys under a scope. Missing dimension = any; unknown value = empty set."""
        result: set[LeafKey] | None = None
        for dim, val in scope.items():
            if dim not in self.index:
                return set()
            candidates = self.index[dim].get(val, set())
            result = set(candidates) if result is None else (result & candidates)
            if not result:
                return set()
        return set(self._all) if result is None else result

    def values_of(self, dimension: str, scope: dict[str, str]) -> list[str]:
        """Distinct values a dimension takes inside a scope (blank = not applicable)."""
        leaves = self.matching_leaves(scope)
        vals = {self.leaf_by_key[lk][dimension] for lk in leaves}
        return sorted(v for v in vals if v)

    # --- reads -------------------------------------------------------------
    def window_minutes(self, end: datetime, minutes: int) -> list[datetime]:
        start = end - timedelta(minutes=minutes - 1)
        return [m for m in self.minutes if start <= m <= end]

    def aggregate(self, scope: dict[str, str], end: datetime, minutes: int,
                  full: bool = False) -> Agg:
        """`full=True` forces the leaf path, which is the only one carrying raw codes."""
        agg = Agg(scope=dict(scope))
        rk = None if full else self._roll_key(scope)
        if rk is not None:
            for m in self.window_minutes(end, minutes):
                r = self.roll_live.get(m, {}).get(rk)
                if r is None:
                    continue
                agg.attempts += r.attempts
                agg.approved += r.approved
                agg.hard_declines += r.hard_declines
                for c, v in r.by_category.items():
                    agg.by_category[c] = agg.by_category.get(c, 0) + v
                agg.raw_status_mismatch += r.raw_status_mismatch
                agg.amount_sum += r.amount_sum
                agg.latency_weighted += r.latency_sum
                agg.latency_p95 = max(agg.latency_p95, r.latency_p95)
            return agg
        leaves = self.matching_leaves(scope)
        if not leaves:
            return agg
        for m in self.window_minutes(end, minutes):
            rows = self.live.get(m)
            if not rows:
                continue
            # Iterate the smaller of the two collections.
            if len(leaves) < len(rows):
                items = ((lk, rows[lk]) for lk in leaves if lk in rows)
            else:
                items = ((lk, r) for lk, r in rows.items() if lk in leaves)
            for _lk, r in items:
                agg.attempts += r.attempts
                agg.approved += r.approved
                agg.hard_declines += r.hard_declines
                for c, v in r.by_category.items():
                    agg.by_category[c] = agg.by_category.get(c, 0) + v
                for c, v in r.by_raw_code.items():
                    agg.by_raw_code[c] = agg.by_raw_code.get(c, 0) + v
                agg.raw_status_mismatch += r.raw_status_mismatch
                agg.amount_sum += r.amount_sum
                agg.latency_weighted += r.latency_sum
                agg.latency_p95 = max(agg.latency_p95, r.latency_p95)
        return agg

    def seasonal(self, scope: dict[str, str], end: datetime, minutes: int) -> Agg:
        """The same window, but drawn from history: same weekday, same hours."""
        agg = Agg(scope=dict(scope))
        if not self.baseline:
            return agg
        rk = self._roll_key(scope)
        if rk is not None:
            for i in range(minutes):
                t = end - timedelta(minutes=i)
                r = self.roll_base.get((t.weekday(), t.hour), {}).get(rk)
                if r is None:
                    continue
                agg.attempts += r.attempts
                agg.approved += r.approved
                agg.hard_declines += r.hard_declines
                for c, v in r.by_category.items():
                    agg.by_category[c] = agg.by_category.get(c, 0) + v
                agg.amount_sum += r.amount_sum
                agg.latency_weighted += r.latency_sum
                agg.latency_p95 = max(agg.latency_p95, r.latency_p95)
            return agg
        leaves = self.matching_leaves(scope)
        if not leaves:
            return agg
        for i in range(minutes):
            t = end - timedelta(minutes=i)
            slot = self.baseline.get((t.weekday(), t.hour))
            if not slot:
                continue
            for lk in leaves:
                r = slot.get(lk)
                if r is None:
                    continue
                agg.attempts += r.attempts
                agg.approved += r.approved
                agg.hard_declines += r.hard_declines
                for c, v in r.by_category.items():
                    agg.by_category[c] = agg.by_category.get(c, 0) + v
                agg.amount_sum += r.amount_sum
                agg.latency_weighted += r.latency_sum
                agg.latency_p95 = max(agg.latency_p95, r.latency_p95)
        return agg

    def split(self, scope: dict[str, str], dimension: str, end: datetime,
              minutes: int) -> dict[str, Agg]:
        """Aggregate the same window once per value of `dimension` inside `scope`."""
        out: dict[str, Agg] = {}
        for val in self.values_of(dimension, scope):
            out[val] = self.aggregate({**scope, dimension: val}, end, minutes)
        return out

    def seasonal_split(self, scope: dict[str, str], dimension: str, end: datetime,
                       minutes: int) -> dict[str, Agg]:
        out: dict[str, Agg] = {}
        for val in self.values_of(dimension, scope):
            out[val] = self.seasonal({**scope, dimension: val}, end, minutes)
        return out

    def series(self, scope: dict[str, str], end: datetime, minutes: int) -> list[dict]:
        """Per-minute rate series for charts."""
        leaves = self.matching_leaves(scope)
        points = []
        for m in self.window_minutes(end, minutes):
            rows = self.live.get(m, {})
            att = app = hard = 0
            for lk in leaves:
                r = rows.get(lk)
                if r is None:
                    continue
                att += r.attempts
                app += r.approved
                hard += r.hard_declines
            op = max(0, att - hard)
            points.append({"minute": m.isoformat(), "attempts": att, "approved": app,
                           "rate": (app / op) if op else None})
        return points

    @staticmethod
    def hard_declines_from(by_category: dict[str, int]) -> int:
        return sum(v for c, v in by_category.items() if c in HARD_CATEGORIES)


def agg_to_json(agg: Agg) -> dict:
    return {
        "scope": agg.scope, "attempts": agg.attempts,
        "operational_attempts": agg.operational_attempts, "approved": agg.approved,
        "hard_declines": agg.hard_declines,
        "rate": round(agg.rate, 4) if agg.rate is not None else None,
        "by_category": {k: v for k, v in agg.by_category.items() if v},
        "avg_ticket_usd": round(agg.avg_ticket, 2),
        "raw_status_mismatch": agg.raw_status_mismatch,
    }


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)
