"""Transaction generator: counts first, individual transactions only as a sample.

Producing 3,000 Transaction objects per simulated minute is pointless — the engine
reasons over counters. So we draw the counters directly from the same generative
process (Poisson volume, Binomial approvals, Multinomial decline mix) and
materialize a handful of real rows per minute for the UI's live feed.
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime

from api.config import SEED
from api.domain import CATEGORIES, Transaction
from api.engine.cube import LeafKey, LeafMinute
from api.engine.stats import sample_binomial, sample_multinomial, sample_poisson
from api.sim import catalog as cat
from api.sim.injector import Injector
from api.sim.mapping import canonical_meta, normalize, novel_code, pick_raw_code

SAMPLE_TX_PER_MINUTE = 12


class Generator:
    def __init__(self, injector: Injector, seed: int = SEED) -> None:
        self.injector = injector
        self.rng = random.Random(seed)
        self.leaves = cat.leaf_cuboids()
        self.keys: list[LeafKey] = [cat.leaf_key(le) for le in self.leaves]
        weights = [cat.leaf_traffic_weight(le) for le in self.leaves]
        total_w = sum(weights)
        self.share = [w / total_w for w in weights]
        self.base_p = [cat.leaf_base_approval(le) for le in self.leaves]
        self.mix = [cat.healthy_decline_mix(le) for le in self.leaves]
        self.ticket = [cat.avg_ticket_usd(le) for le in self.leaves]
        self.latency = [cat.base_latency_ms(le) for le in self.leaves]

    # --- baseline ----------------------------------------------------------
    def build_baseline(self) -> dict[tuple[int, int], dict[LeafKey, LeafMinute]]:
        """The seasonal history, pre-aggregated per (weekday, hour) as per-minute means.

        This is what 3 weeks of generated history would average out to, computed in
        closed form. Same distribution, 57k rows instead of 10M.
        """
        out: dict[tuple[int, int], dict[LeafKey, LeafMinute]] = {}
        for dow in range(7):
            for hour in range(24):
                hf = cat.hour_factor(dow, hour)
                sf = cat.approval_season_factor(dow, hour)
                slot: dict[LeafKey, LeafMinute] = {}
                for i, lk in enumerate(self.keys):
                    attempts = self.share[i] * cat.PEAK_TPM * hf
                    p = min(0.99, self.base_p[i] * sf)
                    approved = attempts * p
                    declines = attempts - approved
                    by_cat = {c: 0.0 for c in CATEGORIES}
                    for c, w in self.mix[i].items():
                        by_cat[c] = declines * w
                    slot[lk] = LeafMinute(
                        attempts=attempts, approved=approved,
                        hard_declines=by_cat.get("hard_decline", 0.0),
                        by_category=by_cat, by_raw_code={},
                        raw_status_mismatch=0,
                        amount_sum=attempts * self.ticket[i],
                        latency_sum=attempts * self.latency[i],
                        latency_p95=int(self.latency[i] * 1.8),
                    )
                out[(dow, hour)] = slot
        return out

    # --- live --------------------------------------------------------------
    def generate_minute(self, minute: datetime) -> tuple[dict[LeafKey, LeafMinute], list[Transaction]]:
        rng = self.rng
        hf = cat.hour_factor(minute.weekday(), minute.hour)
        sf = cat.approval_season_factor(minute.weekday(), minute.hour)
        rows: dict[LeafKey, LeafMinute] = {}
        sample_pool: list[tuple[int, str, str]] = []  # (leaf idx, category, "" ) for the tx feed

        for i, lk in enumerate(self.keys):
            leaf = self.leaves[i]
            eff = self.injector.effect_for(leaf, minute)

            lam = self.share[i] * cat.PEAK_TPM * hf * eff.volume_factor * rng.uniform(0.90, 1.10)
            attempts = sample_poisson(rng, lam)
            if attempts <= 0:
                rows[lk] = LeafMinute()
                continue

            p_healthy = min(0.995, self.base_p[i] * sf)
            p_actual = min(0.995, max(0.0, p_healthy - eff.approval_delta))
            approved = sample_binomial(rng, attempts, p_actual)
            declines = attempts - approved

            # Split declines into "what would have failed anyway" and "the excess",
            # so the excess carries the signature of the failure mode.
            baseline_declines = min(declines, sample_binomial(rng, attempts, 1.0 - p_healthy))
            excess = declines - baseline_declines

            by_cat = {c: 0 for c in CATEGORIES}
            for c, n in sample_multinomial(rng, baseline_declines, self.mix[i]).items():
                by_cat[c] += n
            if excess > 0:
                push = eff.category_push or self.mix[i]
                for c, n in sample_multinomial(rng, excess, push).items():
                    by_cat[c] += n

            # An unseen provider code: our normalization cannot place it, so it lands in `unknown`.
            novel_n = 0
            if eff.novel_code_fraction > 0 and declines > 0:
                novel_n = sample_binomial(rng, declines, eff.novel_code_fraction)
                if novel_n:
                    moved = 0
                    for c in ("soft_decline", "technical", "risk_block", "config"):
                        take = min(by_cat[c], novel_n - moved)
                        by_cat[c] -= take
                        moved += take
                        if moved >= novel_n:
                            break
                    by_cat["unknown"] += moved
                    novel_n = moved

            # The mapping bug: the provider said REJECTED, our table wrote `approved`.
            # Counters get better, reality does not. `raw_status_mismatch` is the tell.
            mismatch = 0
            if eff.mismap_fraction > 0 and declines > 0:
                mismatch = sample_binomial(rng, declines, eff.mismap_fraction)
                mismatch = min(mismatch, declines)
                taken = 0
                for c in ("soft_decline", "technical", "hard_decline", "risk_block",
                          "config", "auth_required", "unknown"):
                    if taken >= mismatch:
                        break
                    take = min(by_cat[c], mismatch - taken)
                    by_cat[c] -= take
                    taken += take
                mismatch = taken
                approved += mismatch

            by_raw = self._raw_codes(rng, self.leaves[i], by_cat, approved, novel_n)
            lat = self.latency[i] * eff.latency_factor * rng.uniform(0.9, 1.15)
            rows[lk] = LeafMinute(
                attempts=attempts, approved=approved,
                hard_declines=by_cat.get("hard_decline", 0),
                by_category={c: v for c, v in by_cat.items() if v},
                by_raw_code=by_raw, raw_status_mismatch=mismatch,
                amount_sum=attempts * self.ticket[i] * rng.uniform(0.85, 1.15),
                latency_sum=attempts * lat, latency_p95=int(lat * 1.8),
            )
            if attempts and len(sample_pool) < 400:
                cats = [c for c, v in by_cat.items() if v] or ["none"]
                sample_pool.append((i, rng.choice(cats), ""))

        txs = self._sample_transactions(rng, minute, sample_pool)
        return rows, txs

    def _raw_codes(self, rng: random.Random, leaf: dict[str, str], by_cat: dict[str, int],
                   approved: int, novel_n: int) -> dict[str, int]:
        """Spread each category's count over the provider's actual codes for that category."""
        out: dict[str, int] = {}
        provider, method = leaf["provider"], leaf["method"]
        if approved:
            code, _m, _s = cat.PROVIDER_CODES[provider]["none"][0]
            out[code] = approved
        for category, count in by_cat.items():
            if count <= 0 or category in ("none",):
                continue
            if category == "unknown":
                code, _m, _s = novel_code(provider)
                out[code] = out.get(code, 0) + count
                continue
            entries = cat.PROVIDER_CODES[provider].get(category) or []
            method_entry = cat.METHOD_CODES.get(method)
            pool = [e[0] for e in entries]
            if method_entry and method_entry[3] == category:
                pool = [method_entry[0]] * 3 + pool
            if not pool:
                out[f"{category}:unspecified"] = out.get(f"{category}:unspecified", 0) + count
                continue
            weights = {c: 1.0 for c in dict.fromkeys(pool)}
            if method_entry and method_entry[0] in weights:
                weights[method_entry[0]] = 3.0
            for code, n in sample_multinomial(rng, count, weights).items():
                if n:
                    out[code] = out.get(code, 0) + n
        return out

    def _sample_transactions(self, rng: random.Random, minute: datetime,
                             pool: list[tuple[int, str, str]]) -> list[Transaction]:
        """A few real rows per minute so the UI can show actual provider payloads."""
        if not pool:
            return []
        picks = rng.sample(pool, min(SAMPLE_TX_PER_MINUTE, len(pool)))
        out: list[Transaction] = []
        for i, category, _ in picks:
            leaf = self.leaves[i]
            provider = leaf["provider"]
            eff = self.injector.effect_for(leaf, minute)
            if category == "unknown":
                raw_code, raw_msg, raw_status = novel_code(provider)
            else:
                raw_code, raw_msg, raw_status = pick_raw_code(rng, provider, leaf["method"], category)
            normalized_code, status, norm_category = normalize(provider, raw_code)
            # Reproduce the mapping bug at row level so the UI can show the disagreement.
            if eff.mismap_fraction > 0 and status != "approved" and rng.random() < eff.mismap_fraction:
                status, norm_category, normalized_code = "approved", "none", "APPROVED"
            issuer = leaf["issuer"] or None
            out.append(Transaction(
                id=f"tx_{uuid.uuid4().hex[:12]}", ts=minute, merchant_id=leaf["merchant"],
                country=leaf["country"], currency=cat.CURRENCY[leaf["country"]],
                amount=round(cat.MERCHANTS[leaf["merchant"]]["ticket"][leaf["country"]]
                             * rng.uniform(0.4, 2.2), 2),
                method=leaf["method"], provider=provider, brand=leaf["brand"] or None,
                issuer=issuer, bin=cat.BIN_PREFIX.get(issuer or "", None),
                status=status, raw_code=raw_code, raw_message=raw_msg, raw_status=raw_status,
                normalized_code=normalized_code,
                iso_8583=canonical_meta(normalized_code)[0],
                retriable=canonical_meta(normalized_code)[1],
                decline_category=norm_category,
                latency_ms=int(self.latency[i] * eff.latency_factor * rng.uniform(0.7, 1.6)),
            ))
        return out
