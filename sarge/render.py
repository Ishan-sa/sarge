"""Deterministic Telegram HTML: every number the user sees is computed here, not by Claude.

Layout rule: summary first (what was logged, what's left), details after. Plain words over
symbols. Every function takes the day's goals `g` explicitly.
"""

from html import escape

from .goals import describe


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def bar(value: float, target: float, width: int = 10) -> str:
    filled = max(0, min(width, round(width * value / target)))
    return "▰" * filled + "▱" * (width - filled)


def left_line(t: dict, g: dict) -> str:
    kcal_left = g["kcal"] - t["kcal"]
    protein_left = g["protein"] - t["protein"]
    kcal = f"{fmt(kcal_left)} cal" if kcal_left >= 0 else f"⚠️ {fmt(-kcal_left)} cal OVER"
    protein = f"{fmt(protein_left)}g protein" if protein_left > 0 else "protein done ✅"
    return f"Left today: {kcal} · {protein}"


def macro_line(x: dict) -> str:
    return f"{fmt(x['kcal'])} cal · {fmt(x['protein'])}g P · {fmt(x['carbs'])}g C · {fmt(x['fat'])}g F"


def item_line(i: dict) -> str:
    name = ("~" if i.get("estimated") else "") + escape(i["name"])
    return f"{escape(i.get('emoji') or '•')} {name} · {fmt(i['kcal'])} cal · 💪{fmt(i['protein'])}g"


def bars(t: dict, g: dict) -> str:
    return (
        f"🔥 {bar(t['kcal'], g['kcal'])} {fmt(t['kcal'])} / {fmt(g['kcal'])} cal\n"
        f"💪 {bar(t['protein'], g['protein'])} {fmt(t['protein'])} / {fmt(g['protein'])}g protein"
    )


def extras_line(t: dict, g: dict) -> str:
    water = f"💧 {t['water_ml'] / 1000:.1f} / {g['water_ml'] / 1000:g}L water"
    steps = f"👟 {fmt(t['steps'])} steps" if t["steps"] is not None else "👟 no steps logged"
    vitd = "💊 Vit D taken" if t["vitd"] else "💊 Vit D not yet"
    return f"{water} · {steps} · {vitd}"


def _sum(items: list[dict]) -> dict:
    return {k: sum(i.get(k) or 0 for i in items) for k in ("kcal", "protein", "carbs", "fat")}


def meal_reply(title: str, items: list[dict], t: dict, g: dict, comment: str) -> str:
    parts = [
        f"✅ <b>Logged {escape(title)}: {macro_line(_sum(items))}</b>\n{left_line(t, g)}",
        "\n".join(item_line(i) for i in items),
        bars(t, g),
    ]
    if comment:
        parts.append(f"🗣 {escape(comment)}")
    return "\n\n".join(parts)


def draft_reply(title: str, items: list[dict], comment: str) -> str:
    """The pending meal: every draft item, so he sees exactly what "ate it" will log."""
    parts = [
        f"📝 <b>Draft {escape(title)}: {macro_line(_sum(items))}</b>\n" + "\n".join(item_line(i) for i in items),
        'Say "ate it" to log it, or correct me first.',
    ]
    if comment:
        parts.append(f"🗣 {escape(comment)}")
    return "\n\n".join(parts)


def picks_block(picks: list[dict], t: dict, g: dict) -> str:
    """Menu photo: the best orders for what's left. Numbers are Claude's estimates, so marked ~."""
    lines = [
        f"{escape(p.get('emoji') or '•')} {escape(p['name'])} · ~{fmt(p['kcal'])} cal · 💪{fmt(p['protein'])}g\n   ↳ {escape(p['how'])}"
        for p in picks
    ]
    return f"🍽 <b>Best picks for what's left</b>\n{left_line(t, g)}\n\n" + "\n".join(lines)


def food_label(f: dict) -> str:
    """Brand + name, e.g. 'Acme protein tortilla'. Escaped."""
    brand = f.get("brand") or ""
    return escape(" ".join(x for x in (brand[:1].upper() + brand[1:], f["name"]) if x))


def food_saved_line(f: dict, updated: bool) -> str:
    return (f"📌 {'Updated' if updated else 'Saved'} {food_label(f)} ({escape(f['serving_desc'])}): "
            f"{fmt(f.get('kcal') or 0)} cal · {fmt(f.get('protein') or 0)}g P")


def goals_line(g: dict) -> str:
    return f"🎯 New goals: {describe(g)}"


def other_reply(changes: list[str], t: dict, g: dict, comment: str, show_status: bool) -> str:
    """Replies with no new food. Chat stays chat: stats only when he asks for them."""
    parts = []
    if changes:
        parts.append("\n".join(changes))
    if comment:
        parts.append(escape(comment))
    if show_status:
        parts.append(f"{left_line(t, g)}\n\n{bars(t, g)}")
    return "\n\n".join(parts) or "Talk to me when you've eaten something."


def day_view(entries: list[dict], t: dict, g: dict) -> str:
    lines = []
    for e in entries:
        x = _sum(e["items"])
        title = e.get("title") or e["slot"].capitalize()
        lines.append(f"{e['ts'][11:16]}  {escape(title)} · {fmt(x['kcal'])} cal · 💪{fmt(x['protein'])}g")
    log = "\n".join(lines) or "Nothing logged yet."
    return f"<b>Today</b>\n{left_line(t, g)}\n\n{log}\n\n{bars(t, g)}\n{extras_line(t, g)}"


def summary_fallback(t: dict, g: dict) -> str:
    problems = []
    if t["protein"] < g["protein"] - 10:
        problems.append(f"💪 protein short by {fmt(g['protein'] - t['protein'])}g")
    if t["kcal"] > g["kcal"] + 100:
        problems.append(f"🔥 {fmt(t['kcal'] - g['kcal'])} cal over")
    if t["water_ml"] < g["water_ml"]:
        problems.append(f"💧 water under {g['water_ml'] / 1000:g}L" if t["water_ml"] else "💧 no water logged")
    if t["steps"] is None or t["steps"] < g["steps"]:
        problems.append(f"👟 steps under {g['steps'] / 1000:g}k" if t["steps"] is not None else "👟 no steps logged")
    if not t["vitd"]:
        problems.append("💊 no vitamin D")
    verdict = "✅ Clean day. Do it again tomorrow." if not problems else "❌ " + "\n❌ ".join(problems)
    return f"🌙 <b>Day wrap-up: {fmt(t['kcal'])} cal · {fmt(t['protein'])}g protein</b>\n\n{bars(t, g)}\n\n{verdict}"


def summary_footer(t: dict, g: dict, streak: int) -> str:
    out = f"🌙 <b>{macro_line(t)}</b>\n{bars(t, g)}\n{extras_line(t, g)}"
    if streak:
        out += f"\n🔥 Streak: {streak} day{'s' if streak != 1 else ''}"
    return out
