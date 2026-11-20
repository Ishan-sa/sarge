# Sarge v2 Photo-First Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Sarge from a reminder bot into a photo-first food tracker. It reads labels and plates (albums too), remembers products as structured label records, builds a draft meal that logs only on "ate it", takes goal changes from chat, and sends one night summary.

**Architecture:** There is one brain call per message or album, through one JSON schema. Claude names foods and amounts. For saved foods it returns a `food_id` plus an amount, and Python scales the stored label values (`sarge/foods.py`). Python validates and applies every action. The goals, draft and food records all live in SQLite. The night summary is the only scheduled job, and `sarge/summary.py` replaces `reminders.py`.

**Tech Stack:** Python 3.12, python-telegram-bot 22 (polling and JobQueue), SQLite, and Claude Code headless (`claude -p --json-schema`) on the subscription. Text calls run on Sonnet and image calls on Opus. Tests use pytest with a fake brain.

**Spec:** `docs/superpowers/specs/2026-11-20-sarge-tracker-redesign-design.md`

## Global Constraints

- Brain = Claude Code headless on the subscription. No API key, no new paid services.
- The repo is public: no personal foods, meals or plans in code, tests, docs or commit messages. Test data stays generic.
- Every commit is authored by the owner alone. **No `Co-Authored-By` or session trailers.**
- Nothing is pushed to GitHub unless the owner asks.
- Existing databases must keep working on first start of the new code: old `foods` rows, old entries with slots and no titles.
- Every number the user sees is computed in Python (`render.py`), never by Claude.
- `.env` defaults: `TARGET_KCAL=1800`, `TARGET_PROTEIN=130`, `TARGET_WATER_ML=3000`, `TARGET_STEPS=8000`. New: `CLAUDE_PHOTO_MODEL=opus`.
- A day rolls over at 04:00 local time (`DAY_ROLLOVER_HOUR`, unchanged).
- Both instances on the home server (`~/sarge`, the second instance in `~/sarge-<name>`) run this same code.

## Review Focus

1. **The brain references a food that can't be scaled.** This covers an unknown `food_id`, grams asked for a food with no `serving_qty`, and `ml` asked for a `g` food. Expected: that item is skipped, the reply names it and asks for the amount in servings, and the rest of the message still applies. Test in Task 6.
2. **"Ate it" with no draft.** Expected: nothing is logged, and the reply says there's nothing pending. Test in Task 6.
3. **Album quirks.** The caption may sit on the 2nd or 3rd photo, two albums may be sent back to back, or a single photo may arrive while an album is buffering. Expected: grouping is by `media_group_id`, the caption is taken from whichever photo has one, and each group gets one reply. Test in Task 9.
4. **Partial or absurd goal changes.** Examples: "protein 1000g", or only protein given. Expected: valid fields change, other fields stay as they were, and invalid values are named in the reply. Test in Task 1.
5. **A summary time after midnight, or the bot down at summary time.** An example is `00:30`. Expected: the summary fires once for the right day (before the 04:00 rollover) and never twice. Test in Task 8.

## File map

| File | Responsibility |
|---|---|
| `sarge/goals.py` (new) | goal defaults, validation, formatting |
| `sarge/foods.py` (new) | pure label scaling (`scale`, `ScaleError`) |
| `sarge/store.py` | adds goals history, structured foods, the draft, and new item columns, plus migrations |
| `sarge/brain.py` | one schema, prompts built per call from goals, multi-image calls, model per call |
| `sarge/core.py` | `handle()` and `apply()`: validate and apply brain actions, build the reply |
| `sarge/render.py` | all user-visible HTML; takes a goals dict and shows 4 macros, with no "Next" line |
| `sarge/summary.py` (new; replaces `reminders.py`) | night summary due logic and content |
| `sarge/bot.py` | album buffer, status message, `/goals`, summary tick |
| `sarge/migrate_foods.py` (new) | one-off brain-assisted enrichment of old foods |
| `sarge/sheets.py` | per-day goals in snapshot |
| `sarge/config.py` | drops reminder constants, adds `CLAUDE_PHOTO_MODEL` default, `DRAFT_TTL_HOURS = 6` |
| `tests/conftest.py` | env defaults, shared `store` fixture, `FakeBrain`, `at()` |
| `tests/test_*.py` | one file per module below |

---

### Task 0: Local test environment

- [ ] **Step 1:** `cd ~/Projects/sarge && python3.12 -m venv .venv || python3 -m venv .venv`, then `.venv/bin/pip install -r requirements.txt pytest`.
- [ ] **Step 2:** `.venv/bin/python -m pytest -q`. Expected: all current tests pass. If the local Python can't install the deps, run the suite on the home server instead: rsync to a scratch dir `~/sarge-dev` and run `~/sarge/.venv/bin/python -m pytest -q` there. Use that same route for every later "run tests" step.
- [ ] **Step 3:** Move `FakeBrain`, `at()`, `EGGS` and the `store` fixture from `tests/test_sarge.py` into `tests/conftest.py`. Add the shared generic test foods there as well:
  - `TORTILLA`: as in Task 3.
  - `SHAKE`: `{"name": "protein shake", "brand": "", "variant": "", "serving_desc": "1 bottle (414 ml)", "serving_qty": 414, "serving_unit": "ml", "kcal": 150, "protein": 30, "carbs": 6, "fat": 3}`.

  Then, in the same step, Make `FakeBrain.interpret(prompt, system, images=())` record `prompts`, `systems` and `images`, and return the queued results in order: the constructor takes `*results`, and the last one repeats. Tests still pass. Commit `tests: shared fixtures`.

### Task 1: Goals

**Files:** Create `sarge/goals.py`. Modify `sarge/store.py`. Test `tests/test_goals.py`.

**Interfaces (produces):**
- `goals.FIELDS = ("kcal", "protein", "water_ml", "steps")`
- `goals.RANGES = {"kcal": (800, 6000), "protein": (20, 400), "water_ml": (500, 8000), "steps": (0, 60000)}`
- `goals.default_goals() -> dict`: the four `TARGET_*` values from config plus `"summary_time": "22:00"`.
- `goals.validate(changes: dict) -> tuple[dict, list[str]]` ignores `0`, `None` and `""`. Out-of-range values become errors such as `"protein 1000g is outside 20–400"`. `summary_time` must be `HH:MM` and must fall from 17:00 through 23:59 or from 00:00 through 03:59.
- `goals.describe(g: dict) -> str` returns `"1,500 cal · 100g protein · 3L water · 8k steps"`.
- `Store.goals(day: date) -> dict` returns the latest `goals` row with `effective_day <= day`, falling back to `default_goals()`. `summary_time` comes from state key `summary_time`, else `"22:00"`.
- `Store.set_goals(day: date, changes: dict) -> dict` merges the changes into `goals(day)`, upserts the row for `day`, and stores `summary_time` in state. It returns the new goals.
- New table: `goals (effective_day TEXT PRIMARY KEY, kcal REAL, protein REAL, water_ml REAL, steps REAL)`

- [ ] **Step 1: Failing tests**

```python
def test_defaults_until_set(store):
    assert store.goals(date(2026, 11, 20)) == {"kcal": 1800, "protein": 130, "water_ml": 3000, "steps": 8000, "summary_time": "22:00"}

def test_set_goals_applies_from_that_day_only(store):
    store.set_goals(date(2026, 11, 20), {"kcal": 1500, "protein": 100})
    assert store.goals(date(2026, 11, 19))["kcal"] == 1800
    g = store.goals(date(2026, 11, 25))
    assert (g["kcal"], g["protein"], g["water_ml"]) == (1500, 100, 3000)

def test_validate_partial_and_absurd():
    clean, errors = validate({"kcal": 0, "protein": 1000, "steps": 9000, "summary_time": "11:00"})
    assert clean == {"steps": 9000}
    assert len(errors) == 2 and "protein" in errors[0] and "summary" in errors[1]
    assert validate({"summary_time": "00:30"}) == ({"summary_time": "00:30"}, [])

def test_describe():
    assert describe({"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000}) == "1,500 cal · 100g protein · 3L water · 8k steps"
```

- [ ] **Step 2:** Run `pytest tests/test_goals.py -v`. Expected: FAIL (import error).
- [ ] **Step 3:** Implement the interfaces above. Add the `goals` table to `SCHEMA`.
- [ ] **Step 4:** Run `pytest -q`. Expected: all pass.
- [ ] **Step 5:** Commit `Goals stored per day, editable`.

### Task 2: Render and everything else read goals; 4 macros; no "Next"

**Files:** Modify `sarge/render.py`, `sarge/store.py` (`day_ok`), `sarge/sheets.py`, `sarge/bot.py` (`week`). Test `tests/test_render.py`, plus updated `tests/test_sarge.py`.

**Interfaces (produces).** Every function takes the goals dict `g` explicitly:
- `left_line(t, g)`, `bars(t, g)`, `extras_line(t, g)`
- `macro_line(x: dict) -> str` gives `"569 cal · 58g P · 40g C · 12g F"`, rounded with `fmt`.
- `item_line(i) -> str` gives `"🍗 Grilled chicken 150g · 248 cal · 💪46g"`. The name is prefixed with `~` when `i.get("estimated")` is truthy.
- `meal_reply(title, items, t, g, comment) -> str`. Its first line is `✅ <b>Logged {title}: {macro_line(sum)}</b>` and its second is `left_line`. Then come the item lines, `bars`, and `🗣 comment`. There is no "Next" line.
- `day_view(entries, t, g)`. An entry title falls back to `e["slot"].capitalize()` when it has no title.
- `other_reply(changes, t, g, comment, show_status)`
- `Store.day_ok(day)` uses `self.goals(day)`. `sheets.snapshot` uses `store.goals(day)` for `kcal_ok` and `protein_ok`. `/week` judges each day with `store.day_ok(d)`.
- Remove `SLOT_NEXT`, `next_line`, `missing_slots`, `meal_reminder`, `nag` and `wrap_up` from render. `SLOT_LABELS` and the `plan.SLOTS` import go too.

- [ ] **Step 1:** Update the failing tests.

```python
def test_meal_reply_summary_first(store):  # rewrite of the existing test
    ...
    assert lines[0] == "✅ <b>Logged scrambled eggs: 251 cal · 19g P · 1g C · 19g F</b>"
    assert lines[1] == "Left today: 1,549 cal · 111g protein"
    assert "⏭" not in out

def test_render_uses_given_goals():
    g = {"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000}
    t = {"kcal": 500, "protein": 40, "carbs": 0, "fat": 0, "water_ml": 0, "steps": None, "vitd": False}
    assert left_line(t, g) == "Left today: 1,000 cal · 60g protein"
    assert "500 / 1,500 cal" in bars(t, g)

def test_estimated_item_marked():
    assert item_line({"name": "Fries", "emoji": "🍟", "kcal": 300, "protein": 4, "estimated": 1}).startswith("🍟 ~Fries")
```

`test_status_only_when_asked` must no longer expect `"⏭ Next:"`.

- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. `core.handle_text` and `handle_photo` pass `store.goals(day)` through for now. They are replaced in Task 6.
- [ ] **Step 4:** `pytest -q`. Expected: all pass. The reminder tests still pass at this point; they're deleted in Task 8. Point their imports at the new signatures as needed, passing `store.goals(day)`.
- [ ] **Step 5:** Commit `Replies show all four macros and use stored goals`.

### Task 3: Structured food memory

**Files:** Create `sarge/foods.py`. Modify `sarge/store.py`. Test `tests/test_foods.py`.

**Interfaces (produces):**
- New `foods` table: `id INTEGER PRIMARY KEY, name TEXT NOT NULL, brand TEXT, variant TEXT, aliases TEXT, serving_desc TEXT NOT NULL, serving_qty REAL, serving_unit TEXT, kcal REAL, protein REAL, carbs REAL, fat REAL, is_default INTEGER DEFAULT 0, notes TEXT`. `name`, `brand` and `variant` are stored lowercase-trimmed for matching, and `serving_unit` is `"g"`, `"ml"` or NULL.
- Migration in `Store._migrate`: if `foods` has no `id` column, `ALTER TABLE foods RENAME TO foods_v1`, then create the new table and copy each old row as `name`, `serving_desc=description`, and the macros. `serving_qty`, `brand` and `variant` are left NULL. `foods_v1` stays in place.
- Items table gets new columns: `food_id INTEGER, servings REAL, amount REAL, unit TEXT, estimated INTEGER DEFAULT 0`. `log_entry` and `edit_item` accept and store them.
- `Store.save_food(f: dict) -> tuple[int, bool]` upserts on (name, brand, variant) and returns (id, updated). If `f["make_default"]` is set, it clears `is_default` on other rows with the same name.
- `Store.foods() -> list[dict]` orders by name, then brand. `Store.food(id) -> dict | None`.
- `Store.edit_food(id, fields: dict) -> bool` accepts only the table columns. `Store.delete_food(id) -> bool`. `Store.set_default_food(id) -> bool`.
- `foods.ScaleError(Exception)`
- `foods.scale(food: dict, servings: float = 0, amount: float = 0, unit: str = "") -> dict` returns `{"grams", "kcal", "protein", "carbs", "fat"}`:
  - `servings > 0`: the per-serving values times `servings`. `grams` is `servings * serving_qty`, or 0 if `serving_qty` is unknown.
  - otherwise, when `amount > 0`, `unit` equals `serving_unit` and `serving_qty` is set: the factor is `amount / serving_qty`, and `grams = amount`.
  - otherwise, `ScaleError(f"need {food['name']} in servings ({food['serving_desc']})")`.

- [ ] **Step 1: Failing tests**

```python
TORTILLA = {"name": "protein tortilla", "brand": "acme", "variant": "", "serving_desc": "1 tortilla (55 g)",
            "serving_qty": 55, "serving_unit": "g", "kcal": 150, "protein": 13, "carbs": 18, "fat": 4}

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
    # build the v1 foods table (name PK, description, macros) with one row, open Store, expect:
    # foods()[0]["serving_desc"] == old description, foods_v1 still has the row
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement. `scale` multiplies first and rounds to 1 decimal.
- [ ] **Step 4:** `pytest -q`. Expected: all pass. Note that `brain.build_prompt` still reads `f["description"]`: switch it to `serving_desc` in this task so the suite stays green.
- [ ] **Step 5:** Commit `Foods become structured label records`.

### Task 4: The draft

**Files:** Modify `sarge/store.py` and `sarge/config.py` (`DRAFT_TTL_HOURS = 6`). Test `tests/test_draft.py`.

**Interfaces (produces):**
- Table `draft_items`, with the same columns as `items` minus `entry_id`, plus `ts TEXT`. State keys `draft_title` and `draft_ts`.
- `Store.draft(now: datetime) -> list[dict]`. If `draft_ts` is older than `DRAFT_TTL_HOURS`, it clears the draft and returns `[]`.
- `Store.draft_title() -> str`
- `Store.draft_add(ts, items: list[dict], title: str | None) -> None` sets `draft_ts=ts`, and sets the title only if the draft was empty or a title is given.
- `Store.draft_edit(item_id, fields) -> bool`, `Store.draft_remove(item_id) -> bool`, `Store.draft_clear() -> None`
- `Store.draft_item(item_id) -> dict | None`

- [ ] **Step 1: Failing tests**

```python
def test_draft_accumulates_and_expires(store):
    store.draft_add(at(12), [EGGS[0]], "wrap")
    store.draft_add(at(12, 5), [EGGS[1]], None)
    assert [i["name"] for i in store.draft(at(12, 6))] == ["eggs", "butter"] and store.draft_title() == "wrap"
    assert store.draft(at(18, 6)) == [] and store.draft(at(12, 7)) == []

def test_draft_survives_restart(tmp_path):
    s = Store(tmp_path / "d.db"); s.draft_add(at(12), [EGGS[0]], "wrap")
    assert len(Store(tmp_path / "d.db").draft(at(12, 1))) == 1
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** `pytest -q` passes. **Step 5:** Commit `Draft meal storage`.

### Task 5: Brain: one schema, per-call prompts, multi-image, model per call

**Files:** Modify `sarge/brain.py` and `sarge/config.py`. Test `tests/test_brain.py`.

**Interfaces (produces):**
- `ITEM` schema properties, all required: `name, emoji, grams, food_id` (0 = not saved), `new_food_index` (-1 = none; otherwise an index into this response's `save_foods`), `servings, amount, unit` (`"g" | "ml" | ""`), `kcal, protein, carbs, fat` (estimates; ignored when a food is referenced).
- `SCHEMA` top-level properties, all required:
  - `items` and `items_to` (`"log" | "draft" | "none"`). Use `"log"` when the user says they ate it now, `"draft"` when they're building or asking about a specific portion, and `"none"` for menu analysis.
  - `title`
  - `eat_draft`: a number from 0 to 1; 0 = don't log the draft, 1 = all, 0.5 = half.
  - `clear_draft`
  - `draft_edits` and `item_edits`, both as `[{id, servings, amount, unit, name, grams, kcal, protein, carbs, fat}]`
  - `draft_remove_ids, delete_item_ids, delete_entry_ids`
  - `save_foods` (`[{name, brand, variant, aliases, serving_desc, serving_qty, serving_unit, kcal, protein, carbs, fat, notes, make_default}]`), `food_edits` (`[{id, ...same fields}]`), `delete_food_ids`, `default_food_id` (0 = none)
  - `set_goals` (`{kcal, protein, water_ml, steps, summary_time}`, with 0 or "" meaning unchanged)
  - `picks` (today's menu-pick object)
  - `water_ml, steps, vitamin_d, show_status, reply`
- `system_prompt(goals: dict) -> str` replaces `SYSTEM_PROMPT` and `PHOTO_PROMPT`. Keep `VOICE` and the plan text. Rules to state:
  - Goals override any numbers in the plan text.
  - Questions never log.
  - "I had / ate / log it" means log.
  - Making, considering, or "how much in N g of this" means draft.
  - "Ate it" uses `eat_draft`.
  - A label photo means `save_foods` with exact label values. If the caption gives an amount, also add an item with `new_food_index`.
  - A saved food means `food_id` plus servings or amount, never its macros.
  - A generic name matching several foods with no default means ask which one in the reply, and add nothing for it.
  - Plate photos: identify every component, estimate grams, call out hidden fat, and assume restaurant portions are larger.
  - Menu photos: picks, as today.
  - Never state totals.
- Both prompt builders return text already passed through `config.pronouns()`, and so does the schema JSON. The second instance relies on this (`SARGE_PRONOUNS=she`).
- `writer_prompt(goals: dict) -> str` replaces `WRITER_PROMPT` and is used for the night summary only.
- `build_prompt(message, now_str, today_log, foods, draft, history, totals, goals, yesterday_log) -> str` has the sections `NOW, GOALS, TOTALS SO FAR, YESTERDAY'S LOG, TODAY'S LOG, DRAFT, MY FOODS, RECENT CONVERSATION, NEW MESSAGE`. Draft lines read `draft item {id}: ...`. Food lines read `food {id}: {name} — {brand} {variant}{' (default)' if is_default} — {serving_desc} [{serving_qty}{serving_unit}] = {kcal} kcal P C F; aliases: …; notes: …`.
- `ClaudeBrain(claude_bin, model="sonnet", photo_model="opus", timeout=90, photo_timeout=180)`
- `ClaudeBrain.interpret(prompt: str, system: str, images: Sequence[tuple[bytes, str]] = ()) -> dict`. With images, it sends a stream-json user message with one image block per image and then the text, using `photo_model` and `photo_timeout`. Without images, it uses the plain JSON path with `model`. It logs `"brain %s %.1fs"` with the model and duration. `look()` is removed.
- `ClaudeBrain.write(brief: str, system: str) -> str`
- `config.CLAUDE_PHOTO_MODEL` is read in `bot.main` via `env("CLAUDE_PHOTO_MODEL", "opus")`.

- [ ] **Step 1: Failing tests.** Monkeypatch `ClaudeBrain._run` to capture its arguments and return `{"structured_output": {...}}`.

```python
def test_images_go_to_photo_model_in_one_message(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("p", "sys", [(b"a", "image/jpeg"), (b"b", "image/png")]))
    args, stream = calls[0]
    msg = json.loads(args[0])
    assert [c["type"] for c in msg["message"]["content"]] == ["image", "image", "text"]
    assert "opus" in args and stream

def test_text_uses_text_model(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("p", "sys"))
    assert "sonnet" in calls[0][0] and not calls[0][1]

def test_prompt_lists_foods_with_ids_and_draft(store):
    fid, _ = store.save_food(TORTILLA)
    store.draft_add(at(12), [EGGS[0]], "wrap")
    p = build_prompt("x", "now", [], store.foods(), store.draft(at(12)), [], store.totals(day_of(at(12))), store.goals(day_of(at(12))), [])
    assert f"food {fid}: protein tortilla — acme" in p and "1 tortilla (55 g) [55g]" in p
    assert "DRAFT" in p and "draft item" in p and "GOALS" in p

def test_system_prompt_states_goals():
    assert "1500 kcal" in system_prompt({"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000, "summary_time": "22:00"})
```

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. Keep `clean_reply` and `_run`, adding a timeout parameter to `_run`. **Step 4:** `pytest tests/test_brain.py -q` passes. (`core` breaks until Task 6. If you run the full suite before Task 6, keep the old `handle_*` working temporarily.) **Step 5:** Commit `One brain schema for text and photos, Opus for images`.

### Task 6: Core: apply actions and build replies

**Files:** Rewrite `sarge/core.py` and modify `sarge/render.py`. Test `tests/test_core.py` (replacing the `handle_text`/`handle_photo` tests in `test_sarge.py`).

**Interfaces:**
- Consumes `Store.*` from Tasks 1, 3 and 4, `scale` from Task 3, and `system_prompt`/`build_prompt` from Task 5.
- Produces `async handle(store, brain, text: str, images: list[tuple[bytes, str]], ts: datetime) -> str`. It replaces `handle_text` and `handle_photo`.
- Produces `apply(store, result: dict, raw: str, ts: datetime) -> Outcome`, with `@dataclass Outcome: logged: list[dict]; title: str; draft_touched: bool; lines: list[str]; problems: list[str]`.
- New render functions:
  - `draft_reply(title, items, comment) -> str`. Its first line is `📝 <b>Draft {title}: {macro_line}</b>`, followed by the item lines and then `Say "ate it" to log it, or correct me first.`
  - `picks_block(picks, t, g)`, which carries over the existing menu layout.
  - `food_saved_line(f, updated)` gives `📌 Saved {Brand} {name} ({serving_desc}): {kcal} cal · {protein}g P`, with "Updated" in place of "Saved" when updated.
  - `goals_line(g)` gives `🎯 New goals: {goals.describe(g)}`.

**`apply` order** (each step validated; every failure appends to `problems` and never raises):
1. `save_foods`: call `store.save_food` on each and keep `new_ids[index]`. Then apply `food_edits`, `delete_food_ids` and `default_food_id`.
2. Resolve each item in `items` to stored form:
   - `new_food_index >= 0` maps to `new_ids[i]`.
   - `food_id > 0` means `scale(store.food(id), servings, amount, unit)`, with name and emoji kept from the brain and `estimated=0`.
   - Otherwise use the brain's macros with `estimated=1`.
   - An unknown id or a `ScaleError` drops the item and adds its message to `problems`.
3. Correcting a saved food (`food_edits`) recomputes today's `items` and the `draft_items` that reference it. The count goes in `lines` (`"✏️ Updated 2 logged items"`).
4. `clear_draft` runs first. Then `draft_edits` and `draft_remove_ids` are applied, and any referenced draft item is re-scaled from its food.
5. `eat_draft > 0`: the draft items, each macro and grams × `eat_draft`, are combined with the resolved items whenever `items_to == "log"`. They are logged as one entry with the title `draft_title()` or `title`, and then the draft is cleared. `eat_draft > 0` with an empty draft adds `"Nothing in the draft to log."` to `problems`.
6. Otherwise, `items_to == "log"` logs the resolved items, and `items_to == "draft"` calls `draft_add`.
7. Existing edits and deletes on today's log, keeping the "today only" checks. `item_edits` on an item with a `food_id` re-scales.
8. `set_goals` goes through `goals.validate`, then `store.set_goals(day, clean)`, and adds `goals_line` to `lines`. Validation errors go to `problems`.
9. Water, steps and vitamin D, as today.

**`handle` reply:**
- `logged` non-empty: `meal_reply`
- else `draft_touched` with a non-empty draft: `draft_reply`
- else `picks`: `picks_block`
- else `other_reply`

Append `lines` and then `problems`, with each problem prefixed `⚠️ `. Store history as today, with `"[photo xN] caption"` for images. The sarge-side history line includes exact draft numbers, so later turns can refer back.

- [ ] **Step 1: Failing tests.** FakeBrain returns queued results. Three helpers live in `tests/test_core.py`:
  - `res(**kw)` fills defaults for every SCHEMA key: empty lists, `items_to="none"`, `eat_draft=0`, `default_food_id=0`, and `set_goals` all zeros or "".
  - `item(name, **kw)` fills `ITEM` defaults: `food_id=0`, `new_food_index=-1`, and zeros elsewhere.
  - `goals_payload(**kw)` gives `set_goals` zeros or "" except the given fields.

```python
def test_label_photo_saves_and_drafts_with_python_math(store):
    label = {**TORTILLA, "aliases": "tortilla", "notes": "", "make_default": False}
    brain = FakeBrain(res(save_foods=[label], items=[item("protein tortilla", new_food_index=0, servings=1, kcal=999)], items_to="draft", title="wrap"))
    out = asyncio.run(handle(store, brain, "1 of these", [(b"img", "image/jpeg")], at(12)))
    assert out.startswith("📝 <b>Draft wrap: 150 cal · 13g P · 18g C · 4g F</b>")
    assert "📌 Saved" in out and store.day_entries(day_of(at(12))) == []
    assert brain.images[0] == [(b"img", "image/jpeg")]

def test_question_logs_nothing(store):
    asyncio.run(handle(store, FakeBrain(res(reply="About 30g.")), "how much protein in power up?", [], at(12)))
    assert store.day_entries(day_of(at(12))) == [] and store.draft(at(12)) == []

def test_ate_it_logs_whole_draft_and_half(store):
    # draft 2 items -> eat_draft=1 -> one entry with both, draft empty
    # second scenario: eat_draft=0.5 halves kcal/protein/grams

def test_ate_it_with_empty_draft(store):
    out = asyncio.run(handle(store, FakeBrain(res(eat_draft=1)), "ate it", [], at(12)))
    assert "Nothing in the draft to log." in out and store.day_entries(day_of(at(12))) == []

def test_bad_food_reference_skips_only_that_item(store):
    # items: [food_id=999 servings 1, estimated salsa 20 kcal], items_to=log
    # -> salsa logged, "⚠️" line mentions the problem

def test_grams_on_food_without_size_asks_for_servings(store):
    # food saved with serving_qty None, item amount=50 unit=g -> problem "need … in servings"

def test_food_correction_updates_today_not_yesterday(store):
    # log tortilla yesterday and today via food_id, food_edits kcal 140
    # -> today's item 140, yesterday's still 150, draft item recomputed

def test_set_goals_from_chat(store):
    out = asyncio.run(handle(store, FakeBrain(res(set_goals=goals_payload(kcal=1500, protein=100))), "new goal 1500/100", [], at(12)))
    assert "🎯 New goals: 1,500 cal · 100g protein" in out
    assert store.goals(day_of(at(12)))["kcal"] == 1500

def test_past_tense_logs_straight_away(store):
    # items_to=log with estimated eggs -> entry logged, reply starts "✅ <b>Logged"

def test_menu_photo_picks_not_logged(store): ...
```

Keep the existing escape, banter, water, and "same as yesterday" prompt tests, ported to `handle`.

- [ ] **Step 2:** Run. Expected: FAIL. **Step 3:** Implement. **Step 4:** `pytest -q` passes, apart from the reminder tests still importing removed things. Leave those for Task 8, or delete them now if they block. **Step 5:** Commit `Draft-and-log flow with Python-scaled saved foods`.

### Task 7: Food migration script

**Files:** Create `sarge/migrate_foods.py`. Test `tests/test_migrate_foods.py`.

**Interfaces:**
- `PARSE_SCHEMA` holds the `save_foods` item fields from Task 5, minus `make_default`.
- `PARSE_SYSTEM` reads: "Parse this saved food's free-text description into label fields. Do not change the numbers; per-serving values are the given kcal/protein/carbs/fat. If the serving size in grams or ml is stated, fill serving_qty/unit, else 0/''."
- `async enrich(store, brain) -> list[dict]` only touches rows where `brand IS NULL AND serving_qty IS NULL`. For each, it calls `brain.interpret(row_text, PARSE_SYSTEM)` and then `store.edit_food(id, parsed minus macros)`. Macros are never taken from the brain. It returns the updated rows.
- `main()` loads env, opens `SARGE_DB` (or `data/sarge.db`), runs `enrich`, and prints one line per food (`id | name | brand variant | serving_desc | qty unit | kcal P`). Run it as `python -m sarge.migrate_foods`.

- [ ] **Step 1: Failing test.** With one old-style row and FakeBrain returning `brand="acme", serving_qty=55, serving_unit="g", kcal=999`, check that the row now has brand `acme` and qty 55 while kcal is unchanged at 150. A second run calls the brain 0 times.
- [ ] **Steps 2–4:** fail, then implement, then pass. **Step 5:** Commit `One-off enrichment of old saved foods`.

### Task 8: Night summary replaces reminders

**Files:** Create `sarge/summary.py`. Delete `sarge/reminders.py`. Modify `sarge/config.py` to remove `MEAL_GAP_HOURS`, `MEAL_REMIND_*`, `MORNING*`, `NAG_HOUR` and `WRAP`. Modify `sarge/render.py`. Test `tests/test_summary.py`, deleting the reminder tests from `test_sarge.py`.

**Interfaces (produces):**
- `@dataclass Summary: brief: str; fallback: str; footer: str; def compose(self, text: str | None) -> str`. This is the same behaviour as `Reminder.compose`.
- `summary.due(store, now) -> Summary | None`. Minutes are measured since rollover: `m(h, mi) = (h*60 + mi - DAY_ROLLOVER_HOUR*60) % 1440`. It fires when `m(now) >= m(summary_time)` and state `wrap_day != day_of(now)`, then sets `wrap_day`.
- `summary.build(store, now) -> Summary`. The brief holds the day's four macros against `store.goals(day)`, the logged items, water, steps and vitamin D, the streak, and the previous 6 days. It asks for what went well, where it slipped, and one focus, in 3–5 sentences. The footer is `render.summary_footer(t, g, streak)`: `🌙 <b>{macro_line}</b>`, then bars, the extras line and the streak. The fallback is `render.summary_fallback(t, g)`, the old `wrap_up` with goals passed in.

- [ ] **Step 1: Failing tests**

```python
def test_summary_once_at_default_time(store):
    assert summary.due(store, at(21, 59)) is None
    assert summary.due(store, at(22, 0)) is not None and summary.due(store, at(22, 30)) is None

def test_summary_time_after_midnight_counts_for_previous_day(store):
    store.set_goals(date(2026, 9, 22), {"summary_time": "00:30"})
    assert summary.due(store, at(23, 0)) is None
    s = summary.due(store, at(0, 31, d=23))
    assert s is not None and summary.due(store, at(1, 0, d=23)) is None

def test_summary_catches_up_after_downtime(store):
    assert summary.due(store, at(2, 0, d=23)) is not None  # down 22:00–02:00, still yesterday's

def test_no_other_scheduled_messages(store):
    # log nothing all day: due() is None at 08:30, 13:00, 17:00
```

- [ ] **Steps 2–4:** fail, then implement, then pass (full suite green). **Step 5:** Commit `Remove reminders; one night summary at a chat-set time`.

### Task 9: Bot: albums, status message, commands

**Files:** Modify `sarge/bot.py`. Test `tests/test_bot.py`.

**Interfaces:**
- `class AlbumBuffer`:
  - `AlbumBuffer(on_ready: Callable[[list[Message]], Awaitable[None]], delay: float = 2.0)`
  - `async add(msg) -> None`. A message without `media_group_id` calls `on_ready([msg])` immediately. Otherwise it is appended to that group, and the group's pending flush task is cancelled and rescheduled for `delay` seconds later, so the timer restarts each time.
- `Sarge.photos(msgs)`. It downloads every image (largest size, same mime check as today) and takes the first non-empty caption. It replies `📸 Reading your photos…` to the first message, then calls `handle` under the lock and runs `status.edit_text(reply)`. On `BadRequest` it falls back to `reply_text`. On `BrainError` it edits the status to `⚠️ Couldn't read that. Nothing logged. Send it again.` Then it calls `mirror()`.
- `Sarge.text` calls `handle(store, brain, text, [], now())`.
- `/goals` replies with `🎯 {goals.describe(g)}\n🌙 Summary at {summary_time}`.
- `/foods` groups products by name, one line each: `📌 <b>{name}</b> · {brand} {variant}{' ⭐' if default}: {serving_desc} = {kcal} cal · {protein}g P`.
- `tick` calls `summary.due(...)`, then `brain.write(brief, writer_prompt(g))` with the fallback.
- The `HELP` copy covers photos of labels, packs and plates; saying "ate it" to log; questions never logging; and "new goal: 1500 cal, 100g protein".
- `main` constructs `ClaudeBrain(env("CLAUDE_BIN"), env("CLAUDE_MODEL", "sonnet"), env("CLAUDE_PHOTO_MODEL", "opus"))`, and the photo handler routes through `AlbumBuffer`.

- [ ] **Step 1: Failing tests** (fake message objects with `media_group_id` and `caption`, `delay=0.01`):

```python
def test_album_grouped_once_caption_from_any_photo():
    got = []
    buf = AlbumBuffer(lambda msgs: record(got, msgs), delay=0.01)
    # add m1(group A, no caption), m2(group A, "1 tbsp"), s(no group) -> s flushed alone immediately
    # after sleep: got == [[s], [m1, m2]]

def test_two_albums_back_to_back_stay_separate(): ...
```

- [ ] **Steps 2–4:** fail, then implement, then pass. **Step 5:** Commit `Albums as one call, status message, /goals`.

### Task 10: Docs

**Files:** `README.md` and `.env.example`.

- [ ] **Step 1:** README changes:
  - Rewrite "What it does": photos of labels, packs and plates; the draft; "ate it"; product memory with brands and defaults; goals from chat; the night summary.
  - Delete the "Stays on your case" reminder list.
  - Update the mermaid chart: the JobQueue node now leads to `summary.py`.
  - Update the "Using it" table.
  - Keep the sample reply in sync: four macros and no "Next".
  - Mention `python -m sarge.migrate_foods` for anyone upgrading.
  - Add `CLAUDE_PHOTO_MODEL` to `.env.example`.
- [ ] **Step 2:** `.venv/bin/python -m pytest -q`. Expected: all pass. Run `grep -rn "remind\|nag\|Next:" sarge README.md`. Expected: no stale references, apart from deliberate ones such as "no reminders".
- [ ] **Step 3:** Commit `README: v2 tracker`.

### Task 11: Rollout to both bots

Confirm with the owner right before this task. It changes the live bots.

- [ ] **Step 1:** Back up both databases on the home server.

```bash
ssh <user>@<home-server> 'cp ~/sarge/data/sarge.db ~/sarge/data/sarge.db.pre-v2 && cp ~/sarge-<name>/data/sarge.db ~/sarge-<name>/data/sarge.db.pre-v2'
```

- [ ] **Step 2:** Rsync the code to both directories.

```bash
for d in sarge sarge-<name>; do rsync -az --delete --exclude .env --exclude data --exclude .venv --exclude sarge/plan_local.py --exclude __pycache__ --exclude .git --exclude demo --exclude .pytest_cache ./ <user>@<home-server>:~/$d/; done
```

- [ ] **Step 3:** Run the tests on the home server. `ssh <user>@<home-server> 'cd ~/sarge && .venv/bin/python -m pytest -q'`. Expected: all pass.
- [ ] **Step 4:** Restart both units, which runs the structural migration on start. `ssh <user>@<home-server> 'systemctl --user restart sarge sarge-<name> && sleep 5 && journalctl --user -u sarge -u sarge-<name> -n 30 --no-pager'`. Expected: `Sarge up` twice and no tracebacks.
- [ ] **Step 5:** Run the enrichment on both. `ssh <user>@<home-server> 'cd ~/sarge && bash -lic ".venv/bin/python -m sarge.migrate_foods"'`, then the same in `~/sarge-<name>`. Expected: a printed table, with the macros of the existing saved foods unchanged. Show the owner both tables; the owner checks the second instance's table, since that bot only answers its own user.
- [ ] **Step 6:** Live check on the owner's bot, done by the owner:
  - send an album of 2 label photos with a caption giving amounts; expect `📸 Reading…`, then a draft with Python numbers
  - send "ate it"; expect it to be logged
  - ask "how much protein in a Power Up?"; expect nothing logged
  - send "new goal 1800 cal 130g protein"; expect `🎯`
  - check the image-call durations in `journalctl --user -u sarge | grep brain`
- [ ] **Step 7:** Update the `sarge-diet-bot` memory with the v2 notes: the draft, structured foods, goals in the DB, the summary time in state, the migrate command, and the `.pre-v2` backups.
