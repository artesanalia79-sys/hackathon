"""Normalization layer: provider raw code -> our canonical code, status and category.

This is the layer that, in a real orchestrator, silently breaks. `PROVIDER_CODES`
in catalog.py is the provider's truth; this module is *our interpretation of it*.
A `mapping_bug` makes the two disagree, and the disagreement is what we detect —
no log integration required.
"""
from __future__ import annotations

import hashlib

from api.sim.catalog import METHOD_CODES, NOVEL_APPROVED_CODES, NOVEL_CODES, PROVIDER_CODES

# Cross-provider canonical codes. Two providers saying the same thing in different
# words must end up as the same normalized_code, or attribution across providers lies.
#
# The vocabulary is Yuno's own `response_code` set, not names we made up: it is what an
# orchestrator in this market actually publishes, and it is what a payments jury
# recognises on sight.
# https://docs.y.uno/reference/payments/status-and-response-codes/transaction
CANONICAL: dict[str, str] = {
    # approvals
    "approved": "APPROVED", "Authorised": "APPROVED", "200": "APPROVED",
    "accredited": "APPROVED",
    # insufficient funds
    "insufficient_funds": "INSUFFICIENT_FUNDS", "NotEnoughBalance": "INSUFFICIENT_FUNDS",
    "301": "INSUFFICIENT_FUNDS", "cc_rejected_insufficient_amount": "INSUFFICIENT_FUNDS",
    # bad card data
    "incorrect_number": "INVALID_CARD_NUMBER", "InvalidCardNumber": "INVALID_CARD_NUMBER",
    "302": "INVALID_CARD_NUMBER", "cc_rejected_bad_filled_card_number": "INVALID_CARD_NUMBER",
    "expired_card": "EXPIRED_CARD", "ExpiredCard": "EXPIRED_CARD", "303": "EXPIRED_CARD",
    "cc_rejected_bad_filled_date": "EXPIRED_CARD",
    "lost_card": "REPORTED_LOST", "304": "REPORTED_LOST",
    "stolen_card": "REPORTED_STOLEN",
    "BlockedCard": "RESTRICTED_BY_BANK",
    # generic issuer refusal
    "card_declined": "DECLINED_BY_BANK", "cc_rejected_other_reason": "DECLINED_BY_BANK",
    "do_not_honor": "DO_NOT_HONOR", "Refused": "DO_NOT_HONOR", "300": "DO_NOT_HONOR",
    "310": "DO_NOT_HONOR",
    "try_again_later": "TRY_AGAIN_LATER",
    "Referral": "REFER_TO_CARD_ISSUER",
    "cc_rejected_call_for_authorize": "CALL_FOR_AUTHORIZE",
    "TransactionNotPermitted": "USER_RESTRICTION",
    "cc_rejected_max_attempts": "USER_RESTRICTION",
    # risk
    "fraudulent": "FRAUD_VALIDATION", "FraudCancelled": "FRAUD_VALIDATION",
    "305": "FRAUD_VALIDATION", "cc_rejected_high_risk": "FRAUD_VALIDATION",
    # technical
    "processing_error": "ACQUIRE_CONTINGENCY", "AcquirerError": "ACQUIRE_CONTINGENCY",
    "307": "ACQUIRE_CONTINGENCY", "internal_error": "ACQUIRE_CONTINGENCY",
    "issuer_not_available": "ACQUIRE_CONTINGENCY", "IssuerUnavailable": "ACQUIRE_CONTINGENCY",
    "306": "ACQUIRE_CONTINGENCY",
    "AB03": "PROVIDER_TIMEOUT", "2103": "PROVIDER_TIMEOUT",
    # config
    "country_not_supported": "COUNTRY_NOT_SUPPORTED", "309": "COUNTRY_NOT_SUPPORTED",
    "collector_unsupported_country": "COUNTRY_NOT_SUPPORTED",
    "currency_not_supported": "CURRENCY_NOT_ALLOWED", "NotSupported": "CURRENCY_NOT_ALLOWED",
    "RestrictedCard": "RESTRICTED_BY_BANK",
    "311": "INVALID_MERCHANT", "payment_method_not_available": "INVALID_MERCHANT",
    # auth
    "authentication_required": "THREE_D_SECURE_REQUIRED",
    "3DNotAuthenticated": "THREE_D_SECURE_REQUIRED",
    "308": "THREE_D_SECURE_REQUIRED", "cc_rejected_3ds_challenge": "THREE_D_SECURE_REQUIRED",
}

# Two facts per canonical code, and they are the two an operator actually acts on.
#
# `iso_8583` is the anchor: every card acquirer on earth ends up speaking ISO 8583, so
# this column is what lets someone check our taxonomy against their own switch. Where
# Yuno collapses several ISO codes into one response_code we keep the full ISO list
# rather than picking one — the collapsing is Yuno's, and hiding it would be our lie.
#
# `retriable` is the difference between a retry that can work and a retry that burns a
# BIN's reputation for nothing: "no" means the answer will not change on its own, and
# "conditional" means it depends on something outside the transaction (the cardholder
# calling the bank, a limit resetting, the merchant enabling the rail).
CANONICAL_META: dict[str, tuple[str, str]] = {
    # canonical code            ISO 8583                retriable
    "APPROVED":                 ("00",                  "n/a"),
    "INSUFFICIENT_FUNDS":       ("51",                  "yes"),
    "DO_NOT_HONOR":             ("05",                  "yes"),
    "DECLINED_BY_BANK":         ("05",                  "yes"),
    "TRY_AGAIN_LATER":          ("91",                  "yes"),
    "REFER_TO_CARD_ISSUER":     ("01",                  "conditional"),
    "CALL_FOR_AUTHORIZE":       ("01",                  "conditional"),
    "USER_RESTRICTION":         ("57",                  "conditional"),
    "RESTRICTED_BY_BANK":       ("62",                  "conditional"),
    "INVALID_CARD_NUMBER":      ("14",                  "no"),
    "EXPIRED_CARD":             ("33/54",               "no"),
    "REPORTED_LOST":            ("41",                  "no"),
    "REPORTED_STOLEN":          ("43",                  "no"),
    "ISSUER_VIOLATION":         ("93",                  "no"),
    "FRAUD_VALIDATION":         ("34/59/63/64",         "no"),
    "ACQUIRE_CONTINGENCY":      ("22/80/90/91/92/96",   "yes"),
    "PROVIDER_TIMEOUT":         ("68",                  "yes"),
    "TERMINAL_ERROR":           ("",                    "yes"),
    "DUPLICATED_TRANSACTION":   ("26/94",               "no"),
    "INVALID_MERCHANT":         ("03",                  "no"),
    "COUNTRY_NOT_SUPPORTED":    ("",                    "no"),
    "CURRENCY_NOT_ALLOWED":     ("",                    "no"),
    "THREE_D_SECURE_REQUIRED":  ("",                    "yes"),
    "UNKNOWN_ERROR":            ("",                    "yes"),
}


def canonical_meta(normalized_code: str) -> tuple[str, str]:
    """(ISO 8583 code, retriable) for a canonical code. Unknown stays unknown."""
    return CANONICAL_META.get(normalized_code, ("", "unknown"))


def _build_table() -> dict[tuple[str, str], tuple[str, str, str]]:
    """(provider, raw_code) -> (normalized_code, status, category)."""
    table: dict[tuple[str, str], tuple[str, str, str]] = {}
    for provider, by_cat in PROVIDER_CODES.items():
        for category, entries in by_cat.items():
            for raw_code, _msg, raw_status in entries:
                status = "approved" if raw_status == "APPROVED" else ("error" if raw_status == "ERROR" else "declined")
                table[(provider, raw_code)] = (CANONICAL.get(raw_code, raw_code), status, category)
    for raw_code, _msg, raw_status, category in METHOD_CODES.values():
        status = "approved" if raw_status == "APPROVED" else ("error" if raw_status == "ERROR" else "declined")
        for provider in PROVIDER_CODES:
            table[(provider, raw_code)] = (CANONICAL.get(raw_code, raw_code), status, category)
    return table


NORMALIZATION = _build_table()


def normalize(provider: str, raw_code: str,
              raw_status: str | None = None) -> tuple[str, str, str]:
    """Map a raw provider code. Anything we have never seen becomes `unknown` — loudly.

    We do not guess where an unseen code belongs: guessing is the exact failure this
    product exists to catch, and a code placed in the "closest looking" bucket is a code
    nobody will ever go and map. `unknown` is the honest answer, and the detector turns
    it into an incident with the literal attached.

    An unmapped APPROVAL still comes back as `declined`, on purpose: that is exactly what
    a real orchestrator does when its table has no entry, and it is the bug worth showing.
    The provider's own `raw_status` travels beside it untouched, so the row on screen says
    APPROVED next to our `declined` — the contradiction is the evidence. An unmapped
    ERROR, on the other hand, is recorded as an error, because there we lose nothing by
    being faithful.
    """
    hit = NORMALIZATION.get((provider, raw_code))
    if hit is None:
        status = "error" if raw_status == "ERROR" else "declined"
        return (f"unmapped:{raw_code}", status, "unknown")
    return hit


def is_known(provider: str, raw_code: str) -> bool:
    return (provider, raw_code) in NORMALIZATION


_FALLBACK_NOVEL = ("999", "Undocumented response", "REJECTED")


def novel_code(provider: str, sources: list[str] | None = None) -> tuple[str, str, str]:
    """The unseen code this provider is emitting, fixed for the life of one injection.

    Keyed off the injection id rather than the clock: within an incident the literal has
    to stay put (one upstream change emits one new code, and the operator is going to
    read it off the card), while two separate injections should not look identical.
    """
    pool = NOVEL_CODES.get(provider)
    if not pool:
        return _FALLBACK_NOVEL
    if not sources:
        return pool[0]
    seed = hashlib.sha1("|".join(sorted(sources)).encode()).hexdigest()
    return pool[int(seed[:8], 16) % len(pool)]


def novel_approved_code(provider: str) -> tuple[str, str, str]:
    """An unseen code the provider returned as an approval."""
    return NOVEL_APPROVED_CODES.get(provider, ("998", "Undocumented approval", "APPROVED"))


def pick_raw_code(rng, provider: str, method: str, category: str) -> tuple[str, str, str]:
    """What the provider mock returns for a given outcome category."""
    if category != "none" and method in METHOD_CODES:
        code, msg, raw_status, cat = METHOD_CODES[method]
        # Use the method-specific code when it matches the category we intend to emit.
        if cat == category and rng.random() < 0.75:
            return code, msg, raw_status
    entries = PROVIDER_CODES[provider].get(category)
    if not entries:
        entries = PROVIDER_CODES[provider]["soft_decline"]
    return rng.choice(entries)
