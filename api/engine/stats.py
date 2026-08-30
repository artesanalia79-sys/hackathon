"""Small statistics kit — pure Python, no scipy/numpy.

Everything the detector and the attributor need: a regularized incomplete beta
(for the Beta posterior tail), Jensen-Shannon divergence (for signature surprise),
and samplers the generator uses.
"""
from __future__ import annotations

import math
import random

_EPS = 1e-12


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-12:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) = P(X <= x) for X ~ Beta(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def prob_rate_below(approved: int, attempts: int, threshold: float) -> float:
    """P(true rate < threshold) given approved/attempts, Jeffreys prior Beta(.5,.5).

    This is the detector's score: "how sure are we that the underlying conversion
    rate really sits below the band we expect", not "did the sample dip".
    """
    if attempts <= 0:
        return 0.0
    if threshold <= 0.0:
        return 0.0
    if threshold >= 1.0:
        return 1.0
    alpha = 0.5 + approved
    beta = 0.5 + (attempts - approved)
    return betainc(alpha, beta, threshold)


def normalize(dist: dict[str, float]) -> dict[str, float]:
    total = sum(dist.values())
    if total <= 0:
        return {k: 0.0 for k in dist}
    return {k: v / total for k, v in dist.items()}


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon divergence in bits, 0..1. Symmetric, bounded, handles zeros."""
    keys = set(p) | set(q)
    if not keys:
        return 0.0
    pn = normalize({k: max(0.0, p.get(k, 0.0)) for k in keys})
    qn = normalize({k: max(0.0, q.get(k, 0.0)) for k in keys})
    if sum(pn.values()) <= 0 or sum(qn.values()) <= 0:
        return 0.0
    div = 0.0
    for k in keys:
        pk, qk = pn[k], qn[k]
        mk = 0.5 * (pk + qk)
        if mk <= _EPS:
            continue
        if pk > _EPS:
            div += 0.5 * pk * math.log2(pk / mk)
        if qk > _EPS:
            div += 0.5 * qk * math.log2(qk / mk)
    return max(0.0, min(1.0, div))


def jaccard(a: dict[str, str], b: dict[str, str]) -> float:
    """Jaccard over (key, value) pairs — two scopes are close if they pin the same things."""
    sa = {(k, v) for k, v in a.items()}
    sb = {(k, v) for k, v in b.items()}
    if not sa and not sb:
        return 1.0
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


# --- samplers ---------------------------------------------------------------

def sample_binomial(rng: random.Random, n: int, p: float) -> int:
    """Binomial draw. Exact for small n, normal approximation above 60 trials."""
    if n <= 0:
        return 0
    p = min(1.0, max(0.0, p))
    if p <= 0.0:
        return 0
    if p >= 1.0:
        return n
    if n <= 60:
        return sum(1 for _ in range(n) if rng.random() < p)
    mean = n * p
    sd = math.sqrt(n * p * (1.0 - p))
    return max(0, min(n, round(rng.gauss(mean, sd))))


def sample_poisson(rng: random.Random, lam: float) -> int:
    """Poisson draw. Knuth for small lambda, normal approximation above 30."""
    if lam <= 0:
        return 0
    if lam < 30:
        target = math.exp(-lam)
        k, prod = 0, 1.0
        while True:
            prod *= rng.random()
            if prod <= target:
                return k
            k += 1
            if k > 1000:
                return k
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def sample_multinomial(rng: random.Random, n: int, weights: dict[str, float]) -> dict[str, int]:
    """Split n items across weighted buckets via sequential conditional binomials."""
    out = {k: 0 for k in weights}
    total = sum(max(0.0, w) for w in weights.values())
    if n <= 0 or total <= 0:
        return out
    remaining = n
    remaining_w = total
    for key in list(weights):
        w = max(0.0, weights[key])
        if remaining <= 0:
            break
        if remaining_w <= _EPS:
            break
        p = min(1.0, w / remaining_w)
        drawn = sample_binomial(rng, remaining, p)
        out[key] = drawn
        remaining -= drawn
        remaining_w -= w
    if remaining > 0:  # rounding slack goes to the heaviest bucket
        top = max(weights, key=lambda k: weights[k])
        out[top] += remaining
    return out
