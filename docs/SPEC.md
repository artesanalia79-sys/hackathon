# SPEC.md — Control Tower (NextWave 2026, Challenge 02)

## Problem
A payment orchestrator (PagoTotal) sees every transaction from several providers. Conversion drops silently and for many reasons. Today a human crosses filters by hand to find *where* and *why*. We build a system that watches the stream, detects drops that matter, isolates the root cause across dimensions, explains it with evidence and money, and recommends (never executes) an action.

## Our mechanism
**Decline-signature attribution: instead of alerting on a rate drop, we isolate the segment whose mix of decline codes changed and cross it with internal change events.**
- A rate drop is a symptom. The *distribution of decline categories* per segment is the fingerprint of the cause (issuer, provider, card network, method, internal mapping/config).
- Internal vs. external is inferred from data, not from logs: raw provider code vs. normalized status decoupling, unseen raw codes, and a mock change-event stream (deploys, mapping changes, routing rules).
- The diagnosis is done by an **agent that can only assert what its tools returned**, on top of a deterministic statistical engine. If the agent fails, times out, or produces invalid JSON, the deterministic engine's diagnosis is shown instead.

## Walking skeleton (must exist by 13:00 Sat)
1. Synthetic transaction generator with seasonal baseline (hour × weekday) and 2–4 weeks of history.
2. Per-minute counters per cuboid (merchant × country × method × brand × issuer × provider × decline_category).
3. One global binomial detector (5-min sensitive window, 30-min confirmation window, min sample).
4. One incident card in the UI showing: what, since when, observed vs. expected, cost/min.

## Then, in order
Injection form (judges' input surface) → deterministic recursive Adtributor → provider code catalog + signature classification → cost model → two simultaneous incidents → change events + `mapping_bug` → incident memory → agent over tools → two-audience narration → polish.

## Scope
- Countries: CO, BR, MX. Merchants: 3. Providers: stripe, adyen, dlocal, mercadopago (+ optional local acquirer).
- Methods: card (brand + issuer), pse, nequi, daviplata, breb (CO); pix, boleto (BR); spei, codi, dimo, oxxo (MX).
- Hard declines (insufficient funds, wrong card data, lost/stolen) are excluded from the operational conversion rate.
- Out of scope: real Datadog/Slack integration, remediation, i18n, multi-tenant auth.

## Stack (decided before the event)
Python 3.12 + FastAPI (engine, API, agent loop) · React (UI) · SQLite (counters, incidents, memory) · OpenAI Responses API with tool calling (agent) · one-command deploy.

## Definition of done (mirrors the judges' lenses)
- Runs end to end; judges inject any dimension combination via the form and the system detects + diagnoses without the team touching anything.
- Never fires on noise; says "insufficient evidence" when n is too small.
- Two simultaneous incidents are separated and ranked by cost/min.
- Every claim in a diagnosis is traceable to a tool call visible in the trace panel.
- `make eval` reports pass / degraded / failed over UGLY_CASES.md.
