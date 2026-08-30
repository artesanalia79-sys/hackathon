"""The ugly cases from docs/UGLY_CASES.md, as executable checks.

Each case builds a world, perturbs it, lets it run, and asserts on what the engine
concluded. The engine is never told what was injected.

A case returns (status, detail): "pass", "degraded" (safe but not the full answer,
e.g. it said insufficient evidence when it could have named the cause), or "fail".
"""
from __future__ import annotations

from datetime import datetime

from eval.harness import Run, advance, build, find, inject

Result = tuple[str, str]
PASS, DEGRADED, FAIL = "pass", "degraded", "fail"

SATURDAY = datetime(2026, 8, 29, 14, 0, 0)


def _summary(run: Run) -> str:
    rows = [f"{r.cause_type}@{r.scope}(${r.cost_per_min_usd:.0f}/min,{r.status})" for r in run.open]
    return "; ".join(rows) or "no open incidents"


def case_01_quiet() -> Result:
    """Normal traffic for 30 minutes, night included: nothing should fire."""
    run = build()
    advance(run, 30)
    n = len(run.open)
    return (PASS, "0 incidents in 30 quiet minutes") if n == 0 else (FAIL, f"opened {n}: {_summary(run)}")


def case_02_weekend() -> Result:
    """Saturday traffic is ~40% lighter; the seasonal baseline must absorb it."""
    run = build(origin=SATURDAY)
    advance(run, 30)
    n = len(run.open)
    return (PASS, "0 incidents on a Saturday") if n == 0 else (FAIL, f"opened {n}: {_summary(run)}")


def case_03_provider_country() -> Result:
    """dLocal over-declining only in Brazil."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"}, severity=0.35)
    advance(run, 20)
    r = find(run, cause="provider_degraded", scope={"provider": "dlocal", "country": "BR"})
    if not r:
        return FAIL, f"not isolated: {_summary(run)}"
    extra = set(r.scope) - {"provider", "country"}
    if extra:
        return DEGRADED, f"isolated but over-specified with {extra}: {r.scope}"
    return PASS, f"{r.scope} cause={r.cause_type} status={r.status} ${r.cost_per_min_usd:.0f}/min"


def case_04_two_at_once() -> Result:
    """A Brazilian provider outage and a Mexican issuer, at the same time, ranked."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"}, severity=0.35)
    inject(run, type="issuer_over_declining", scope={"issuer": "banorte"}, severity=0.30)
    advance(run, 20)
    a = find(run, cause="provider_degraded", scope={"provider": "dlocal"})
    b = find(run, scope={"issuer": "banorte"})
    if not a or not b:
        return FAIL, f"only found {'provider' if a else ''}{'issuer' if b else ''}: {_summary(run)}"
    if a.id == b.id:
        return FAIL, "the two stories collapsed into one incident"
    ranked = [r.id for r in run.open]
    order_ok = ranked.index(a.id) < ranked.index(b.id) if a.cost_per_min_usd > b.cost_per_min_usd else True
    detail = (f"{a.scope} ${a.cost_per_min_usd:.0f}/min + {b.scope} "
              f"({b.cause_type}) ${b.cost_per_min_usd:.0f}/min")
    return (PASS, detail) if order_ok else (DEGRADED, "separated but mis-ranked: " + detail)


def case_05_small_sample() -> Result:
    """A drop in a segment too small to judge: watch, do not claim."""
    run = build(5)
    inject(run, type="provider_degraded",
           scope={"merchant": "m_viajesya", "country": "MX", "method": "codi"}, severity=0.5)
    advance(run, 12)
    wrong = [r for r in run.open if r.cause_type not in (None, "insufficient_evidence")
             and r.confidence >= 0.7 and "codi" not in r.scope.values()]
    if wrong:
        return FAIL, f"invented a cause elsewhere: {_summary(run)}"
    return PASS, f"no over-claim on a sub-threshold segment ({len(run.open)} open, all low-confidence)"


def case_06_hard_declines() -> Result:
    """A spike of insufficient-funds must not move the operational rate."""
    run = build(5)
    inject(run, type="hard_decline_spike", scope={"country": "CO"}, severity=0.25)
    advance(run, 20)
    bad = [r for r in run.open if r.kind == "conversion_drop"]
    if bad:
        return FAIL, f"fired on hard declines: {_summary(run)}"
    return PASS, "hard declines excluded from the operational rate; nothing fired"


def case_07_mapping_bug() -> Result:
    """The provider said REJECTED and we stored `approved`."""
    run = build(5)
    inject(run, type="mapping_bug", scope={"provider": "dlocal"}, severity=0.35)
    advance(run, 15)
    r = find(run, cause="mapping_bug")
    if not r:
        return FAIL, f"missed the mapping bug: {_summary(run)}"
    if not r.related_change_event_ids:
        return DEGRADED, f"found {r.scope} but did not correlate the change event"
    return PASS, f"{r.scope} kind={r.kind} mismatch={r.detail.get('mismatch_rate')} +change event"


def case_08_unknown_code() -> Result:
    """A provider code we have never seen must land in `unknown` and be flagged."""
    run = build(5)
    inject(run, type="unknown_code", scope={"provider": "adyen"}, severity=0.4)
    advance(run, 15)
    r = find(run, cause="unmapped_provider_code")
    if not r:
        alt = find(run, scope={"provider": "adyen"})
        return (DEGRADED, f"flagged as {alt.cause_type} instead of unmapped code") if alt else \
               (FAIL, f"missed it: {_summary(run)}")
    codes = r.signature_json.get("unmapped_codes") or r.signature_json.get("top_raw_codes")
    return PASS, f"{r.scope} unknown_share={r.signature_json.get('unknown_share')} codes={codes}"


def case_09_routing_config() -> Result:
    """Stripe pointed at Colombia starts returning country_not_supported."""
    run = build(5)
    inject(run, type="routing_change", scope={"provider": "stripe", "country": "CO"}, severity=0.4)
    advance(run, 18)
    r = find(run, cause="internal_change")
    if not r:
        alt = find(run, scope={"provider": "stripe", "country": "CO"})
        return (DEGRADED, f"found the segment but called it {alt.cause_type}") if alt else \
               (FAIL, f"missed it: {_summary(run)}")
    if not r.related_change_event_ids:
        return DEGRADED, f"{r.scope} classified internal but no change event correlated"
    return PASS, f"{r.scope} internal change, {len(r.related_change_event_ids)} event(s) correlated"


def case_10_network() -> Result:
    """Visa degraded across every issuer and provider: blame the brand, not a provider."""
    run = build(5)
    inject(run, type="network_degraded", scope={"brand": "visa"}, severity=0.30)
    advance(run, 20)
    r = find(run, scope={"brand": "visa"})
    if not r:
        return FAIL, f"did not isolate the brand: {_summary(run)}"
    if "provider" in r.scope:
        return FAIL, f"blamed a provider: {r.scope}"
    if r.cause_type != "network_degraded":
        return DEGRADED, f"isolated brand=visa but called it {r.cause_type}"
    return PASS, f"{r.scope} cause=network_degraded"


def case_11_issuer_all_providers() -> Result:
    """One issuer declining through every provider is the issuer's doing."""
    run = build(5)
    inject(run, type="issuer_over_declining", scope={"issuer": "itau"}, severity=0.35)
    advance(run, 20)
    r = find(run, scope={"issuer": "itau"})
    if not r:
        return FAIL, f"did not isolate the issuer: {_summary(run)}"
    if "provider" in r.scope:
        return FAIL, f"blamed a provider: {r.scope}"
    if r.cause_type != "issuer_over_declining":
        return DEGRADED, f"isolated issuer=itau but called it {r.cause_type}"
    return PASS, f"{r.scope} cause=issuer_over_declining"


def case_12_issuer_one_provider() -> Result:
    """The same issuer failing through one provider only is a routing problem."""
    run = build(5)
    inject(run, type="issuer_over_declining", scope={"issuer": "itau", "provider": "adyen"},
           severity=0.45)
    advance(run, 20)
    r = find(run, scope={"issuer": "itau", "provider": "adyen"})
    if not r:
        return FAIL, f"did not isolate the pair: {_summary(run)}"
    if r.cause_type != "issuer_provider_routing":
        return DEGRADED, f"isolated {r.scope} but called it {r.cause_type}"
    return PASS, f"{r.scope} cause=issuer_provider_routing"


def case_13_method_down() -> Result:
    """PIX down in Brazil: no issuer or brand exists to blame."""
    run = build(5)
    inject(run, type="method_down", scope={"method": "pix", "country": "BR"}, severity=0.45)
    advance(run, 18)
    r = find(run, scope={"method": "pix"})
    if not r:
        return FAIL, f"did not isolate the method: {_summary(run)}"
    if r.scope.get("issuer") or r.scope.get("brand"):
        return FAIL, f"invented a card dimension for an APM: {r.scope}"
    if r.cause_type != "method_down":
        return DEGRADED, f"isolated {r.scope} but called it {r.cause_type}"
    return PASS, f"{r.scope} cause=method_down"


def case_14_ramp() -> Result:
    """A 20-minute ramp, not a cliff: `since` should point at the start of the ramp."""
    run = build(5)
    start = run.world.now
    inject(run, type="provider_degraded", scope={"provider": "mercadopago"}, severity=0.35,
           ramp_minutes=20)
    advance(run, 35)
    r = find(run, scope={"provider": "mercadopago"})
    if not r:
        return FAIL, f"missed the gradual degradation: {_summary(run)}"
    drift = abs((r.started_at - start).total_seconds() / 60.0)
    if drift > 12:
        return DEGRADED, f"detected but `since` is {drift:.0f} min off the ramp start"
    return PASS, f"{r.scope} since is {drift:.0f} min from ramp start"


def case_15_self_resolves() -> Result:
    """An incident that ends must close, with its duration and cost recorded."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "adyen", "country": "MX"},
           severity=0.40, duration_minutes=12)
    advance(run, 45)
    resolved = [r for r in run.all_incidents() if r.status == "resolved"]
    if not resolved:
        still = [r for r in run.all_incidents() if r.status in ("watching", "confirmed")]
        return FAIL, f"nothing resolved; {len(still)} still open: {_summary(run)}"
    r = resolved[0]
    return PASS, f"{r.scope} resolved after {r.duration_min:.0f} min, ${r.cost_usd:.0f} total"


def case_16_memory() -> Result:
    """A fingerprint we have seen before should surface the earlier incident."""
    from api.engine.memory import find_similar_incidents
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"}, severity=0.35)
    advance(run, 20)
    r = find(run, scope={"provider": "dlocal", "country": "BR"})
    if not r:
        return FAIL, "incident not detected at all"
    similar = find_similar_incidents(run.world.detector, r)
    if not similar:
        return FAIL, "memory returned nothing for a repeat of a resolved incident"
    top = similar[0]
    return PASS, f"matched a past incident at similarity {top['similarity']:.2f}: {top['resolution']}"


def case_17_novel_combination() -> Result:
    """A dimension combination nobody wired a demo path for."""
    run = build(5)
    inject(run, type="provider_degraded",
           scope={"merchant": "m_fastcart", "country": "MX", "brand": "mastercard"}, severity=0.40)
    advance(run, 20)
    hits = [r for r in run.open if r.kind == "conversion_drop"
            and any(v in ("m_fastcart", "MX", "mastercard") for v in r.scope.values())]
    if not hits:
        return FAIL, f"missed a novel combination: {_summary(run)}"
    r = hits[0]
    return PASS, f"{r.scope} cause={r.cause_type} conf={r.confidence:.2f} (no code path for this)"


def case_18_double_click() -> Result:
    """A judge double-clicking Inject must not create two incidents."""
    run = build(5)
    payload = dict(type="provider_degraded", scope={"provider": "stripe"}, severity=0.35)
    a = inject(run, **payload)
    b = inject(run, **payload)
    advance(run, 15)
    if a != b:
        return FAIL, f"two injections created: {a} != {b}"
    dupes = [r for r in run.open if r.scope.get("provider") == "stripe"]
    if len(dupes) > 1:
        return FAIL, f"{len(dupes)} incidents for one injection"
    return PASS, f"one injection ({a}), {len(dupes)} incident"


def case_21_spanish() -> Result:
    """The note is free text in any language; it must not change the mechanics."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"},
           severity=0.35, note="dLocal está rechazando casi todo en Brasil desde hace un rato")
    advance(run, 20)
    r = find(run, cause="provider_degraded", scope={"provider": "dlocal", "country": "BR"})
    return (PASS, f"{r.scope} unaffected by the Spanish note") if r else \
           (FAIL, f"the note changed the outcome: {_summary(run)}")


def case_22_latency() -> Result:
    """Slow but not declining: a different incident, priced with low confidence."""
    run = build(5)
    inject(run, type="latency_spike", scope={"provider": "adyen"}, severity=0.6)
    advance(run, 18)
    r = find(run, cause="latency_spike")
    if not r:
        return FAIL, f"missed the latency spike: {_summary(run)}"
    if r.confidence > 0.6:
        return DEGRADED, f"detected but over-confident ({r.confidence:.2f}) for an estimate"
    return PASS, (f"{r.scope} kind={r.kind} {r.detail.get('latency_ms')}ms vs "
                  f"{r.detail.get('latency_baseline_ms')}ms, conf={r.confidence:.2f}")


def case_23_no_traffic() -> Result:
    """The merchant's checkout died: that is not a conversion problem."""
    run = build(5)
    inject(run, type="merchant_outage", scope={"merchant": "m_streamly"}, severity=0.95)
    advance(run, 15)
    r = find(run, cause="no_traffic")
    if not r:
        return FAIL, f"missed the outage: {_summary(run)}"
    wrong = [x for x in run.open if x.kind == "conversion_drop"
             and x.scope.get("merchant") == "m_streamly"]
    if wrong:
        return DEGRADED, "flagged as no-traffic but also opened a conversion incident"
    return PASS, f"{r.scope} kind=no_traffic, volume drop {r.detail.get('volume_drop')}"


def case_24_reset() -> Result:
    """Reset mid-incident leaves no ghosts."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"}, severity=0.4)
    advance(run, 15)
    if not run.open:
        return FAIL, "nothing to reset: the incident never opened"
    run.world.reset()
    advance(run, 10)
    ghosts = [r for r in run.world.detector.incidents.values() if not r.detail.get("seeded")]
    if ghosts:
        return FAIL, f"{len(ghosts)} incidents survived the reset"
    if run.world.injector.all():
        return FAIL, "injections survived the reset"
    return PASS, "clean baseline: no incidents, no injections, no ghosts"


def case_25_chart_freezes() -> Result:
    """A finished incident's chart is history: bounded, and it stops moving."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "adyen", "country": "MX"},
           severity=0.40, duration_minutes=12)
    advance(run, 45)
    closed = [r for r in run.all_incidents() if r.status in ("resolved", "expired")]
    if not closed:
        return FAIL, "nothing closed, so there is no frozen chart to check"
    rec = closed[0]
    advance(run, 35)                       # let the 30-minute tail finish recording
    if rec.frozen_series is None:
        return FAIL, "a closed incident's chart was never frozen"
    snapshot = list(rec.frozen_series)
    advance(run, 20)                       # the world moves on; the chart must not
    if rec.frozen_series != snapshot:
        return FAIL, "a closed incident's chart kept changing"

    start, end = run.world.detector.chart_window(rec, run.world.now)
    closed_at = rec.resolved_at or rec.last_seen_at
    pad_before = (rec.started_at - start).total_seconds() / 60
    pad_after = (end - closed_at).total_seconds() / 60
    if abs(pad_before - 30) > 1 or abs(pad_after - 30) > 1:
        return DEGRADED, f"frozen, but the window pads {pad_before:.0f}/{pad_after:.0f} min"
    return PASS, (f"{len(snapshot)} points, frozen, spanning 30 min before to 30 min after "
                  f"({rec.status})")


def case_26_open_chart_follows() -> Result:
    """An open incident's chart keeps up, and starts 30 min before the incident did."""
    run = build(5)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"},
           severity=0.35)
    advance(run, 20)
    rec = find(run, scope={"provider": "dlocal", "country": "BR"})
    if not rec:
        return FAIL, "incident not detected"
    start, end = run.world.detector.chart_window(rec, run.world.now)
    if end != run.world.now:
        return FAIL, "an open incident's chart does not run to now"
    before = (rec.started_at - start).total_seconds() / 60
    n_before = len(run.world.cube.series(rec.scope, end,
                                         int((end - start).total_seconds() // 60) + 1))
    advance(run, 10)
    _s2, e2 = run.world.detector.chart_window(rec, run.world.now)
    n_after = len(run.world.cube.series(rec.scope, e2,
                                        int((e2 - _s2).total_seconds() // 60) + 1))
    if n_after <= n_before:
        return FAIL, "an open incident's chart stopped growing"
    if abs(before - 30) > 1:
        return DEGRADED, f"live, but starts {before:.0f} min before the incident"
    return PASS, f"live and growing ({n_before} -> {n_after} points), starts 30 min before"


def case_27_clock_speed_labels() -> Result:
    """The speed control's labels must mean what they say.

    `sim_speed` is a multiple of real time: at 60x one simulated minute passes per real
    second. This once meant simulated *minutes* per real second, so every label was off
    by a factor of sixty and the world blew past far too fast to watch — which is the
    only reason this case exists.
    """
    from api.config import SIM_SPEEDS

    tick = 0.25
    problems = []
    for speed in SIM_SPEEDS:
        # Replay the accumulator in api/runtime.py::_loop over 10 minutes of real time.
        real_seconds = 600.0
        carry, minutes = 0.0, 0
        for _ in range(int(real_seconds / tick)):
            carry += (speed / 60.0) * tick
            step = int(carry)
            carry -= step
            minutes += step
        want = speed * real_seconds / 60.0     # real minutes elapsed x the multiplier
        if abs(minutes - want) > 1:
            problems.append(f"{speed}x gave {minutes} sim-min, expected {want:.0f}")
    if problems:
        return FAIL, "; ".join(problems)
    return PASS, ("every speed advances the clock by exactly its multiple of real time "
                  f"({', '.join(f'{s:g}x' for s in SIM_SPEEDS)})")


def case_28_no_incident_churn() -> Result:
    """Two failures should leave two records — not two plus a trail of bookkeeping.

    Attribution lands a notch deeper or shallower as noise moves, and each depth is a
    different fingerprint. Before this was folded at creation time, one hour of two
    injections left thirteen records: eleven of them the same story superseded moments
    after being opened, all of them visible in the closed list.
    """
    run = build(5)
    inject(run, type="issuer_over_declining", scope={"issuer": "banorte"}, severity=0.30)
    inject(run, type="provider_degraded", scope={"provider": "dlocal", "country": "BR"},
           severity=0.35)
    advance(run, 60)
    recs = run.all_incidents()
    visible = [r for r in recs if not r.detail.get("superseded_by")]
    if len(visible) > 4:
        rows = "; ".join(f"{r.status}:{r.cause_type}@{r.scope}" for r in visible)
        return FAIL, f"{len(visible)} records for 2 failures: {rows}"
    if len(recs) > 6:
        return DEGRADED, f"{len(visible)} visible but {len(recs)} records created"
    return PASS, (f"{len(visible)} visible record(s) for 2 injections over an hour "
                  f"({len(recs)} created in total)")


ENGINE_CASES = [
    ("01", "Normal traffic, nothing fires", case_01_quiet),
    ("02", "Weekend volume absorbed by the baseline", case_02_weekend),
    ("03", "Provider degraded in one country", case_03_provider_country),
    ("04", "Two simultaneous incidents, separated and ranked", case_04_two_at_once),
    ("05", "Segment below the minimum sample", case_05_small_sample),
    ("06", "Hard-decline spike is not a conversion drop", case_06_hard_declines),
    ("07", "Mapping bug: we recorded what the provider never said", case_07_mapping_bug),
    ("08", "Unseen provider raw code", case_08_unknown_code),
    ("09", "Routing/config change correlated to a change event", case_09_routing_config),
    ("10", "Card network degraded across providers", case_10_network),
    ("11", "Issuer over-declining through every provider", case_11_issuer_all_providers),
    ("12", "Issuer failing through one provider only", case_12_issuer_one_provider),
    ("13", "Alternative payment method down", case_13_method_down),
    ("14", "Gradual degradation (20-minute ramp)", case_14_ramp),
    ("15", "Incident resolves by itself", case_15_self_resolves),
    ("16", "Memory: this already happened", case_16_memory),
    ("17", "Never-seen dimension combination", case_17_novel_combination),
    ("18", "Double-clicked Inject", case_18_double_click),
    ("21", "Injection note written in Spanish", case_21_spanish),
    ("22", "Latency spike without decline increase", case_22_latency),
    ("23", "Merchant volume goes to zero", case_23_no_traffic),
    ("24", "Reset pressed mid-incident", case_24_reset),
    ("25", "A closed incident's chart freezes", case_25_chart_freezes),
    ("26", "An open incident's chart follows it", case_26_open_chart_follows),
    ("27", "Clock speed labels mean what they say", case_27_clock_speed_labels),
    ("28", "One failure stays one incident record", case_28_no_incident_churn),
]
