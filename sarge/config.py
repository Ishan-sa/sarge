import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def env(key: str, default: str | None = None) -> str:
    value = os.environ.get(key, default)
    if value is None:
        raise SystemExit(f"Missing required env var {key}")
    return value


load_env()  # targets below can be overridden from .env

TZ = ZoneInfo(env("SARGE_TZ", "America/Vancouver"))
USER_NAME = env("SARGE_USER_NAME", "the user")  # how Sarge refers to you in its prompts
PRONOUNS = env("SARGE_PRONOUNS", "he")  # "he" or "she": how Sarge's prompts refer to the user

_SHE = {"he": "she", "him": "her", "his": "her", "himself": "herself", "guy": "woman"}


def pronouns(text: str) -> str:
    """Prompts are written with he/him; rewrite them for SARGE_PRONOUNS=she."""
    if PRONOUNS != "she":
        return text
    def swap(m: re.Match) -> str:
        w = m.group(0)
        out = _SHE[w.lower()]
        return out.capitalize() if w[0].isupper() else out
    return re.sub(r"\b(?:he|him|his|himself|guy)\b", swap, text, flags=re.IGNORECASE)

TARGET_KCAL = int(env("TARGET_KCAL", "1800"))
TARGET_PROTEIN = int(env("TARGET_PROTEIN", "130"))
TARGET_WATER_ML = int(env("TARGET_WATER_ML", "3000"))
TARGET_STEPS = int(env("TARGET_STEPS", "8000"))

MEAL_GAP_HOURS = 3.5
MEAL_REMIND_START = (8, 0)   # no meal reminders before this
MEAL_REMIND_END = (21, 30)   # ...or after this (night summary owns the evening)
MORNING = (8, 30)            # morning kick-off
MORNING_CUTOFF_HOUR = 12     # if the bot was down, don't send "good morning" after noon
NAG_HOUR = 13                # nothing logged by now -> nag
WRAP = (22, 0)               # night summary
DAY_ROLLOVER_HOUR = 4        # food eaten before 4am counts toward the previous day

