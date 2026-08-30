"""The judges' surface: inject, reset, and everything needed to build the form."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.config import SIM_SPEEDS
from api.domain import Injection
from api.runtime import get_world
from api.sim import catalog as cat

router = APIRouter(tags=["control"])


@router.get("/catalog")
def catalog() -> dict:
    """Every valid value per dimension, so the form can never offer an impossible scope."""
    w = get_world()
    return {
        "dimensions": {
            "merchant": [{"id": m, "name": v["name"]} for m, v in cat.MERCHANTS.items()],
            "country": list(cat.METHODS_BY_COUNTRY),
            "method": sorted({m for ms in cat.METHODS_BY_COUNTRY.values() for m in ms}),
            "brand": cat.BRANDS,
            "issuer": {c: iss for c, iss in cat.ISSUERS_BY_COUNTRY.items()},
            "provider": sorted(cat.PROVIDER_CODES),
        },
        "methods_by_country": cat.METHODS_BY_COUNTRY,
        "providers_by_method": {f"{c}|{m}": p for (c, m), p in cat.PROVIDERS_BY_METHOD.items()},
        "injection_types": [
            {"id": "provider_degraded", "label": "Provider degraded",
             "hint": "technical declines rise inside the scope"},
            {"id": "issuer_over_declining", "label": "Issuer over-declining",
             "hint": "soft declines rise; scope an issuer, optionally a provider too"},
            {"id": "method_down", "label": "Payment method down",
             "hint": "a rail fails in a country"},
            {"id": "network_degraded", "label": "Card network degraded",
             "hint": "scope a brand; it will hit every provider and issuer"},
            {"id": "mapping_bug", "label": "Mapping bug (internal)",
             "hint": "we record approvals the provider never sent; severity = share mis-mapped"},
            {"id": "routing_change", "label": "Routing / config change (internal)",
             "hint": "config declines rise and a change event is emitted"},
            {"id": "unknown_code", "label": "Unseen provider code",
             "hint": "a raw code we do not map starts arriving"},
            {"id": "latency_spike", "label": "Latency spike",
             "hint": "slower, but not declining more"},
            {"id": "hard_decline_spike", "label": "Hard-decline spike",
             "hint": "insufficient funds; must NOT open an incident"},
            {"id": "merchant_outage", "label": "Merchant stops sending traffic",
             "hint": "volume goes to zero; not a conversion problem"},
        ],
        "now": w.now.isoformat(),
    }


@router.post("/inject")
def inject(injection: Injection) -> dict:
    """Any subset of dimensions is valid. Nothing here names an incident."""
    w = get_world()
    injection_id, duplicate = w.inject(injection)
    return {"injection_id": injection_id, "duplicate": duplicate,
            "applied_at": w.now.isoformat(), "injection": injection.model_dump(mode="json")}


@router.get("/speed")
def get_speed() -> dict:
    w = get_world()
    return {"sim_speed": w.sim_speed, "options": list(SIM_SPEEDS)}


@router.post("/speed")
def set_speed(value: float) -> dict:
    """Change how fast simulated time runs. 0 pauses the world without stopping anything.

    Detection windows are measured in simulated minutes, so slowing the clock down changes
    nothing about what the engine concludes — only how long you get to watch it happen.
    """
    if value not in SIM_SPEEDS:
        raise HTTPException(400, f"speed must be one of {list(SIM_SPEEDS)}")
    w = get_world()
    return {"sim_speed": w.set_speed(value), "options": list(SIM_SPEEDS)}


@router.post("/injections/{injection_id}/stop")
def stop_injection(injection_id: str) -> dict:
    """End one injection, leaving the rest alone — the way to watch an incident recover."""
    w = get_world()
    if not w.stop_injection(injection_id):
        raise HTTPException(404, "no such active injection")
    return {"ok": True, "stopped": injection_id, "now": w.now.isoformat()}


@router.get("/injections")
def injections() -> dict:
    """Ground truth. The engine never reads this; it exists so a judge can check us."""
    w = get_world()
    return {"now": w.now.isoformat(),
            "active": w.injector.ground_truth(w.now),
            "all": [a.model_dump(mode="json") for a in w.injector.all()]}


@router.post("/reset")
async def reset() -> dict:
    w = get_world()
    await w.reset_async()
    return {"ok": True, "now": w.now.isoformat()}


@router.get("/change-events")
def change_events() -> dict:
    w = get_world()
    return {"events": [e.model_dump(mode="json") for e in w.detector.change_events]}


@router.get("/transactions")
def transactions(limit: int = 40) -> dict:
    """A live sample of real rows, including what the provider actually said.

    The `raw_status` vs `status` columns are the point: that is where a mapping bug
    becomes visible to a human.
    """
    w = get_world()
    rows = [t.model_dump(mode="json") for t in list(w.recent_tx)[:max(1, min(200, limit))]]
    return {"transactions": rows}
