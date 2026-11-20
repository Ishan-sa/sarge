from sarge.store import Store, day_of
from tests.conftest import EGGS, at


def log(store, items, ts, title="meal"):
    store.log_entry(ts, "x", True, "meal", items, title)


def test_day_rolls_over_at_4am():
    assert day_of(at(3, 59, d=23)).isoformat() == "2026-09-22"
    assert day_of(at(4, 0, d=23)).isoformat() == "2026-09-23"








def test_migration_adds_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE entries (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL, raw TEXT NOT NULL, is_meal INTEGER NOT NULL, slot TEXT NOT NULL);"
                      "CREATE TABLE items (id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL, name TEXT NOT NULL, grams REAL, kcal REAL NOT NULL, protein REAL NOT NULL, carbs REAL NOT NULL, fat REAL NOT NULL);")
    old.close()
    s = Store(path)
    s.log_entry(at(11), "x", True, "meal", [{**EGGS[0], "emoji": "🍳"}], "eggs")
    assert s.day_entries(day_of(at(11)))[0]["items"][0]["emoji"] == "🍳"


def test_sheet_snapshot(store):
    from sarge.sheets import snapshot
    log(store, EGGS, at(11, 5), "scrambled eggs")
    store.add_extra(at(11, 5), "water", 500)
    snap = snapshot(store, day_of(at(11)))
    assert snap["daily"]["date"] == "2026-09-22"
    assert snap["daily"]["kcal"] == 251 and snap["daily"]["water_l"] == 0.5
    assert snap["daily"]["kcal_ok"] and not snap["daily"]["protein_ok"]
    assert snap["daily"]["steps"] == ""
    assert [i["name"] for i in snap["items"]] == ["eggs", "butter"]
    assert snap["items"][0]["meal"] == "scrambled eggs" and snap["items"][0]["time"] == "11:05"













def test_pronouns(monkeypatch):
    from sarge import config
    text = "Push him. His plan; he says he took it himself."
    monkeypatch.setattr(config, "PRONOUNS", "he")
    assert config.pronouns(text) == text
    monkeypatch.setattr(config, "PRONOUNS", "she")
    assert config.pronouns(text) == "Push her. Her plan; she says she took it herself."
    assert config.pronouns("the chef, then") == "the chef, then"


def test_reply_markup_leak_is_stripped():
    from sarge.brain import clean_reply
    assert clean_reply("Skip the naan.</reply>\n</invoke>") == "Skip the naan."
    assert clean_reply("Paneer <3 is fine") == "Paneer <3 is fine"
