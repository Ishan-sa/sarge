"""Glue: user message -> Claude interpretation -> validated store writes -> reply HTML.

Claude decides what was eaten and how much; every number that reaches the log is checked or computed
here. A bad action becomes a problem line in the reply, never an exception.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape

from . import goals as goals_mod
from . import render
from .brain import build_prompt, system_prompt
from .foods import ScaleError, scale
from .store import Store, day_of

MACROS = ("kcal", "protein", "carbs", "fat")
FOOD_FIELDS = ("name", "brand", "variant", "aliases", "serving_desc", "serving_qty", "serving_unit",
               "kcal", "protein", "carbs", "fat", "notes")
FOOD_NUMBERS = ("serving_qty", *MACROS)
KEEP_IF_BLANK = ("name", "brand", "variant", "serving_desc")  # identify the product; a blank is a copying slip
KEEP_IF_EMPTY = ("serving_qty", "serving_unit")  # the size isn't shown in MY FOODS lines; 0 or "" is a slip too
JUNK = {"none", "no brand", "n/a", "na", "null", "-"}
UNITS = ("g", "ml")


@dataclass
class Outcome:
    logged: list[dict] = field(default_factory=list)
    title: str = ""
    draft_touched: bool = False
    lines: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _num(v) -> float | None:
    """A real, finite number from the brain, or None. bool is not a number here."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _list(result: dict, key: str) -> list:
    v = result.get(key)
    return v if isinstance(v, list) else []


def _ids(result: dict, key: str) -> list[int]:
    return [int(v) for v in _list(result, key) if _num(v) is not None]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _note(i: dict) -> str:
    grams = f"{i['grams']:g}g" if i.get("grams") else "?g"
    return f"{i['name']} {grams} — {i['kcal']:g} kcal P{i['protein']:g} C{i['carbs']:g} F{i['fat']:g}"


# --- numbers -----------------------------------------------------------------


def _macros(src: dict) -> dict | None:
    """Claude's own numbers for an estimated item: all four macros must be numbers >= 0."""
    out = {k: _num(src.get(k)) for k in MACROS}
    if any(v is None or v < 0 for v in out.values()):
        return None
    grams = _num(src.get("grams"))
    return {"grams": grams if grams and grams > 0 else 0, **out}


def _ref(src: dict) -> dict:
    """How much of a saved food: servings, or amount + unit."""
    servings = _num(src.get("servings")) or 0
    if servings > 0:
        return {"servings": servings, "amount": 0, "unit": ""}
    unit = src.get("unit") if src.get("unit") in UNITS else ""
    return {"servings": 0, "amount": _num(src.get("amount")) or 0, "unit": unit}


def _scaled(food: dict, ref: dict, what: str, problems: list[str]) -> dict | None:
    try:
        return scale(food, servings=ref["servings"] or 0, amount=ref["amount"] or 0, unit=ref["unit"] or "")
    except ScaleError as e:
        problems.append(f"{what}: {e}")
        return None


# --- step 1: saved foods ------------------------------------------------------


def _food_problem(f: dict) -> str | None:
    if not _text(f.get("name")) or not _text(f.get("serving_desc")):
        return "a label without a name or serving"
    for k in FOOD_NUMBERS:
        v = f.get(k)
        if (v is not None or k != "serving_qty") and (_num(v) is None or v < 0):
            return f"{_text(f.get('name'))}: {k} isn't a valid number"
    return None


IDENTITY = ("name", "brand", "variant")
SCALING = (*FOOD_NUMBERS, "serving_unit")  # fields that change what a logged amount is worth


def _identity(f: dict) -> tuple[str, ...]:
    return tuple(_text(f.get(k)).lower() for k in IDENTITY)


def _clean_identity(f: dict) -> dict:
    """name/brand/variant trimmed and lowercased; a junk brand or variant ("none", "n/a") is blank."""
    out = {k: _text(f.get(k)).lower() for k in IDENTITY}
    for k in ("brand", "variant"):
        if out[k] in JUNK:
            out[k] = ""
    return out


def _save_foods(store: Store, result: dict, ts: datetime, out: Outcome) -> list[int | None]:
    new_ids: list[int | None] = []
    for f in _list(result, "save_foods"):
        problem = _food_problem(f) if isinstance(f, dict) else "a label I couldn't read"
        if problem:
            out.problems.append(f"Didn't save {problem}.")
            new_ids.append(None)
            continue
        f = {**f, **_clean_identity(f)}
        before = next((x for x in store.foods() if _identity(x) == _identity(f)), None)
        unit = f.get("serving_unit") if f.get("serving_unit") in UNITS else None
        food_id, updated = store.save_food({**f,
                                            "serving_qty": f.get("serving_qty") or None, "serving_unit": unit})
        new_ids.append(food_id)
        food = store.food(food_id)
        out.lines.append(render.food_saved_line(food, updated))
        if before and any((before[k] or None) != (food[k] or None) for k in SCALING):
            _rescale_lines(store, food, ts, out)
    return new_ids


def _food_changes(store: Store, food: dict, edit: dict) -> tuple[dict, str | None]:
    """Only the fields that really change. Identity fields never go blank or to 'none'."""
    changes = {}
    for k in FOOD_FIELDS:
        if k not in edit:
            continue
        v = edit[k]
        if k in KEEP_IF_EMPTY and v in (0, None, ""):
            continue
        if k in FOOD_NUMBERS:
            v = _num(v)
            if v is None or v < 0:
                return {}, f"{food['name']}: {k} {edit[k]!r} isn't a valid number"
        elif k == "serving_unit":
            v = v if v in UNITS else None
        else:
            v = _text(v)
            if k in IDENTITY:
                v = v.lower()
            if k in ("brand", "variant") and v in JUNK:
                v = ""
            if not v and k in KEEP_IF_BLANK:
                continue
        if (v or None) != (food[k] or None):
            changes[k] = v
    if set(IDENTITY) & changes.keys():
        key = tuple(changes.get(k, food[k]) or "" for k in IDENTITY)
        if any(f["id"] != food["id"] and _identity(f) == key
               for f in store.foods()):
            return {}, f"another saved food is already called {' '.join(x for x in key if x)}"
    return changes, None


def _rescale_refs(store: Store, food: dict, ts: datetime, problems: list[str]) -> tuple[int, int]:
    """A corrected label recomputes today's items and the draft items that use it. Past days keep their numbers."""
    logged = drafted = 0
    for e in store.day_entries(day_of(ts)):
        for i in e["items"]:
            if i["food_id"] == food["id"]:
                fields = _scaled(food, _ref(i), f"Couldn't recompute {i['name']}", problems)
                if fields and store.edit_item(i["id"], fields):
                    logged += 1
    for d in store.draft(ts):
        if d["food_id"] == food["id"]:
            fields = _scaled(food, _ref(d), f"Couldn't recompute {d['name']}", problems)
            if fields and store.draft_edit(d["id"], fields):
                drafted += 1
    return logged, drafted


def _rescale_lines(store: Store, food: dict, ts: datetime, out: Outcome) -> None:
    logged, drafted = _rescale_refs(store, food, ts, out.problems)
    if logged:
        out.lines.append(f"✏️ Updated {_plural(logged, 'logged item')}")
    if drafted:
        out.lines.append(f"✏️ Updated {_plural(drafted, 'draft item')}")


def _edit_foods(store: Store, result: dict, ts: datetime, out: Outcome) -> None:
    for edit in _list(result, "food_edits"):
        food = store.food(int(_num(edit.get("id")) or 0)) if isinstance(edit, dict) else None
        if not food:
            out.problems.append("Couldn't find that saved food to fix.")
            continue
        changes, problem = _food_changes(store, food, edit)
        if problem:
            out.problems.append(f"Didn't change the food: {problem}.")
            continue
        if changes:
            store.edit_food(food["id"], changes)
            food = store.food(food["id"])
            out.lines.append(render.food_saved_line(food, True))
            if changes.keys() & set(SCALING):
                _rescale_lines(store, food, ts, out)
        if (edit.get("make_default") is True or edit.get("is_default") is True) and not food["is_default"]:
            _make_default(store, food["id"], out)

    for food_id in _ids(result, "delete_food_ids"):
        food = store.food(food_id)
        if food and store.delete_food(food_id):
            out.lines.append(f"🗑 Deleted {render.food_label(food)}")
        else:
            out.problems.append(f"No saved food {food_id} to delete.")

    default_id = _num(result.get("default_food_id"))
    if default_id and default_id > 0:
        _make_default(store, int(default_id), out)


def _make_default(store: Store, food_id: int, out: Outcome) -> None:
    if store.set_default_food(food_id):
        food = store.food(food_id)
        out.lines.append(f"⭐ {render.food_label(food)} is your default {escape(food['name'])}")
    else:
        out.problems.append(f"No saved food {food_id} to make the default.")


# --- step 2: items ---------------------------------------------------------------


def _resolve(store: Store, it: dict, new_ids: list[int | None], problems: list[str]) -> dict | None:
    """A brain item in stored form. Saved and new foods are scaled from the label; the rest keep Claude's estimate."""
    name = _text(it.get("name"))
    if not name:
        return None
    base = {"name": name, "emoji": _text(it.get("emoji")) or None}
    index, food_id = _num(it.get("new_food_index")), _num(it.get("food_id"))
    if index is not None and index >= 0:
        if index == int(index) and index < len(new_ids) and new_ids[int(index)] is not None:
            food_id = new_ids[int(index)]
        elif not food_id and (macros := _macros(it)) and any(macros[k] > 0 for k in MACROS):
            problems.append(f"No saved label for {name}, so I used my estimate.")
            return {**base, **macros, "food_id": None, "servings": None, "amount": None, "unit": None, "estimated": 1}
        else:
            problems.append(f"Skipped {name}: no saved label to go with it.")
            return None
    if food_id and food_id > 0:
        food = store.food(int(food_id))
        if not food:
            problems.append(f"Skipped {name}: saved food {food_id:g} doesn't exist.")
            return None
        ref = _ref(it)
        fields = _scaled(food, ref, f"Skipped {name}", problems)
        if fields is None:
            return None
        return {**base, **fields, "food_id": food["id"], **ref, "estimated": 0}
    macros = _macros(it)
    if macros is None:
        problems.append(f"Skipped {name}: its numbers aren't valid.")
        return None
    return {**base, **macros, "food_id": None, "servings": None, "amount": None, "unit": None, "estimated": 1}


def _edited(store: Store, current: dict, edit: dict, problems: list[str]) -> dict | None:
    """New fields for a logged or draft item. A saved-food item is re-scaled; the brain's macros are ignored."""
    name = _text(edit.get("name")) or current["name"]
    if current.get("food_id"):
        food = store.food(current["food_id"])
        if not food:
            problems.append(f"Couldn't change {current['name']}: its saved food was deleted.")
            return None
        ref = _ref(edit)
        if not ref["servings"] and not ref["amount"]:
            ref = _ref(current)  # a rename only: keep the amount
        fields = _scaled(food, ref, f"Couldn't change {current['name']}", problems)
        return {"name": name, **fields, **ref} if fields else None
    macros = _macros(edit)
    if macros is None:
        problems.append(f"Couldn't change {current['name']}: the new numbers aren't valid.")
        return None
    return {"name": name, **macros}


# --- steps 4-6: the draft and the log --------------------------------------------------


def _portion(d: dict, share: float) -> dict:
    """The part of a draft item he ate."""
    out = {k: d[k] for k in ("name", "emoji", "food_id", "unit", "estimated")}
    for k in ("grams", *MACROS):
        out[k] = round((d[k] or 0) * share, 1)
    for k in ("servings", "amount"):
        out[k] = d[k] * share if d[k] else d[k]
    if share < 1:
        out["name"] = f"{d['name']} ×{share:.2g}"
    return out


def _edit_draft(store: Store, result: dict, ts: datetime, out: Outcome) -> None:
    draft_ids = {d["id"] for d in store.draft(ts)}  # draft() drops an expired draft first
    if result.get("clear_draft") is True:
        out.draft_touched = True
        if draft_ids:
            store.draft_clear()
            draft_ids = set()
            out.lines.append("🗑 Draft scrapped")
    for edit in _list(result, "draft_edits"):
        item_id = _num(edit.get("id")) if isinstance(edit, dict) else None
        if item_id not in draft_ids:
            out.problems.append("That draft item isn't in the draft any more.")
            continue
        fields = _edited(store, store.draft_item(int(item_id)), edit, out.problems)
        if fields and store.draft_edit(int(item_id), fields):
            out.draft_touched = True
    for item_id in _ids(result, "draft_remove_ids"):
        if item_id in draft_ids and store.draft_remove(item_id):
            out.draft_touched = True
        else:
            out.problems.append("That draft item isn't in the draft any more.")


def _log_and_draft(store: Store, result: dict, resolved: list[dict], raw: str, ts: datetime, out: Outcome) -> None:
    title = _text(result.get("title"))
    items_to = result.get("items_to")
    share = min(max(_num(result.get("eat_draft")) or 0, 0), 1)
    to_log, ate_draft, log_title = [], False, title
    if share > 0:
        draft = store.draft(ts)
        if draft:
            to_log, ate_draft = [_portion(d, share) for d in draft], True
            log_title = store.draft_title() or title  # the eaten draft keeps its name; a new draft gets the brain's
        else:
            out.problems.append("Nothing in the draft to log.")
    if items_to == "log":
        to_log += resolved
    if to_log:
        out.title = log_title or "food"
        store.log_entry(ts, raw, True, "meal", to_log, out.title)
        out.logged = to_log
    if ate_draft:
        store.draft_clear()
        out.draft_touched = True
    if items_to == "draft" and resolved:
        store.draft_add(ts, resolved, title or None)
        out.title = out.title or title
        out.draft_touched = True


# --- step 7: today's log -------------------------------------------------------------


def _edit_log(store: Store, result: dict, ts: datetime, out: Outcome) -> None:
    today = day_of(ts).isoformat()
    for entry_id in _ids(result, "delete_entry_ids"):
        if store.entry_day(entry_id) == today and store.delete_entry(entry_id):
            out.lines.append("🗑 <b>Deleted an entry</b>")
        else:
            out.problems.append("Can only delete entries from today's log.")
    for item_id in _ids(result, "delete_item_ids"):
        if store.item_day(item_id) == today and store.delete_item(item_id):
            out.lines.append("🗑 <b>Removed an item</b>")
        else:
            out.problems.append("Can only remove items from today's log.")
    for edit in _list(result, "item_edits"):
        item_id = _num(edit.get("id")) if isinstance(edit, dict) else None
        if item_id is None or store.item_day(int(item_id)) != today:
            out.problems.append("Can only change items in today's log.")
            continue
        fields = _edited(store, store.item(int(item_id)), edit, out.problems)
        if fields and store.edit_item(int(item_id), fields):
            out.lines.append(f"✏️ <b>Updated:</b> {render.item_line(store.item(int(item_id)))}")


# --- steps 8-9: goals and extras --------------------------------------------------------


def _set_goals(store: Store, result: dict, ts: datetime, out: Outcome) -> None:
    asked = result.get("set_goals")
    if not isinstance(asked, dict):
        return
    changes = {"summary_time": asked.get("summary_time")}
    for k in goals_mod.FIELDS:
        v = asked.get(k)
        if _num(v) is not None:
            changes[k] = v
        elif v not in (None, "", False):
            out.problems.append(f"{k} goal {v!r} isn't a number")
    clean, errors = goals_mod.validate(changes)
    out.problems += errors
    if clean:
        out.lines.append(render.goals_line(store.set_goals(day_of(ts), clean)))


def _extras(store: Store, result: dict, ts: datetime, out: Outcome) -> None:
    water, steps = _num(result.get("water_ml")), _num(result.get("steps"))
    if water and water > 0:
        store.add_extra(ts, "water", water)
        out.lines.append(f"💧 <b>+{water:.0f}ml water</b>")
    if steps and steps > 0:
        store.add_extra(ts, "steps", steps)
        out.lines.append(f"👟 <b>Steps: {render.fmt(steps)}</b>")
    if result.get("vitamin_d") is True:
        store.add_extra(ts, "vitd", 1)
        out.lines.append("💊 <b>Vitamin D taken</b>")


def apply(store: Store, result: dict, raw: str, ts: datetime) -> Outcome:
    """Validate and apply a brain result. Failures go to Outcome.problems; nothing raises."""
    out = Outcome()
    new_ids = _save_foods(store, result, ts, out)
    _edit_foods(store, result, ts, out)
    resolved = [r for it in _list(result, "items") if isinstance(it, dict)
                and (r := _resolve(store, it, new_ids, out.problems))]
    _edit_draft(store, result, ts, out)
    _log_and_draft(store, result, resolved, raw, ts, out)
    _edit_log(store, result, ts, out)
    _set_goals(store, result, ts, out)
    _extras(store, result, ts, out)
    return out


# --- the message --------------------------------------------------------------------------


def _picks(result: dict) -> list[dict]:
    return [
        {**p, "how": _text(p.get("how"))}
        for p in _list(result, "picks")
        if isinstance(p, dict) and _text(p.get("name")) and _num(p.get("kcal")) is not None and _num(p.get("protein")) is not None
    ]


def _history(out: Outcome, draft: list[dict], draft_title: str, picks: list[dict], comment: str) -> str:
    """How Sarge's turn is remembered: exact numbers, so a later "ate it" or "fix that" can refer back."""
    parts = []
    if out.logged:
        parts.append(f"LOGGED {out.title}: " + "; ".join(_note(i) for i in out.logged))
    if out.draft_touched and draft:
        parts.append(f"DRAFT {draft_title or 'meal'} (not eaten yet): " + "; ".join(_note(d) for d in draft))
    if picks:
        parts.append("menu picks, NOT logged: " + "; ".join(f"{p['name']} ~{p['kcal']:g} kcal P{p['protein']:g}" for p in picks))
    if out.problems:
        parts.append("problems: " + "; ".join(out.problems))
    if comment:
        parts.append(comment)
    return " | ".join(parts) or "(ok)"


async def handle(store: Store, brain, text: str, images: list[tuple[bytes, str]], ts: datetime) -> str:
    """One message (text, a photo or an album) in, the reply HTML out."""
    day = day_of(ts)
    goals = store.goals(day)
    caption = (text or "").strip()
    said = f"[photo x{len(images)}] {caption}".strip() if images else caption
    prompt = build_prompt(
        caption or (f"({_plural(len(images), 'photo')}, no caption)" if images else ""),
        ts.strftime("%A %Y-%m-%d %H:%M"),
        store.day_entries(day),
        store.foods(),
        store.draft(ts),
        store.recent_messages(),
        store.totals(day),
        goals,
        store.day_entries(day - timedelta(days=1)),
    )
    result = await brain.interpret(prompt, system_prompt(goals), images)
    out = apply(store, result, said, ts)

    comment = _text(result.get("reply"))
    t, g = store.totals(day), store.goals(day)
    draft, draft_title = store.draft(ts), store.draft_title()
    picks = _picks(result)
    notes = out.lines + [f"⚠️ {escape(p)}" for p in out.problems]
    if out.logged:
        reply = render.meal_reply(out.title, out.logged, t, g, comment)
        if out.draft_touched and draft:  # the same message also changed the pending meal: show it
            reply += "\n\n" + render.draft_reply(draft_title or "meal", draft, "")
    elif out.draft_touched and draft:
        reply = render.draft_reply(draft_title or "meal", draft, comment)
    elif picks:
        reply = render.picks_block(picks, t, g) + (f"\n\n🗣 {escape(comment)}" if comment else "")
    else:
        reply, notes = render.other_reply(notes, t, g, comment, result.get("show_status") is True), []
    if notes:
        reply += "\n\n" + "\n".join(notes)

    store.add_message(ts, "user", said)
    store.add_message(ts, "sarge", _history(out, draft, draft_title, picks, comment))
    return reply
