# Sarge v2: photo-first food tracker (design)

Agreed in chat 2026-11-20. Supersedes the reminder parts of `2026-09-22-sarge-design.md`.

## Intent

Today the real workflow is: photograph the labels and the plate, paste them into ChatGPT/Gemini/Claude
with "this is what I used and how much", get macros back, then paste that answer into Sarge so it logs it.
The log on the home server shows this: a pasted LLM answer like 'Name: 2 wraps … Calories: ~600 kcal'.

v2 cuts the middle step. Sarge itself reads the photos (nutrition labels, packs, plates, menus), does the
math, remembers every product it has seen, answers nutrition questions, and logs only when told the food
was eaten. Reminders go away; one night summary stays.

## Goals

1. **Photos in, exact macros out.** Several photos plus short captions ("1 of these", "about 1 tbsp")
   build up one meal. A label photo gives exact numbers; a plate photo gives a careful per-ingredient
   estimate.
2. **A food memory that learns.** Every label it reads is saved as a product. Later, "protein tortilla",
   "tortilla" or "Northfield" uses those numbers. Several products under one generic name (protein shakes:
   Northfield Power Up, Brightfarm, Acme) are kept apart.
3. **Python does the arithmetic for saved foods.** Claude says *which* food and *how much*; Python scales
   the stored label values. Claude only estimates macros for foods that aren't saved.
4. **Ask freely, log deliberately.** Questions ("how much protein is in this?") never log. Food is logged
   when the user says it was eaten ("ate it", "I had…", "ate half").
5. **Goals from chat.** "New goal: 1500 cal, 100g protein" updates the targets immediately and persists.
6. **One night summary,** default 22:00, time changeable from chat.
7. Full macros: calories, protein, carbs and fat.

## Non-goals

- Reminders of any kind: no morning kick-off, no "go eat" timer, no 1pm nag.
- Workout coaching, weight tracking, auto-adjusting targets.
- Online nutrition databases or barcode lookups (labels come from photos and text).
- A web UI. Telegram stays the only interface.

## Anti-goals (failure even if it "works")

- Logging something that was only asked about.
- A saved food producing different numbers on different days for the same amount.
- Photo replies so slow the user goes back to ChatGPT. An instant status message covers the wait; Opus calls over ~45 s routinely trigger the Sonnet fallback.
- Any nagging.

## Constraints

- Brain stays Claude Code headless on the Claude subscription (`claude -p --json-schema`). No API key.
- Runs on the home server as systemd user services. **Both instances** (the owner's bot and the
  second instance in `~/sarge-<name>`) run the same code and both get v2. Each keeps its own `.env`,
  database and `plan_local.py`; deploys exclude `.env`, `data/`, `.venv`, `plan_local.py`.
- The repo is public. No personal meals, foods or plan details in committed code, tests or docs.
- Existing data must survive: the logged entries and the existing saved foods on both instances.
- Commits authored solely by the owner, no co-author trailers.

## Approaches considered

1. **Claude reads, Python counts from saved labels (chosen).** Claude identifies foods and amounts;
   for saved foods it returns a reference (`food_id` + amount) and Python computes the macros. Claude
   estimates only unsaved foods. Exact and fast; costs a restructure of the foods table.
2. **Same flow, Claude does the scaling** (today's behaviour). Smallest change, but it's how 27 g vs 30 g
   and the sourdough/rye mix-up got through. Rejected: works against the reason for v2.
3. **Agent with tools over the database.** Most flexible, but several model turns per message
   (20–60 s) and numbers that are harder to validate before they reach the log. Rejected.

The user picked option 1.

## Design

### Message flow

One brain call per incoming message (text, single photo, or a Telegram album). Images and text go
through the **same** schema and prompt; the separate photo schema goes away.

```
photos/text ─► bot.py (album buffer) ─► core.handle(...) ─► brain.interpret(prompt, images)
                                              │                     │
                                              │      structured actions + reply
                                              ▼                     │
                                   validate + apply  ◄──────────────┘
                                   (Python scales saved foods)
                                              ▼
                                   render reply (all numbers from Python)
```

**Albums.** Photos sharing a `media_group_id` are buffered and sent as one call once no new photo has
arrived for ~2 s. The caption (Telegram puts it on one photo) applies to the whole album. Single photos
and photos sent one by one work too, through the draft (below).

**Models.** Calls with images use a stronger model (`CLAUDE_PHOTO_MODEL`, default `opus`); text-only
calls keep `CLAUDE_MODEL` (default `sonnet`). Timeout for image calls is raised (~180 s); text stays 90 s.
Accuracy wins over the ~30 s target (owner's decision): as soon as photos arrive, Sarge sends an instant
status message ("📸 Reading your labels…") and edits or follows it with the result. Image call durations
are logged; if Opus is routinely slower than ~45 s in real use, image calls switch to Sonnet via
`CLAUDE_PHOTO_MODEL`.

### The draft (pending meal)

A single open draft holds food that has been analysed but not eaten yet.

- Photos of labels/packs with an amount, plate photos, and descriptions of food being made or
  considered ("making a wrap with…") add items to the draft. The reply shows the draft's running total
  and says how to log it.
- "Ate it" / "log it" logs the whole draft as one entry and clears it. "Ate half" / "ate 2 of the 3"
  scale it. Corrections before logging ("it was 2 tbsp") edit draft items.
- A plain past-tense report ("I had 2 eggs and toast") logs straight away, together with anything in the
  draft it refers to. This is today's behaviour and stays.
- Pure questions don't touch the draft or the log. If a question is about a specific portion ("how much
  protein is in 200 g of this?"), the answer is given and that portion **joins** the draft (or updates
  the matching draft item, e.g. the sauce already in the wrap), so a following "ate it" logs it. Nothing
  is ever dropped from a draft silently: every draft reply lists all draft items, so the user sees what
  "ate it" will log.
- "Scrap that" / "never mind" clears the draft. A draft older than ~6 hours is dropped silently
  (builder's call on the exact window).
- The draft is stored in the database (survives restarts) and shown to the brain in every prompt.

### Food memory

Replace the flat `foods` table with structured products:

| field | meaning |
|---|---|
| `id` | integer key the brain references |
| `name` | short lookup name, e.g. `protein shake`, `protein tortilla` |
| `brand` / `variant` | e.g. `Northfield` / `Power Up 26g chocolate` |
| `aliases` | other words that should match (`tortilla`, `power up`) |
| `serving_desc` | as on the label, e.g. `1 tortilla (55 g)`, `1 bottle (414 ml)` |
| `serving_qty` + `serving_unit` | numeric size of one serving in `g` or `ml`, if known |
| `kcal`, `protein`, `carbs`, `fat` | per one serving, straight from the label |
| `is_default` | the one to use when the generic name is said with no brand |
| `notes` | free text (prep notes for things like a marinated chicken bag) |

- **Saving.** A label photo, or label values given in text, produces `save_foods` with these fields. If a
  product with the same brand+variant exists it's updated (the reply says "updated").
- **Using.** For a saved food the brain returns `{food_id, servings}` or `{food_id, amount, unit}`.
  Python converts: servings × per-serving values, or amount ÷ `serving_qty` × per-serving values (needs
  matching unit). If the brain asks for grams on a food with no `serving_qty`, Python rejects that item
  and the reply asks for the amount in servings. The brain never supplies macros for a referenced food.
- **Logged items copy the numbers.** When an item is logged (or added to the draft), Python computes its
  macros and stores them on the item, plus the `food_id` and amount for reference. Past days never
  change when a label is corrected later. A correction ("the tortilla is 140 cal") updates the product,
  then Python recomputes today's items and draft items that reference it, and the reply says how many were
  updated. Deleting a product leaves logged items untouched (their `food_id` is just no longer
  resolvable). "Same as yesterday" copies yesterday's stored numbers, as today. Editing the amount of a
  referenced item ("it was 2 tbsp") is recomputed by Python from the reference; the brain only sends
  macros when editing an estimated item.
- **Ambiguity.** If a generic name matches several products and none is default, Sarge asks which one
  (listing them) instead of guessing, and nothing for that item is added. "Northfield is my default shake"
  sets `is_default`.
- **Managing.** `/foods` lists products grouped by name. Chat can rename, fix or delete a product
  ("delete the Brightfarm one", "the tortilla is 140 cal not 150").
- **Migration.** The existing saved foods have free-text descriptions. A one-off script converts them to the
  new shape using the brain to parse each description, then prints the result for the owner to check in
  `/foods`. It runs on **both** instances (each has its own database). The new code must also start
  cleanly before the migration has run (old rows readable as per-serving foods with no `serving_qty`).
  Old rows are copied to a `foods_v1` backup table that is simply left in place; no confirm step.

### Rollout

Part of this job: run tests locally, rsync to both instance directories on the home server (usual excludes), run the food
migration on both databases, restart both units, check logs, and verify on the owner's bot with a real
label photo and an album. Deploying touches live bots, so the builder confirms with the owner right
before that step.

### Estimates for unsaved food

Plate and restaurant photos get a careful breakdown: identify each component, estimate its portion
(grams), name hidden fat (oil, butter, dressings, sauces), and say what was guessed. Restaurant portions
are assumed larger than home cooking. These items carry Claude's macros (as today) and are marked as
estimates in the reply. Menu photos keep the "best 1–3 picks for what's left today" behaviour.

### Goals

- Goals live in the database: `kcal`, `protein`, `water_ml`, `steps`, plus `summary_time`. On first run
  they're seeded from `.env` (`TARGET_*`), so existing instances keep their current targets.
- The brain emits `set_goals` when the user changes them. Python validates sane ranges and stores them
  with an effective-from day, so past days are judged against the goals that applied then (streak,
  `/week`, sheet).
- The reply confirms the new goals. `/goals` shows them.
- Everything that read the `TARGET_*` constants (prompts, render, store `day_ok`, sheet, `/week`) reads
  current goals instead. Prompts are built per call, not once at import.
- Plan text (`PLAN_TEXT` in `plan.py`/`plan_local.py`) stays as food context and rules (e.g. vegetarian),
  but the prompt states the stored goals override any numbers in the plan text.

### Night summary

- The only scheduled message. Sent once per day at `summary_time` (default 22:00), with the existing
  catch-up if the bot was down (still before the 04:00 rollover).
- Content: the day's totals for all four macros against goals, what was eaten, a short verdict in
  Sarge's voice, streak. Claude writes the prose; Python supplies every number.
- "Send my summary at 11" updates `summary_time`.

### Removed

- Morning message, meal-gap reminder, 1pm nag, and their config/state keys and tests.
- The "⏭ Next: <plan meal>" line in replies and `/today`. (Slot tagging can stay internally for titles,
  or be simplified; builder's call, as long as old entries still render.)

### Replies

- Meal logged: `✅ Logged <title>: X cal · Yg P · Zg C · Wg F`, then `Left today: …`, item lines,
  progress bars, one coach line. Saved-food items are plain; estimated items are marked (e.g. `~`).
- Draft updated: `📝 Draft <title>: X cal · Yg P · …` with item lines and `Say "ate it" to log it.`
- Question: the answer, plus numbers if it's about a specific food. No stats block unless asked.
- Food saved: `📌 Saved Northfield Power Up (1 bottle, 414 ml): 150 cal · 30g P`.
- Voice stays: blunt, short, coach-like. It just doesn't chase.

### Water, steps, vitamin D

Unchanged tracking. Water and steps targets become goals editable from chat. They appear in the night
summary.

### Sheet mirror

Unchanged mechanism. `kcal_ok` / `protein_ok` use the goals for that day.

## Decided in chat

- No reminders. One night summary around 22:00–23:00.
- Pure food tracker plus nutrition Q&A; no workout or weight coaching.
- Goals editable from chat, persisted.
- Logging only on "I ate it"-type messages; questions never log.
- Both instances get v2.
- Approach 1.
- Photos: Opus plus an instant status message; fall back to Sonnet only if Opus is routinely >45 s.

## My calls (owner can override)

- Draft/pending-meal model as described, single draft at a time.
- Sonnet for text-only calls.
- Night summary default 22:00, changeable from chat.
- Carbs and fat shown in meal summaries (today they're stored but hidden).
- Ambiguous generic names prompt a question rather than a guess.
- Goals stored with effective-from dates.
- Keep Sarge's blunt voice.

## Left to the builder

- Exact schema field names, the album wait time, the draft expiry window.
- How to restructure `brain.py` prompts (one combined prompt is expected).
- Test layout. Every Python-side calculation (scaling, goals, draft, album grouping, summary timing)
  needs unit tests with the fake brain; existing tests for removed reminders are deleted.
- README update: remove the reminders section, describe photos/labels/draft/goals.
