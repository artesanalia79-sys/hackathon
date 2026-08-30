# DECISION_LOG.md — Control Tower

*Alternatives we considered and why we chose what we chose.* This is a required
deliverable for NextWave Challenge 02, and it is also the honest record of where the
design pushed back on us. Every entry points at the code that implements it, so the
decision can be checked, not just asserted.

Three people built this across separate working sessions; the reasoning lives in the
code and its comments as much as in anyone's head. Where a decision was *forced* by a
test rather than chosen up front, we say so — those are marked and cross-referenced to
[`docs/UGLY_CASES.md`](docs/UGLY_CASES.md), which is executable via `make eval`.

Format of each entry: **Decision · Alternatives considered · Why this one · Trade-off we accepted.**

---

## 1. Product shape

### 1.1 A deterministic engine that always answers, with the LLM as an optional upgrade layer
- **Decision.** The detection, attribution, classification and pricing are pure code with
  no model in the loop. The agent runs *only* on already-confirmed incidents and only
  *upgrades* a card the engine has already filled in. No key → the agent is simply off and
  everything still works. See [`api/config.py`](api/config.py) (`OPENAI_API_KEY` empty =
  off), [`api/runtime.py`](api/runtime.py) `_diagnose_loop`, and the labelled fallback in
  [`api/agent/loop.py`](api/agent/loop.py).
- **Alternatives.** (a) LLM-first: feed transactions to a model and ask for the diagnosis.
  (b) LLM-in-detection: let a model decide what "matters".
- **Why this one.** Cost and latency stay bounded and predictable; a five-minute blip
  never pays for an LLM call; the demo is defensible because the core reasoning is
  inspectable and reproducible; and there is always an answer on the card even if the API
  is down, slow, or unconfigured.
- **Trade-off.** Two diagnosis paths to maintain (`agent` vs `deterministic_fallback`),
  both labelled on the card. The agent's added value is narration and corroboration, never
  the numbers.

### 1.2 Diagnose, never remediate
- **Decision.** Nothing in the system moves traffic, edits a mapping table, or closes an
  incident. The one outbound effect is `send_slack_alert`, which interrupts a person.
  Enforced structurally in [`api/agent/tools.py`](api/agent/tools.py) — the agent has no
  tool that touches production.
- **Alternatives.** Auto-reroute away from a degraded provider; auto-rollback a change.
- **Why this one.** The brief is explicit: this challenge diagnoses, it does not remediate.
  And the safety argument is real: interrupting a human is reversible by that human; moving
  live payment traffic is not. So one is ours to do and the other is not — by construction,
  not by prompt.
- **Trade-off.** We stop one step short of "fixing it", by design.

---

## 2. Detection

### 2.1 Decline-signature attribution as the core mechanism
- **Decision.** A rate drop is treated as a *symptom*; the fingerprint of the cause is the
  **distribution of decline categories** per segment vs its own history. See
  [`api/engine/signature.py`](api/engine/signature.py) and the README.
- **Alternatives.** Classic threshold/anomaly alerts on the conversion rate itself.
- **Why this one.** A degraded provider, an issuer tightening rules, a card network
  wobbling and our own broken code-mapping all drop the *same number* and look nothing
  alike once you read the shape of the declines. Threshold alerts can't tell them apart —
  which is exactly the "detecting is easy, diagnosing is hard" problem in the brief.
- **Trade-off.** Requires a decline-category taxonomy and provider raw-code tables to be
  modelled ([`api/sim/catalog.py`](api/sim/catalog.py), [`api/sim/mapping.py`](api/sim/mapping.py)).

### 2.2 A Beta-posterior binomial test, not a fixed threshold
- **Decision.** The detector's score is `P(true approval rate < expected − DELTA)` under a
  Jeffreys `Beta(.5,.5)` prior, and it only fires above `SCORE_FIRE = 0.99` with at least
  `N_MIN = 40` operational attempts. See `prob_rate_below` in
  [`api/engine/stats.py`](api/engine/stats.py) and `_score` in
  [`api/engine/detector.py`](api/engine/detector.py).
- **Alternatives.** A fixed "conversion dropped X%" threshold; a z-test; a rolling stddev band.
- **Why this one.** It answers "how sure are we the *underlying* rate is below the band",
  not "did this noisy sample dip". That is what lets a low-volume segment stay quiet instead
  of firing on variance, and it is why weekend/night traffic (ugly cases #1, #2) does not
  open incidents.
- **Trade-off.** We hand-wrote the regularized incomplete beta (Lentz's method) rather than
  pull in scipy — see §7.1.

### 2.3 Expectation = 0.7·seasonal + 0.3·EWMA, and the EWMA excludes the window under test
- **Decision.** `p0 = 0.7 * seasonal(same weekday & hour) + 0.3 * EWMA(recent live)`, with
  the recent-history window deliberately ending *before* the window being tested. See
  [`api/engine/expectation.py`](api/engine/expectation.py).
- **Alternatives.** Pure seasonal baseline; pure recent-traffic baseline; include the
  current window in the EWMA.
- **Why this one.** Seasonal absorbs time-of-day and weekend shape; the EWMA tracks
  legitimate recent drift. Excluding the window under test is the load-bearing part: if the
  current dip fed the expectation, the expectation would chase the dip and the detector
  would go blind exactly when it matters.
- **Trade-off.** `SEASONAL_WEIGHT = 0.7` is a tuned constant, not derived.

### 2.4 Freeze the recent-history baseline while an incident is open
- **Decision.** Once an incident is open on a scope, its EWMA baseline is held at the value
  captured at onset. See `_frozen_ewma` in [`api/engine/detector.py`](api/engine/detector.py)
  and the `_frozen` path in [`api/engine/expectation.py`](api/engine/expectation.py).
- **Alternatives.** Let the 2-hour EWMA keep moving during the incident.
- **Why this one.** Left free, the window swallows the incident itself: the expectation
  walks down onto the failure, measured excess shrinks, and the money on the card falls
  while nothing is actually getting better. Measured drift was **−41 % of $/min over five
  simulated hours** on an unchanged injection.
- **Trade-off.** A little extra per-incident state (`baseline_ewma`).

### 2.5 Four independent scans, not one "conversion is down" alert
- **Decision.** Each tick asks four separate questions: conversion drop, data integrity,
  no-traffic, latency spike. See the four `_scan_*` methods in
  [`api/engine/detector.py`](api/engine/detector.py).
- **Alternatives.** A single conversion detector.
- **Why this one.** They are four different failures a single alert would blur, and two of
  them are *invisible* to a conversion detector: a mapping bug makes conversion look
  **better** (ugly #7), and a merchant outage makes conversion **undefined**, not bad
  (ugly #23). Latency without declines is a fifth story where the loss is abandonment, so
  its confidence is capped low.
- **Trade-off.** Four confirm/resolve rules to maintain instead of one.

### 2.6 Exclude hard declines from the operational rate
- **Decision.** Insufficient-funds/hard declines are removed from the denominator the
  detector watches (`operational_attempts`), and priced as almost fully recoverable. See
  `RECOVERABILITY` in [`api/config.py`](api/config.py) and ugly #6.
- **Alternatives.** Count every non-approval as a lost sale.
- **Why this one.** A hard-decline spike is real but not an incident — that sale was never
  going to happen, and no operator action recovers it. Counting it would fire on noise and
  mis-price everything.
- **Trade-off.** Depends on the category taxonomy being right about which codes are "hard".

---

## 3. Attribution

### 3.1 Recursive Adtributor scored by explanatory power **and** surprise **and** lift
- **Decision.** At each level we score every `(dimension, value)` by explanatory power
  (share of the excess it carries), surprise (Jensen-Shannon divergence of its decline
  shape vs history), and lift (EP ÷ its share of attempts). Surprise picks the *dimension*,
  EP picks the *value*, lift gates it. See [`api/engine/adtributor.py`](api/engine/adtributor.py).
- **Alternatives.** Greedy single-dimension drilldown; "blame the biggest bucket"; a flat
  scan of pre-chosen segments.
- **Why this one.** Without lift, a single provider outage looks "explained" by the biggest
  merchant, because the biggest merchant carries the most of *everything*. Surprise is what
  distinguishes "this dimension carries excess because it's big" from "this dimension's
  shape changed".
- **Trade-off.** More cube queries per tick, and three tuned thresholds
  (`EP_THRESHOLD`, `EP_BRANCH`, `LIFT_MIN`).

### 3.2 Branch into two incidents when nothing dominates
- **Decision.** If no single value clears the primary threshold but two independent values
  each clear `EP_BRANCH` with enough sample, we open **two** incidents, subtracting the
  overlap so one story isn't reported twice. See `_descend`/`_overlap_excess` in
  [`api/engine/adtributor.py`](api/engine/adtributor.py).
- **Alternatives.** Always return a single root cause.
- **Why this one.** The brief explicitly requires two simultaneous incidents to be
  separated and prioritized (ugly #4, and the demo scenario in
  [`eval/scenario_parallel.py`](eval/scenario_parallel.py)).
- **Trade-off.** Overlap-excess bookkeeping to avoid double-counting money.

### 3.3 Attribute from the global scope first; firing slices are a gated fallback — *forced by ugly #4*
- **Decision.** Build one tree from the top; only give a firing slice its own tree if its
  excess is genuinely its own (`residual_share ≥ UNEXPLAINED_SHARE`). See
  `_attribute_and_upsert` in [`api/engine/detector.py`](api/engine/detector.py).
- **Alternatives.** Attribute independently from each firing slice.
- **Why this one.** Every firing slice produced the *same* outage under a dozen scopes
  (`{country,provider}`, `{method,provider}`, …). And an issuer whose traffic routes through
  a broken provider is *below expectation* too — it is not a second incident, it is the same
  one seen from another angle. Case #4 is what exposed this.
- **Trade-off.** A residual-overlap computation on every candidate slice.

---

## 4. Classification & cost

### 4.1 Hand-written signature rules in priority order, not a trained classifier
- **Decision.** Cause type comes from an ordered rule set over the decline signature and the
  structural spread across providers/issuers/merchants. See `classify` in
  [`api/engine/signature.py`](api/engine/signature.py).
- **Alternatives.** Train an ML classifier on labelled incidents.
- **Why this one.** There is no labelled incident history to train on, and — more
  importantly — the output has to be *defensible line by line* in front of judges. Each rule
  states the structural claim it is making ("the same issuers convert fine through other
  providers"), and we *check* that claim with `spread_across` rather than assert it.
- **Trade-off.** Rule thresholds and per-rule confidences are set by hand and maintained by
  hand.

### 4.2 Data integrity is its own cause, split into mapping-bug vs unmapped-code — *forced by ugly #7*
- **Decision.** When we record a status the provider never returned, that's a first-class
  incident (`kind=data_integrity`). If the disagreeing rows carry codes we don't map, the
  fix is "map the code" (`unmapped_provider_code`); if the mapping is clean but still
  disagrees, the fix is "roll back" (`mapping_bug`). See `_scan_integrity` in
  [`api/engine/detector.py`](api/engine/detector.py) and rule 1 of `classify`.
- **Alternatives.** Treat it as a normal conversion drop (and miss it entirely).
- **Why this one.** A mapping bug makes conversion look *better*, so no conversion detector
  can ever catch it. The raw-vs-normalized decoupling is the only place it's visible.
- **Trade-off.** Requires the normalization layer to be derived from the provider code
  tables so a bug is a genuine divergence, not a special case.

### 4.3 Price by recoverability, and accrue on the clock
- **Decision.** Each excess decline is valued at `ticket × (1 − recoverability[category])`,
  and cost accrues every minute an incident is open, re-priced from the live window. See
  [`api/engine/cost.py`](api/engine/cost.py) and `_accrue_cost` in
  [`api/engine/detector.py`](api/engine/detector.py).
- **Alternatives.** Count every lost sale at the full ticket; accrue only on the ticks the
  detector re-fires.
- **Why this one.** A hard decline costs almost nothing; a technical one costs nearly the
  whole ticket — ranking incidents by money is meaningless without that weighting. And
  accruing on re-fire meant a confirmed incident that went quiet kept bleeding while its
  total stood still.
- **Trade-off.** The recoverability fractions are stated assumptions, exposed in
  [`api/config.py`](api/config.py) so they can be argued with.

### 4.4 Money is the engine's; the agent may never state a figure
- **Decision.** The agent narrates; the engine prices. A figure written in the agent's own
  prose or a Slack headline is *rejected*, not silently stripped. See `_money_in_prose` in
  [`api/agent/loop.py`](api/agent/loop.py), `MONEY_IN_HEADLINE` in
  [`api/agent/tools.py`](api/agent/tools.py), and rule 2 of the system prompt in
  [`api/agent/schema.py`](api/agent/schema.py).
- **Alternatives.** Let the model quote the numbers it's shown.
- **Why this one.** It removes the entire class of "the LLM got the arithmetic wrong". This
  isn't hypothetical — an earlier version put *"costing over $1.2M so far"* on a card,
  contradicting a guarantee we make out loud in the pitch.
- **Trade-off.** A guardrail regex and an occasional rejected `conclude` (which falls back
  to the deterministic card, so nothing is lost).

---

## 5. The agent

### 5.1 Read-only tools over the same cube; every claim must cite a call it actually made
- **Decision.** Seven read-only tools, plus the one Slack side effect. Each `conclude`
  evidence entry must carry a `tool_call_id` from *this* run, or the whole answer is
  rejected and the deterministic diagnosis is shown. See `_finish_conclude` in
  [`api/agent/loop.py`](api/agent/loop.py).
- **Alternatives.** Trust the model's prose; let it summarize freely.
- **Why this one.** The trace *is* the product — an incident card is only trustworthy if a
  reader can see where each claim came from. Citations make hallucinated evidence impossible
  to pass off.
- **Trade-off.** Strict validation occasionally rejects an otherwise fine answer.

### 5.2 Legible call handles (`call_1`), not the API's opaque ids — *forced by the first live run*
- **Decision.** We hand the model short handles and ask it to cite those, mapping back to
  the real ids internally. See `handle_for` in [`api/agent/loop.py`](api/agent/loop.py).
- **Alternatives.** Ask the model to echo the API's 29-character opaque call id.
- **Why this one.** Against the *real* Responses API the model cited tool *names* instead of
  ids, so every honest answer was rejected. Our earlier stub happened to use ids that
  matched, which hid the bug completely (see the note in
  [`docs/UGLY_CASES.md`](docs/UGLY_CASES.md)). Asking a model to echo a long opaque string is
  a guardrail that fails honest answers.
- **Trade-off.** A small handle-mapping table per run.

### 5.3 Cap the agent's confidence at the engine's + a small headroom
- **Decision.** `confidence ≤ engine_confidence + 0.05`. See `AGENT_CONFIDENCE_HEADROOM` in
  [`api/config.py`](api/config.py) and the ceiling in [`api/agent/loop.py`](api/agent/loop.py).
- **Alternatives.** Trust whatever confidence the model reports.
- **Why this one.** The agent reads the engine's own evidence, so it cannot legitimately be
  much more certain than the engine that produced it. Without the ceiling the card showed a
  `1.0` sitting on top of an engine reading of `0.45` — the agent's certainty dressed up as
  the system's (ugly #19e).
- **Trade-off.** The headroom is a tuned constant.

### 5.4 "Insufficient evidence" is a first-class answer
- **Decision.** The agent can decline to name a cause, and the engine falls through to the
  same answer when nothing concentrates with enough sample. See `insufficient_evidence` in
  [`api/agent/schema.py`](api/agent/schema.py) and the fall-through in `classify`.
- **Alternatives.** Always output a named cause.
- **Why this one.** The brief awards bonus points for admitting uncertainty instead of
  inventing a diagnosis, and guessing on a sub-`N_MIN` segment is simply wrong.
- **Trade-off.** Sometimes the honest card says "keep watching", which is less of a
  demo flourish than a confident wrong answer would be.

### 5.5 Make the alert decision structural, not just prompted
- **Decision.** The first time the agent tries to conclude a nameable cause without having
  decided about Slack, it gets the turn back — once. Concluding again *is* the decision not
  to alert, and it stands. See the `needs_alert_call` branch in
  [`api/agent/loop.py`](api/agent/loop.py).
- **Alternatives.** Just tell it in the prompt to alert before concluding.
- **Why this one.** Prompted alone, the model reads `conclude` as the finish line and goes
  straight there; an alert it postpones is an alert that never happens.
- **Trade-off.** Occasionally one extra round-trip.

---

## 6. Delivery, lifecycle & concurrency

### 6.1 Slack: off unless configured, one per incident, never blocks, only on confirmed
- **Decision.** Same on/off discipline as the agent key; dedupe on our side; send on the
  diagnosis loop off the tick path; and never page a `watching` (i.e. hypothetical)
  incident. See [`api/notify/slack.py`](api/notify/slack.py).
- **Alternatives.** Alert on `watching`; alert from the tick path.
- **Why this one.** Paging a human for a hypothesis is how an alert channel becomes a
  channel nobody reads — the exact failure mode the brief calls out ("fire on everything and
  get ignored"). Off-path sending keeps a slow webhook from stalling the simulation.
- **Trade-off.** A small "already sent" set to maintain.

### 6.2 One writer per structure; reset takes the simulation lock — *the reset half forced by `make smoke`*
- **Decision.** Ingest writes counters, the detector writes incidents, the agent writes
  diagnoses; state lives in one `World` object; `reset` runs under the sim lock. See
  [`api/runtime.py`](api/runtime.py) and `docs/ARCHITECTURE.md`.
- **Alternatives.** A shared database; reset without the lock.
- **Why this one.** In-memory is fast enough (342 leaf segments) and one writer per table
  removes a whole class of races. Without the lock, a generation batch already in flight
  lands *after* the wipe and the detector re-opens the incident we just cleared — the ghost
  incidents ugly #24 exists to prevent, and which only `make smoke` (with a real concurrent
  loop) could surface.
- **Trade-off.** No persistence across a server restart — acceptable for a live demo.

### 6.3 Simulated clock decoupled from real time
- **Decision.** `SIM_SPEED` multiplies real time; detection windows are counted in
  *simulated* minutes, so speed changes how long you get to *watch*, never what the engine
  concludes. See [`api/config.py`](api/config.py) and `_loop` in
  [`api/runtime.py`](api/runtime.py).
- **Alternatives.** Real-time only.
- **Why this one.** A live demo needs an incident to visibly *build* over ~30 seconds, and a
  judge needs to pause. (The label-vs-reality bug where the clock ran 60× its stated speed,
  ugly #27, is why the conversion factor is now explicit.)
- **Trade-off.** One more control to explain.

### 6.4 Idempotent injection and shadow-dedupe: one failure, one record — *ugly #18, #28*
- **Decision.** Identical injection payloads inside a wall-clock window reuse the same id
  ([`api/sim/injector.py`](api/sim/injector.py)); and a narrower incident that is only a
  shadow of a bigger one is superseded rather than shown twice (`_dedupe_shadowed` in
  [`api/engine/detector.py`](api/engine/detector.py)).
- **Alternatives.** Take every click at face value; show every attribution depth.
- **Why this one.** Judges double-click, and attribution can land a notch deeper or
  shallower minute to minute — both produced a trail of near-identical records that buried
  the real incident and double-counted its money.
- **Trade-off.** Supersede/dedup logic, and "superseded" records hidden from the board by
  default.

---

## 7. Stack

### 7.1 Dependency-free numerics in the engine
- **Decision.** The incomplete beta, Jensen-Shannon divergence, Jaccard and the samplers are
  hand-written pure Python. See [`api/engine/stats.py`](api/engine/stats.py).
- **Alternatives.** scipy/numpy.
- **Why this one.** Keeps the engine light and trivially deployable, and keeps the math
  visible and defensible rather than hidden behind a library call.
- **Trade-off.** ~180 lines of numerics we own and test ourselves.

### 7.2 FastAPI + Server-Sent Events + React/Vite; OpenAI Responses API for tool-calling
- **Decision.** One-way SSE streams ticks, traces and diagnoses to a React UI; the agent
  uses the Responses API with `parallel_tool_calls=false` and `temperature=0`. See
  [`api/routes/stream.py`](api/routes/stream.py), [`api/agent/loop.py`](api/agent/loop.py),
  and [`ui/`](ui/).
- **Alternatives.** WebSockets; the Chat Completions API; a heavier front-end framework.
- **Why this one.** The trace is a one-way stream, which is exactly what SSE is for; the
  Responses API gives first-class tool calling; `temperature=0` and serialized tool calls
  make a demo run reproducible.
- **Trade-off.** SSE is one-directional (fine here — all commands are plain POSTs).

---

## What we deliberately did *not* build

Saying no is a decision too, and these are the ones most likely to come up in defense:

- **No auto-remediation.** Covered in §1.2 — the challenge diagnoses, and moving live
  traffic is irreversible in a way interrupting a human is not.
- **No LLM-authored numbers.** Covered in §4.4 — the engine is the single source of every
  figure, so arithmetic can't be hallucinated.
- **No trained models anywhere.** Covered in §4.1 / §7.1 — no labelled data, and everything
  has to be explainable line by line.
- **No persistent database.** Covered in §6.2 — in-memory is fast enough for the scale and
  removes a class of races; persistence buys us nothing for a live demo.
- **No Datadog / external log ingestion (yet).** The world is self-contained so the demo
  can't fail on someone else's uptime. A log-shipping microservice and an "internal error →
  read the code" path are on the roadmap, not in scope for the hackathon, because they add
  integration surface without strengthening the diagnosis that judges actually score.
```
