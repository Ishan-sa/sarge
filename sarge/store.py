import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DAY_ROLLOVER_HOUR, DRAFT_TTL_HOURS, TZ

FOODS_DDL = """
CREATE TABLE IF NOT EXISTS foods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    brand TEXT,
    variant TEXT,
    aliases TEXT,
    serving_desc TEXT NOT NULL,
    serving_qty REAL,
    serving_unit TEXT,
    kcal REAL,
    protein REAL,
    carbs REAL,
    fat REAL,
    is_default INTEGER DEFAULT 0,
    notes TEXT
);
"""

FOOD_COLS = ("name", "brand", "variant", "aliases", "serving_desc", "serving_qty", "serving_unit",
             "kcal", "protein", "carbs", "fat", "is_default", "notes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    raw TEXT NOT NULL,
    is_meal INTEGER NOT NULL,
    slot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    grams REAL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    carbs REAL NOT NULL,
    fat REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS draft_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    grams REAL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    carbs REAL NOT NULL,
    fat REAL NOT NULL,
    emoji TEXT,
    food_id INTEGER,
    servings REAL,
    amount REAL,
    unit TEXT,
    estimated INTEGER DEFAULT 0,
    ts TEXT
);
CREATE TABLE IF NOT EXISTS extras (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,   -- water | steps | vitd
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS goals (
    effective_day TEXT PRIMARY KEY,
    kcal REAL,
    protein REAL,
    water_ml REAL,
    steps REAL
);
""" + FOODS_DDL


def now() -> datetime:
    return datetime.now(TZ)


def day_of(ts: datetime) -> date:
    return (ts.astimezone(TZ) - timedelta(hours=DAY_ROLLOVER_HOUR)).date()


class Store:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        self._seed_goals()

    def _migrate(self) -> None:
        cols = {t: {r["name"] for r in self.db.execute(f"PRAGMA table_info({t})")} for t in ("entries", "items", "foods")}
        self._migrate_foods(cols["foods"])
        with self.db:
            for col, decl in (("food_id", "INTEGER"), ("servings", "REAL"), ("amount", "REAL"),
                              ("unit", "TEXT"), ("estimated", "INTEGER DEFAULT 0")):
                if col not in cols["items"]:
                    self.db.execute(f"ALTER TABLE items ADD COLUMN {col} {decl}")
            if "title" not in cols["entries"]:
                self.db.execute("ALTER TABLE entries ADD COLUMN title TEXT")
            if "emoji" not in cols["items"]:
                self.db.execute("ALTER TABLE items ADD COLUMN emoji TEXT")

    def _migrate_foods(self, food_cols: set[str]) -> None:
        """v1 foods (name PK + description) -> structured table, in one transaction."""
        copy = ("INSERT INTO foods (name, serving_desc, kcal, protein, carbs, fat) "
                "SELECT name, description, kcal, protein, carbs, fat FROM foods_v1")
        old_level, self.db.isolation_level = self.db.isolation_level, None  # we issue BEGIN/COMMIT ourselves
        try:
            if "id" not in food_cols:
                self.db.execute("BEGIN")
                try:
                    self.db.execute("ALTER TABLE foods RENAME TO foods_v1")
                    self.db.execute(FOODS_DDL)
                    self.db.execute(copy)
                    self.db.execute("COMMIT")
                except BaseException:
                    self.db.execute("ROLLBACK")
                    raise
        finally:
            self.db.isolation_level = old_level

    def _seed_goals(self) -> None:
        """Pin the .env targets once, from the first logged day (today on a fresh database).

        Days without a goals row of their own then keep the targets they were judged by,
        however TARGET_* changes later. Days before the seed still fall back to the live defaults.
        """
        from .goals import FIELDS, default_goals
        if self.db.execute("SELECT 1 FROM goals LIMIT 1").fetchone():
            return
        g, day = default_goals(), self.first_day() or day_of(now())
        with self.db:
            self.db.execute("INSERT INTO goals (effective_day, kcal, protein, water_ml, steps) VALUES (?, ?, ?, ?, ?)",
                            (day.isoformat(), *(g[k] for k in FIELDS)))

    # --- draft meal -----------------------------------------------------

    def _expire(self, now: datetime) -> bool:
        ts = self.get("draft_ts")
        if ts and now - datetime.fromisoformat(ts) > timedelta(hours=DRAFT_TTL_HOURS):
            self.draft_clear()
            return True
        return False

    def draft(self, now: datetime) -> list[dict]:
        if self._expire(now):
            return []
        return [dict(r) for r in self.db.execute("SELECT * FROM draft_items ORDER BY id")]

    def draft_title(self) -> str:
        return self.get("draft_title") or ""

    def draft_add(self, ts: datetime, items: list[dict], title: str | None) -> None:
        self._expire(ts)
        empty = self.db.execute("SELECT COUNT(*) FROM draft_items").fetchone()[0] == 0
        with self.db:
            for it in items:
                self.db.execute(
                    "INSERT INTO draft_items (name, grams, kcal, protein, carbs, fat, emoji, food_id, servings, amount, unit, estimated, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (it["name"], it.get("grams"), it["kcal"], it["protein"], it["carbs"], it["fat"], it.get("emoji"),
                     it.get("food_id"), it.get("servings"), it.get("amount"), it.get("unit"), int(it.get("estimated") or 0),
                     ts.isoformat()),
                )
            self.db.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('draft_ts', ?)", (ts.isoformat(),))
            if title or empty:
                self.db.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('draft_title', ?)", (title or "",))

    def draft_item(self, item_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM draft_items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None

    def draft_edit(self, item_id: int, fields: dict) -> bool:
        allowed = {k: v for k, v in fields.items() if k in ("name", "grams", "kcal", "protein", "carbs", "fat", "food_id", "servings", "amount", "unit", "estimated")}
        if not allowed:
            return False
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.db:
            return self.db.execute(
                f"UPDATE draft_items SET {sets} WHERE id = ?", (*allowed.values(), item_id)
            ).rowcount > 0

    def draft_remove(self, item_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM draft_items WHERE id = ?", (item_id,)).rowcount > 0

    def draft_clear(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM draft_items")
            self.db.execute("DELETE FROM state WHERE key IN ('draft_title', 'draft_ts')")

    # --- food log -------------------------------------------------------

    def log_entry(self, ts: datetime, raw: str, is_meal: bool, slot: str, items: list[dict], title: str | None = None) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO entries (ts, day, raw, is_meal, slot, title) VALUES (?, ?, ?, ?, ?, ?)",
                (ts.isoformat(), day_of(ts).isoformat(), raw, int(is_meal), slot, title),
            )
            entry_id = cur.lastrowid
            for it in items:
                self.db.execute(
                    "INSERT INTO items (entry_id, name, grams, kcal, protein, carbs, fat, emoji, food_id, servings, amount, unit, estimated) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry_id, it["name"], it.get("grams"), it["kcal"], it["protein"], it["carbs"], it["fat"], it.get("emoji"),
                     it.get("food_id"), it.get("servings"), it.get("amount"), it.get("unit"), int(it.get("estimated") or 0)),
                )
        return entry_id

    def delete_entry(self, entry_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def delete_item(self, item_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0

    def edit_item(self, item_id: int, fields: dict) -> bool:
        allowed = {k: v for k, v in fields.items() if k in ("name", "grams", "kcal", "protein", "carbs", "fat", "food_id", "servings", "amount", "unit", "estimated")}
        if not allowed:
            return False
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.db:
            return self.db.execute(
                f"UPDATE items SET {sets} WHERE id = ?", (*allowed.values(), item_id)
            ).rowcount > 0

    def set_entry_slot(self, entry_id: int, slot: str) -> bool:
        with self.db:
            return self.db.execute("UPDATE entries SET slot = ? WHERE id = ?", (slot, entry_id)).rowcount > 0

    def item(self, item_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else None

    def last_entry_id(self, day: date) -> int | None:
        row = self.db.execute(
            "SELECT id FROM entries WHERE day = ? ORDER BY id DESC LIMIT 1", (day.isoformat(),)
        ).fetchone()
        return row["id"] if row else None

    def last_meal_ts(self) -> datetime | None:
        row = self.db.execute("SELECT ts FROM entries WHERE is_meal = 1 ORDER BY ts DESC LIMIT 1").fetchone()
        return datetime.fromisoformat(row["ts"]) if row else None

    def day_entries(self, day: date) -> list[dict]:
        entries = []
        for e in self.db.execute("SELECT * FROM entries WHERE day = ? ORDER BY ts", (day.isoformat(),)):
            items = [dict(i) for i in self.db.execute("SELECT * FROM items WHERE entry_id = ? ORDER BY id", (e["id"],))]
            entries.append({**dict(e), "items": items})
        return entries

    def entry_items(self, entry_id: int) -> list[dict]:
        return [dict(i) for i in self.db.execute("SELECT * FROM items WHERE entry_id = ? ORDER BY id", (entry_id,))]

    def item_day(self, item_id: int) -> str | None:
        row = self.db.execute(
            "SELECT e.day FROM items i JOIN entries e ON e.id = i.entry_id WHERE i.id = ?", (item_id,)
        ).fetchone()
        return row["day"] if row else None

    def entry_day(self, entry_id: int) -> str | None:
        row = self.db.execute("SELECT day FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return row["day"] if row else None

    # --- water / steps / vitamin D --------------------------------------

    def add_extra(self, ts: datetime, kind: str, value: float) -> None:
        with self.db:
            if kind == "steps":  # steps is a running count: latest value replaces
                self.db.execute("DELETE FROM extras WHERE day = ? AND kind = 'steps'", (day_of(ts).isoformat(),))
            self.db.execute(
                "INSERT INTO extras (ts, day, kind, value) VALUES (?, ?, ?, ?)",
                (ts.isoformat(), day_of(ts).isoformat(), kind, value),
            )

    # --- totals ---------------------------------------------------------

    def totals(self, day: date) -> dict:
        d = day.isoformat()
        row = self.db.execute(
            """SELECT COALESCE(SUM(kcal),0) kcal, COALESCE(SUM(protein),0) protein,
                      COALESCE(SUM(carbs),0) carbs, COALESCE(SUM(fat),0) fat
               FROM items i JOIN entries e ON e.id = i.entry_id WHERE e.day = ?""",
            (d,),
        ).fetchone()
        extras = {
            r["kind"]: r["v"]
            for r in self.db.execute("SELECT kind, SUM(value) v FROM extras WHERE day = ? GROUP BY kind", (d,))
        }
        slots = {r["slot"] for r in self.db.execute("SELECT DISTINCT slot FROM entries WHERE day = ?", (d,))}
        count = self.db.execute("SELECT COUNT(*) c FROM entries WHERE day = ?", (d,)).fetchone()["c"]
        return {
            **dict(row),
            "water_ml": extras.get("water", 0),
            "steps": extras.get("steps"),
            "vitd": bool(extras.get("vitd")),
            "slots": slots,
            "entries": count,
        }

    def day_ok(self, day: date) -> bool | None:
        """True if the day hit both targets (small tolerance), False if missed, None if nothing logged."""
        t = self.totals(day)
        if t["entries"] == 0:
            return None
        g = self.goals(day)
        return t["kcal"] <= g["kcal"] + 100 and t["protein"] >= g["protein"] - 10

    def first_day(self) -> date | None:
        row = self.db.execute("SELECT MIN(day) d FROM entries").fetchone()
        return date.fromisoformat(row["d"]) if row and row["d"] else None

    def streak(self, through: date) -> int:
        """Consecutive on-target days ending at `through`."""
        n, d = 0, through
        while self.day_ok(d):
            n += 1
            d -= timedelta(days=1)
        return n

    # --- goals ------------------------------------------------------------

    def goals(self, day: date) -> dict:
        from .goals import DEFAULT_SUMMARY_TIME, FIELDS, default_goals
        g = default_goals()
        row = self.db.execute(
            "SELECT * FROM goals WHERE effective_day <= ? ORDER BY effective_day DESC LIMIT 1", (day.isoformat(),)
        ).fetchone()
        if row:
            g.update({k: row[k] for k in FIELDS if row[k] is not None})
        g["summary_time"] = self.get("summary_time") or DEFAULT_SUMMARY_TIME
        return g

    def set_goals(self, day: date, changes: dict) -> dict:
        from .goals import FIELDS
        g = {**self.goals(day), **changes}
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO goals (effective_day, kcal, protein, water_ml, steps) VALUES (?, ?, ?, ?, ?)",
                (day.isoformat(), *(g[k] for k in FIELDS)),
            )
        if "summary_time" in changes:
            self.set("summary_time", changes["summary_time"])
        return self.goals(day)

    # --- remembered foods -------------------------------------------------

    @staticmethod
    def _norm(v) -> str:
        return (v or "").strip().lower()

    def save_food(self, f: dict) -> tuple[int, bool]:
        """Upsert on (name, brand, variant). Returns (id, updated)."""
        name, brand, variant = self._norm(f["name"]), self._norm(f.get("brand")), self._norm(f.get("variant"))
        vals = {
            "aliases": f.get("aliases"), "serving_desc": f.get("serving_desc") or f.get("description"),
            "serving_qty": f.get("serving_qty"), "serving_unit": f.get("serving_unit") or None,
            "kcal": f.get("kcal"), "protein": f.get("protein"), "carbs": f.get("carbs"), "fat": f.get("fat"),
            "notes": f.get("notes"),
        }
        with self.db:
            row = self.db.execute(
                "SELECT id FROM foods WHERE name = ? AND COALESCE(brand, '') = ? AND COALESCE(variant, '') = ?",
                (name, brand, variant),
            ).fetchone()
            if row:
                food_id, updated = row["id"], True
                old = self.db.execute("SELECT aliases, notes FROM foods WHERE id = ?", (food_id,)).fetchone()
                vals["aliases"] = self._merge_aliases(old["aliases"], vals["aliases"])
                vals["notes"] = vals["notes"] or old["notes"]  # a re-read label without notes keeps his
                sets = ", ".join(f"{k} = ?" for k in vals)
                self.db.execute(f"UPDATE foods SET {sets} WHERE id = ?", (*vals.values(), food_id))
            else:
                cols = ", ".join(("name", "brand", "variant", *vals))
                marks = ", ".join("?" * (3 + len(vals)))
                food_id = self.db.execute(
                    f"INSERT INTO foods ({cols}) VALUES ({marks})", (name, brand, variant, *vals.values())
                ).lastrowid
                updated = False
            if f.get("make_default"):
                self._make_default(food_id)
        return food_id, updated

    @staticmethod
    def _merge_aliases(old: str | None, new: str | None) -> str:
        """Comma-separated aliases, old ones first, duplicates (any case) dropped."""
        out, seen = [], set()
        for a in f"{old or ''},{new or ''}".split(","):
            if (a := a.strip()) and a.lower() not in seen:
                seen.add(a.lower())
                out.append(a)
        return ", ".join(out)

    def _make_default(self, food_id: int) -> None:
        self.db.execute(
            "UPDATE foods SET is_default = 0 WHERE name = (SELECT name FROM foods WHERE id = ?) AND id != ?",
            (food_id, food_id),
        )
        self.db.execute("UPDATE foods SET is_default = 1 WHERE id = ?", (food_id,))

    def foods(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM foods ORDER BY name, brand")]

    def food(self, food_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM foods WHERE id = ?", (food_id,)).fetchone()
        return dict(row) if row else None

    def edit_food(self, food_id: int, fields: dict) -> bool:
        allowed = {k: (self._norm(v) if k in ("name", "brand", "variant") else v)
                   for k, v in fields.items() if k in FOOD_COLS}
        if not allowed:
            return False
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.db:
            return self.db.execute(f"UPDATE foods SET {sets} WHERE id = ?", (*allowed.values(), food_id)).rowcount > 0

    def delete_food(self, food_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM foods WHERE id = ?", (food_id,)).rowcount > 0

    def set_default_food(self, food_id: int) -> bool:
        if not self.food(food_id):
            return False
        with self.db:
            self._make_default(food_id)
        return True

    # --- conversation + state --------------------------------------------

    def add_message(self, ts: datetime, role: str, text: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO messages (ts, role, text) VALUES (?, ?, ?)", (ts.isoformat(), role, text))

    def recent_messages(self, n: int = 8) -> list[dict]:
        rows = self.db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value))
