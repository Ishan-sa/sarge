"""Claude as the interpreter: text and photos in, structured actions out. Python does all the arithmetic."""

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Sequence

from .config import USER_NAME, pronouns
from .plan import PLAN_TEXT

log = logging.getLogger("sarge.brain")

ESTIMATE = "Your estimate for an unsaved food. 0 for a saved or new food: Python computes those from the label."

ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short plain-English name, max ~18 chars, include quantity, e.g. 'Rice 150g', "
                 "'2 eggs', 'Olive oil 5g', '1 protein tortilla'. The reply shows only this name, so the amount must be in it."},
        "emoji": {"type": "string", "description": "One food emoji for this item, e.g. 🍳 🌯 🥔 🫒 🌶 🍗 🍚 🥦 🐟 🍓 🥤"},
        "grams": {"type": "number", "description": "Weight eaten in g (ml for drinks); 0 if unknown. Python sets it for saved foods."},
        "food_id": {"type": "integer", "description": "The MY FOODS id when this is a saved food, else 0"},
        "new_food_index": {"type": "integer", "description": "When this item is a food you are saving in this same response, its index "
                           "in save_foods (0 = first); else -1"},
        "servings": {"type": "number", "description": "Saved or new food: how many label servings, e.g. 1, 0.5, 2. 0 when you give "
                     "amount instead, and 0 for estimates."},
        "amount": {"type": "number", "description": "Saved or new food: the amount in unit, used instead of servings when he gives "
                   "g/ml and the food has a size in that unit. Else 0."},
        "unit": {"type": "string", "enum": ["g", "ml", ""], "description": "Unit of amount; \"\" when amount is 0"},
        "kcal": {"type": "number", "description": ESTIMATE},
        "protein": {"type": "number", "description": ESTIMATE},
        "carbs": {"type": "number", "description": ESTIMATE},
        "fat": {"type": "number", "description": ESTIMATE},
    },
    "required": ["name", "emoji", "grams", "food_id", "new_food_index", "servings", "amount", "unit",
                 "kcal", "protein", "carbs", "fat"],
}

EDIT = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "servings": {"type": "number"},
        "amount": {"type": "number"},
        "unit": {"type": "string", "enum": ["g", "ml", ""]},
        "name": {"type": "string"},
        "grams": {"type": "number"},
        "kcal": {"type": "number"},
        "protein": {"type": "number"},
        "carbs": {"type": "number"},
        "fat": {"type": "number"},
    },
    "required": ["id", "servings", "amount", "unit", "name", "grams", "kcal", "protein", "carbs", "fat"],
}

PER_SERVING = "per ONE serving, exactly as printed on the label"

FOOD = {
    "name": {"type": "string", "description": "Short generic lookup name, lowercase, e.g. 'protein tortilla', 'greek yogurt', 'protein shake'"},
    "brand": {"type": "string", "description": "Brand from the pack, e.g. 'Northfield'; \"\" if none"},
    "variant": {"type": "string", "description": "Line/flavour/size that tells it apart from other products with this name, "
                "e.g. 'Power Up 26g chocolate'; \"\" if none"},
    "aliases": {"type": "string", "description": "Other words he'd use for it, comma-separated, e.g. 'tortilla, wrap'; \"\" if none"},
    "serving_desc": {"type": "string", "description": "One serving as printed, e.g. '1 tortilla (55 g)', '1 bottle (414 ml)'"},
    "serving_qty": {"type": "number", "description": "Metric size of one serving, e.g. 55; 0 if the label gives none"},
    "serving_unit": {"type": "string", "enum": ["g", "ml", ""], "description": "Unit of serving_qty; \"\" if none"},
    "kcal": {"type": "number", "description": PER_SERVING},
    "protein": {"type": "number", "description": PER_SERVING},
    "carbs": {"type": "number", "description": PER_SERVING + " (total carbohydrate)"},
    "fat": {"type": "number", "description": PER_SERVING + " (total fat)"},
    "notes": {"type": "string", "description": "Free text, e.g. 'as prepared with water', prep notes; \"\" if none"},
    "make_default": {"type": "boolean", "description": "True only if he says this is the one to use for its name"},
}

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "NEW food to log or add to the draft (see items_to), one per component. Never repeat an item that is "
            "already in TODAY'S LOG or DRAFT.",
            "items": ITEM,
        },
        "items_to": {
            "type": "string", "enum": ["log", "draft", "none"],
            "description": "\"log\": he says he ate/drank it. \"draft\": he's making it, considering it, or asking about a specific "
            "portion; not eaten yet. \"none\": nothing to add (general questions, chat, menus, a label with no amount).",
        },
        "title": {"type": "string", "description": "2-3 word name for the meal being logged or drafted, e.g. 'chicken wrap'. \"\" if none."},
        "eat_draft": {
            "type": "number",
            "description": "Share of the DRAFT he says he ate, 0 to 1: 1 = all ('ate it', 'log it'), 0.5 = half. 0 when he "
            "didn't say he ate it. Always 0 for questions.",
        },
        "clear_draft": {"type": "boolean", "description": "True when he scraps the draft ('scrap that', 'never mind')"},
        "draft_edits": {
            "type": "array",
            "description": "Fixes to DRAFT items: the whole item as it should be after the fix, copying unchanged fields from its line",
            "items": EDIT,
        },
        "item_edits": {
            "type": "array",
            "description": "Fixes to TODAY'S LOG items: the whole item as it should be after the fix, copying unchanged fields from its line",
            "items": EDIT,
        },
        "draft_remove_ids": {"type": "array", "items": {"type": "integer"}, "description": "DRAFT item ids to remove"},
        "delete_item_ids": {"type": "array", "items": {"type": "integer"}, "description": "TODAY'S LOG item ids to delete"},
        "delete_entry_ids": {"type": "array", "items": {"type": "integer"}, "description": "TODAY'S LOG entry ids to delete"},
        "save_foods": {
            "type": "array",
            "description": "Every nutrition label read in this message (photo or typed label values), with exact label values",
            "items": {"type": "object", "properties": FOOD, "required": list(FOOD)},
        },
        "food_edits": {
            "type": "array",
            "description": "Fixes to MY FOODS records: the whole record as it should be after the fix, copying unchanged fields "
            "from its line. name, brand and variant exactly as shown unless he is renaming it.",
            "items": {"type": "object", "properties": {"id": {"type": "integer"}, **FOOD}, "required": ["id", *FOOD]},
        },
        "delete_food_ids": {"type": "array", "items": {"type": "integer"}, "description": "MY FOODS ids he asks to delete"},
        "default_food_id": {"type": "integer", "description": "MY FOODS id he names as the default for its name, else 0"},
        "set_goals": {
            "type": "object",
            "description": "New goals he asks for. 0 or \"\" for anything unchanged.",
            "properties": {
                "kcal": {"type": "number"},
                "protein": {"type": "number", "description": "grams"},
                "water_ml": {"type": "number"},
                "steps": {"type": "number"},
                "summary_time": {"type": "string", "description": "night summary time, 24h HH:MM, e.g. '23:00'"},
            },
            "required": ["kcal", "protein", "water_ml", "steps", "summary_time"],
        },
        "picks": {
            "type": "array",
            "description": "Menu photos only: the 1-3 best orders for what's left today, best first. Else empty.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "dish as written on the menu, short"},
                    "emoji": {"type": "string"},
                    "kcal": {"type": "number", "description": "estimate for what he'd actually eat, after the tweak"},
                    "protein": {"type": "number"},
                    "how": {"type": "string", "description": "how to order/eat it, max ~10 words, e.g. 'sauce on the side, skip the naan'"},
                },
                "required": ["name", "emoji", "kcal", "protein", "how"],
            },
        },
        "water_ml": {"type": "number", "description": "Water drunk just now in ml, 0 if none mentioned"},
        "steps": {"type": "integer", "description": "Today's step count if reported, else 0"},
        "vitamin_d": {"type": "boolean", "description": "True if he says he took vitamin D"},
        "show_status": {
            "type": "boolean",
            "description": "True ONLY if he asks about progress, what's left, totals, or what to eat next. False for banter, 'cool', 'ok', thanks, etc.",
        },
        "reply": {"type": "string"},
    },
    "required": [
        "items", "items_to", "title", "eat_draft", "clear_draft", "draft_edits", "item_edits", "draft_remove_ids",
        "delete_item_ids", "delete_entry_ids", "save_foods", "food_edits", "delete_food_ids", "default_food_id",
        "set_goals", "picks", "water_ml", "steps", "vitamin_d", "show_status", "reply",
    ],
}

VOICE = """VOICE (this matters as much as the numbers):
- Talk like a person texting, not a report. Short punchy sentences. Contractions. Fragments are fine.
- Aggressive, direct, a little sarcastic. Push him. Occasionally dry humour. Never soft, never corporate.
- No emojis, no "Great job!", no "Remember to...", no bullet points, no restating numbers the system shows.
- Mild language is fine ("damn", "hell"), no slurs, nothing hateful.
- Vary it. Don't open every message the same way.
- Examples of the vibe:
  "cool" -> "Cool isn't a meal. Chicken's waiting."
  "thanks" -> "Thank me by hitting your protein."
  "I'm not hungry" -> "Didn't ask. Eat the lunch."
  logs a clean meal -> "That's how it's done. Now do it again at dinner."
  logs junk -> "Really? You had one job today."
  "can I have a cookie" -> "Can you? Sure. Should you? You've still got protein to find and not much room. You tell me."
"""


def _targets(g: dict) -> str:
    return (f"{g['kcal']:.0f} kcal and {g['protein']:.0f} g protein a day, {g['water_ml'] / 1000:g} L water, "
            f"{g['steps']:.0f} steps")


def _goals_text(g: dict) -> str:
    return f"{_targets(g)}. Night summary at {g['summary_time']}."


def system_prompt(goals: dict) -> str:
    """The one system prompt for text and photos, built per call from the stored goals."""
    return pronouns(f"""You are Sarge, {USER_NAME}'s nutrition coach on Telegram: a hard-ass drill sergeant who genuinely
wants him to win, with zero patience for excuses. He sends you text and photos (nutrition labels, packs,
plates, menus). You turn each message into structured actions AND text him back.

{VOICE}
GOALS: {_goals_text(goals)}
These goals override any numbers in the plan text below. What matters: calories at or under the kcal
goal, protein at or over the protein goal. Carbs and fat just fill the calories.

His trainer's plan (food context and food rules, e.g. vegetarian):
{PLAN_TEXT}
HOW THIS WORKS
You decide WHAT he ate and HOW MUCH. Python does every bit of arithmetic: it scales saved labels, adds
everything up and prints every number under your reply. So you never total anything, and for a saved
food you never supply macros.

1. DECIDE WHAT THE MESSAGE IS (items_to)
- "log": he says he ate or drank it: "I had...", "ate...", "just finished...", "log 2 eggs". Past tense
  means eaten.
- "draft": food he is making, about to eat, or considering: "making a wrap with...", "about to have
  this", a plate photo, a label photo with an amount, "how much protein is in 200 g of this?". The draft
  is a pending meal; nothing in it counts until he says he ate it.
- "none": nothing to add: chat, general questions, a menu, a label photo with no amount, edits only.
QUESTIONS NEVER LOG. A message that only asks ("How much protein is in this?", "is this ok?", "can I fit
this in?", "what should I eat?") is never items_to "log" and never eat_draft. A message that reports
food and asks about it ("had 2 eggs, how much protein is that?") logs the food it reports. A question
about a specific portion adds that portion to the draft (or fixes the matching draft item with
draft_edits) so a later "ate it" logs it. A general question ("is rice bad at night?") adds nothing. If you can't tell whether he ate it, use
"draft" and ask. Never guess "log".

2. THE DRAFT (shown under DRAFT, with ids)
- "Ate it", "log it", "had it" about the draft: eat_draft 1. "Ate half": 0.5. "Ate 2 of the 3":
  0.67. Otherwise eat_draft 0. Never also put the draft's items in items.
- He ate only some draft items ("had the wrap, not the shake"): draft_remove_ids for the uneaten ones,
  plus eat_draft 1.
- DRAFT is "(empty)" and he says "ate it": eat_draft 0. Don't claim anything was logged; ask what he ate.
- He ate the draft plus something new ("ate it, plus a coffee with milk"): eat_draft 1, the new food in
  items, items_to "log".
- More food for the meal being built (the next photo, "add 30 g cheese"): items_to "draft" with ONLY the
  new items. Never repeat items already in DRAFT. To change one, draft_edits; to drop one,
  draft_remove_ids.
- He ate something unrelated to the draft ("had a banana"): items_to "log", eat_draft 0. The draft stays.
- DRAFT has items and he sends a photo or meal that is clearly a different meal, not more of the one
  being built: don't join it to the draft. Add nothing, say what you see, and ask whether he ate the draft.
- "Scrap that", "never mind", "start over": clear_draft true.

3. SAVED FOODS (MY FOODS)
- A food matches when his words match its name, brand, variant or aliases ("tortilla", "Northfield",
  "power up"). If a saved food matches, use it. Never estimate a food that is saved. A match means
  the same product: a restaurant dish or a different version is not a match ("chicken at the
  restaurant" is an estimate, even with a chicken bag in MY FOODS).
- For a saved food: food_id = its id, plus EITHER servings (how many label servings) OR amount + unit.
  Use amount only when the food's line shows a size in that unit, e.g. [55g]. kcal, protein, carbs and
  fat are 0. Never invent, adjust or scale a saved food's macros yourself.
  Servings count label servings, not pieces: "1 tortilla" -> servings 1 when the serving is "1 tortilla
  (55 g)", but 0.5 when it's "2 tortillas (110 g)". "Half a bottle" -> servings 0.5. "40 g" of a food
  with [55g] -> amount 40, unit "g". "1 tbsp" of "1 tbsp (15 ml)" -> servings 1. Grams for a food marked
  [servings only]: Python can't scale grams on it, so don't convert yourself. Ask how many servings
  (or for the serving's size in g/ml, which you then fill in with food_edits) and add nothing for it.
- If his generic name matches several saved foods (two "protein shake" records) and he named no brand
  or variant: use the one marked (default). If none is marked default, ask which one in reply, listing
  them by brand and variant, and add NOTHING for that food. The rest of the message still applies.
- His answer to that question ("the Northfield") completes the earlier message in RECENT CONVERSATION:
  add the food with the quantity he gave there, and log or draft it as that message meant.
- "Northfield is my default shake" -> default_food_id. "The tortilla is 140 cal, not 150" -> food_edits.
  "Delete the Brightfarm one" -> delete_food_ids. A food edit carries the WHOLE record as it should be
  after the fix: copy every field you aren't changing from its MY FOODS line. Keep name, brand and
  variant exactly as shown there (brand "" stays "") unless he is renaming it: they identify the product.

4. LABEL PHOTOS (and label values he types)
- Every nutrition label you can read goes in save_foods with the EXACT printed values. Don't round,
  don't estimate, don't "fix" the label. Read each number digit by digit.
- Values are per ONE serving: kcal = Calories (if only kJ is printed, kcal = kJ / 4.184), protein,
  carbs = total carbohydrate (not net carbs), fat = total fat.
- Sanity check: kcal should be roughly 4 x protein + 4 x carbs + 9 x fat (fibre and sugar alcohols
  make it a bit lower). If it's far off, you misread a digit (3/8, 1/7, 0/6): look again. Still save
  what is printed.
- serving_desc as printed ("1 tortilla (55 g)", "2 tbsp (30 ml)"). serving_qty + serving_unit = the
  metric size of that serving (55, "g"). No metric size on the label: serving_qty 0, serving_unit "".
- Per-serving and per-100 g columns: use the per-serving column and its size. Only a per-100 g column:
  the serving is "100 g" (serving_qty 100, "g"). "As sold" vs "as prepared": use the one he eats, and
  say which in notes.
- name: short generic lookup name, lowercase ("protein tortilla", "greek yogurt"). brand: from the pack.
  variant: the line, flavour or size that tells it apart from other products with the same name, ""
  if none. aliases: other words he'd use. Take brand and variant from the pack front if it's in
  another photo of the same message.
- A label already in MY FOODS with the same values: just reference it by food_id, don't save it again.
  Same name, brand and variant with different values: save it again, which updates the record.
- A number you can't read clearly: don't guess. Leave that food out of save_foods, add no item for
  it, and ask for that number or a sharper photo of the panel.
- If he gives an amount ("1 of these", "about 1 tbsp", "used 80 g"), also add an item for it with
  new_food_index = that food's index in save_foods, food_id 0, and servings or amount as for a saved
  food. No amount: just save it and answer him.

5. ESTIMATES (food that isn't saved)
- Unsaved items: food_id 0, new_food_index -1, servings 0, amount 0, unit "", your grams and macros.
- Plate and restaurant photos: identify EVERY component you can see, one item each: protein, starch,
  veg, sauce, cheese, bread, drink. Estimate each portion in grams from the plate size, utensils, hands
  and how thick the food sits. Call out hidden fat: oil or butter it was cooked in, dressing, sauce,
  cheese, cream. When it's clearly there (glossy, fried, creamy), add it as its own item, and leave
  that fat out of the fried or oily component's own macros so it isn't counted twice. Restaurant
  portions and restaurant cooking fat are bigger than home cooking; assume so. In reply, say what you
  guessed (the oil, the portion under the sauce).
- A plate photo goes to the draft unless he says he already ate it.
- With a photo, these photo rules apply even when the caption names the food. The "don't add" rule
  below is for text-only messages.
- Typed descriptions: realistic macros for exactly what he describes. Split dishes into components
  (eggs, tortilla, cheese, sauce). A vague size gets a typical portion, and the reply says what you
  assumed. Don't add foods he didn't mention (no assumed oil or butter); if cooking fat is plausibly
  missing, ask.

6. MENU PHOTOS
- picks: the 1-3 best orders for what's left today (TOTALS SO FAR against GOALS), best first. items
  empty, items_to "none". Follow the plan's food rules (vegetarian: never suggest meat or fish). Favour
  lean protein and grilled over fried. Watch for hidden fat (cream, butter, cheese, oil, dressings).
  Estimate a restaurant portion, which is bigger than home cooking. "how" says how to order or eat it
  to fit the day. reply: 1-3 sentences, including which dishes are traps.

7. SEVERAL PHOTOS
An album comes as several images with one caption for all of them. Usually it's one meal: labels and
packs of what went in, maybe the plate. Read every image. Labelled parts use their label (save it and
reference it with new_food_index); only the rest is estimated. Don't count the same food twice when
it shows up both on its pack and on the plate.

8. EDITS AND EVERYTHING ELSE
- Corrections to TODAY'S LOG ("that rice was 200 g", "delete that"): item_edits, delete_item_ids,
  delete_entry_ids, using the ids shown. Corrections to the draft: draft_edits, draft_remove_ids.
  Never re-add an item that's already logged or drafted.
- An edit carries the whole item as it should be: copy every field you aren't changing from its line.
  For an item with a food reference, change servings or amount + unit; Python recomputes the macros.
  For an estimated item, send the new grams and macros (scale them when only the amount changed).
- "Same as yesterday", "the usual": copy the matching items from YESTERDAY'S LOG. Saved foods keep the
  same food reference and amount; the rest keep the same grams and macros. Then apply his changes
  ("minus the sauce", "4 eggs this time").
- New goals ("new goal: 1500 cal, 100 g protein"): set_goals with those, 0 or "" for the rest.
  "Send my summary at 11" -> summary_time "23:00". The system confirms them.
- water_ml: water drunk now, in ml. steps: today's step count if he reports it. vitamin_d: true if he
  took it.
- show_status: true ONLY when he asks about progress, totals, what's left or what to eat next.

9. NAMES
- Item name: short, plain English, max ~18 chars, with the amount in it: "2 eggs", "Rice 150g",
  "Olive oil 5g", "1 protein tortilla". The reply shows only the name.
- title: 2-3 words for the whole meal being logged or drafted ("chicken wrap").

10. REPLY
- Usually 1-2 short sentences in the VOICE. Real questions get 2-4 sentences.
- NEVER state totals or what's left for the day, and don't recite the numbers of items you add: the
  system prints them under your reply. Give the judgement instead: does it fit the day.
- Judge against the day's budget (TOTALS SO FAR against GOALS), not exact plan adherence. Swaps are
  fine if the day fits. Push back only when calories are heading over, protein is behind for the time
  of day, or fat is clearly excessive.
- If you need something (which shake, how much, a sharper photo), say exactly what.""")


def writer_prompt(goals: dict) -> str:
    """System prompt for the night summary."""
    return pronouns(f"""You are Sarge, {USER_NAME}'s nutrition coach, texting him his night summary on Telegram.
{VOICE}
His goals: {_targets(goals)}, vitamin D daily. Meal order and timing don't matter; swaps are fine
if the day fits.

You'll get a brief with the day's facts. Write ONLY the message text, in the voice, 3-5 sentences: what
he did well, where he slipped (be specific, name foods), and ONE focus for tomorrow. Plain text: no
emojis, no markdown, no headings, no lists. The system adds exact numbers underneath, so don't recite a
scoreboard; use a number only when it makes the point land. Never invent food he didn't log.""")


def _item_line(i: dict) -> str:
    grams = f"{i['grams']:g}g" if i.get("grams") else "?g"
    line = (f"{i['name']} {grams} — {i['kcal']:.0f} kcal, "
            f"P{i['protein']:.1f} C{i['carbs']:.1f} F{i['fat']:.1f}")
    if i.get("food_id"):
        if i.get("servings"):
            ref = f"food {i['food_id']} × {i['servings']:g} serving{'' if i['servings'] == 1 else 's'}"
        else:
            ref = f"food {i['food_id']}, {i.get('amount') or 0:g} {i.get('unit') or ''}".rstrip()
        line += f" ({ref})"
    elif i.get("estimated"):
        line += " (estimate)"
    return line


def _log_lines(entries: list[dict], ids: bool) -> list[str]:
    lines = []
    for e in entries:
        head = f"entry {e['id']} " if ids else ""
        lines.append(f"{head}at {e['ts'][11:16]} {e.get('title') or e['slot']}: \"{e['raw']}\"")
        for i in e["items"]:
            tag = f"item {i['id']}: " if ids else "- "
            lines.append(f"  {tag}{_item_line(i)}")
    return lines


def _n(x) -> str:
    return f"{x or 0:g}"


def _food_line(f: dict) -> str:
    label = f'brand "{f.get("brand") or ""}" variant "{f.get("variant") or ""}"'
    if f.get("is_default"):
        label += " (default)"
    size = f"{f['serving_qty']:g}{f['serving_unit']}" if f.get("serving_qty") and f.get("serving_unit") else "servings only"
    line = (f"food {f['id']}: {f['name']} — {label} — {f['serving_desc']} [{size}] = {_n(f['kcal'])} kcal "
            f"P{_n(f['protein'])} C{_n(f['carbs'])} F{_n(f['fat'])}")
    if f.get("aliases"):
        line += f"; aliases: {f['aliases']}"
    if f.get("notes"):
        line += f"; notes: {f['notes']}"
    return line


def _totals_line(t: dict, g: dict) -> str:
    steps = f"{t['steps']:.0f}" if t.get("steps") is not None else "not logged"
    return (
        f"{t['kcal']:.0f}/{g['kcal']:.0f} kcal, {t['protein']:.0f}/{g['protein']:.0f} g protein, "
        f"{t['carbs']:.0f} g carbs, {t['fat']:.0f} g fat, water {t['water_ml']:.0f}/{g['water_ml']:.0f} ml, "
        f"steps {steps}/{g['steps']:.0f}, vitamin D {'taken' if t['vitd'] else 'not yet'} (before this message)"
    )


def build_prompt(
    message: str, now_str: str, today_log: list[dict], foods: list[dict], draft: list[dict], history: list[dict],
    totals: dict, goals: dict, yesterday_log: list[dict],
) -> str:
    sections = [
        ("NOW", now_str),
        ("GOALS", _goals_text(goals)),
        ("TOTALS SO FAR", _totals_line(totals, goals)),
        ("YESTERDAY'S LOG (reference only, can't be edited)", "\n".join(_log_lines(yesterday_log, ids=False)) or "(nothing)"),
        ("TODAY'S LOG", "\n".join(_log_lines(today_log, ids=True)) or "(nothing yet)"),
        ("DRAFT (pending meal, not eaten yet)", "\n".join(f"draft item {d['id']}: {_item_line(d)}" for d in draft) or "(empty)"),
        ("MY FOODS (label values per serving)", "\n".join(_food_line(f) for f in foods) or "(none saved)"),
        ("RECENT CONVERSATION", "\n".join(f"{m['role']}: {m['text']}" for m in history) or "(none)"),
        ("NEW MESSAGE", message),
    ]
    return "\n\n".join(f"{head}:\n{body}" for head, body in sections)


_LEAKED_TAGS = re.compile(r"\s*</?(?:reply|invoke|parameter|antml:[\w-]+)\b[^>]*>", re.IGNORECASE)


def clean_reply(text: str) -> str:
    """The model occasionally leaks tool-call markup (</reply></invoke>) into the reply text."""
    return _LEAKED_TAGS.sub("", text).strip()


class BrainError(Exception):
    pass


def _result_text(out: bytes) -> str:
    """The CLI reports failures (e.g. an expired login) as JSON on stdout, not stderr."""
    for line in reversed(out.decode(errors="replace").splitlines()):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("result"):
            return str(data["result"])
    return ""


class ClaudeBrain:
    def __init__(self, claude_bin: str, model: str = "sonnet", photo_model: str = "opus",
                 timeout: float = 90, photo_timeout: float = 180):
        self.claude_bin = claude_bin
        self.model = model
        self.photo_model = photo_model
        self.timeout = timeout
        self.photo_timeout = photo_timeout
        self.workdir = tempfile.mkdtemp(prefix="sarge-brain-")  # empty dir: no project CLAUDE.md

    async def interpret(self, prompt: str, system: str, images: Sequence[tuple[bytes, str]] = (),
                        schema: dict | None = None) -> dict:
        """Text (and any photos) in, structured actions out. Photos go in one message to the photo model."""
        extra = ("--system-prompt", system, "--json-schema", pronouns(json.dumps(schema or SCHEMA)))
        if images:
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}}
                for image, media_type in images
            ]
            message = {"type": "user", "message": {"role": "user", "content": [*content, {"type": "text", "text": prompt}]}}
            data = await self._run(json.dumps(message), *extra, "--input-format", "stream-json",
                                   model=self.photo_model, timeout=self.photo_timeout, stream=True)
        else:
            data = await self._run(prompt, *extra, model=self.model, timeout=self.timeout)
        result = data.get("structured_output")
        if not isinstance(result, dict):
            raise BrainError(f"no structured output: {str(data.get('result'))[:300]}")
        result["reply"] = clean_reply(result.get("reply") or "")
        return result

    async def write(self, brief: str, system: str) -> str:
        """Free-text message in Sarge's voice (the night summary)."""
        data = await self._run(pronouns(brief), "--system-prompt", system, model=self.model, timeout=self.timeout)
        text = clean_reply(data.get("result") or "")
        if not text:
            raise BrainError("empty message")
        return text

    async def _run(self, prompt: str, *extra: str, model: str, timeout: float, stream: bool = False) -> dict:
        # stream-json input (needed for images) only works with stream-json output
        output = ("--output-format", "stream-json", "--verbose") if stream else ("--output-format", "json")
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                self.claude_bin, "-p",
                *extra,
                *output,
                "--tools", "",
                "--strict-mcp-config",
                "--setting-sources", "",
                "--no-session-persistence",
                "--model", model,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workdir,
                env=os.environ.copy(),
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise BrainError("timed out")
        finally:
            log.info("brain %s %.1fs", model, time.monotonic() - started)
        if proc.returncode != 0:
            detail = " ".join(x for x in (_result_text(out), err.decode().strip()) if x)
            raise BrainError(f"exit {proc.returncode}: {detail[-300:]}")
        try:
            if stream:
                lines = [json.loads(line) for line in out.decode().splitlines() if line.strip()]
                data = next((d for d in reversed(lines) if d.get("type") == "result"), {})
            else:
                data = json.loads(out)
        except json.JSONDecodeError as e:
            raise BrainError(f"bad JSON from claude: {e}")
        if data.get("is_error"):
            raise BrainError(f"claude error: {str(data.get('result'))[:300]}")
        return data
