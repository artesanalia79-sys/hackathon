"""`make eval` — run every ugly case and print a verdict table."""
from __future__ import annotations

import argparse
import sys
import time
import traceback

from eval.cases import DEGRADED, ENGINE_CASES, FAIL, PASS

MARK = {PASS: "PASS", DEGRADED: "DEGR", FAIL: "FAIL"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated case numbers, e.g. 03,07,10")
    ap.add_argument("--agent", action="store_true", help="include the agent cases (19, 20)")
    args = ap.parse_args()

    cases = list(ENGINE_CASES)
    if args.agent:
        from eval.agent_cases import AGENT_CASES
        cases += AGENT_CASES
        cases.sort(key=lambda c: c[0])
    if args.only:
        wanted = {c.strip().zfill(2) for c in args.only.split(",")}
        cases = [c for c in cases if c[0] in wanted]

    counts = {PASS: 0, DEGRADED: 0, FAIL: 0}
    width = max(len(t) for _n, t, _f in cases)
    print(f"\n  Control Tower — ugly cases ({len(cases)})\n")
    t_all = time.perf_counter()
    for number, title, fn in cases:
        t0 = time.perf_counter()
        try:
            status, detail = fn()
        except Exception:
            status, detail = FAIL, "raised: " + traceback.format_exc(limit=2).strip().replace("\n", " | ")
        counts[status] = counts.get(status, 0) + 1
        secs = time.perf_counter() - t0
        print(f"  [{MARK[status]}] {number}  {title:<{width}}  {secs:5.1f}s")
        print(f"         {detail}")
    total = time.perf_counter() - t_all
    print(f"\n  {counts[PASS]} pass · {counts[DEGRADED]} degraded · {counts[FAIL]} failed "
          f"· {total:.1f}s\n")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
