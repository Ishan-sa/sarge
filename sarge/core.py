"""Glue: user message -> Claude interpretation -> validated store writes -> reply HTML."""

from datetime import datetime, timedelta
from html import escape

from . import render
from .brain import build_prompt
from .plan import SLOTS
from .store import Store, day_of

VALID_SLOTS = {*SLOTS, "extra"}


def apply(store: Store, result: dict, raw: str, ts: datetime) -> tuple[list[dict], list[str]]:
    """Apply a brain result to the store. Returns (new food items, lines describing other changes)."""
    today = day_of(ts).isoformat()
    changes: list[str] = []

    for entry_id in result.get("delete_entry_ids", []):
        if store.entry_day(entry_id) == today and store.delete_entry(entry_id):
            changes.append("🗑 <b>Deleted an entry</b>")
    for item_id in result.get("delete_item_ids", []):
        if store.item_day(item_id) == today and store.delete_item(item_id):
            changes.append("🗑 <b>Removed an item</b>")
    for edit in result.get("item_edits", []):
        if store.item_day(edit.get("item_id")) == today and store.edit_item(edit["item_id"], edit):
            changes.append(f"✏️ <b>Updated:</b> {render.item_line(store.item(edit['item_id']))}")
    for se in result.get("slot_edits", []):
        slot = se.get("slot")
        if slot in VALID_SLOTS and store.entry_day(se.get("entry_id")) == today and store.set_entry_slot(se["entry_id"], slot):
            changes.append(f"🏷 <b>Moved to {escape(render.SLOT_LABELS[slot])}</b>")

    items = [i for i in result.get("items", []) if i.get("name")]
    if items:
        slot = result.get("slot") if result.get("slot") in VALID_SLOTS else "extra"
        title = (result.get("title") or "").strip() or render.SLOT_LABELS[slot].lower()
        store.log_entry(ts, raw, bool(result.get("is_meal")), slot, items, title)

    if result.get("water_ml", 0) > 0:
        store.add_extra(ts, "water", result["water_ml"])
        changes.append(f"💧 <b>+{result['water_ml']:.0f}ml water</b>")
    if result.get("steps", 0) > 0:
        store.add_extra(ts, "steps", result["steps"])
        changes.append(f"👟 <b>Steps: {render.fmt(result['steps'])}</b>")
    if result.get("vitamin_d"):
        store.add_extra(ts, "vitd", 1)
        changes.append("💊 <b>Vitamin D taken</b>")
    for food in result.get("save_foods", []):
        store.save_food(food)
        changes.append(f"📌 Saved to your foods: {escape(food['name'])}")
    return items, changes


async def handle_text(store: Store, brain, text: str, ts: datetime) -> str:
    day = day_of(ts)
    prompt = build_prompt(
        text,
        ts.strftime("%A %Y-%m-%d %H:%M"),
        store.day_entries(day),
        store.foods(),
        store.recent_messages(),
        store.totals(day),
        store.day_entries(day - timedelta(days=1)),
    )
    result = await brain.interpret(prompt)
    items, changes = apply(store, result, text, ts)
    comment = result.get("reply", "").strip()
    totals = store.totals(day)
    if items:
        title = (result.get("title") or "").strip() or "food"
        out = render.meal_reply(title, items, totals, comment)
        if changes:
            out += "\n\n" + "\n".join(changes)
    else:
        out = render.other_reply(changes, totals, comment, bool(result.get("show_status")))
    store.add_message(ts, "user", text)
    store.add_message(ts, "sarge", comment or "(logged)")
    return out
