import asyncio

from sarge.brain import ITEM, SCHEMA
from sarge.core import apply, handle
from sarge.store import day_of
from tests.conftest import EGGS, SHAKE, TORTILLA, FakeBrain, at

_BLANK = {"array": [], "string": "", "number": 0, "integer": 0, "boolean": False}


def goals_payload(**kw):
    return {"kcal": 0, "protein": 0, "water_ml": 0, "steps": 0, "summary_time": "", **kw}


def res(**kw):
    base = {k: _BLANK.get(v.get("type")) for k, v in SCHEMA["properties"].items()}
    base.update(items_to="none", eat_draft=0, default_food_id=0, set_goals=goals_payload())
    return {**base, **kw}


def item(name, **kw):
    base = {k: _BLANK.get(v.get("type")) for k, v in ITEM["properties"].items()}
    base.update(name=name, emoji="🍽", food_id=0, new_food_index=-1)
    return {**base, **kw}


def label(**kw):
    return {**TORTILLA, "aliases": "tortilla", "notes": "", "make_default": False, **kw}


def food_edit(food_id, **kw):
    return {"id": food_id, **label(), **kw}


def edit(item_id, **kw):
    base = {"id": item_id, "servings": 0, "amount": 0, "unit": "", "name": "", "grams": 0,
            "kcal": 0, "protein": 0, "carbs": 0, "fat": 0}
    return {**base, **kw}


EST_EGGS = [item(e["name"], **{k: v for k, v in e.items() if k != "name"}) for e in EGGS]


def run(store, result, text="x", ts=None, images=()):
    brain = FakeBrain(result)
    return asyncio.run(handle(store, brain, text, list(images), ts or at(12))), brain


def today(ts=None):
    return day_of(ts or at(12))


# --- saved foods and the draft -------------------------------------------------


def test_label_photo_saves_and_drafts_with_python_math(store):
    brain = FakeBrain(res(save_foods=[label()], items=[item("protein tortilla", new_food_index=0, servings=1, kcal=999)],
                          items_to="draft", title="wrap"))
    out = asyncio.run(handle(store, brain, "1 of these", [(b"img", "image/jpeg")], at(12)))
    assert out.startswith("📝 <b>Draft wrap: 150 cal · 13g P · 18g C · 4g F</b>")
    assert "📌 Saved Acme protein tortilla (1 tortilla (55 g)): 150 cal · 13g P" in out
    assert 'Say "ate it" to log it, or correct me first.' in out
    assert store.day_entries(today()) == []
    assert brain.images[0] == [(b"img", "image/jpeg")]
    [d] = store.draft(at(12))
    assert d["food_id"] == store.foods()[0]["id"] and d["estimated"] == 0 and d["grams"] == 55


def test_question_logs_nothing(store):
    run(store, res(reply="About 30g."), "how much protein in power up?")
    assert store.day_entries(today()) == [] and store.draft(at(12)) == []


def _draft_wrap(store, ts):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(items=[item("1 tortilla", food_id=fid, servings=1), EST_EGGS[0]], items_to="draft", title="wrap"), ts=ts)
    return fid


def test_ate_it_logs_whole_draft_and_half(store):
    _draft_wrap(store, at(12))
    out, _ = run(store, res(eat_draft=1), "ate it", at(12, 30))
    assert out.startswith("✅ <b>Logged wrap: 365 cal · 32g P · 19g C · 19g F</b>")
    [entry] = store.day_entries(today())
    assert [i["name"] for i in entry["items"]] == ["1 tortilla", "eggs"] and store.draft(at(12, 31)) == []

    run(store, res(items=[item("1 tortilla", food_id=store.foods()[0]["id"], servings=1), EST_EGGS[0]],
                   items_to="draft", title="wrap"), ts=at(13))
    run(store, res(eat_draft=0.5), "ate half", at(13, 30))
    half = store.day_entries(today())[1]["items"]
    assert [(i["kcal"], i["protein"], i["grams"]) for i in half] == [(75, 6.5, 27.5), (107.5, 9.5, 75)]
    assert half[0]["servings"] == 0.5 and half[0]["estimated"] == 0 and half[1]["estimated"] == 1


def test_eat_draft_is_clamped(store):
    _draft_wrap(store, at(12))
    run(store, res(eat_draft=3), "ate it", at(12, 30))
    assert store.totals(today())["kcal"] == 365


def test_ate_it_with_empty_draft(store):
    out, _ = run(store, res(eat_draft=1), "ate it")
    assert "Nothing in the draft to log." in out and store.day_entries(today()) == []


def test_ate_draft_plus_new_food_is_one_entry(store):
    _draft_wrap(store, at(12))
    run(store, res(eat_draft=1, items=[item("coffee", kcal=30, protein=2)], items_to="log"), "ate it plus a coffee", at(12, 30))
    [entry] = store.day_entries(today())
    assert [i["name"] for i in entry["items"]] == ["1 tortilla", "eggs", "coffee"] and entry["title"] == "wrap"


def test_partial_draft_eating_and_scrapping(store):
    _draft_wrap(store, at(12))
    eggs_id = store.draft(at(12))[1]["id"]
    run(store, res(draft_remove_ids=[eggs_id], eat_draft=1), "had the tortilla, not the eggs", at(12, 30))
    assert [i["name"] for e in store.day_entries(today()) for i in e["items"]] == ["1 tortilla"]

    _draft_wrap(store, at(13))
    out, _ = run(store, res(clear_draft=True, reply="Fine."), "scrap that", at(13, 5))
    assert store.draft(at(13, 6)) == [] and "Fine." in out


def test_draft_edit_rescales_saved_food_and_takes_estimate_macros(store):
    _draft_wrap(store, at(12))
    tortilla, eggs = store.draft(at(12))
    out, _ = run(store, res(draft_edits=[
        edit(tortilla["id"], servings=2, name="2 tortillas", kcal=1),
        edit(eggs["id"], name="2 eggs", grams=100, kcal=143, protein=13, carbs=1, fat=10),
    ]), "2 tortillas, 2 eggs", at(12, 5))
    tortilla, eggs = store.draft(at(12, 6))
    assert (tortilla["name"], tortilla["kcal"], tortilla["grams"], tortilla["servings"]) == ("2 tortillas", 300, 110, 2)
    assert (eggs["name"], eggs["kcal"], eggs["estimated"]) == ("2 eggs", 143, 1)
    assert out.startswith("📝 <b>Draft wrap: 443 cal")


def test_bad_food_reference_skips_only_that_item(store):
    out, _ = run(store, res(items=[item("tortilla", food_id=999, servings=1), item("salsa", grams=30, kcal=20, protein=1)],
                            items_to="log", title="snack"))
    [entry] = store.day_entries(today())
    assert [i["name"] for i in entry["items"]] == ["salsa"]
    assert "⚠️" in out and "tortilla" in out.split("⚠️")[1]


def test_bad_new_food_index_is_a_problem(store):
    out, _ = run(store, res(items=[item("tortilla", new_food_index=2, servings=1)], items_to="log"))
    assert store.day_entries(today()) == [] and "⚠️" in out


def test_grams_on_food_without_size_asks_for_servings(store):
    fid, _ = store.save_food({**TORTILLA, "serving_desc": "1 tortilla", "serving_qty": None, "serving_unit": None})
    out, _ = run(store, res(items=[item("tortilla 50g", food_id=fid, amount=50, unit="g")], items_to="log"))
    assert store.day_entries(today()) == []
    assert "⚠️" in out and "need protein tortilla in servings (1 tortilla)" in out


def test_food_correction_updates_today_not_yesterday(store):
    fid, _ = store.save_food(TORTILLA)
    ref = item("1 tortilla", food_id=fid, servings=1)
    run(store, res(items=[ref], items_to="log"), ts=at(12, d=21))
    run(store, res(items=[ref], items_to="log"), ts=at(12))
    run(store, res(items=[{**ref, "servings": 2}], items_to="draft"), ts=at(13))
    out, _ = run(store, res(food_edits=[food_edit(fid, kcal=140)]), "the tortilla is 140", at(14))
    assert store.day_entries(today())[0]["items"][0]["kcal"] == 140
    assert store.day_entries(day_of(at(12, d=21)))[0]["items"][0]["kcal"] == 150
    assert store.draft(at(14))[0]["kcal"] == 280
    assert "📌 Updated Acme protein tortilla" in out and "✏️ Updated 1 logged item" in out


def test_food_edit_keeps_identity_fields(store):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(food_edits=[food_edit(fid, brand="", variant="none", kcal=140)]))
    f = store.food(fid)
    assert (f["name"], f["brand"], f["variant"], f["kcal"]) == ("protein tortilla", "acme", "", 140)


def test_food_edit_rejects_bad_numbers(store):
    fid, _ = store.save_food(TORTILLA)
    out, _ = run(store, res(food_edits=[food_edit(fid, kcal="lots", protein=-3)]))
    assert store.food(fid)["kcal"] == 150 and store.food(fid)["protein"] == 13 and "⚠️" in out


def test_defaults_clear_siblings(store):
    a, _ = store.save_food(SHAKE)
    b, _ = store.save_food({**SHAKE, "brand": "other"})
    run(store, res(default_food_id=b))
    assert (store.food(a)["is_default"], store.food(b)["is_default"]) == (0, 1)
    run(store, res(food_edits=[{"id": a, **SHAKE, "aliases": "", "notes": "", "make_default": True}]))
    assert (store.food(a)["is_default"], store.food(b)["is_default"]) == (1, 0)


def test_delete_food_leaves_logged_items(store):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(items=[item("1 tortilla", food_id=fid, servings=1)], items_to="log"))
    out, _ = run(store, res(delete_food_ids=[fid, 999]), ts=at(12, 5))
    assert store.food(fid) is None and store.totals(today())["kcal"] == 150 and "⚠️" in out


def test_item_edit_on_saved_food_rescales(store):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(items=[item("1 tortilla", food_id=fid, servings=1)], items_to="log"))
    item_id = store.day_entries(today())[0]["items"][0]["id"]
    out, _ = run(store, res(item_edits=[edit(item_id, amount=110, unit="g", name="2 tortillas", kcal=5)]), ts=at(12, 5))
    i = store.item(item_id)
    assert (i["kcal"], i["grams"], i["amount"], i["name"]) == (300, 110, 110, "2 tortillas")
    assert "✏️ <b>Updated:</b>" in out


# --- goals, extras, picks -------------------------------------------------------


def test_set_goals_from_chat(store):
    out, _ = run(store, res(set_goals=goals_payload(kcal=1500, protein=100)), "new goal 1500/100")
    assert "🎯 New goals: 1,500 cal · 100g protein" in out
    assert store.goals(today())["kcal"] == 1500


def test_bad_goals_never_crash_or_store(store):
    out, _ = run(store, res(set_goals=goals_payload(kcal=50, protein=True, steps="lots", summary_time="noon")))
    g = store.goals(today())
    assert (g["kcal"], g["protein"], g["steps"]) == (1800, 130, 8000)
    assert out.count("⚠️") == 4 and "🎯" not in out


def test_totals_sum_items_and_extras(store):
    apply(store, res(items=EST_EGGS, items_to="log", water_ml=500, steps=4000, vitamin_d=True), "eggs", at(11))
    apply(store, res(water_ml=750, steps=6000), "water", at(12))
    t = store.totals(today())
    assert t["kcal"] == 251 and t["protein"] == 19
    assert t["water_ml"] == 1250
    assert t["steps"] == 6000  # latest step count replaces, doesn't add
    assert t["vitd"]


def test_menu_photo_picks_not_logged(store):
    picks = [{"name": "Tandoori chicken (half)", "emoji": "🍗", "kcal": 450, "protein": 48, "how": "skip the butter naan"}]
    out, _ = run(store, res(picks=picks, reply="Easy call."), "", at(19), [(b"img", "image/jpeg")])
    assert out.splitlines()[0] == "🍽 <b>Best picks for what's left</b>"
    assert "🍗 Tandoori chicken (half) · ~450 cal · 💪48g\n   ↳ skip the butter naan" in out
    assert "🗣 Easy call." in out and store.day_entries(day_of(at(19))) == [] and store.draft(at(19)) == []


def test_past_tense_logs_straight_away(store):
    out, _ = run(store, res(items=EST_EGGS, items_to="log", title="eggs"), "I had 3 eggs in butter")
    assert out.startswith("✅ <b>Logged eggs") and store.totals(today())["kcal"] == 251
    assert "🍽 ~eggs · 215 cal · 💪19g" in out


def test_items_to_none_adds_nothing(store):
    run(store, res(items=EST_EGGS, items_to="none"))
    assert store.day_entries(today()) == [] and store.draft(at(12)) == []


# --- history ----------------------------------------------------------------------


def test_history_records_photos_and_exact_draft_numbers(store):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(items=[item("1 tortilla", food_id=fid, servings=1)], items_to="draft", title="wrap", reply="Add protein."),
        "lunch", at(12), [(b"a", "image/jpeg"), (b"b", "image/jpeg")])
    user, sarge = [m["text"] for m in store.recent_messages()]
    assert user == "[photo x2] lunch"
    assert "1 tortilla 55g — 150 kcal P13 C18 F4" in sarge and "Add protein." in sarge


def test_history_records_logged_numbers(store):
    run(store, res(items=EST_EGGS, items_to="log", title="eggs"), "had eggs")
    assert "eggs 150g — 215 kcal P19 C1 F15" in store.recent_messages()[1]["text"]


# --- ported from the v1 handle_text tests -----------------------------------------


def test_meal_reply_summary_first(store):
    out, _ = run(store, res(items=EST_EGGS, items_to="log", title="scrambled eggs", reply="Butter counted."),
                 "3 eggs in 5g butter", at(11))
    lines = out.splitlines()
    assert lines[0] == "✅ <b>Logged scrambled eggs: 251 cal · 19g P · 1g C · 19g F</b>"
    assert lines[1] == "Left today: 1,549 cal · 111g protein"
    assert "💪 ▰▱▱▱▱▱▱▱▱▱ 19 / 130g protein" in out
    assert "🗣 Butter counted." in out
    # second message sees the first in its context
    run(store, res(), "how am I doing", at(11, 5))
    assert store.recent_messages()[0]["text"] == "3 eggs in 5g butter"
    assert store.day_entries(day_of(at(11)))[0]["title"] == "scrambled eggs"


def test_over_budget_is_flagged(store):
    big = [item("pizza", kcal=1900, protein=60, carbs=200, fat=80)]
    out, _ = run(store, res(items=big, items_to="log", title="pizza"), "pizza", at(19))
    assert "⚠️ 100 cal OVER" in out.splitlines()[1]


def test_banter_gets_no_stats(store):
    out, _ = run(store, res(reply="Cool isn't a meal."), "cool")
    assert out == "Cool isn&#x27;t a meal."


def test_status_only_when_asked(store):
    out, _ = run(store, res(show_status=True, reply="Behind."), "what's left")
    assert out.startswith("Behind.") and "Left today: 1,800 cal" in out


def test_water_log_is_short(store):
    out, _ = run(store, res(water_ml=500, reply="Keep it coming."), "500ml water", at(11))
    assert out == "💧 <b>+500ml water</b>\n\nKeep it coming."


def test_html_is_escaped(store):
    out, _ = run(store, res(items=[item("Mac & <chz>", kcal=300, protein=12, carbs=30, fat=14)], items_to="log",
                            title="mac & cheese", reply="Hot & sweet <b>"), "mac", at(11))
    assert "Mac &amp; &lt;chz&gt;" in out and "Hot &amp; sweet &lt;b&gt;" in out and "mac &amp; cheese" in out


def test_problems_are_escaped(store):
    out, _ = run(store, res(items=[item("<b>x</b>", food_id=999, servings=1)], items_to="log"))
    assert "<b>x</b>" not in out and "&lt;b&gt;x&lt;/b&gt;" in out


def test_edits_and_deletes_only_touch_today(store):
    apply(store, res(items=EST_EGGS, items_to="log"), "yesterday eggs", at(11, d=21))
    old_item = store.day_entries(day_of(at(11, d=21)))[0]["items"][0]["id"]
    apply(store, res(items=EST_EGGS, items_to="log"), "eggs", at(11))
    eggs, butter = (i["id"] for i in store.day_entries(day_of(at(11)))[0]["items"])

    outcome = apply(store, res(
        delete_item_ids=[butter, old_item],
        item_edits=[edit(eggs, name="eggs", grams=100, kcal=143, protein=13, carbs=1, fat=10)],
    ), "fix", at(11, 5))

    assert store.totals(day_of(at(11)))["kcal"] == 143
    assert store.totals(day_of(at(11, d=21)))["kcal"] == 251  # yesterday untouched
    assert len(outcome.problems) == 1


def test_item_edit_keeps_emoji(store):
    apply(store, res(items=[{**EST_EGGS[0], "emoji": "🍳"}], items_to="log"), "eggs", at(11))
    item_id = store.day_entries(day_of(at(11)))[0]["items"][0]["id"]
    outcome = apply(store, res(item_edits=[edit(item_id, name="3 eggs", grams=150, kcal=215, protein=19, carbs=1, fat=15)]),
                    "3 eggs", at(11, 1))
    assert outcome.lines == ["✏️ <b>Updated:</b> 🍳 ~3 eggs · 215 cal · 💪19g"]


def test_prompt_sees_yesterday(store):
    apply(store, res(items=EST_EGGS, items_to="log", title="breakfast burrito"), "burrito, 3 eggs", at(11, d=21))
    _, brain = run(store, res(), "same burrito as yesterday", at(11))
    y = brain.prompts[0].split("YESTERDAY'S LOG")[1].split("TODAY'S LOG")[0]
    assert "breakfast burrito" in y and "eggs 150g" in y


def test_non_finite_numbers_are_rejected(store):
    out, _ = run(store, res(items=[item("mystery", kcal=float("nan"), protein=1)], items_to="log", water_ml=float("inf"),
                            set_goals=goals_payload(kcal=float("inf"))))
    assert store.day_entries(today()) == [] and store.totals(today())["water_ml"] == 0 and out.count("⚠️") == 2


def test_label_resave_rescales_today_and_draft(store):
    fid, _ = store.save_food(TORTILLA)
    ref = item("1 tortilla", food_id=fid, servings=1)
    run(store, res(items=[ref], items_to="log"), ts=at(12, d=21))
    run(store, res(items=[ref], items_to="log"), ts=at(12))
    run(store, res(items=[ref], items_to="draft"), ts=at(13))
    out, _ = run(store, res(save_foods=[label(kcal=140)]), "new label", at(14))
    assert store.day_entries(today())[0]["items"][0]["kcal"] == 140
    assert store.draft(at(14))[0]["kcal"] == 140
    assert store.day_entries(day_of(at(12, d=21)))[0]["items"][0]["kcal"] == 150
    assert "📌 Updated Acme protein tortilla" in out and "✏️ Updated 1 logged item" in out and "✏️ Updated 1 draft item" in out
    out, _ = run(store, res(save_foods=[label(kcal=140)]), "same label", at(14, 5))
    assert "✏️" not in out


def test_claude_emoji_is_escaped(store):
    picks = [{"name": "Dal", "emoji": "<b>", "kcal": 300, "protein": 15, "how": "no ghee"}]
    out, _ = run(store, res(picks=picks), "menu")
    assert "<b>" not in out.replace("<b>Best", "")
    out, _ = run(store, res(items=[item("eggs", emoji="<b>", kcal=70, protein=6)], items_to="log", title="eggs"), "eggs")
    assert out.count("<b>") == 1 and "&lt;b&gt; ~eggs" in out


def test_share_suffix_is_rounded(store):
    _draft_wrap(store, at(12))
    run(store, res(eat_draft=2 / 3), "ate 2 of the 3", at(12, 30))
    names = [i["name"] for i in store.day_entries(today())[0]["items"]]
    assert names == ["1 tortilla ×0.67", "eggs ×0.67"]


def test_log_and_draft_change_shows_both(store):
    _draft_wrap(store, at(12))
    eggs_id = store.draft(at(12))[1]["id"]
    out, _ = run(store, res(items=[item("banana", kcal=105, protein=1)], items_to="log", title="snack",
                            draft_remove_ids=[eggs_id]), "had a banana, no eggs in the wrap", at(12, 30))
    assert out.startswith("✅ <b>Logged snack")
    assert "📝 <b>Draft wrap: 150 cal" in out and out.index("✅") < out.index("📝")
    out, _ = run(store, res(eat_draft=1, items=[item("2 eggs", kcal=140, protein=12)], items_to="draft", title="next"),
                 "ate it, now making eggs", at(13))
    assert out.startswith("✅ <b>Logged wrap") and "📝 <b>Draft next: 140 cal" in out
    out, _ = run(store, res(items=[item("coffee", kcal=5)], items_to="log"), "coffee", at(13, 5))
    assert "📝" not in out  # untouched draft isn't repeated


def test_food_edit_with_blank_size_keeps_the_size(store):
    fid, _ = store.save_food(TORTILLA)
    run(store, res(items=[item("1 tortilla", food_id=fid, servings=1)], items_to="log"))
    for blank in ({"serving_qty": 0, "serving_unit": ""}, {"serving_qty": None, "serving_unit": None}):
        run(store, res(food_edits=[food_edit(fid, kcal=140, **blank)]), "the tortilla is 140 cal not 150", at(13))
        f = store.food(fid)
        assert (f["kcal"], f["serving_qty"], f["serving_unit"]) == (140, 55, "g")
    assert store.day_entries(today())[0]["items"][0]["kcal"] == 140
    run(store, res(items=[item("tortilla 110g", food_id=fid, amount=110, unit="g")], items_to="log"), ts=at(14))
    assert store.day_entries(today())[1]["items"][0]["kcal"] == 280


def test_junk_brand_on_save_updates_the_same_product(store):
    fid, _ = store.save_food(SHAKE)
    out, _ = run(store, res(save_foods=[{**SHAKE, "brand": "None", "variant": "n/a", "kcal": 160,
                                         "aliases": "", "notes": "", "make_default": False}]))
    [f] = store.foods()
    assert (f["id"], f["brand"], f["variant"], f["kcal"]) == (fid, "", "", 160)
    assert "Updated" in out


def test_missing_new_food_label_falls_back_to_the_estimate(store):
    out, _ = run(store, res(items=[item("tortilla", new_food_index=2, servings=1, grams=55, kcal=150, protein=13,
                                        carbs=18, fat=4)], items_to="log"))
    [i] = store.day_entries(today())[0]["items"]
    assert (i["name"], i["kcal"], i["estimated"], i["food_id"]) == ("tortilla", 150, 1, None)
    assert "⚠️" in out and "estimate" in out
