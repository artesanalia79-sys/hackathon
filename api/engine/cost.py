"""Money. An incident that cannot be priced cannot be ranked."""
from __future__ import annotations

from api.config import RECOVERABILITY
from api.engine.cube import Agg


def excess_by_category(observed: Agg, seasonal: Agg) -> dict[str, float]:
    """Declines per category above what history says this segment normally produces.

    Scaled to the observed volume, so a quiet hour is not read as an improvement.
    """
    obs_n = observed.attempts
    sea_n = seasonal.attempts
    if obs_n <= 0 or sea_n <= 0:
        return {}
    out: dict[str, float] = {}
    for cat, count in observed.by_category.items():
        if cat == "none" or count <= 0:
            continue
        expected = seasonal.by_category.get(cat, 0.0) * (obs_n / sea_n)
        delta = count - expected
        if delta > 0:
            out[cat] = delta
    return out


def cost_per_minute(observed: Agg, seasonal: Agg, excess_declines: float,
                    window_minutes: int) -> tuple[float, dict[str, float]]:
    """USD per minute, weighted by how recoverable each kind of decline actually is.

    A hard decline costs almost nothing (that sale was never going to happen);
    a technical one costs nearly the whole ticket.
    """
    ticket = observed.avg_ticket
    by_cat = excess_by_category(observed, seasonal)
    total_excess_cat = sum(by_cat.values())
    if total_excess_cat <= 0 or ticket <= 0 or window_minutes <= 0:
        # Fall back to the detector's excess at an average recoverability.
        cost = excess_declines * ticket * (1 - RECOVERABILITY["soft_decline"]) / max(1, window_minutes)
        return max(0.0, cost), {}

    # Attribute the detector's excess proportionally to the categories that actually rose.
    scale = excess_declines / total_excess_cat if total_excess_cat > 0 else 0.0
    breakdown: dict[str, float] = {}
    total = 0.0
    for cat, delta in by_cat.items():
        weighted = delta * scale
        value = weighted * ticket * (1.0 - RECOVERABILITY.get(cat, 0.2))
        breakdown[cat] = round(value / window_minutes, 2)
        total += value
    return total / window_minutes, breakdown
