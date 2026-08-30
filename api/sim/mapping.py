"""Normalization layer: provider raw code -> our canonical code, status and category.

This is the layer that, in a real orchestrator, silently breaks. `PROVIDER_CODES`
in catalog.py is the provider's truth; this module is *our interpretation of it*.
A `mapping_bug` makes the two disagree, and the disagreement is what we detect —
no log integration required.
"""
from __future__ import annotations

from api.sim.catalog import METHOD_CODES, NOVEL_CODES, PROVIDER_CODES

# Cross-provider canonical codes. Two providers saying the same thing in different
# words must end up as the same normalized_code, or attribution across providers lies.
CANONICAL: dict[str, str] = {
    # approvals
    "approved": "approved", "Authorised": "approved", "200": "approved", "accredited": "approved",
    # insufficient funds
    "insufficient_funds": "insufficient_funds", "NotEnoughBalance": "insufficient_funds",
    "301": "insufficient_funds", "cc_rejected_insufficient_amount": "insufficient_funds",
    # bad card data
    "incorrect_number": "invalid_card", "InvalidCardNumber": "invalid_card", "302": "invalid_card",
    "cc_rejected_bad_filled_card_number": "invalid_card",
    "expired_card": "expired_card", "ExpiredCard": "expired_card", "303": "expired_card",
    "cc_rejected_bad_filled_date": "expired_card",
    "lost_card": "lost_or_stolen", "stolen_card": "lost_or_stolen", "304": "lost_or_stolen",
    "BlockedCard": "lost_or_stolen",
    # generic issuer refusal
    "card_declined": "do_not_honor", "do_not_honor": "do_not_honor", "Refused": "do_not_honor",
    "300": "do_not_honor", "310": "do_not_honor", "cc_rejected_other_reason": "do_not_honor",
    "try_again_later": "retry_later", "Referral": "call_issuer",
    "cc_rejected_call_for_authorize": "call_issuer",
    "TransactionNotPermitted": "not_permitted",
    # risk
    "fraudulent": "fraud_block", "FraudCancelled": "fraud_block", "305": "fraud_block",
    "cc_rejected_high_risk": "fraud_block",
    # technical
    "processing_error": "processing_error", "AcquirerError": "processing_error",
    "307": "processing_error", "internal_error": "processing_error",
    "issuer_not_available": "issuer_unavailable", "IssuerUnavailable": "issuer_unavailable",
    "306": "issuer_unavailable", "cc_rejected_max_attempts": "issuer_unavailable",
    # config
    "country_not_supported": "country_not_supported", "309": "country_not_supported",
    "collector_unsupported_country": "country_not_supported",
    "currency_not_supported": "currency_not_supported", "NotSupported": "currency_not_supported",
    "RestrictedCard": "restricted_card", "311": "method_not_enabled",
    "payment_method_not_available": "method_not_enabled",
    # auth
    "authentication_required": "3ds_required", "3DNotAuthenticated": "3ds_required",
    "308": "3ds_required", "cc_rejected_3ds_challenge": "3ds_required",
}


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


def normalize(provider: str, raw_code: str) -> tuple[str, str, str]:
    """Map a raw provider code. Anything we have never seen becomes `unknown` — loudly.

    Returning `unknown` instead of guessing is the point: an unmapped code that we
    silently treated as a decline (or an approval) is exactly the failure we hunt.
    """
    hit = NORMALIZATION.get((provider, raw_code))
    if hit is None:
        return (f"unmapped:{raw_code}", "declined", "unknown")
    return hit


def is_known(provider: str, raw_code: str) -> bool:
    return (provider, raw_code) in NORMALIZATION


def novel_code(provider: str) -> tuple[str, str, str]:
    return NOVEL_CODES.get(provider, ("999", "Undocumented response", "REJECTED"))


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
