import re

from .config import TARGET_KCAL, TARGET_PROTEIN, TARGET_STEPS, TARGET_WATER_ML

FIELDS = ("kcal", "protein", "water_ml", "steps")
RANGES = {"kcal": (800, 6000), "protein": (20, 400), "water_ml": (500, 8000), "steps": (0, 60000)}
_UNITS = {"kcal": "", "protein": "g", "water_ml": "ml", "steps": ""}
_LABELS = {"kcal": "kcal", "protein": "protein", "water_ml": "water", "steps": "steps"}
DEFAULT_SUMMARY_TIME = "22:00"


def default_goals() -> dict:
    return {
        "kcal": TARGET_KCAL,
        "protein": TARGET_PROTEIN,
        "water_ml": TARGET_WATER_ML,
        "steps": TARGET_STEPS,
        "summary_time": DEFAULT_SUMMARY_TIME,
    }


def _summary_time_ok(value: str) -> bool:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not m:
        return False
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return False
    return h >= 17 or h < 4


def validate(changes: dict) -> tuple[dict, list[str]]:
    """Drop empty values, range-check the rest. Returns (clean, errors)."""
    clean, errors = {}, []
    for key in FIELDS:
        value = changes.get(key)
        if value in (0, None, ""):
            continue
        lo, hi = RANGES[key]
        if lo <= value <= hi:
            clean[key] = value
        else:
            errors.append(f"{_LABELS[key]} {value:g}{_UNITS[key]} is outside {lo}–{hi}")
    t = changes.get("summary_time")
    if t not in (0, None, ""):
        if isinstance(t, str) and _summary_time_ok(t):
            clean["summary_time"] = t
        else:
            errors.append(f"summary time {t} must be HH:MM between 17:00 and 03:59")
    return clean, errors


def describe(g: dict) -> str:
    return (
        f"{g['kcal']:,.0f} cal · {g['protein']:g}g protein · "
        f"{g['water_ml'] / 1000:g}L water · {g['steps'] / 1000:g}k steps"
    )
