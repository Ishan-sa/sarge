import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DAY_ROLLOVER_HOUR, TZ

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
CREATE TABLE IF NOT EXISTS extras (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,   -- water | steps | vitd
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS foods (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    kcal REAL NOT NULL,
    protein REAL NOT NULL,
    carbs REAL NOT NULL,
    fat REAL NOT NULL
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
"""


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

    def _migrate(self) -> None:
        cols = {t: {r["name"] for r in self.db.execute(f"PRAGMA table_info({t})")} for t in ("entries", "items")}
        with self.db:
            if "title" not in cols["entries"]:
                self.db.execute("ALTER TABLE entries ADD COLUMN title TEXT")
            if "emoji" not in cols["items"]:
                self.db.execute("ALTER TABLE items ADD COLUMN emoji TEXT")

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
                    "INSERT INTO items (entry_id, name, grams, kcal, protein, carbs, fat, emoji) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (entry_id, it["name"], it.get("grams"), it["kcal"], it["protein"], it["carbs"], it["fat"], it.get("emoji")),
                )
        return entry_id

    def delete_entry(self, entry_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount > 0

    def delete_item(self, item_id: int) -> bool:
        with self.db:
            return self.db.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0

    def edit_item(self, item_id: int, fields: dict) -> bool:
        allowed = {k: v for k, v in fields.items() if k in ("name", "grams", "kcal", "protein", "carbs", "fat")}
        if not allowed:
            return False
        sets = ", ".join(f"{k} = ?" for k in allowed)
        with self.db:
            return self.db.execute(
                f"UPDATE items SET {sets} WHERE id = ?", (*allowed.values(), item_id)
            ).rowcount > 0

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

    def save_food(self, f: dict) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO foods (name, description, kcal, protein, carbs, fat) VALUES (?, ?, ?, ?, ?, ?)",
                (f["name"].strip().lower(), f["description"], f["kcal"], f["protein"], f["carbs"], f["fat"]),
            )

    def foods(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM foods ORDER BY name")]

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
