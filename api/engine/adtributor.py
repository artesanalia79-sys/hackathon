"""Recursive Adtributor: where, in a six-dimensional cube, does the excess live?

Two numbers per candidate value:
  explanatory power  = share of the incident's excess declines this value carries
  surprise           = how far the value's share of declines moved from its history

Surprise picks the dimension (a dimension can carry excess just by being big;
surprise is what says the *shape* changed). Explanatory power picks the value.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from api.config import EP_BRANCH, EP_THRESHOLD, LIFT_MIN, MAX_DEPTH, N_MIN
from api.domain import DIMENSIONS
from api.engine.expectation import Expector
from api.engine.stats import js_divergence


@dataclass
class Candidate:
    dimension: str
    value: str
    excess: float
    explanatory_power: float
    surprise: float
    operational_attempts: int
    observed_rate: float | None
    expected_rate: float
    expected_share: float = 0.0   # share of the segment's attempts this value carries
    lift: float = 0.0             # explanatory power / expected share

    @property
    def concentrated(self) -> bool:
        """Does this value carry *more* of the excess than its size alone predicts?

        Without this, a single provider outage looks like it is "explained" by the
        biggest merchant, because the biggest merchant carries the most of everything.
        """
        return self.lift >= LIFT_MIN


@dataclass
class Node:
    """One isolated segment plus the trail of decisions that got us there."""
    scope: dict[str, str]
    excess_declines: float
    explanatory_power: float
    depth: int
    path: list[Candidate] = field(default_factory=list)
    stop_reason: str = ""
    considered: list[Candidate] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "scope": self.scope,
            "excess_declines": round(self.excess_declines, 1),
            "explanatory_power": round(self.explanatory_power, 3),
            "depth": self.depth,
            "stop_reason": self.stop_reason,
            "path": [
                {"dimension": c.dimension, "value": c.value,
                 "explanatory_power": round(c.explanatory_power, 3),
                 "surprise": round(c.surprise, 3),
                 "lift": round(c.lift, 2),
                 "expected_share": round(c.expected_share, 3),
                 "observed_rate": round(c.observed_rate, 4) if c.observed_rate is not None else None,
                 "expected_rate": round(c.expected_rate, 4),
                 "operational_attempts": c.operational_attempts}
                for c in self.path
            ],
        }


class Adtributor:
    def __init__(self, expector: Expector, end: datetime, minutes: int) -> None:
        self.ex = expector
        self.end = end
        self.minutes = minutes

    def _candidates(self, scope: dict[str, str], total_excess: float) -> list[Candidate]:
        """Every (dimension, value) inside `scope`, scored."""
        out: list[Candidate] = []
        for dim in DIMENSIONS:
            if dim in scope:
                continue
            values = self.ex.cube.values_of(dim, scope)
            if len(values) < 2:
                continue
            expected_share: dict[str, float] = {}
            observed_share: dict[str, float] = {}
            per_value: dict[str, tuple[float, int, float | None, float]] = {}
            size: dict[str, float] = {}
            for v in values:
                sub = {**scope, dim: v}
                exp = self.ex.expect(sub, self.end, self.minutes)
                obs_declines = exp.observed.operational_attempts - exp.observed.approved
                sea_declines = max(0.0, exp.seasonal.operational_attempts - exp.seasonal.approved)
                expected_share[v] = sea_declines
                observed_share[v] = max(0.0, obs_declines)
                # Size, for lift, is share of *attempts*: one outage dropping a segment by
                # N points produces excess proportional to volume, not to how many declines
                # the segment normally has. Using expected declines instead would make any
                # near-perfect rail (pix at 95.5%) look like a concentration.
                size[v] = float(exp.observed.operational_attempts)
                per_value[v] = (exp.excess_declines, exp.observed.operational_attempts,
                                exp.observed.rate, exp.p0)
            surprise = js_divergence(expected_share, observed_share)
            size_total = sum(size.values())
            for v in values:
                excess, n, obs_rate, p0 = per_value[v]
                ep = (excess / total_excess) if total_excess > 0 else 0.0
                exp_share = (size[v] / size_total) if size_total > 0 else 0.0
                out.append(Candidate(
                    dimension=dim, value=v, excess=excess, explanatory_power=ep,
                    surprise=surprise, operational_attempts=n,
                    observed_rate=obs_rate, expected_rate=p0,
                    expected_share=exp_share,
                    lift=(ep / exp_share) if exp_share > 1e-6 else (0.0 if ep <= 0 else 99.0),
                ))
        return out

    def _overlap_excess(self, scope: dict[str, str], a: Candidate, b: Candidate) -> float:
        """Excess that candidates a and b both claim — used to see past double counting."""
        if a.dimension == b.dimension:
            return 0.0 if a.value != b.value else min(a.excess, b.excess)
        sub = {**scope, a.dimension: a.value, b.dimension: b.value}
        return self.ex.expect(sub, self.end, self.minutes).excess_declines

    def run(self, root_scope: dict[str, str]) -> list[Node]:
        root = self.ex.expect(root_scope, self.end, self.minutes)
        nodes: list[Node] = []
        self._descend(dict(root_scope), root.excess_declines, root.excess_declines,
                      depth=0, path=[], out=nodes)
        if not nodes:
            nodes.append(Node(scope=dict(root_scope), excess_declines=root.excess_declines,
                              explanatory_power=1.0, depth=0, stop_reason="no_signal"))
        nodes.sort(key=lambda n: n.excess_declines, reverse=True)
        return nodes

    def _descend(self, scope: dict[str, str], excess: float, root_excess: float,
                 depth: int, path: list[Candidate], out: list[Node]) -> None:
        ep = (excess / root_excess) if root_excess > 0 else 0.0
        here = self.ex.expect(scope, self.end, self.minutes)

        def stop(reason: str) -> None:
            out.append(Node(scope=dict(scope), excess_declines=excess, explanatory_power=ep,
                            depth=depth, path=list(path), stop_reason=reason))

        if depth >= MAX_DEPTH:
            return stop("max_depth")
        if here.observed.operational_attempts < N_MIN:
            return stop("below_min_sample")
        if excess <= 0:
            return stop("no_excess")

        candidates = self._candidates(scope, excess)
        if not candidates:
            return stop("no_further_dimensions")
        candidates.sort(key=lambda c: (c.explanatory_power, c.surprise), reverse=True)

        # Primary: the most surprising dimension whose leading value both carries the
        # excess (explanatory power) and carries more of it than its size predicts (lift).
        primary: Candidate | None = None
        by_surprise = sorted({c.dimension for c in candidates},
                             key=lambda d: -max(c.surprise for c in candidates if c.dimension == d))
        for dim in by_surprise:
            top = max((c for c in candidates if c.dimension == dim),
                      key=lambda c: c.explanatory_power)
            if (top.explanatory_power >= EP_THRESHOLD and top.concentrated
                    and top.operational_attempts >= N_MIN):
                primary = top
                break

        if primary is None:
            # Nothing dominates. Either two independent stories are running at once,
            # or the excess is genuinely spread and there is nothing left to isolate.
            viable = [c for c in candidates
                      if c.explanatory_power >= EP_BRANCH and c.concentrated
                      and c.operational_attempts >= N_MIN]
            viable.sort(key=lambda c: c.explanatory_power, reverse=True)
            if len(viable) < 2:
                return stop("excess_spread_evenly")
            primary = viable[0]

        branches: list[Candidate] = [primary]
        # A second story hiding under the first: keep only the excess it does not share
        # with the primary, so one incident does not get reported twice.
        for cand in candidates:
            if len(branches) >= 3:
                break
            if cand.dimension == primary.dimension and cand.value == primary.value:
                continue
            if cand.operational_attempts < N_MIN or not cand.concentrated:
                continue
            residual = cand.excess - self._overlap_excess(scope, primary, cand)
            if root_excess > 0 and (residual / root_excess) >= EP_BRANCH:
                branches.append(cand)

        for cand in branches:
            sub_scope = {**scope, cand.dimension: cand.value}
            sub = self.ex.expect(sub_scope, self.end, self.minutes)
            self._descend(sub_scope, sub.excess_declines, root_excess,
                          depth + 1, path + [cand], out)
