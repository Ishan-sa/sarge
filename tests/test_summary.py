from datetime import date

from sarge import summary
from sarge.store import day_of
from tests.conftest import EGGS, at


def log(store, items, ts, title="meal"):
    store.log_entry(ts, "x", True, "meal", items, title)


def test_summary_once_at_default_time(store):
    assert summary.due(store, at(21, 59)) is None
    assert summary.due(store, at(22, 0)) is not None and summary.due(store, at(22, 30)) is None


def test_summary_time_after_midnight_counts_for_previous_day(store):
    store.set_goals(date(2026, 9, 22), {"summary_time": "00:30"})
    assert summary.due(store, at(23, 0)) is None
    assert summary.due(store, at(0, 31, d=23)) is not None
    assert summary.due(store, at(1, 0, d=23)) is None
    assert store.get("wrap_day") == "2026-09-22"


def test_summary_time_one_digit_hour(store):
    store.set_goals(date(2026, 9, 22), {"summary_time": "1:30"})
    assert summary.due(store, at(1, 29, d=23)) is None
    assert summary.due(store, at(1, 30, d=23)) is not None


def test_summary_catches_up_after_downtime(store):
    assert summary.due(store, at(2, 0, d=23)) is not None  # down 22:00-02:00, still yesterday's


def test_no_other_scheduled_messages(store):
    for h, m in ((8, 30), (13, 0), (17, 0)):
        assert summary.due(store, at(h, m)) is None


def test_brief_states_goals_and_is_end_of_day(store):
    log(store, EGGS, at(20))
    s = summary.due(store, at(22))
    assert "end-of-day summary" in s.brief and "1800 kcal, 130 g protein" in s.brief
    assert "MISSED" in s.brief and "eggs" in s.brief
    assert "protein short by 111g" in s.fallback


def test_streak_in_footer_and_brief(store):
    good = [{"name": "food", "grams": 0, "kcal": 1750, "protein": 135, "carbs": 0, "fat": 0}]
    for d in (19, 20, 21):
        log(store, good, at(12, d=d))
    log(store, EGGS, at(12, d=18))  # missed day breaks it
    assert store.streak(day_of(at(12, d=21))) == 3
    assert store.streak(day_of(at(12, d=22))) == 0  # nothing logged today yet
    s = summary.due(store, at(22, d=21))
    assert "Streak: 3 days" in s.footer and "HIT both targets" in s.brief


def test_compose_falls_back_and_escapes():
    s = summary.Summary("brief", "<b>fallback</b>", "footer")
    assert s.compose(None) == "<b>fallback</b>\n\nfooter"
    assert s.compose("Eat & log <now>") == "Eat &amp; log &lt;now&gt;\n\nfooter"
