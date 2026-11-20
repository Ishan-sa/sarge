import sqlite3

import pytest

from sarge.foods import ScaleError, scale
from sarge.store import Store
from tests.conftest import SHAKE, TORTILLA


def test_scale_by_servings_and_grams():
    assert scale(TORTILLA, servings=2) == {"grams": 110, "kcal": 300, "protein": 26, "carbs": 36, "fat": 8}
    assert scale(TORTILLA, amount=27.5, unit="g")["kcal"] == 75


def test_scale_rejects_wrong_unit_or_unknown_size():
    with pytest.raises(ScaleError):
        scale(TORTILLA, amount=100, unit="ml")
    with pytest.raises(ScaleError):
        scale({**TORTILLA, "serving_qty": None}, amount=50, unit="g")


def test_brands_kept_apart_and_default(store):
    a, _ = store.save_food({**SHAKE, "brand": "northfield"})
    b, _ = store.save_food({**SHAKE, "brand": "brightfarm", "make_default": True})
    assert a != b and [f["is_default"] for f in store.foods()] == [1, 0]  # brightfarm sorts first
    _, updated = store.save_food({**SHAKE, "brand": "northfield", "kcal": 160})
    assert updated and store.food(a)["kcal"] == 160


def test_old_foods_table_migrates(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE foods (name TEXT PRIMARY KEY, description TEXT NOT NULL, kcal REAL NOT NULL, "
               "protein REAL NOT NULL, carbs REAL NOT NULL, fat REAL NOT NULL)")
    db.execute("INSERT INTO foods VALUES ('greek yogurt', 'Hillcrest 0%, 1 cup (170g)', 100, 17, 6, 0)")
    db.commit()
    db.close()
    for _ in range(2):  # second open proves the migration is idempotent
        s = Store(path)
        rows = s.foods()
        assert len(rows) == 1 and rows[0]["serving_desc"] == "Hillcrest 0%, 1 cup (170g)"
        assert rows[0]["serving_qty"] is None and rows[0]["brand"] is None
        assert s.db.execute("SELECT COUNT(*) FROM foods_v1").fetchone()[0] == 1


def test_food_edit_delete_default_and_item_columns(store):
    a, _ = store.save_food({**SHAKE, "brand": "x"})
    b, _ = store.save_food({**SHAKE, "brand": "y"})
    assert store.set_default_food(b) and store.food(b)["is_default"] == 1
    assert store.set_default_food(a) and store.food(b)["is_default"] == 0
    assert store.edit_food(a, {"kcal": 99, "bogus": 1}) and store.food(a)["kcal"] == 99
    assert store.delete_food(a) and store.food(a) is None
    from tests.conftest import at
    eid = store.log_entry(at(9), "x", True, "breakfast",
                          [{"name": "shake", "kcal": 1, "protein": 1, "carbs": 1, "fat": 1,
                            "food_id": b, "servings": 2, "amount": 0, "unit": "g", "estimated": 1}])
    it = store.entry_items(eid)[0]
    assert (it["food_id"], it["servings"], it["estimated"]) == (b, 2, 1)
    store.edit_item(it["id"], {"servings": 3})
    assert store.item(it["id"])["servings"] == 3


def _v1_db(path, description="'Hillcrest 0%, 1 cup (170g)'"):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE foods (name TEXT PRIMARY KEY, description TEXT, kcal REAL NOT NULL, "
               "protein REAL NOT NULL, carbs REAL NOT NULL, fat REAL NOT NULL)")
    db.execute(f"INSERT INTO foods VALUES ('greek yogurt', {description}, 100, 17, 6, 0)")
    db.commit()
    return db


def test_failed_migration_rolls_back_and_retries(tmp_path):
    path = tmp_path / "old.db"
    _v1_db(path, description="NULL").close()  # NULL description makes the copy fail (serving_desc NOT NULL)
    with pytest.raises(sqlite3.IntegrityError):
        Store(path)
    db = sqlite3.connect(path)
    cols = {r[1] for r in db.execute("PRAGMA table_info(foods)")}
    assert "id" not in cols and db.execute("SELECT name FROM foods").fetchall() == [("greek yogurt",)]
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='foods_v1'").fetchone()
    db.execute("UPDATE foods SET description = 'fixed'")
    db.commit()
    db.close()
    assert Store(path).foods()[0]["serving_desc"] == "fixed"


def test_deleted_foods_are_not_reimported(tmp_path):
    path = tmp_path / "old.db"
    _v1_db(path).close()
    s = Store(path)
    for f in s.foods():
        s.delete_food(f["id"])
    s = Store(path)
    assert s.foods() == []
    assert s.db.execute("SELECT COUNT(*) FROM foods_v1").fetchone()[0] == 1


def test_old_items_keep_rows_through_alters(tmp_path):
    path = tmp_path / "items.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE entries (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, day TEXT NOT NULL, raw TEXT NOT NULL,
                              is_meal INTEGER NOT NULL, slot TEXT NOT NULL);
        CREATE TABLE items (id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL, name TEXT NOT NULL, grams REAL,
                            kcal REAL NOT NULL, protein REAL NOT NULL, carbs REAL NOT NULL, fat REAL NOT NULL);
        INSERT INTO entries VALUES (1, '2026-09-22T09:00:00', '2026-09-22', 'eggs', 1, 'breakfast');
        INSERT INTO items VALUES (1, 1, 'eggs', 150, 215, 19, 1, 15);
    """)
    db.commit()
    db.close()
    s = Store(path)
    it = s.entry_items(1)[0]
    assert it["name"] == "eggs" and it["kcal"] == 215
    assert it["food_id"] is None and it["estimated"] == 0


def test_resaving_a_label_keeps_aliases_and_notes(store):
    fid, _ = store.save_food({**TORTILLA, "aliases": "wrap, tortilla", "notes": "keep cold"})
    store.save_food({**TORTILLA, "aliases": "", "notes": "", "kcal": 140})
    f = store.food(fid)
    assert (f["aliases"], f["notes"], f["kcal"]) == ("wrap, tortilla", "keep cold", 140)
    store.save_food({**TORTILLA, "aliases": "Wrap, flatbread", "notes": "new note"})
    f = store.food(fid)
    assert (f["aliases"], f["notes"]) == ("wrap, tortilla, flatbread", "new note")
