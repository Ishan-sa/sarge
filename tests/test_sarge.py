import asyncio
from datetime import datetime

import pytest

from sarge import reminders
from sarge.config import TZ
from sarge.core import apply, handle_text
from sarge.plan import SLOTS
from sarge.store import Store, day_of

S0, S1 = list(SLOTS)[:2]  # first two plan slots, whatever the plan calls them


def at(h, m=0, d=22):
    return datetime(2026, 9, d, h, m, tzinfo=TZ)


EGGS = [
    {"name": "eggs", "grams": 150, "kcal": 215, "protein": 19, "carbs": 1, "fat": 15},
    {"name": "butter", "grams": 5, "kcal": 36, "protein": 0, "carbs": 0, "fat": 4},
]


def result(**kw):
    base = dict(items=[], is_meal=False, slot="extra", delete_entry_ids=[], delete_item_ids=[],
                item_edits=[], water_ml=0, steps=0, vitamin_d=False, save_foods=[], show_status=False, reply="ok")
    return {**base, **kw}


@pytest.fixture
def store():
    return Store(":memory:")


def test_day_rolls_over_at_4am():
    assert day_of(at(3, 59, d=23)).isoformat() == "2026-09-22"
    assert day_of(at(4, 0, d=23)).isoformat() == "2026-09-23"


def test_totals_sum_items_and_extras(store):
    apply(store, result(items=EGGS, is_meal=True, slot=S0, water_ml=500, steps=4000, vitamin_d=True), "eggs", at(11))
    apply(store, result(water_ml=750, steps=6000), "water", at(12))
    t = store.totals(day_of(at(12)))
    assert t["kcal"] == 251 and t["protein"] == 19
    assert t["water_ml"] == 1250
    assert t["steps"] == 6000  # latest step count replaces, doesn't add
    assert t["vitd"] and t["slots"] == {S0}


def test_edits_and_deletes_only_touch_today(store):
    apply(store, result(items=EGGS, is_meal=True, slot=S0), "yesterday eggs", at(11, d=21))
    old_item = store.day_entries(day_of(at(11, d=21)))[0]["items"][0]["id"]
    apply(store, result(items=EGGS, is_meal=True, slot=S0), "eggs", at(11))
    entry = store.day_entries(day_of(at(11)))[0]
    butter = entry["items"][1]["id"]
    eggs = entry["items"][0]["id"]

    apply(store, result(
        delete_item_ids=[butter, old_item],
        item_edits=[{"item_id": eggs, "name": "eggs", "grams": 100, "kcal": 143, "protein": 13, "carbs": 1, "fat": 10}],
    ), "fix", at(11, 5))

    assert store.totals(day_of(at(11)))["kcal"] == 143
    assert store.totals(day_of(at(11, d=21)))["kcal"] == 251  # yesterday untouched


def test_bad_slot_falls_back_to_extra(store):
    apply(store, result(items=EGGS, slot="brunch"), "x", at(11))
    assert store.totals(day_of(at(11)))["slots"] == {"extra"}


def kinds(rs):
    return [r.kind for r in rs]


def test_meal_reminder_fires_once_after_gap(store):
    store.set("morning_day", "2026-09-22")
    apply(store, result(items=EGGS, is_meal=True, slot=S0), "eggs", at(11))
    assert reminders.due(store, at(14, 29)) == []
    fired = reminders.due(store, at(14, 30))
    assert kinds(fired) == ["meal"] and "Next: Lunch" in fired[0].footer
    assert "Tell him to eat" in fired[0].brief
    assert reminders.due(store, at(14, 31)) == []


def test_minor_item_does_not_reset_meal_timer(store):
    store.set("morning_day", "2026-09-22")
    apply(store, result(items=EGGS, is_meal=True, slot=S0), "eggs", at(11))
    apply(store, result(items=[{"name": "coke zero", "grams": 330, "kcal": 1, "protein": 0, "carbs": 0, "fat": 0}]), "coke", at(13))
    assert kinds(reminders.due(store, at(14, 30))) == ["meal"]


def test_no_meal_reminder_after_930pm(store):
    apply(store, result(items=EGGS, is_meal=True, slot=S1), "late lunch", at(18))
    assert "meal" not in kinds(reminders.due(store, at(21, 31)))


def test_morning_once_at_830(store):
    assert reminders.due(store, at(8, 29)) == []
    fired = reminders.due(store, at(8, 30))
    assert kinds(fired) == ["morning"] and "1,800 cal" in fired[0].footer
    assert reminders.due(store, at(8, 31)) == []


def test_no_good_morning_after_noon(store):
    assert "morning" not in kinds(reminders.due(store, at(12, 5)))


def test_nag_when_nothing_logged_by_1pm(store):
    store.set("morning_day", "2026-09-22")
    assert reminders.due(store, at(12, 59)) == []
    assert kinds(reminders.due(store, at(13))) == ["nag"]
    assert reminders.due(store, at(13, 1)) == []


def test_wrap_once_at_10pm(store):
    store.set("morning_day", "2026-09-22")
    apply(store, result(items=EGGS, is_meal=True, slot=S0), "eggs", at(20))
    assert "wrap" not in kinds(reminders.due(store, at(21, 59)))
    fired = [r for r in reminders.due(store, at(22)) if r.kind == "wrap"]
    assert len(fired) == 1 and "MISSED" in fired[0].brief and "eggs" in fired[0].brief
    assert "protein short by 111g" in fired[0].fallback
    assert "wrap" not in kinds(reminders.due(store, at(23)))


def test_wrap_catches_up_after_midnight(store):
    store.set("morning_day", "2026-09-22")
    fired = reminders.due(store, at(0, 30, d=23))  # bot was down at 10pm
    assert kinds(fired) == ["wrap"]
    assert store.get("wrap_day") == "2026-09-22"


def test_streak_counts_consecutive_on_target_days(store):
    good = [{"name": "food", "grams": 0, "kcal": 1750, "protein": 135, "carbs": 0, "fat": 0}]
    for d in (19, 20, 21):
        apply(store, result(items=good, is_meal=True), "x", at(12, d=d))
    apply(store, result(items=EGGS, is_meal=True), "x", at(12, d=18))  # missed day breaks it
    assert store.streak(day_of(at(12, d=21))) == 3
    assert store.streak(day_of(at(12, d=22))) == 0  # nothing logged today yet
    m = reminders.morning(store, at(8, 30))
    assert "Streak: 3 days" in m.footer and "HIT both targets" in m.brief


def test_compose_falls_back_and_escapes():
    r = reminders.Reminder("nag", "brief", "<b>fallback</b>", "footer")
    assert r.compose(None) == "<b>fallback</b>\n\nfooter"
    assert r.compose("Eat & log <now>") == "Eat &amp; log &lt;now&gt;\n\nfooter"


class FakeBrain:
    def __init__(self, res):
        self.res = res
        self.prompts = []

    async def interpret(self, prompt):
        self.prompts.append(prompt)
        return self.res


def test_meal_reply_summary_first(store):
    brain = FakeBrain(result(items=EGGS, title="scrambled eggs", is_meal=True, slot=S0, reply="Butter counted."))
    out = asyncio.run(handle_text(store, brain, "3 eggs in 5g butter", at(11)))
    lines = out.splitlines()
    assert lines[0] == "✅ <b>Logged scrambled eggs: 251 cal · 19g protein</b>"
    assert lines[1] == "Left today: 1,549 cal · 111g protein"
    assert "💪 ▰▱▱▱▱▱▱▱▱▱ 19 / 130g protein" in out
    assert "🗣 Butter counted." in out
    assert "⏭ Next: Lunch" in out
    assert "⬜" not in out and "<pre>" not in out
    # second message sees the first in its context, with ids for corrections
    asyncio.run(handle_text(store, FakeBrain(result()), "how am I doing", at(11, 5)))
    assert store.recent_messages()[0]["text"] == "3 eggs in 5g butter"
    assert store.day_entries(day_of(at(11)))[0]["title"] == "scrambled eggs"


def test_over_budget_is_flagged(store):
    big = [{"name": "pizza", "grams": 0, "kcal": 1900, "protein": 60, "carbs": 200, "fat": 80}]
    out = asyncio.run(handle_text(store, FakeBrain(result(items=big, title="pizza")), "pizza", at(19)))
    assert "⚠️ 100 cal OVER" in out.splitlines()[1]


def test_banter_gets_no_stats(store):
    out = asyncio.run(handle_text(store, FakeBrain(result(reply="Cool isn't a meal.")), "cool", at(12)))
    assert out == "Cool isn&#x27;t a meal."


def test_status_only_when_asked(store):
    out = asyncio.run(handle_text(store, FakeBrain(result(show_status=True, reply="Behind.")), "what's left", at(12)))
    assert out.startswith("Behind.") and "Left today: 1,800 cal" in out and "⏭ Next:" in out


def test_water_log_is_short(store):
    out = asyncio.run(handle_text(store, FakeBrain(result(water_ml=500, reply="Keep it coming.")), "500ml water", at(11)))
    assert out == "💧 <b>+500ml water</b>\n\nKeep it coming."


def test_html_is_escaped(store):
    brain = FakeBrain(result(items=[{"name": "Mac & <chz>", "grams": 0, "kcal": 300, "protein": 12, "carbs": 30, "fat": 14}],
                             title="mac & cheese", reply="Hot & sweet <b>"))
    out = asyncio.run(handle_text(store, brain, "mac", at(11)))
    assert "Mac &amp; &lt;chz&gt;" in out and "Hot &amp; sweet &lt;b&gt;" in out and "mac &amp; cheese" in out


def test_migration_adds_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL, raw TEXT NOT NULL, is_meal INTEGER NOT NULL, slot TEXT NOT NULL);"
                      "CREATE TABLE items (id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL, name TEXT NOT NULL, grams REAL, kcal REAL NOT NULL, protein REAL NOT NULL, carbs REAL NOT NULL, fat REAL NOT NULL);")
    old.close()
    s = Store(path)
    s.log_entry(at(11), "x", True, S0, [{**EGGS[0], "emoji": "🍳"}], "eggs")
    assert s.day_entries(day_of(at(11)))[0]["items"][0]["emoji"] == "🍳"


def test_sheet_snapshot(store):
    from sarge.sheets import snapshot
    apply(store, result(items=EGGS, title="scrambled eggs", is_meal=True, slot=S0, water_ml=500), "eggs", at(11, 5))
    snap = snapshot(store, day_of(at(11)))
    assert snap["daily"]["date"] == "2026-09-22"
    assert snap["daily"]["kcal"] == 251 and snap["daily"]["water_l"] == 0.5
    assert snap["daily"]["kcal_ok"] and not snap["daily"]["protein_ok"]
    assert snap["daily"]["steps"] == ""
    assert [i["name"] for i in snap["items"]] == ["eggs", "butter"]
    assert snap["items"][0]["meal"] == "scrambled eggs" and snap["items"][0]["time"] == "11:05"


def test_morning_knows_diet_day(store):
    assert "day 1 of the diet" in reminders.morning(store, at(8, 30)).brief
    apply(store, result(items=EGGS, is_meal=True), "x", at(12, d=22))
    m = reminders.morning(store, at(8, 30, d=23))
    assert "day 2 of the diet" in m.brief and "MISSED" in m.brief
    m = reminders.morning(store, at(8, 30, d=25))
    assert "day 4 of the diet" in m.brief and "logged NOTHING" in m.brief
