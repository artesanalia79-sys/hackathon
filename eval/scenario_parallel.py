"""Fire five overlapping incidents at once and watch the engine separate them.

This is the "two simultaneous incidents, correctly separated and prioritized"
deliverable turned up to five, with staggered onsets and durations so some are
still ramping while others have already recovered. Nothing here names an
incident — every injection just perturbs the world, exactly like a judge's would,
and the engine has to find, split, price and rank them on its own.

The five stories, chosen to exercise every branch of the classifier at once:

  1. Bancolombia over-declines in CO         (soft_decline, issuer scope)
  2. Banorte over-declines in MX             (soft_decline, different country → clearly its own story)
  3. dLocal degraded across ALL of Colombia  (technical, "todos los rieles de CO" — dLocal runs every CO rail)
  4. PSE goes down in CO                      (short, technical, nested inside #3 → should be folded in, not double-counted)
  5. Adyen degraded in Brazil                 (technical, a third independent story on another corridor)

What to watch for on the board this prints (and in the UI):
  - #1, #2, #3, #5 stand up as separate incidents, ranked by $/min;
  - #4 gets superseded by #3 instead of appearing twice (the dedupe of shadows);
  - onsets are staggered and #4 recovers first, so the board changes shape over time.

Run against a live server (`make run` in another terminal):
    uv run python -m eval.scenario_parallel --port 8000
    uv run python -m eval.scenario_parallel --watch 120 --speed 10
    uv run python -m eval.scenario_parallel --reset-after      # tidy up when done

By default it does NOT reset at the end, so the incidents stay on screen for the
live demo. Pass --reset-after to clear them.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# Injection start/duration are in *simulated* minutes. At the default SIM_SPEED of 10,
# one simulated minute is six real seconds, so these offsets play out over a couple of
# real minutes — slow enough to narrate, fast enough for a demo.
SCENARIO: list[dict] = [
    {"label": "1· Bancolombia over-declining (CO)",
     "type": "issuer_over_declining",
     "scope": {"country": "CO", "issuer": "bancolombia"},
     "severity": 0.40, "start_in_minutes": 0, "duration_minutes": 24, "ramp_minutes": 2},
    {"label": "2· Banorte over-declining (MX)",
     "type": "issuer_over_declining",
     "scope": {"country": "MX", "issuer": "banorte"},
     "severity": 0.38, "start_in_minutes": 3, "duration_minutes": 40, "ramp_minutes": 2},
    {"label": "3· dLocal degraded — all CO rails",
     "type": "provider_degraded",
     "scope": {"country": "CO", "provider": "dlocal"},
     "severity": 0.42, "start_in_minutes": 0, "duration_minutes": 30, "ramp_minutes": 3},
    {"label": "4· PSE down in CO (nested in #3)",
     "type": "method_down",
     "scope": {"country": "CO", "method": "pse"},
     "severity": 0.90, "start_in_minutes": 6, "duration_minutes": 12, "ramp_minutes": 0},
    {"label": "5· Adyen degraded in BR",
     "type": "provider_degraded",
     "scope": {"country": "BR", "provider": "adyen"},
     "severity": 0.45, "start_in_minutes": 2, "duration_minutes": 34, "ramp_minutes": 2},
]


def call(base: str, path: str, body=None):
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def scope_str(scope: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in scope.items()) or "platform-wide"


def print_board(snapshot: dict) -> None:
    """One frame of the live board: every incident the engine is currently telling a story about."""
    rows = snapshot["incidents"]
    live = [r for r in rows if r["status"] in ("watching", "confirmed")]
    live.sort(key=lambda r: -r["cost_per_min_usd"])
    now = snapshot["now"].split("T")[-1][:8]
    print(f"\n  sim {now} · {snapshot['open_count']} open · "
          f"${snapshot['total_cost_per_min_usd']:,.0f}/min total")
    if not live:
        print("    (nothing open yet — the engine is still inside its detection window)")
        return
    print(f"    {'STATUS':<10}{'CAUSE':<22}{'$/MIN':>9}{'CONF':>6}  SCOPE")
    for r in live:
        conf = r["detail"].get("confidence", 0.0)
        print(f"    {r['status']:<10}{(r['cause_type'] or '-'):<22}"
              f"{r['cost_per_min_usd']:>9,.0f}{conf:>6.2f}  {scope_str(r['scope'])}")


def summarize(base: str) -> None:
    """After the watch window: how many stories did five overlapping injections become?"""
    truth = call(base, "/api/injections")
    all_inc = call(base, "/api/incidents?include_superseded=true")["incidents"]
    seeded_out = [r for r in all_inc if not r["detail"].get("seeded")]
    live = [r for r in seeded_out if r["status"] in ("watching", "confirmed")]
    superseded = [r for r in seeded_out if r["detail"].get("superseded_by")]

    print("\n" + "=" * 70)
    print(f"  injected (ground truth): {len(truth['all'])} perturbations")
    print(f"  distinct live incidents: {len(live)}")
    print(f"  folded into a bigger one (superseded): {len(superseded)}")
    if superseded:
        for r in superseded:
            print(f"      - {scope_str(r['scope'])} → superseded_by {r['detail']['superseded_by']}")
    print("\n  live incidents, priced and ranked:")
    for r in sorted(live, key=lambda r: -r["cost_per_min_usd"]):
        print(f"      ${r['cost_per_min_usd']:>8,.0f}/min  {(r['cause_type'] or '-'):<20}"
              f"  {scope_str(r['scope'])}")
    print("=" * 70)
    print("  Expected: ~3–4 distinct incidents (the two banks, the CO-wide provider,")
    print("  the BR provider), with PSE folded into the CO-wide one rather than counted")
    print("  twice. Exact count shifts as injections ramp in and recover.\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--speed", type=float, default=None,
                    help="set SIM_SPEED before firing (e.g. 10); default leaves it unchanged")
    ap.add_argument("--watch", type=int, default=90,
                    help="seconds to watch the board after injecting (default 90)")
    ap.add_argument("--no-reset-first", action="store_true",
                    help="do NOT clear the world before injecting")
    ap.add_argument("--reset-after", action="store_true",
                    help="clear everything when done (default: leave it running for the demo)")
    args = ap.parse_args()
    base = f"http://localhost:{args.port}"

    try:
        health = call(base, "/health")
    except urllib.error.URLError as exc:
        print(f"  server not reachable on {base}: {exc}\n  start it with `make run`")
        return 1
    print(f"  server healthy · sim clock {health['sim_now']} · "
          f"agent {'on' if health['agent']['available'] else 'off (deterministic path)'}")

    if not args.no_reset_first:
        call(base, "/api/reset", {})
        print("  world reset")
    if args.speed is not None:
        got = call(base, f"/api/speed?value={args.speed}")
        print(f"  sim speed → {got['sim_speed']}x")

    print("\n  firing five overlapping injections:")
    for s in SCENARIO:
        payload = {k: s[k] for k in ("type", "scope", "severity",
                                     "start_in_minutes", "duration_minutes", "ramp_minutes")}
        res = call(base, "/api/inject", payload)
        when = ("now" if s["start_in_minutes"] == 0
                else f"+{s['start_in_minutes']}min")
        print(f"    {s['label']:<38} {res['injection_id']}  "
              f"(starts {when}, {s['duration_minutes']}min)")

    print(f"\n  watching for {args.watch}s — separation and priority should emerge below")
    deadline = time.time() + args.watch
    while time.time() < deadline:
        time.sleep(4)
        print_board(call(base, "/api/incidents"))

    summarize(base)

    if args.reset_after:
        call(base, "/api/reset", {})
        print("  world reset — board cleared\n")
    else:
        print("  (injections still running; `make reset` or --reset-after to clear)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
