"""Claude as the interpreter: free text in, structured actions out. No arithmetic on totals."""

import asyncio
import json
import os
import tempfile

from .config import TARGET_KCAL, TARGET_PROTEIN, TARGET_STEPS, TARGET_WATER_ML, USER_NAME
from .plan import PLAN_TEXT, SLOTS

MACROS = {
    "kcal": {"type": "number"},
    "protein": {"type": "number"},
    "carbs": {"type": "number"},
    "fat": {"type": "number"},
}

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "Food/drink just eaten, one line per component. Empty if nothing new was eaten.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short plain-English name, max ~18 chars, include quantity, e.g. '2 eggs', 'Rice 150g', 'Olive oil 5g'"},
                    "emoji": {"type": "string", "description": "One food emoji for this item, e.g. 🍳 🌯 🥔 🫒 🌶 🍗 🍚 🥦 🐟 🍓 🥤"},
                    "grams": {"type": "number", "description": "Weight in g (or ml for liquids); 0 if unknown"},
                    **MACROS,
                },
                "required": ["name", "emoji", "grams", "kcal", "protein", "carbs", "fat"],
            },
        },
        "title": {"type": "string", "description": "2-3 word name for what was just eaten, e.g. 'breakfast burrito', 'chicken rice bowl'. Empty if nothing eaten."},
        "is_meal": {
            "type": "boolean",
            "description": "True if the new items are a real meal/snack that should reset the meal timer. "
            "False for zero-cal drinks, a few bites, condiments, supplements.",
        },
        "slot": {"type": "string", "enum": [*SLOTS, "extra"]},
        "slot_edits": {
            "type": "array",
            "description": "Re-tag an entry already in TODAY'S LOG, e.g. he says 'that was my breakfast'",
            "items": {
                "type": "object",
                "properties": {"entry_id": {"type": "integer"}, "slot": {"type": "string", "enum": [*SLOTS, "extra"]}},
                "required": ["entry_id", "slot"],
            },
        },
        "delete_entry_ids": {"type": "array", "items": {"type": "integer"}},
        "delete_item_ids": {"type": "array", "items": {"type": "integer"}},
        "item_edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "grams": {"type": "number"},
                    **MACROS,
                },
                "required": ["item_id", "name", "grams", "kcal", "protein", "carbs", "fat"],
            },
        },
        "water_ml": {"type": "number", "description": "Water drunk just now in ml, 0 if none mentioned"},
        "steps": {"type": "integer", "description": "Today's step count if reported, else 0"},
        "vitamin_d": {"type": "boolean", "description": "True if he says he took vitamin D"},
        "save_foods": {
            "type": "array",
            "description": "Exact label values he explicitly gives for a food he eats regularly",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "short lookup name, e.g. 'greek yogurt'"},
                    "description": {"type": "string", "description": "brand + serving, e.g. 'Chobani 0%, 1 cup (170g)'"},
                    **MACROS,
                },
                "required": ["name", "description", "kcal", "protein", "carbs", "fat"],
            },
        },
        "show_status": {
            "type": "boolean",
            "description": "True ONLY if he asks about progress, what's left, totals, or what to eat next. False for banter, 'cool', 'ok', thanks, etc.",
        },
        "reply": {"type": "string"},
    },
    "required": [
        "items", "title", "is_meal", "slot", "slot_edits", "delete_entry_ids", "delete_item_ids", "item_edits",
        "water_ml", "steps", "vitamin_d", "save_foods", "show_status", "reply",
    ],
}

SLOT_LINES = "\n".join(f"- {k}: {s['plan']}" for k, s in SLOTS.items())

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
  "can I have a cookie" -> "Can you? Sure. Should you? You've got 300 cal left and 60g protein to find. You tell me."
"""

SYSTEM_PROMPT = f"""You are Sarge, {USER_NAME}'s personal trainer on Telegram. You text like a real human coach:
a hard-ass drill sergeant who genuinely wants him to win, but has zero patience for excuses.
You interpret his messages into structured log actions AND text him back.

{VOICE}
His trainer's plan:
{PLAN_TEXT}
Daily targets: {TARGET_KCAL} kcal, {TARGET_PROTEIN} g protein.

Plan slots:
{SLOT_LINES}
Tag new food with the plan slot it stands in for. A meal fills a slot when it replaces that meal:
he calls it that meal ("breakfast", "lunch"), it has that slot's core food (eggs, chicken, whey...),
or it's the obvious meal for the time of day. A different dish is still that slot (a breakfast
burrito IS breakfast). Use "extra" only when that slot is already filled today, or for small bites,
drinks and add-ons. If he says an entry was a different meal, fix it with slot_edits.

Rules:
- Estimate macros realistically for what he describes. Split composite dishes into components
  (eggs, oil/butter, tortilla, sauce...). Cooking fat counts. If a size is vague, assume a typical
  portion and say what you assumed in the reply.
- If a food matches one in MY FOODS, use those exact values (scaled to the quantity).
- Log only what he says he ate. Never add items he didn't mention (no assumed oil, butter or sauce).
  If cooking fat is plausibly missing, ask about it in the reply instead.
- "Same as yesterday" / "the usual": copy the matching items from YESTERDAY'S LOG exactly (same
  quantities and macros), then apply his changes ("minus the sauce", "4 eggs this time").
- If he gives exact label values for a food, log it with them and add it to save_foods.
- Corrections ("that rice was 200g", "remove the sauce", "delete that") go in item_edits /
  delete_item_ids / delete_entry_ids using ids from TODAY'S LOG. Never re-add items that are already logged.
- A question or chat with nothing eaten means empty items.
- What matters: daily calories at or under the target, and protein at or over the target. Carbs and
  fat just fill the remaining calories. Swaps, additions and meal modifications are FINE as long as
  the day still fits. The plan as written is only ~1300-1400 kcal, so there's ~400 kcal of slack.
  Judge against the day's budget (see TOTALS SO FAR), never against exact plan adherence.
  Only push back when calories are heading over, protein is falling behind for the time of day,
  or oil/fat is clearly excessive.
- NEVER state daily totals or what's remaining; the system shows exact numbers after your reply.
- reply: usually 1-2 short sentences in the VOICE above. If you assumed a portion size, say so in
  his language ("assumed a normal scoop"). Real questions can get 2-4 sentences. You may reference
  numbers from TOTALS SO FAR when it makes the point land, but don't recite a status report."""


def _log_lines(entries: list[dict], ids: bool) -> list[str]:
    lines = []
    for e in entries:
        head = f"entry {e['id']} " if ids else ""
        title = f" {e['title']}" if e.get("title") else ""
        lines.append(f"{head}at {e['ts'][11:16]} [{e['slot']}{', meal' if e['is_meal'] else ''}]{title}: \"{e['raw']}\"")
        for i in e["items"]:
            tag = f"item {i['id']}: " if ids else "- "
            grams = f"{i['grams']:g}" if i["grams"] else "?"
            lines.append(
                f"  {tag}{i['name']} {grams}g — {i['kcal']:.0f} kcal, "
                f"P{i['protein']:.1f} C{i['carbs']:.1f} F{i['fat']:.1f}"
            )
    return lines


def build_prompt(
    message: str, now_str: str, today_log: list[dict], foods: list[dict], history: list[dict],
    totals: dict | None = None, yesterday_log: list[dict] | None = None,
) -> str:
    log_lines = _log_lines(today_log, ids=True)
    y_lines = _log_lines(yesterday_log or [], ids=False)
    food_lines = [
        f"- {f['name']}: {f['description']} = {f['kcal']:.0f} kcal, P{f['protein']:.0f} C{f['carbs']:.0f} F{f['fat']:.0f}"
        for f in foods
    ]
    hist_lines = [f"{m['role']}: {m['text']}" for m in history]
    totals_line = (
        f"{totals['kcal']:.0f}/{TARGET_KCAL} kcal, {totals['protein']:.0f}/{TARGET_PROTEIN} g protein (before this message)"
        if totals else "(unknown)"
    )
    return (
        f"NOW: {now_str}\n\n"
        f"TOTALS SO FAR: {totals_line}\n\n"
        f"YESTERDAY'S LOG (reference only, can't be edited):\n{chr(10).join(y_lines) or '(nothing)'}\n\n"
        f"TODAY'S LOG:\n{chr(10).join(log_lines) or '(nothing yet)'}\n\n"
        f"MY FOODS:\n{chr(10).join(food_lines) or '(none saved)'}\n\n"
        f"RECENT CONVERSATION:\n{chr(10).join(hist_lines) or '(none)'}\n\n"
        f"NEW MESSAGE:\n{message}"
    )


WRITER_PROMPT = f"""You are Sarge, {USER_NAME}'s personal trainer, texting him on Telegram unprompted.
{VOICE}

His trainer's plan: {TARGET_KCAL} kcal and {TARGET_PROTEIN} g protein a day, {TARGET_WATER_ML / 1000:g}+ L water,
{TARGET_STEPS:,}+ steps, vitamin D with dinner. Meal order and timing don't matter; swaps are fine if the day fits.

You'll get a brief with facts. Write ONLY the message text, in the voice. Plain text: no emojis, no
markdown, no headings, no lists. The system adds exact numbers underneath, so don't recite a scoreboard;
use a number only when it makes the point land. Use the facts, be specific, never invent food he didn't log.
Length: morning 2-3 sentences, meal nudge 1-2, nag 1-2, night review 3-5."""


class BrainError(Exception):
    pass


class ClaudeBrain:
    def __init__(self, claude_bin: str, model: str = "sonnet", timeout: float = 90):
        self.claude_bin = claude_bin
        self.model = model
        self.timeout = timeout
        self.workdir = tempfile.mkdtemp(prefix="sarge-brain-")  # empty dir: no project CLAUDE.md

    async def interpret(self, prompt: str) -> dict:
        data = await self._run(prompt, "--system-prompt", SYSTEM_PROMPT, "--json-schema", json.dumps(SCHEMA))
        result = data.get("structured_output")
        if not isinstance(result, dict):
            raise BrainError(f"no structured output: {str(data.get('result'))[:300]}")
        return result

    async def write(self, brief: str) -> str:
        """Free-text message in Sarge's voice for a scheduled reminder."""
        data = await self._run(brief, "--system-prompt", WRITER_PROMPT)
        text = (data.get("result") or "").strip()
        if not text:
            raise BrainError("empty message")
        return text

    async def _run(self, prompt: str, *extra: str) -> dict:
        proc = await asyncio.create_subprocess_exec(
            self.claude_bin, "-p",
            *extra,
            "--output-format", "json",
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--no-session-persistence",
            "--model", self.model,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir,
            env=os.environ.copy(),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(prompt.encode()), self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise BrainError("timed out")
        if proc.returncode != 0:
            raise BrainError(f"exit {proc.returncode}: {err.decode()[-300:]}")
        try:
            data = json.loads(out)
        except json.JSONDecodeError as e:
            raise BrainError(f"bad JSON from claude: {e}")
        if data.get("is_error"):
            raise BrainError(f"claude error: {str(data.get('result'))[:300]}")
        return data
