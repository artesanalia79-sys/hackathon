# NEXT_STEPS_2.md — the action layer, and what is left

Follow-up to `NEXT_STEPS.md`. That document was an audit of what was *wrong*. This one is
about what is *missing*: the half of the challenge that says **recommend an action**.

Written against `main` at `014dc46`, after Team A's branch (`f1fa267`) merged.
`make eval` on this tree: **33 pass · 0 degraded · 0 failed** (102 s). Nothing below is
blocked on a red suite.

---

## 0. Where the repo actually stands

**Team A (engine and data) landed almost everything.** Verified in the current tree, not
in the plan:

| Item | State | Evidence |
|---|---|---|
| A1.1 `fingerprint()` ignores `kind` | done | `api/engine/incidents.py:16` now takes `kind` |
| A1.2 "cost so far" frozen at $0 | done | accrues per tick, `api/engine/detector.py:118` |
| A1.3 agent confidence overrides the engine | done | cap in `api/agent/loop.py` |
| A1.4 agent writes money in its own prose | done | money stripped from the tool payload (`api/agent/tools.py:53-72`) + `_money_in_prose()` rejection in `loop.py` |
| A1.5 self-contradicting "insufficient evidence" | done | `api/engine/signature.py` |
| A1.6 `p0` chases the incident | done | frozen EWMA while an incident is open, `api/engine/expectation.py:66-79` |
| A2.1 Yuno canonical vocabulary | done | `api/sim/mapping.py`, commit `a8aae84` |
| A2.2 `normalize()` on the counting path | done | commit `ffd3c83` |
| A2.3 unmapped code arriving as an approval | done | commit `6716d92` |
| A2.4 varied novel codes | done | commit `6716d92` |
| A2.5 invented `METHOD_CODES` | done | commit `31e7453` |

**Team B (eval, UI, docs) has not started.** The UI moved a lot (redesign, `Chart.jsx`,
`Scope.jsx`, `Resizer.jsx`), but none of the B1/B2 items were touched. Still open, all of
them verified in the current tree — see §4.

So the engine is in good shape and the *presentation and proof* side is where the
remaining rubric points are. That is also where the action layer lives.

---

## 1. The gap you spotted: we diagnose, we do not hand over an action

The challenge asks for a recommended action. What the system produces today is **one
generic sentence from a static table**, plus an Acknowledge button.

- `api/engine/signature.py:40` — `RECOMMENDATION` is `cause_type → (action, rationale)`,
  eleven fixed strings. `provider_degraded` always says *"Reroute the affected traffic
  away from this provider"*.
- `api/domain.py:150` — `Recommendation` is `action: str`, `rationale: str`,
  `not_executed: True`. Nothing structured.
- `ui/src/components/IncidentCard.jsx:242-256` — renders those two strings and an
  Acknowledge button that only writes `acknowledged_by`
  (`api/routes/incidents.py:131`).

Everything upstream of that line is specific: the attribution isolated
`provider=dlocal, country=BR`, the signature named the decline categories, the cost model
priced it per minute. Then the last step — the one the challenge names explicitly —
throws the specificity away and prints a sentence that would read identically for a
different provider, a different country, a different day.

Three concrete things a payments operator would ask that we cannot answer:

1. **Reroute to *what*?** We know `("BR","card") → [dlocal, adyen, stripe, mercadopago]`
   (`api/sim/catalog.py:32`) and we can measure each one's current rate on the same
   segment. We never look.
2. **What does it buy me?** We price the bleeding but not the recovery. "Reroute" and
   "keep watching" are presented with the same weight.
3. **Did anyone do it, and did it work?** An incident that resolves looks identical
   whether someone acted or it healed on its own. `find_similar_incidents`
   (`api/engine/memory.py:21`) returns duration and cost of past occurrences — never what
   resolved them.

That last one is the interesting one, because **the fix strengthens the "never executes"
guarantee instead of weakening it**: recording a human decision, with a timestamp and an
author, is the audit trail that proves a human was in the loop.

---

## 2. What to build — the action layer, in four increments

Each increment is independently shippable and independently demoable. Stop wherever the
clock runs out.

### 2.1 Make the recommendation name the thing — ~40 min · engine · highest value/effort

Extend `Recommendation` (`api/domain.py:150`) with optional structured fields, and fill
them in `api/engine/diagnose.py:133` from the cause type plus the already-isolated scope:

```python
class Recommendation(BaseModel):
    action: str
    rationale: str = ""
    not_executed: Literal[True] = True
    target: dict[str, str] = {}       # the scope the action applies to
    alternatives: list[dict] = []     # filled by 2.2 for reroute-shaped actions
    owner: str = ""                   # payments platform | issuer relations | merchant success
    verification: str = ""            # what to watch to know it worked
    revert: str | None = None         # change_event id for internal_change / mapping_bug
```

`owner` and `verification` are one more column each in the `RECOMMENDATION` table —
cheap, and they turn a sentence into something a human can pick up. `revert` already
exists in the record as `related_change_event_ids`; it just is not carried through.

**Done when:** the card says *"Reroute BR card traffic away from dlocal"* — with the
scope named — instead of *"Reroute the affected traffic away from this provider"*, and
`make eval` is still green.

### 2.2 The counterfactual: where to reroute, and what it recovers — ~60 min · engine + UI · the demo moment

New read-only endpoint `GET /incidents/{id}/action-preview`. For a reroute-shaped cause
(`provider_degraded`, `issuer_provider_routing`), take the incident scope, drop the
`provider` pin, and for every other provider serving that `(country, method)`:

- its observed rate right now on the same segment, and its sample size,
- whether it is itself below *its own* baseline (`Expector.expect`, same call the
  detector uses — a sick alternative must be disqualified, not recommended),
- projected recovery: `(alt_rate − observed_rate) × attempts_per_min × avg_ticket ×
  (1 − recoverability)`, using `api/engine/cost.py` so the number is the same model as
  the bleeding figure it is compared against.

`compare_across` (`api/agent/tools.py:94`) already computes most of this per dimension
value; this is that computation pointed at a decision instead of at an explanation.

Two guardrails that make it honest, and both are good on stage:

- **`network_degraded` and `method_down` must return "no alternative recovers this"**,
  with the numbers showing every provider equally hurt. That is the exact claim the
  signature classifier makes structurally (`spread_across`), now shown as money.
- If no alternative clears the current rate by a margin, say so. Never manufacture a
  recommendation to fill the panel.

**Done when:** on a `dlocal × BR` injection the card shows the surviving providers with
their live rates and a projected `$/min` recovered, and on a `visa` network injection the
same panel says nowhere to go — from the same code path, with no special casing.

### 2.3 The decision trail — ~40 min · engine + UI

`POST /incidents/{id}/actions` with `{action: str, taken_by: str, note: str}`. It records
a human decision on `IncidentRecord`. It does **not** touch the simulation, the injector,
or anything else — same discipline as `ack`, one more field.

What it unlocks, all of it presentation, none of it new machinery:

- A marker on the incident chart at the simulated minute the decision was logged
  (`Chart.jsx` already draws threshold lines — this is one more).
- On resolution: *"recovered 7 min after the reroute was logged"* versus *"recovered on
  its own; no action was logged"*. Both are true statements the system can now make.
- `find_similar_incidents` (`api/engine/memory.py:21`) gains one field: what was logged
  last time and how long recovery took. "We have seen this before" becomes "we have seen
  this before, and this is what closed it."

**Done when:** logging an action on an open incident, then stopping the injection,
produces a card that states the recovery relative to the logged decision, and the record
survives in memory for the next occurrence.

### 2.4 The handoff artifact — ~30 min · UI only

A **Copy incident brief** button that produces a paste-ready block: cause, scope, since,
observed vs expected, `$/min` and total, the top evidence lines with their tool-call ids,
the recommended action with its alternatives, and the "not executed" line. Optionally a
second button for the JSON payload of the routing change — **displayed, never sent**.

Cheap, and it closes the loop a judge will imagine anyway: what does the operator
actually do with this card at 3am.

---

## 3. Other things worth the remaining time, ranked

1. **Confidence above the recommendation** (B1.3, still open — `IncidentCard.jsx:242`
   vs `:261`). A confident-sounding narration sits eight blocks above the number that
   qualifies it. Move it up and treat anything under ~0.5 visually. 20 min.
2. **The board shows records the API hides** (B1.1, still open — `IncidentList.jsx:5-7`
   filters on `status` only, and the SSE snapshot at `api/routes/stream.py:33` does not
   filter `superseded_by` either). Two injections can leave three or more rows. This is
   the one item the previous audit called blocking, and it is still there. 10 min.
3. **Recommendation coverage in eval** (B2.3). Nothing asserts that each row of
   `RECOMMENDATION` produces its expected action. With §2.1 and §2.2 landing on exactly
   that table, these tests are what keeps them honest. One case per row. 30 min.
4. **`DECISIONS.md`** (B2.4). Still does not exist; thirteen `[changed]` markers in
   `docs/ARCHITECTURE.md` and four generic commit messages are carrying all of it. The
   `sim_speed` 60× unit bug, the dLocal outage fragmenting into twelve incidents, the
   thirteen records from two injections, the agent evidence guardrail rejecting honest
   answers, SQLite dropped for a single in-memory owner. 40 min.
5. **Cases #29–35** (B2.1, B2.2). Team A changed the code these were written against —
   the unmapped-code path now really runs through `normalize()`, so #29 and #30 may pass
   on arrival. Write them and record the verdict either way. 40 min.
6. **Three inline colors from the redesign** (B1.2, still open): `IncidentCard.jsx:248`
   (`#fbbf24`, the "Not executed" line — the sentence the whole pitch rests on),
   `IncidentList.jsx:50` (`#a78bfa`), `TracePanel.jsx:60` (`#34d399`). 10 min.
7. **Leftovers**: delete `ui/src/components/Injector.jsx` (dead since `InjectPanel.jsx`);
   `IncidentCard.jsx:112` still hardcodes `- 0.05` for the chart's alert threshold
   instead of reading the `baseline` block the API returns. 10 min.

---

## 4. Deliberately not doing

- **Executing anything.** No reroute is applied, no config is written, no injection is
  cancelled by an "action". The whole value of §2.3 is that it records a *human* decision;
  if the system acted, the audit trail would be worthless and the pitch would be false.
- **An LLM anywhere near the action.** The alternatives and the projected recovery come
  from the cube and `cost.py`. The agent may phrase the recommendation, as it does today,
  but every number stays the engine's — the rule that already survives to the screen via
  `refresh_numbers` (`api/routes/incidents.py:100`).
- **Rewriting the recommendation table into something generated.** Eleven explicit rows a
  judge can read beat a clever derivation nobody can audit in the room.

---

## 5. Open questions for the team

1. **Does the action layer beat the eval/docs backlog for the remaining hours?** §2.1 +
   §2.2 is roughly 100 minutes and is the most visible unclaimed rubric point. §3.1–3.2
   is 30 minutes and fixes things a judge could stumble into. My read: do §3.1, §3.2,
   then §2.1, §2.2, then reassess.
2. **Is the decision trail (§2.3) worth 40 minutes**, or does it read as scope creep to a
   judge who already heard "it never executes"? It is the strongest answer to "and then
   what happens", but it is the one increment that adds a new verb to the product.
3. **The two questions from the previous audit are still unanswered**: the ceiling on
   `cost_per_min` (an extreme case reaches $176M/day for one merchant), and whether shadow
   suppression should keep hiding a genuine second incident that shares traffic with a
   big one. Both are product calls, not bugs.
4. **Should Inject stay disabled below the minimum sample?** (`InjectPanel.jsx`) It
   currently prevents a judge from seeing "insufficient evidence" live — which is an
   explicit definition-of-done item.

---

## 6. If there is only one hour

`§3.2` (10 min, blocking) → `§3.1` (20 min) → `§2.1` (40 min).

That leaves the board honest, the confidence visible where it qualifies the narration,
and a recommendation that names the provider, the country and the owner instead of a
sentence that fits any incident.
