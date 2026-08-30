"""Runtime settings. Everything tunable lives here so the demo can be re-tuned without hunting."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("CT_DB_PATH", DATA_DIR / "control_tower.db"))

# --- simulation clock -------------------------------------------------------
# The sim advances SIM_SPEED simulated minutes per real second. 60 => a 5-minute
# detection window happens in 5 real seconds, which is what makes a live demo possible.
# A multiple of real time. 60 = one simulated minute per real second.
# 10x is the default because it is watchable: a 5-minute detection window takes 30
# real seconds, so an incident visibly builds instead of appearing fully formed.
SIM_SPEED = float(os.getenv("CT_SIM_SPEED", "10"))
# What the speed control offers. 0 pauses the world without stopping the server.
SIM_SPEEDS: tuple[float, ...] = (0, 1, 2, 5, 10, 30, 60)
HISTORY_DAYS = int(os.getenv("CT_HISTORY_DAYS", "21"))  # 3 weeks of seasonal history

# --- detector ---------------------------------------------------------------
WINDOW_SENSITIVE_MIN = 5
WINDOW_CONFIRM_MIN = 30
N_MIN = int(os.getenv("CT_N_MIN", "40"))          # min operational attempts in a window
DELTA = float(os.getenv("CT_DELTA", "0.05"))       # drop in points that we care about
SCORE_FIRE = float(os.getenv("CT_SCORE_FIRE", "0.99"))
SEASONAL_WEIGHT = 0.7                              # p0 = 0.7*seasonal + 0.3*ewma
EWMA_HOURS = 2
WATCHING_TTL_MIN = 20                              # not confirmed in 20 min => expired
RESOLVE_WINDOWS = 3                                # consecutive healthy windows to resolve
CHART_PAD_MIN = 30                                 # minutes shown either side of an incident
NO_TRAFFIC_DROP = 0.8                              # >=80% volume loss => "no traffic", not a decline story

# --- attribution ------------------------------------------------------------
EP_THRESHOLD = float(os.getenv("CT_EP_THRESHOLD", "0.8"))   # explanatory power to fix a value
EP_BRANCH = float(os.getenv("CT_EP_BRANCH", "0.25"))        # two branches => two incidents
# A value must carry more of the excess than its own size predicts, or it is not a
# cause — it is just the biggest bucket. lift = explanatory_power / expected share.
LIFT_MIN = float(os.getenv("CT_LIFT_MIN", "1.35"))
MAX_DEPTH = 3

# --- cost -------------------------------------------------------------------
# Fraction of a lost sale we would have recovered anyway (retry, customer comes back).
RECOVERABILITY = {
    "hard_decline": 0.90,
    "soft_decline": 0.30,
    "risk_block": 0.50,
    "technical": 0.15,
    "config": 0.05,
    "auth_required": 0.40,
    "unknown": 0.20,
    "none": 1.00,
}
FX_TO_USD = {"COP": 1 / 4000.0, "BRL": 1 / 5.4, "MXN": 1 / 17.0}

# --- memory -----------------------------------------------------------------
SIMILARITY_THRESHOLD = 0.7

# --- agent ------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
AGENT_MAX_STEPS = 10
# How much surer than the engine the agent is allowed to be. It reads the engine's own
# evidence, so it cannot legitimately be much more certain than the engine that produced
# it; a little headroom covers the case where its extra tool calls did corroborate.
AGENT_CONFIDENCE_HEADROOM = 0.05
# A real run against gpt-4.1-mini takes ~12s over 7 round trips. The 15s in the spec
# left no headroom on a slow network. This costs nothing perceptually: the deterministic
# diagnosis is already on the card before the agent starts, and the agent upgrades it.
AGENT_TIMEOUT_S = float(os.getenv("CT_AGENT_TIMEOUT_S", "40"))

# What a diagnosis actually costs in API spend. USD per 1M tokens, per model, so the card
# can price its own reasoning next to the money the incident is losing. These are list
# prices at build time — override them for your account, or add a model, via this table;
# an unknown model shows its token count with no dollar figure rather than a wrong one.
OPENAI_PRICE_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "cached_input": 0.50, "output": 8.00},
    "gpt-4.1-nano": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.00},
}


def price_for(model: str) -> dict[str, float] | None:
    """Prices for a model id, tolerant of a dated suffix (gpt-4.1-mini-2025-...)."""
    exact = OPENAI_PRICE_PER_1M.get(model)
    if exact is not None:
        return exact
    for name, prices in OPENAI_PRICE_PER_1M.items():
        if model.startswith(name):
            return prices
    return None

# --- slack alerts -----------------------------------------------------------
# Empty webhook = alerting off, the same way an empty OPENAI_API_KEY turns the agent off.
# Nothing is attempted, nothing is logged, nothing fails.
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()
SLACK_TIMEOUT_S = float(os.getenv("CT_SLACK_TIMEOUT_S", "5"))
# A confirmed incident under this rate is real but not worth waking anyone for. 0 alerts
# on everything confirmed.
SLACK_ALERT_MIN_COST_PER_MIN = float(os.getenv("CT_SLACK_MIN_COST_PER_MIN", "0"))
# Used to build the "Open incident" button. Empty = no button.
PUBLIC_BASE_URL = os.getenv("CT_PUBLIC_BASE_URL", "").strip()

SEED = int(os.getenv("CT_SEED", "20260829"))
