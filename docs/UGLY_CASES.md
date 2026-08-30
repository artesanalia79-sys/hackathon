# UGLY_CASES.md — Control Tower

Each case feeds `make eval`, the demo script, and the Q&A answer bank.
Every case is executable: see `eval/cases.py` and `eval/agent_cases.py`.
Status: OK / pending / failing. **Run `make eval` — 33/33 OK as of the last run.**

The engine is never told what was injected. A case injects a perturbation, lets the
world run, and asserts on what the system concluded on its own.

| # | Ugly case | Source | Expected behavior | Status |
|---|---|---|---|---|
| 1 | Normal traffic for 30 min, including night-time low volume | Brief §3 "not firing on noise" | Zero incidents opened | OK |
| 2 | Weekend traffic 40% lower than weekday | Brief "weekends" | No incident (seasonal baseline absorbs it) | OK |
| 3 | Provider over-declines only in Brazil (dlocal × BR, technical) | Brief minimal case | Isolated to `provider=dlocal, country=BR`; cause: provider degraded | OK |
| 4 | Mexican issuer down, simultaneous with #3 | Brief minimal case | Two incidents, separated, ranked by cost/min | OK |
| 5 | Drop in a segment with < 40 tx / 5 min | Design (min sample) | No cause claimed anywhere; stays low-confidence | OK |
| 6 | Drop entirely made of hard declines (insufficient funds spike) | Yuno interview | No incident: hard declines excluded from the operational rate | OK |
| 7 | Mapping bug: provider says failed, we store approved | Yuno interview | Caught by the integrity scan via raw/normalized decoupling + change event; `kind=data_integrity` | OK |
| 8 | Unseen raw code appears from one provider | Yuno interview | Categorized `unknown`, code named in the signature; cause: unmapped provider code | OK |
| 9 | Stripe routed for Colombia → `country_not_supported` | Yuno interview | Cause: internal change; change event correlated | OK |
| 10 | Card network (Visa) degraded across all issuers and providers | Yuno interview (franchise flow) | Isolated to `brand=visa`, **not** to any provider | OK |
| 11 | Same issuer over-declining via all providers | Design | Cause: issuer, not provider | OK |
| 12 | Same issuer failing via one provider only | Design | Cause: provider ↔ issuer routing; recommend rerouting that BIN | OK |
| 13 | PIX down in BR (alternative method, no issuer/brand dims) | Yuno interview | Tree prunes issuer/brand; cause: method × country | OK |
| 14 | Gradual degradation (ramp 20 min) instead of abrupt | Design | Detected; "since" lands within a few minutes of the ramp start | OK |
| 15 | Incident resolves by itself | Design | Incident closes; duration and total cost recorded | OK |
| 16 | Same incident fingerprint as one 2 days ago | Brief bonus (memory) | "This already happened on X" with the past resolution | OK |
| 17 | Judge injects a never-seen dimension combination | Trial by fire | Detected and diagnosed with no code change | OK |
| 18 | Judge double-clicks "Inject" | Rule 6 (idempotency) | One injection, one incident (wall-clock window) | OK |
| 19 | Agent answers in prose instead of calling a tool | Rules 3–4 | Deterministic diagnosis, labelled with the reason | OK |
| 19b | Agent exceeds its time budget | Rules 3–4 | Budget wins; deterministic diagnosis shown | OK |
| 19c | Agent's `conclude` fails schema validation | Rule 3 | Rejected; deterministic diagnosis shown | OK |
| 19d | Well-behaved agent concludes correctly | Design | Accepted — and the money on the card is still the engine's number | OK |
| 19e | Agent reports uncertainty at high confidence | Live run | Confidence capped at 0.4; recommendation forced to "keep watching" | OK |
| 19f | Agent fills unused scope dimensions with `""` / `"any"` | Live run | Placeholders stripped before anything reaches the card | OK |
| 20 | Agent cites evidence not backed by a tool call | Design | Run rejected, fallback used | OK |
| 21 | Injection description written in Spanish | Guide §10 | Processed identically (the note is never read by the engine) | OK |
| 22 | Latency spike without decline increase | Design | Separate incident kind; cost estimated via abandonment, confidence capped at 0.45 | OK |
| 23 | Merchant volume goes to zero (merchant outage) | Design | Flagged as `no_traffic`, not as a conversion drop | OK |
| 24 | Reset pressed mid-incident | Rule 7 | Clean baseline, no ghost incidents (reset takes the sim lock) | OK |
| 25 | A closed incident's chart | UI review | Frozen, bounded 30 min either side of the incident, stops moving | OK |
| 26 | An open incident's chart | UI review | Live, starts 30 min before the incident, keeps up | OK |
| 27 | Clock speed labels | UI review | Each speed advances the clock by exactly its multiple of real time | OK |
| 28 | One failure, one record | UI review | Two injections leave two records, not a trail of superseded ones | OK |

## Cases that changed the design

Three of these were not just tests — they forced real changes:

- **#4** exposed that a small simultaneous incident never survives the global attribution
  tree next to a large one. Firing slices now get their own tree, gated by residual excess.
- **#7** exposed that a mapping bug makes conversion look *better*, so no conversion
  detector can ever catch it. It needed a separate integrity scan.
- **#11 / #12** exposed that issuers were missing from the first-level scan entirely.

And two that no case caught, because a stub is not a model:

- The evidence guardrail compared against the API's opaque call ids. Against the real API the
  agent cited tool *names* instead, so every honest answer was rejected. The stub happened to
  use ids that matched, which hid it completely. Cases **19e** and **19f** exist because of
  what the first live runs actually did.
- Placeholder scope values (`"any"`) matched zero segments, so all six tools returned empty
  and the agent declined — correctly, on data that was broken upstream of it.

And four that only came from looking at the screen: the clock ran sixty times faster than
its own label (**27**), a finished incident's chart kept sliding as if it were live (**25**),
and one outage left a trail of near-identical superseded records in the closed list (**28**).
None of these were wrong *answers* — they were answers nobody could read.

And one that only `make smoke` could find: `POST /reset` raced the simulation loop and left
ghosts, because the headless harness has no concurrent loop to race with.
