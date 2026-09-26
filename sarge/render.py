"""Deterministic Telegram HTML: every number the user sees is computed here, not by Claude.

Layout rule: summary first (what was logged, what's left), details after. Plain words over
symbols; only calories and protein are shown (carbs/fat are stored, never displayed).
"""

from html import escape

from .config import TARGET_KCAL, TARGET_PROTEIN, TARGET_STEPS, TARGET_WATER_ML
from .plan import SLOTS

SLOT_LABELS = {**{k: s["label"] for k, s in SLOTS.items()}, "extra": "Extra"}
SLOT_NEXT = {k: s["next"] for k, s in SLOTS.items()}


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def bar(value: float, target: float, width: int = 10) -> str:
    filled = max(0, min(width, round(width * value / target)))
    return "▰" * filled + "▱" * (width - filled)


def left_line(t: dict) -> str:
    kcal_left = TARGET_KCAL - t["kcal"]
    protein_left = TARGET_PROTEIN - t["protein"]
    kcal = f"{fmt(kcal_left)} cal" if kcal_left >= 0 else f"⚠️ {fmt(-kcal_left)} cal OVER"
    protein = f"{fmt(protein_left)}g protein" if protein_left > 0 else "protein done ✅"
    return f"Left today: {kcal} · {protein}"


def item_line(i: dict) -> str:
    return f"{i.get('emoji') or '•'} {escape(i['name'])} · {fmt(i['kcal'])} cal · 💪{fmt(i['protein'])}g"


def bars(t: dict) -> str:
    return (
        f"🔥 {bar(t['kcal'], TARGET_KCAL)} {fmt(t['kcal'])} / {fmt(TARGET_KCAL)} cal\n"
        f"💪 {bar(t['protein'], TARGET_PROTEIN)} {fmt(t['protein'])} / {TARGET_PROTEIN}g protein"
    )


def missing_slots(t: dict) -> list[str]:
    return [s for s in SLOTS if s not in t["slots"]]


def next_line(t: dict) -> str:
    missing = missing_slots(t)
    return f"⏭ Next: {escape(SLOT_NEXT[missing[0]])}" if missing else "⏭ Plan meals done. Only lean protein if you're short."


def extras_line(t: dict) -> str:
    water = f"💧 {t['water_ml'] / 1000:.1f} / {TARGET_WATER_ML / 1000:.0f}L water"
    steps = f"👟 {fmt(t['steps'])} steps" if t["steps"] is not None else "👟 no steps logged"
    vitd = "💊 Vit D taken" if t["vitd"] else "💊 Vit D not yet"
    return f"{water} · {steps} · {vitd}"


def meal_reply(title: str, items: list[dict], t: dict, comment: str) -> str:
    kcal = sum(i["kcal"] for i in items)
    protein = sum(i["protein"] for i in items)
    parts = [
        f"✅ <b>Logged {escape(title)}: {fmt(kcal)} cal · {fmt(protein)}g protein</b>\n{left_line(t)}",
        "\n".join(item_line(i) for i in items),
        bars(t),
    ]
    if comment:
        parts.append(f"🗣 {escape(comment)}")
    parts.append(next_line(t))
    return "\n\n".join(parts)


def photo_reply(kind: str, items: list[dict], picks: list[dict], t: dict, comment: str) -> str:
    """Photo answers. Nothing here is logged; the numbers are Claude's estimate."""
    parts = []
    if kind == "plate" and items:
        kcal = sum(i["kcal"] for i in items)
        protein = sum(i["protein"] for i in items)
        after = {**t, "kcal": t["kcal"] + kcal, "protein": t["protein"] + protein}
        parts += [
            f"📸 <b>Estimate: {fmt(kcal)} cal · {fmt(protein)}g protein</b> (not logged)\n"
            f"If you eat it → {left_line(after)}",
            "\n".join(item_line(i) for i in items),
        ]
    elif kind == "menu" and picks:
        lines = [
            f"{p.get('emoji') or '•'} {escape(p['name'])} · ~{fmt(p['kcal'])} cal · 💪{fmt(p['protein'])}g\n   ↳ {escape(p['how'])}"
            for p in picks
        ]
        parts += [f"🍽 <b>Best picks for what's left</b>\n{left_line(t)}", "\n".join(lines)]
    if comment:
        parts.append(f"🗣 {escape(comment)}")
    if kind == "plate" and items:
        parts.append("Reply \"ate it\" to log it, or correct me first.")
    return "\n\n".join(parts) or "Couldn't make that out. Send a clearer photo."


def other_reply(changes: list[str], t: dict, comment: str, show_status: bool) -> str:
    """Replies with no new food. Chat stays chat: stats only when he asks for them."""
    parts = []
    if changes:
        parts.append("\n".join(changes))
    if comment:
        parts.append(escape(comment))
    if show_status:
        parts.append(f"{left_line(t)}\n\n{bars(t)}\n\n{next_line(t)}")
    return "\n\n".join(parts) or "Talk to me when you've eaten something."


def day_view(entries: list[dict], t: dict) -> str:
    lines = []
    for e in entries:
        kcal = sum(i["kcal"] for i in e["items"])
        protein = sum(i["protein"] for i in e["items"])
        title = e.get("title") or SLOT_LABELS.get(e["slot"], "Extra")
        lines.append(f"{e['ts'][11:16]}  {escape(title)} · {fmt(kcal)} cal · 💪{fmt(protein)}g")
    log = "\n".join(lines) or "Nothing logged yet."
    return f"<b>Today</b>\n{left_line(t)}\n\n{log}\n\n{bars(t)}\n{extras_line(t)}\n\n{next_line(t)}"


def meal_reminder(t: dict) -> str:
    protein_left = max(TARGET_PROTEIN - t["protein"], 0)
    return (
        f"⏰ <b>3.5h since your last meal. Eat.</b>\n"
        f"Still need {fmt(protein_left)}g protein · {fmt(max(TARGET_KCAL - t['kcal'], 0))} cal left\n\n"
        f"{next_line(t)}"
    )


def nag() -> str:
    return "⏰ <b>1pm and nothing logged.</b> Either you're starving or you're not reporting. Log it."


def wrap_up(t: dict) -> str:
    problems = []
    if t["protein"] < TARGET_PROTEIN - 10:
        problems.append(f"💪 protein short by {fmt(TARGET_PROTEIN - t['protein'])}g")
    if t["kcal"] > TARGET_KCAL + 100:
        problems.append(f"🔥 {fmt(t['kcal'] - TARGET_KCAL)} cal over")
    if t["water_ml"] < TARGET_WATER_ML:
        problems.append("💧 water under 3L" if t["water_ml"] else "💧 no water logged")
    if t["steps"] is None or t["steps"] < TARGET_STEPS:
        problems.append("👟 steps under 8k" if t["steps"] is not None else "👟 no steps logged")
    if not t["vitd"]:
        problems.append("💊 no vitamin D")
    verdict = "✅ Clean day. Do it again tomorrow." if not problems else "❌ " + "\n❌ ".join(problems)
    return f"🌙 <b>Day wrap-up: {fmt(t['kcal'])} cal · {fmt(t['protein'])}g protein</b>\n\n{bars(t)}\n\n{verdict}"
