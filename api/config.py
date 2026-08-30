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
# A real run against gpt-4.1-mini takes ~12s over 7 round trips. The 15s in the spec
# left no headroom on a slow network. This costs nothing perceptually: the deterministic
# diagnosis is already on the card before the agent starts, and the agent upgrades it.
AGENT_TIMEOUT_S = float(os.getenv("CT_AGENT_TIMEOUT_S", "40"))

SEED = int(os.getenv("CT_SEED", "20260829"))
