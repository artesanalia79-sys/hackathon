"""The simulated world: merchants, corridors, providers, and the raw code tables.

One source of truth. `PROVIDER_CODES` is what the provider mocks *return*;
`api/sim/mapping.py` derives the normalization table from it, so a mapping bug
is a divergence between the two rather than a special case sprinkled around.
"""
from __future__ import annotations

import hashlib

# --- merchants --------------------------------------------------------------
# Tickets are local currency. Calibrated so the volume-weighted average across the whole
# platform lands at ~$20 USD, which is the LatAm e-commerce ticket a judge will recognise;
# the per-vertical spread (retail ~$12, subscriptions ~$7, travel ~$72) is what makes one
# incident worth more than another.
MERCHANTS: dict[str, dict] = {
    "m_fastcart": {"name": "FastCart", "vertical": "retail", "ticket": {"CO": 48_000.0, "BR": 65.0, "MX": 205.0}},
    "m_streamly": {"name": "Streamly", "vertical": "subscriptions", "ticket": {"CO": 28_000.0, "BR": 37.9, "MX": 119.0}},
    "m_viajesya": {"name": "ViajesYa", "vertical": "travel", "ticket": {"CO": 290_000.0, "BR": 390.0, "MX": 1_220.0}},
}

CURRENCY = {"CO": "COP", "BR": "BRL", "MX": "MXN"}

# --- methods & providers ----------------------------------------------------
METHODS_BY_COUNTRY: dict[str, list[str]] = {
    "CO": ["card", "pse", "nequi", "daviplata", "breb"],
    "BR": ["card", "pix", "boleto"],
    "MX": ["card", "spei", "codi", "dimo", "oxxo"],
}

# Which providers can actually run each method in each country.
PROVIDERS_BY_METHOD: dict[tuple[str, str], list[str]] = {
    ("CO", "card"): ["dlocal", "adyen", "stripe", "mercadopago"],
    ("CO", "pse"): ["dlocal", "mercadopago"],
    ("CO", "nequi"): ["dlocal", "mercadopago"],
    ("CO", "daviplata"): ["dlocal"],
    ("CO", "breb"): ["dlocal"],
    ("BR", "card"): ["dlocal", "adyen", "stripe", "mercadopago"],
    ("BR", "pix"): ["dlocal", "adyen", "mercadopago"],
    ("BR", "boleto"): ["dlocal", "mercadopago"],
    ("MX", "card"): ["dlocal", "adyen", "stripe", "mercadopago"],
    ("MX", "spei"): ["dlocal", "stripe"],
    ("MX", "codi"): ["dlocal"],
    ("MX", "dimo"): ["mercadopago"],
    ("MX", "oxxo"): ["dlocal", "stripe", "mercadopago"],
}

BRANDS = ["visa", "mastercard"]

ISSUERS_BY_COUNTRY: dict[str, list[str]] = {
    "CO": ["bancolombia", "davivienda", "bbva_co", "banco_bogota"],
    "BR": ["itau", "bradesco", "nubank", "santander_br"],
    "MX": ["banorte", "bbva_mx", "santander_mx", "banamex"],
}

# Share of a country's card traffic per issuer (roughly matches real concentration).
ISSUER_SHARE: dict[str, float] = {
    "bancolombia": 0.40, "davivienda": 0.25, "bbva_co": 0.20, "banco_bogota": 0.15,
    "itau": 0.32, "bradesco": 0.26, "nubank": 0.27, "santander_br": 0.15,
    "banorte": 0.30, "bbva_mx": 0.34, "santander_mx": 0.21, "banamex": 0.15,
}
BRAND_SHARE = {"visa": 0.58, "mastercard": 0.42}
PROVIDER_SHARE = {"dlocal": 0.38, "adyen": 0.24, "stripe": 0.20, "mercadopago": 0.18}

# Share of a country's volume per method, and per merchant.
METHOD_SHARE: dict[tuple[str, str], float] = {
    ("CO", "card"): 0.46, ("CO", "pse"): 0.22, ("CO", "nequi"): 0.18,
    ("CO", "daviplata"): 0.09, ("CO", "breb"): 0.05,
    ("BR", "card"): 0.44, ("BR", "pix"): 0.44, ("BR", "boleto"): 0.12,
    ("MX", "card"): 0.52, ("MX", "spei"): 0.22, ("MX", "oxxo"): 0.16,
    ("MX", "codi"): 0.06, ("MX", "dimo"): 0.04,
}
COUNTRY_SHARE = {"CO": 0.38, "BR": 0.36, "MX": 0.26}
MERCHANT_SHARE = {"m_fastcart": 0.50, "m_streamly": 0.33, "m_viajesya": 0.17}

# Peak attempts per minute across the whole platform (scaled by seasonality below).
PEAK_TPM = 3200.0

BIN_PREFIX = {
    "bancolombia": "450879", "davivienda": "455174", "bbva_co": "477198", "banco_bogota": "421865",
    "itau": "515590", "bradesco": "544731", "nubank": "526398", "santander_br": "498407",
    "banorte": "547096", "bbva_mx": "491777", "santander_mx": "557904", "banamex": "544041",
}

# --- provider raw codes -----------------------------------------------------
# PROVIDER_CODES[provider][category] -> list of (raw_code, raw_message, raw_status)
_A = "APPROVED"
_R = "REJECTED"
_E = "ERROR"

PROVIDER_CODES: dict[str, dict[str, list[tuple[str, str, str]]]] = {
    "stripe": {
        "none": [("approved", "Payment succeeded", _A)],
        "hard_decline": [
            ("insufficient_funds", "Your card has insufficient funds.", _R),
            ("incorrect_number", "The card number is incorrect.", _R),
            ("expired_card", "The card has expired.", _R),
            ("lost_card", "The card was reported lost.", _R),
            ("stolen_card", "The card was reported stolen.", _R),
        ],
        "soft_decline": [
            ("card_declined", "The card was declined.", _R),
            ("do_not_honor", "The issuer declined without a reason.", _R),
            ("try_again_later", "The issuer asked to retry later.", _R),
        ],
        "risk_block": [("fraudulent", "Payment blocked as likely fraud.", _R)],
        "technical": [
            ("processing_error", "An error occurred while processing the card.", _E),
            ("issuer_not_available", "The issuer could not be reached.", _E),
        ],
        "config": [
            ("country_not_supported", "This country is not supported for this account.", _R),
            ("currency_not_supported", "The currency is not supported.", _R),
        ],
        "auth_required": [("authentication_required", "The card requires authentication.", _R)],
    },
    "adyen": {
        "none": [("Authorised", "Authorised", _A)],
        "hard_decline": [
            ("NotEnoughBalance", "Not enough balance", _R),
            ("InvalidCardNumber", "Invalid Card Number", _R),
            ("ExpiredCard", "Expired Card", _R),
            ("BlockedCard", "Blocked Card", _R),
        ],
        "soft_decline": [
            ("Refused", "Refused", _R),
            ("Referral", "Referral", _R),
            ("TransactionNotPermitted", "Transaction Not Permitted", _R),
        ],
        "risk_block": [("FraudCancelled", "FRAUD-CANCELLED", _R)],
        "technical": [
            ("AcquirerError", "Acquirer Error", _E),
            ("IssuerUnavailable", "Issuer Unavailable", _E),
        ],
        "config": [
            ("RestrictedCard", "Restricted Card", _R),
            ("NotSupported", "Not supported", _R),
        ],
        "auth_required": [("3DNotAuthenticated", "3D Not Authenticated", _R)],
    },
    "dlocal": {
        "none": [("200", "The payment was paid", _A)],
        "hard_decline": [
            ("301", "Rejected by bank - insufficient funds", _R),
            ("302", "Rejected by bank - invalid card number", _R),
            ("303", "Rejected by bank - card expired", _R),
            ("304", "Rejected by bank - card reported lost", _R),
        ],
        "soft_decline": [
            ("300", "The payment was rejected", _R),
            ("310", "Rejected by bank - do not honor", _R),
        ],
        "risk_block": [("305", "Rejected by risk engine", _R)],
        "technical": [
            ("306", "Issuer unavailable, please retry", _E),
            ("307", "Processing error at the acquirer", _E),
        ],
        "config": [
            ("309", "Country not supported for this merchant", _R),
            ("311", "Payment method not enabled", _R),
        ],
        "auth_required": [("308", "3DS authentication required", _R)],
    },
    "mercadopago": {
        "none": [("accredited", "Payment accredited", _A)],
        "hard_decline": [
            ("cc_rejected_insufficient_amount", "Insufficient amount", _R),
            ("cc_rejected_bad_filled_card_number", "Bad filled card number", _R),
            ("cc_rejected_bad_filled_date", "Bad filled expiration date", _R),
        ],
        "soft_decline": [
            ("cc_rejected_other_reason", "Rejected for another reason", _R),
            ("cc_rejected_call_for_authorize", "Call for authorize", _R),
        ],
        "risk_block": [("cc_rejected_high_risk", "Rejected by risk", _R)],
        "technical": [
            ("internal_error", "Internal error at the processor", _E),
            ("cc_rejected_max_attempts", "Issuer timed out after retries", _E),
        ],
        "config": [
            ("payment_method_not_available", "Payment method not available", _R),
            ("collector_unsupported_country", "Collector does not support this country", _R),
        ],
        "auth_required": [("cc_rejected_3ds_challenge", "3DS challenge required", _R)],
    },
}

# Method-flavoured technical codes: an APM failure does not look like a card failure.
# Two of these are the real, documented codes; the other eight are illustrative and
# labelled as such below. Do not present an illustrative one as a real scheme code:
# for most alternative rails in LatAm the rejection catalogue is simply not public.
METHOD_CODES: dict[str, tuple[str, str, str, str]] = {
    # method -> (raw_code, raw_message, raw_status, category)

    # REAL. PIX rejections travel as ISO 20022 reason codes in pacs.002 (`codigoDeErro`).
    # BACEN Informe SPI-055/2020 instructs participants to use the "Tabela de Domínios —
    # Reason"; AB03 is the SPI settlement timeout.
    # https://www.bcb.gov.br/content/estabilidadefinanceira/informesspi/InformeSPI-055-2020.pdf
    "pix": ("AB03", "Timeout do SPI durante a liquidacao da transacao", _E, "technical"),

    # REAL. Davivienda publishes a "Errores conocidos" table in its DaviPlata payment API
    # guide; 2103 is the service timeout.
    # https://conectesunegocio.daviplata.com/sites/default/files/2023-03/Guia%20APIs%20Pago%20con%20DaviPlata.pdf
    "daviplata": ("2103", "Internal Server Error - servicio DaviPlata no responde", _E, "technical"),

    # ILLUSTRATIVE — no public rejection catalogue found for these rails. PSE and Nequi
    # expose codes only through each PSP's own wrapper (proprietary, not the scheme's);
    # Bre-B (Banco de la Republica, 2025) and CoDi (Banxico, gated behind certification)
    # publish no error tables at all; boleto and OXXO have no rejection *code* — the real
    # mechanism is a lifecycle state (`CA` / `expired`); SPEI has plausible numeric codes
    # via third-party PSPs but two sources disagree on their meaning, so it stays here.
    "pse": ("pse_bank_unavailable", "PSE bank is not responding", _E, "technical"),
    "nequi": ("nequi_push_expired", "Nequi push notification expired", _R, "soft_decline"),
    "breb": ("breb_key_not_found", "Bre-B key could not be resolved", _R, "config"),
    "boleto": ("boleto_expired", "Boleto expired before payment", _R, "soft_decline"),
    "spei": ("spei_clabe_invalid", "CLABE rejected by the receiving bank", _R, "hard_decline"),
    "codi": ("codi_qr_expired", "CoDi QR expired", _R, "soft_decline"),
    "dimo": ("dimo_phone_unregistered", "Phone not registered in DiMo", _R, "config"),
    "oxxo": ("oxxo_voucher_expired", "OXXO voucher expired unpaid", _R, "soft_decline"),
}

# Codes the platform has never seen — used by the `unknown_code` injection.
# Codes our normalization table has never seen. Several per provider, because a single
# fixed one turns the flagship scenario into a constant: inject `unknown_code` twice and
# a judge sees the same literal both times. One code is chosen per *injection*, not per
# minute or per row - a single change upstream emits a single new code, and the number
# the card shows has to hold still while the incident is open.
NOVEL_CODES: dict[str, list[tuple[str, str, str]]] = {
    "stripe": [
        ("issuer_rule_v2_block", "Blocked by issuer rule set v2", _R),
        ("network_advice_47", "Network advice code 47 returned by issuer", _R),
        ("velocity_shield_hit", "Velocity shield threshold reached", _R),
    ],
    "adyen": [
        ("AcquirerFraudShield", "Acquirer fraud shield triggered", _R),
        ("IssuerRiskProfile", "Issuer risk profile mismatch", _R),
        ("SchemeAdviceRetry", "Scheme advised no retry for this account", _R),
    ],
    "dlocal": [
        ("412", "Undocumented acquirer response", _R),
        ("418", "Acquirer returned an unmapped status", _R),
        ("451", "Blocked by local compliance rule", _R),
    ],
    "mercadopago": [
        ("cc_rejected_policy_v3", "Rejected by policy engine v3", _R),
        ("cc_rejected_issuer_ruleset", "Rejected by issuer rule set", _R),
        ("cc_rejected_network_advice", "Rejected following network advice", _R),
    ],
}

# The mirror: an unseen code that the provider returned as an APPROVAL. Our table cannot
# place it, so it books as a decline - a sale that succeeded and that we are counting,
# reporting and possibly retrying as a failure. Same bug family as a wrong mapping, in
# the direction nobody instruments.
NOVEL_APPROVED_CODES: dict[str, tuple[str, str, str]] = {
    "stripe": ("succeeded_via_network_token", "Payment succeeded via network token", _A),
    "adyen": ("AuthorisedPartial", "Authorised - partial approval", _A),
    "dlocal": ("201", "The payment was paid - settled offline", _A),
    "mercadopago": ("accredited_deferred", "Accredited with deferred capture", _A),
}


def leaf_cuboids() -> list[dict[str, str]]:
    """Every leaf of the cube: merchant x country x method x brand x issuer x provider.

    Non-card methods have no brand/issuer; those dimensions are the empty string so
    the primary key stays fixed-width and SQL stays simple.
    """
    leaves: list[dict[str, str]] = []
    for merchant in MERCHANTS:
        for country, methods in METHODS_BY_COUNTRY.items():
            for method in methods:
                providers = PROVIDERS_BY_METHOD[(country, method)]
                if method == "card":
                    for brand in BRANDS:
                        for issuer in ISSUERS_BY_COUNTRY[country]:
                            for provider in providers:
                                leaves.append({
                                    "merchant": merchant, "country": country, "method": method,
                                    "brand": brand, "issuer": issuer, "provider": provider,
                                })
                else:
                    for provider in providers:
                        leaves.append({
                            "merchant": merchant, "country": country, "method": method,
                            "brand": "", "issuer": "", "provider": provider,
                        })
    return leaves


def leaf_key(leaf: dict[str, str]) -> tuple[str, ...]:
    return (leaf["merchant"], leaf["country"], leaf["method"],
            leaf["brand"], leaf["issuer"], leaf["provider"])


def _hash_unit(*parts: str) -> float:
    """Deterministic 0..1 from a set of strings — stable per-leaf idiosyncrasy."""
    h = hashlib.sha1("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def leaf_traffic_weight(leaf: dict[str, str]) -> float:
    """Relative share of platform volume for this leaf."""
    w = (COUNTRY_SHARE[leaf["country"]]
         * MERCHANT_SHARE[leaf["merchant"]]
         * METHOD_SHARE[(leaf["country"], leaf["method"])])
    providers = PROVIDERS_BY_METHOD[(leaf["country"], leaf["method"])]
    prov_total = sum(PROVIDER_SHARE[p] for p in providers)
    w *= PROVIDER_SHARE[leaf["provider"]] / prov_total
    if leaf["method"] == "card":
        w *= BRAND_SHARE[leaf["brand"]]
        issuers = ISSUERS_BY_COUNTRY[leaf["country"]]
        iss_total = sum(ISSUER_SHARE[i] for i in issuers)
        w *= ISSUER_SHARE[leaf["issuer"]] / iss_total
    # A little stable per-leaf idiosyncrasy so the world is not perfectly uniform.
    return w * (0.85 + 0.30 * _hash_unit("traffic", *leaf_key(leaf)))


def leaf_base_approval(leaf: dict[str, str]) -> float:
    """Healthy approval probability for this leaf (before seasonality and injections)."""
    base = 0.90 if leaf["method"] != "card" else 0.86
    # Cards are harder in some corridors; APMs are near-deterministic.
    if leaf["method"] in ("pix", "nequi", "breb"):
        base = 0.955
    elif leaf["method"] in ("boleto", "oxxo"):
        base = 0.72          # voucher methods: many are simply never paid
    elif leaf["method"] in ("spei", "codi", "dimo", "pse", "daviplata"):
        base = 0.925
    if leaf["method"] == "card":
        base += {"CO": -0.02, "BR": -0.01, "MX": 0.0}[leaf["country"]]
        base += {"visa": 0.005, "mastercard": -0.005}[leaf["brand"]]
        base += (_hash_unit("issuer", leaf["issuer"], leaf["provider"]) - 0.5) * 0.05
    base += (_hash_unit("base", *leaf_key(leaf)) - 0.5) * 0.03
    return min(0.985, max(0.45, base))


def hour_factor(dow: int, hour: int) -> float:
    """Volume multiplier for hour-of-week. Nights are quiet, weekends are 40% lighter."""
    # Latin-American e-commerce curve: trough at 04:00, peaks at 13:00 and 21:00.
    day = 0.30 + 0.70 * max(0.0, (1 - abs(hour - 13) / 9.0)) + 0.55 * max(0.0, (1 - abs(hour - 21) / 4.0))
    day = max(0.06, day)
    weekend = 0.60 if dow >= 5 else 1.0
    return day * weekend


def approval_season_factor(dow: int, hour: int) -> float:
    """Approval is genuinely a bit worse at night (batch windows, sleepy issuers)."""
    if 2 <= hour <= 5:
        return 0.975
    if hour in (0, 1, 6):
        return 0.99
    return 1.0


def healthy_decline_mix(leaf: dict[str, str]) -> dict[str, float]:
    """How a leaf's declines are normally distributed across categories.

    This is the baseline "signature". An incident is a change in this shape,
    which is the whole premise of decline-signature attribution.
    """
    if leaf["method"] == "card":
        mix = {"hard_decline": 0.46, "soft_decline": 0.32, "risk_block": 0.06,
               "technical": 0.08, "config": 0.01, "auth_required": 0.07, "unknown": 0.0}
    elif leaf["method"] in ("boleto", "oxxo"):
        mix = {"hard_decline": 0.06, "soft_decline": 0.86, "risk_block": 0.01,
               "technical": 0.06, "config": 0.01, "auth_required": 0.0, "unknown": 0.0}
    else:
        mix = {"hard_decline": 0.18, "soft_decline": 0.46, "risk_block": 0.04,
               "technical": 0.28, "config": 0.04, "auth_required": 0.0, "unknown": 0.0}
    jitter = _hash_unit("mix", *leaf_key(leaf))
    mix["technical"] *= 0.8 + 0.4 * jitter
    mix["soft_decline"] *= 0.9 + 0.2 * (1 - jitter)
    total = sum(mix.values())
    return {k: v / total for k, v in mix.items()}


def avg_ticket_usd(leaf: dict[str, str]) -> float:
    """Average ticket in USD — the cost model needs money, not counts."""
    from api.config import FX_TO_USD
    local = MERCHANTS[leaf["merchant"]]["ticket"][leaf["country"]]
    usd = local * FX_TO_USD[CURRENCY[leaf["country"]]]
    if leaf["method"] in ("boleto", "oxxo", "codi", "dimo"):
        usd *= 0.7   # low-ticket cash/QR rails
    return usd


def base_latency_ms(leaf: dict[str, str]) -> int:
    base = {"card": 950, "pix": 420, "pse": 1400, "nequi": 700, "daviplata": 800,
            "breb": 500, "boleto": 300, "spei": 600, "codi": 550, "dimo": 620, "oxxo": 280}
    v = base.get(leaf["method"], 800)
    return int(v * (0.8 + 0.4 * _hash_unit("lat", *leaf_key(leaf))))
