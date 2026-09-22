"""Scheduled messages.

`due()` decides WHAT fires (pure bookkeeping on the store, restart-safe, testable).
Each Reminder carries a context brief for Claude to write the message in Sarge's voice,
a template fallback in case Claude fails, and a deterministic footer with the exact numbers.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from . import render
from .config import (
    MEAL_GAP_HOURS, MEAL_REMIND_END, MEAL_REMIND_START, MORNING, MORNING_CUTOFF_HOUR, NAG_HOUR,
    TARGET_KCAL, TARGET_PROTEIN, TARGET_STEPS, TARGET_WATER_ML, WRAP, DAY_ROLLOVER_HOUR,
)
from .plan import PLAN_TEXT
from .store import Store, day_of


@dataclass
class Reminder:
    kind: str       # morning | meal | nag | wrap
    brief: str      # facts for Claude to write from
    fallback: str   # HTML used if Claude fails
    footer: str     # HTML appended under Claude's text (exact numbers)

    def compose(self, text: str | None) -> str:
        from html import escape
        head = escape(text.strip()) if text and text.strip() else self.fallback
        return f"{head}\n\n{self.footer}" if self.footer else head


def _hm(now: datetime) -> tuple[int, int]:
    return (now.hour, now.minute)


def _totals_brief(t: dict) -> str:
    steps = f"{t['steps']:.0f}" if t["steps"] is not None else "not logged"
    return (
        f"{t['kcal']:.0f}/{TARGET_KCAL} kcal, {t['protein']:.0f}/{TARGET_PROTEIN} g protein, "
        f"water {t['water_ml'] / 1000:.1f}/{TARGET_WATER_ML / 1000:.0f} L, steps {steps}/{TARGET_STEPS}, "
        f"vitamin D {'taken' if t['vitd'] else 'not taken'}"
    )


def _log_brief(store: Store, day) -> str:
    lines = []
    for e in store.day_entries(day):
        items = ", ".join(f"{i['name']} ({i['kcal']:.0f} kcal, {i['protein']:.0f}g P)" for i in e["items"])
        lines.append(f"{e['ts'][11:16]} {e.get('title') or e['slot']}: {items}")
    return "\n".join(lines) or "(nothing logged)"


def morning(store: Store, now: datetime) -> Reminder:
    today = day_of(now)
    yday = today - timedelta(days=1)
    yt = store.totals(yday)
    y_ok = store.day_ok(yday)
    streak = store.streak(yday)
    first = store.first_day()
    if first is None or first > yday:
        day_n = 1 if first is None or first == today else (today - first).days + 1
        yesterday = "Yesterday was before he started the diet; don't judge it."
    else:
        day_n = (today - first).days + 1
        verdict = {True: "HIT both targets", False: "MISSED", None: "logged NOTHING (skipped tracking)"}[y_ok]
        yesterday = f"Yesterday: {verdict}. {_totals_brief(yt) if y_ok is not None else ''}"
    brief = (
        f"It's {now:%A} morning, {now:%H:%M}. Write his morning kick-off. This is day {day_n} of the diet.\n"
        f"{yesterday}\n"
        f"Current streak of on-target days: {streak}.\n"
        f"Today's plan:\n{PLAN_TEXT}"
    )
    goals = (
        f"{render.fmt(TARGET_KCAL)} cal · {TARGET_PROTEIN}g protein · "
        f"{TARGET_WATER_ML / 1000:g}L water · {TARGET_STEPS // 1000}k steps"
    )
    fallback = f"☀️ <b>Morning.</b> Clock's running. {goals}. Go."
    footer = f"🎯 Today: {goals}"
    if streak:
        footer += f"\n🔥 Streak: {streak} day{'s' if streak != 1 else ''}"
    return Reminder("morning", brief, fallback, footer)


def meal(store: Store, now: datetime, last: datetime) -> Reminder:
    t = store.totals(day_of(now))
    hours = (now - last).total_seconds() / 3600
    brief = (
        f"It's {now:%H:%M}. His last real meal was {hours:.1f} hours ago. Tell him to eat now.\n"
        f"Today so far: {_totals_brief(t)}\n"
        f"Logged today:\n{_log_brief(store, day_of(now))}\n"
        f"{render.next_line(t)}"
    )
    footer = f"{render.left_line(t)}\n{render.next_line(t)}"
    return Reminder("meal", brief, "⏰ <b>3.5h since your last meal. Eat.</b>", footer)


def nag(now: datetime) -> Reminder:
    brief = f"It's {now:%H:%M} and he has logged NOTHING today. Call it out; either he's skipping meals or not reporting."
    return Reminder("nag", brief, render.nag(), "")


def wrap(store: Store, now: datetime) -> Reminder:
    day = day_of(now)
    t = store.totals(day)
    ok = store.day_ok(day)
    streak = store.streak(day)
    week = []
    for back in range(6, 0, -1):
        d = day - timedelta(days=back)
        dt = store.totals(d)
        week.append(f"{d:%a}: " + (f"{dt['kcal']:.0f} kcal, {dt['protein']:.0f}g P" if dt["entries"] else "no data"))
    brief = (
        f"It's {now:%H:%M}, end of the day. Write his night review: what he did well, where he slipped "
        f"(be specific, name foods), and ONE focus for tomorrow.\n"
        f"Today's result: {'HIT both targets' if ok else 'MISSED' if ok is False else 'nothing logged'}. "
        f"{_totals_brief(t)}\n"
        f"Logged today:\n{_log_brief(store, day)}\n"
        f"Streak of on-target days including today: {streak}.\n"
        f"Previous 6 days: {'; '.join(week)}"
    )
    footer = (
        f"🌙 <b>{render.fmt(t['kcal'])} cal · {render.fmt(t['protein'])}g protein</b>\n"
        f"{render.bars(t)}\n{render.extras_line(t)}"
    )
    if streak:
        footer += f"\n🔥 Streak: {streak} day{'s' if streak != 1 else ''}"
    return Reminder("wrap", brief, render.wrap_up(t), footer)


def due(store: Store, now: datetime) -> list[Reminder]:
    day = day_of(now)
    key = day.isoformat()
    t = store.totals(day)
    out: list[Reminder] = []

    if MORNING <= _hm(now) and now.hour < MORNING_CUTOFF_HOUR and store.get("morning_day") != key:
        out.append(morning(store, now))
        store.set("morning_day", key)

    last = store.last_meal_ts()
    if (
        last is not None
        and MEAL_REMIND_START <= _hm(now) < MEAL_REMIND_END
        and timedelta(hours=MEAL_GAP_HOURS) <= now - last < timedelta(hours=10)
        and store.get("meal_reminded_for") != last.isoformat()
        and (t["protein"] < TARGET_PROTEIN or render.missing_slots(t))
    ):
        out.append(meal(store, now, last))
        store.set("meal_reminded_for", last.isoformat())

    if NAG_HOUR <= now.hour and _hm(now) < WRAP and t["entries"] == 0 and store.get("nag_day") != key:
        out.append(nag(now))
        store.set("nag_day", key)

    # 22:00 onwards, or after midnight if the bot was down (day_of still points at yesterday)
    if (_hm(now) >= WRAP or now.hour < DAY_ROLLOVER_HOUR) and store.get("wrap_day") != key:
        out.append(wrap(store, now))
        store.set("wrap_day", key)

    return out
