"""One-off: turn the old free-text saved foods into label fields. Run: python -m sarge.migrate_foods

Only rows the automatic migration left behind (brand NULL, no serving size) are touched, and only their
label fields: the macros are never read back from the brain. Safe to re-run; a failed row is retried.
Back up the .db before running."""

import asyncio
import sqlite3

from .brain import FOOD, BrainError, ClaudeBrain
from .config import ROOT, env, load_env
from .store import Store

PARSE_FIELDS = {k: v for k, v in FOOD.items() if k != "make_default"}
PARSE_SCHEMA = {"type": "object", "properties": PARSE_FIELDS, "required": list(PARSE_FIELDS)}

PARSE_SYSTEM = (
    "Parse this saved food's free-text description into label fields. Do not change the numbers; per-serving values "
    "are the given kcal/protein/carbs/fat. If the serving size in grams or ml is stated, fill serving_qty/unit, else 0/''. "
    "Brand is only the manufacturer or store brand, 1-3 words (e.g. 'Hillcrest', 'Valley Basics'); product descriptors go in "
    "variant (e.g. '0% plain'); preparation or recipe details go in notes; leave brand '' if none is stated."
)

LABEL_FIELDS = ("name", "brand", "variant", "aliases", "serving_desc", "serving_qty", "serving_unit", "notes")


def row_text(f: dict) -> str:
    return (f"name: {f['name']}\nserving_desc: {f['serving_desc'] or ''}\n"
            f"per serving: {f['kcal']} kcal, {f['protein']} g protein, {f['carbs']} g carbs, {f['fat']} g fat")


def label_fields(f: dict, parsed: dict, others: list[dict]) -> dict:
    """Label fields to write. The name is never changed (a different parsed name becomes an alias), and
    brand/variant are left alone when another food already has that identity."""
    norm = Store._norm
    out = {"notes": parsed.get("notes")}
    aliases = [a.strip() for a in (parsed.get("aliases") or "").split(",") if a.strip()]
    parsed_name = (parsed.get("name") or "").strip().lower()
    if parsed_name and parsed_name != f["name"]:
        aliases.append(parsed_name)
    seen, kept = set(), []
    for a in aliases:
        if a.lower() not in seen:
            seen.add(a.lower())
            kept.append(a)
    out["aliases"] = ", ".join(kept)
    if (parsed.get("serving_desc") or "").strip():
        out["serving_desc"] = parsed["serving_desc"]
    try:
        qty = float(parsed.get("serving_qty") or 0)
    except (TypeError, ValueError):
        qty = 0
    out["serving_qty"] = qty or None
    out["serving_unit"] = parsed.get("serving_unit") if parsed.get("serving_unit") in ("g", "ml") else None
    brand, variant = parsed.get("brand") or "", parsed.get("variant") or ""   # never NULL: marks a row as done
    if any((norm(o["name"]), norm(o["brand"]), norm(o["variant"])) == (f["name"], norm(brand), norm(variant)) for o in others):
        print(f"warning {f['id']} | {f['name']}: another food is already {brand!r}/{variant!r}; brand and variant not set")
    else:
        out["brand"], out["variant"] = brand, variant
    return out


async def enrich(store: Store, brain) -> list[dict]:
    updated = []
    for f in pending(store):
        try:
            parsed = await brain.interpret(row_text(f), PARSE_SYSTEM, schema=PARSE_SCHEMA)
            others = [o for o in store.foods() if o["id"] != f["id"]]
            store.edit_food(f["id"], label_fields(f, parsed, others))
        except (BrainError, ValueError, TypeError, sqlite3.Error) as e:
            print(f"skipped {f['id']} | {f['name']}: {e}")
            continue
        updated.append(store.food(f["id"]))
    return updated


def pending(store: Store) -> list[dict]:
    return [f for f in store.foods() if f["brand"] is None and f["serving_qty"] is None]


def line(f: dict) -> str:
    qty = f"{f['serving_qty']:g} {f['serving_unit']}" if f["serving_qty"] and f["serving_unit"] else "-"
    return (f"{f['id']} | {f['name']} | {f['brand'] or ''} {f['variant'] or ''}".rstrip()
            + f" | {f['serving_desc'] or ''} | {qty} | {f['kcal']:g} kcal {f['protein']:g}P")


def main() -> None:
    load_env()
    store = Store(env("SARGE_DB", str(ROOT / "data" / "sarge.db")))
    brain = ClaudeBrain(env("CLAUDE_BIN"), env("CLAUDE_MODEL", "sonnet"), env("CLAUDE_PHOTO_MODEL", "opus"))
    needed = len(pending(store))
    updated = asyncio.run(enrich(store, brain))
    for f in store.foods():
        print(line(f))
    print(f"{len(updated)} of {needed} enriched, {needed - len(updated)} failed")


if __name__ == "__main__":
    main()
