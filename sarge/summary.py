"""The night summary: the only scheduled message.

`due()` decides WHEN it fires (pure bookkeeping on the store, restart-safe, testable).
A Summary carries a context brief for Claude to write the prose in Sarge's voice, a template
fallback in case Claude fails, and a deterministic footer with the exact numbers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import render
from .config import DAY_ROLLOVER_HOUR
from .store import Store, day_of


@dataclass
class Summary:
    brief: str      # facts for Claude to write from
    fallback: str   # HTML used if Claude fails
    footer: str     # HTML appended under Claude's text (exact numbers)

    def compose(self, text: str | None) -> str:
        from html import escape
        head = escape(text.strip()) if text and text.strip() else self.fallback
        return f"{head}\n\n{self.footer}" if self.footer else head


def _since_rollover(h: int, m: int) -> int:
    """Minutes since the day rolled over, so 00:30 sorts after 22:00."""
    return (h * 60 + m - DAY_ROLLOVER_HOUR * 60) % 1440


def _goals_brief(g: dict) -> str:
    return (
        f"{g['kcal']} kcal, {g['protein']} g protein, water {g['water_ml'] / 1000:g} L, "
        f"{g['steps']} steps, vitamin D daily"
    )


def _log_brief(store: Store, day) -> str:
    lines = []
    for e in store.day_entries(day):
        items = ", ".join(f"{i['name']} ({i['kcal']:.0f} kcal, {i['protein']:.0f}g P)" for i in e["items"])
        lines.append(f"{e['ts'][11:16]} {e.get('title') or e['slot']}: {items}")
    return "\n".join(lines) or "(nothing logged)"


def build(store: Store, now: datetime) -> Summary:
    day = day_of(now)
    t = store.totals(day)
    g = store.goals(day)
    ok = store.day_ok(day)
    streak = store.streak(day)
    steps = f"{t['steps']:.0f}" if t["steps"] is not None else "not logged"
    week = []
    for back in range(6, 0, -1):
        d = day - timedelta(days=back)
        dt = store.totals(d)
        week.append(f"{d:%a}: " + (f"{dt['kcal']:.0f} kcal, {dt['protein']:.0f}g P" if dt["entries"] else "no data"))
    brief = (
        f"This is his end-of-day summary. Write what he did well, where he slipped "
        f"(be specific, name foods), and ONE focus for tomorrow.\n"
        f"His goals today: {_goals_brief(g)}.\n"
        f"Today's result: {'HIT both targets' if ok else 'MISSED' if ok is False else 'nothing logged'}.\n"
        f"Day totals: {t['kcal']:.0f} kcal, {t['protein']:.0f} g protein, {t['carbs']:.0f} g carbs, "
        f"{t['fat']:.0f} g fat; water {t['water_ml'] / 1000:.1f} L; steps {steps}; "
        f"vitamin D {'taken' if t['vitd'] else 'not taken'}.\n"
        f"Logged today:\n{_log_brief(store, day)}\n"
        f"Streak of on-target days including today: {streak}.\n"
        f"Previous 6 days: {'; '.join(week)}"
    )
    return Summary(brief, render.summary_fallback(t, g), render.summary_footer(t, g, streak))


def due(store: Store, now: datetime) -> Summary | None:
    """The summary, once per day, from `summary_time` on (catching up after downtime)."""
    key = day_of(now).isoformat()
    if store.get("wrap_day") == key:
        return None
    h, m = (int(x) for x in store.goals(day_of(now))["summary_time"].split(":"))
    if _since_rollover(now.hour, now.minute) >= _since_rollover(h, m):
        store.set("wrap_day", key)
        return build(store, now)
    return None
