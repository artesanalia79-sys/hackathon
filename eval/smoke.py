"""End-to-end smoke test against a running server: inject, wait, assert, reset.

This is the check to run before handing the laptop to a judge.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base: str, path: str, body=None):
    url = f"{base}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    base = f"http://localhost:{args.port}"
    checks: list[tuple[str, bool, str]] = []

    try:
        health = call(base, "/health")
    except urllib.error.URLError as exc:
        print(f"  server not reachable on {base}: {exc}\n  start it with `make run`")
        return 1
    checks.append(("server healthy", bool(health.get("ok")), f"sim clock {health['sim_now']}"))
    checks.append(("agent status known", True,
                   f"agent {'on: ' + str(health['agent']['model']) if health['agent']['available'] else 'off (deterministic path)'}"))

    call(base, "/api/reset", {})
    payload = {"type": "provider_degraded", "scope": {"provider": "dlocal", "country": "BR"},
               "severity": 0.35}
    first = call(base, "/api/inject", payload)
    second = call(base, "/api/inject", payload)
    checks.append(("double-click is idempotent",
                   first["injection_id"] == second["injection_id"] and second["duplicate"],
                   first["injection_id"]))

    deadline = time.time() + 45
    found = None
    while time.time() < deadline:
        time.sleep(2)
        incidents = call(base, "/api/incidents")["incidents"]
        found = next((i for i in incidents
                      if i["scope"].get("provider") == "dlocal"
                      and i["scope"].get("country") == "BR"
                      and i["status"] in ("watching", "confirmed")), None)
        if found and found["status"] == "confirmed":
            break

    checks.append(("incident detected and isolated", found is not None,
                   f"{found['scope']} · {found['cause_type']}" if found else "nothing opened in 45s"))
    if found:
        checks.append(("cause identified", found["cause_type"] == "provider_degraded",
                       found["cause_type"] or "-"))
        checks.append(("priced", found["cost_per_min_usd"] > 0,
                       f"${found['cost_per_min_usd']:,.0f}/min"))
        diag = call(base, f"/api/incidents/{found['id']}/diagnosis")["diagnosis"]
        checks.append(("diagnosis present", bool(diag.get("ops_explanation")), diag["source"]))
        checks.append(("every claim cites a call", all(e.get("tool_call_id") for e in diag["evidence"]),
                       f"{len(diag['evidence'])} evidence items"))
        checks.append(("recommends, does not execute", diag["recommendation"]["not_executed"] is True,
                       diag["recommendation"]["action"][:60]))

        # The card is deterministic the instant the incident confirms; the agent upgrades
        # it a few seconds later. Both are correct states, so check the one that applies.
        if health["agent"]["available"]:
            end = time.time() + 45
            while time.time() < end and diag["source"] != "agent":
                time.sleep(3)
                diag = call(base, f"/api/incidents/{found['id']}/diagnosis")["diagnosis"]
            trace = call(base, f"/api/incidents/{found['id']}/trace")
            tools = [s["tool"] for s in trace["steps"] if s.get("tool")]
            checks.append(("agent diagnosed it", diag["source"] == "agent",
                           f"{trace['status']} after {tools}"
                           + ("" if diag["source"] == "agent"
                              else f" — fell back: {diag.get('fallback_reason')}")))
            checks.append(("agent cited only calls it made",
                           all(e["tool_call_id"] in {s["tool_call_id"] for s in trace["steps"]
                                                     if s.get("tool_call_id")}
                               for e in diag["evidence"]) if diag["source"] == "agent" else True,
                           f"{len(diag['evidence'])} claims"))
            # The regression this guards is a *frozen* figure: a diagnosis written once
            # while the incident keeps costing money. Comparing against a separately
            # fetched incident would just race the 60x clock — so check the thing that
            # actually distinguishes live from frozen, which is that it moves.
            first = diag["affected"]["cost_per_min_usd"]
            time.sleep(6)
            second = call(base, f"/api/incidents/{found['id']}/diagnosis")["diagnosis"]
            checks.append(("money on the card is recomputed, not frozen",
                           second["affected"]["cost_per_min_usd"] != first,
                           f"${first:,.0f}/min -> ${second['affected']['cost_per_min_usd']:,.0f}/min"))
            checks.append(("the agent's words are stable across reads",
                           second["exec_line"] == diag["exec_line"], "narration unchanged"))

    call(base, "/api/reset", {})
    after = call(base, "/api/incidents")["incidents"]
    ghosts = [i for i in after if not i["detail"].get("seeded")]
    checks.append(("reset leaves no ghosts", not ghosts, f"{len(ghosts)} left"))

    print()
    ok = True
    for name, passed, detail in checks:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name:<32} {detail}")
    print(f"\n  {'all good' if ok else 'SOMETHING IS BROKEN'}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
