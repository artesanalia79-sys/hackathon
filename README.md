# Control Tower

A payment orchestrator sees every transaction from several providers. Conversion drops
silently, for many reasons, and today a human crosses filters by hand to find *where* and
*why*. This watches the stream, detects drops that matter, isolates the root cause across
six dimensions, explains it with evidence and money, and recommends an action.

It never executes anything.

**The mechanism: decline-signature attribution.** A rate drop is a symptom. The
*distribution of decline categories* per segment is the fingerprint of the cause. A
degraded provider, an issuer tightening its rules, a card network wobbling, and our own
broken code-mapping all drop the same number — and look nothing alike once you read the
shape of the decline codes and cross it with what we deployed.

NextWave 2026, Challenge 02.

## Run it

```bash
make setup     # Python 3.12 via uv, deps, UI build
make run       # http://localhost:8000
```

No API key needed. The agent layer stays off and every incident is diagnosed by the
deterministic engine, labelled as such. Drop an `OPENAI_API_KEY` into `.env` to turn the
agent on; nothing else changes. Verified against `gpt-4.1-mini`: 5–7 tool calls, 10–14
seconds, on top of a card that was already on screen.

```bash
make eval      # 33 ugly cases, headless (no API key needed, no network)
make smoke     # end-to-end against the running server
```

## Using it

Three sections: **Incidents**, **Live traffic**, **Inject**.

The clock runs at a **speed you choose** — pause, or 1× to 60× real time. At the default 10×
a 5-minute detection window takes 30 real seconds, slow enough to watch an incident build.
Detection windows are counted in simulated minutes, so the speed changes how long you get to
watch, never what the engine concludes.

1. **Inject** — pick what breaks and any subset of `merchant · country · method · brand ·
   issuer · provider`. A missing dimension means "any". Before you commit, the panel tells
   you how much traffic that scope actually carries and whether it is even detectable, so
   "nothing happened" is never a mystery. The engine is not told what you did.
2. Watch the incident open as `watching`, then `confirmed`.
3. The card shows: conversion against its own seasonal band on a chart bounded by the
   incident itself, where "expected" came from and the counts behind it, how the segment was
   isolated (explanatory power and lift at each step), the decline signature before vs now,
   every claim traced to the call that supports it, the money per minute, whether this has
   happened before, and a recommended action that has not been taken.
4. **Stop one injection** from the Inject panel to watch that incident recover and close on
   its own, while the others keep running. **Reset** puts everything back.

Two things worth trying: inject `mapping_bug` on a provider and watch the live attempt feed
at the bottom — the provider column and our column stop agreeing, and conversion goes *up*
while the incident opens anyway. And inject two unrelated failures at once and watch them
stay separate and get ranked by cost.

## How it is put together

- `api/sim/` — the world: 342 leaf segments, seasonal volume and approval curves, provider
  code tables, the normalization layer that a mapping bug corrupts, and the injector.
- `api/engine/` — detection (Beta-posterior binomial test against a seasonal baseline),
  recursive Adtributor, decline-signature classifier, cost model, memory. No LLM anywhere.
- `api/agent/` — the diagnosis agent over read-only tools. It cannot change production,
  and it cannot state a number: the engine attaches every figure after the fact.
- `ui/` — React. Incident list, incident card, live agent trace, injector, attempt feed.

`docs/SPEC.md` is what we set out to build, `docs/ARCHITECTURE.md` is what exists (with
the deviations marked and explained), `docs/UGLY_CASES.md` is what it survives.
