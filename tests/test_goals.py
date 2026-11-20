from datetime import date

from sarge.goals import describe, validate


def test_defaults_until_set(store):
    assert store.goals(date(2026, 11, 20)) == {"kcal": 1800, "protein": 130, "water_ml": 3000, "steps": 8000, "summary_time": "22:00"}


def test_set_goals_applies_from_that_day_only(store):
    store.set_goals(date(2026, 11, 20), {"kcal": 1500, "protein": 100})
    assert store.goals(date(2026, 11, 19))["kcal"] == 1800
    g = store.goals(date(2026, 11, 25))
    assert (g["kcal"], g["protein"], g["water_ml"]) == (1500, 100, 3000)


def test_set_goals_returns_new_goals_and_stores_summary_time(store):
    g = store.set_goals(date(2026, 11, 20), {"summary_time": "21:30"})
    assert g["summary_time"] == "21:30"
    assert store.goals(date(2026, 11, 20))["summary_time"] == "21:30"


def test_validate_partial_and_absurd():
    clean, errors = validate({"kcal": 0, "protein": 1000, "steps": 9000, "summary_time": "11:00"})
    assert clean == {"steps": 9000}
    assert len(errors) == 2 and "protein" in errors[0] and "summary" in errors[1]
    assert validate({"summary_time": "00:30"}) == ({"summary_time": "00:30"}, [])


def test_describe():
    assert describe({"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000}) == "1,500 cal · 100g protein · 3L water · 8k steps"


def test_goals_seeded_once_from_first_day_and_env_changes_dont_rejudge(tmp_path, monkeypatch):
    from sarge import goals as goals_mod
    from sarge.store import Store
    from tests.conftest import at

    path = tmp_path / "s.db"
    s = Store(path)
    s.log_entry(at(12), "x", True, "meal", [{"name": "eggs", "kcal": 200, "protein": 15, "carbs": 1, "fat": 14}])
    s.db.execute("DELETE FROM goals")  # an old database: entries but no goals rows
    s.db.commit()
    s = Store(path)
    rows = [dict(r) for r in s.db.execute("SELECT * FROM goals")]
    assert rows == [{"effective_day": "2026-09-22", "kcal": 1800, "protein": 130, "water_ml": 3000, "steps": 8000}]
    monkeypatch.setattr(goals_mod, "TARGET_KCAL", 2500)
    s = Store(path)
    assert s.db.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 1
    assert s.goals(date(2026, 9, 22))["kcal"] == 1800 and s.goals(date(2026, 10, 1))["kcal"] == 1800


def test_goals_seeded_at_today_without_entries(store):
    from sarge.store import day_of, now
    [row] = store.db.execute("SELECT effective_day FROM goals").fetchall()
    assert row[0] == day_of(now()).isoformat()
