import asyncio

from sarge.brain import BrainError
from sarge.migrate_foods import PARSE_SCHEMA, enrich
from tests.conftest import FakeBrain, SHAKE, TORTILLA

PARSED = {"name": "Protein Tortilla ", "brand": "acme", "variant": "", "aliases": "wrap", "serving_desc": "1 tortilla (55 g)",
          "serving_qty": 55, "serving_unit": "g", "kcal": 999, "protein": 99, "carbs": 99, "fat": 99, "notes": ""}


def old_food(store, name="protein tortilla", desc="1 tortilla, 55g", kcal=150):
    """A row as the automatic migration leaves it: brand and variant NULL, no serving size."""
    fid, _ = store.save_food({"name": name, "serving_desc": desc, "kcal": kcal, "protein": 13, "carbs": 18, "fat": 4})
    store.db.execute("UPDATE foods SET brand = NULL, variant = NULL, serving_qty = NULL WHERE id = ?", (fid,))
    store.db.commit()
    return fid


def run(store, brain):
    return asyncio.run(enrich(store, brain))


def test_schema_is_the_label_fields_without_make_default():
    props = PARSE_SCHEMA["properties"]
    assert "make_default" not in props and "serving_qty" in props
    assert PARSE_SCHEMA["required"] == list(props)


def test_enrich_fills_label_fields_but_never_macros(store):
    fid = old_food(store)
    brain = FakeBrain(PARSED)
    rows = run(store, brain)
    food = store.food(fid)
    assert (food["brand"], food["serving_qty"], food["serving_unit"], food["name"]) == ("acme", 55, "g", "protein tortilla")
    assert food["aliases"] == "wrap"
    assert (food["kcal"], food["protein"], food["carbs"], food["fat"]) == (150, 13, 18, 4)
    assert [r["id"] for r in rows] == [fid]
    assert "1 tortilla, 55g" in brain.prompts[0] and "150" in brain.prompts[0]


def test_second_run_makes_no_brain_calls(store):
    old_food(store)
    run(store, FakeBrain(PARSED))
    brain = FakeBrain(PARSED)
    assert run(store, brain) == []
    assert brain.prompts == []


def test_unbranded_food_gets_empty_strings_so_it_is_not_picked_up_again(store):
    fid = old_food(store)
    run(store, FakeBrain({**PARSED, "brand": None, "variant": None, "serving_qty": 0, "serving_unit": ""}))
    food = store.food(fid)
    assert (food["brand"], food["variant"], food["serving_qty"], food["serving_unit"]) == ("", "", None, None)
    brain = FakeBrain(PARSED)
    run(store, brain)
    assert brain.prompts == []  # brand "" (not NULL) marks it done even with no serving size


def test_rows_saved_by_v2_are_skipped(store):
    store.save_food(TORTILLA)
    store.save_food(SHAKE)
    brain = FakeBrain(PARSED)
    assert run(store, brain) == []
    assert brain.prompts == []


def test_bad_unit_and_empty_name_are_normalised(store):
    fid = old_food(store)
    run(store, FakeBrain({**PARSED, "name": "  ", "serving_unit": "oz", "serving_desc": ""}))
    food = store.food(fid)
    assert food["name"] == "protein tortilla" and food["serving_unit"] is None
    assert food["serving_desc"] == "1 tortilla, 55g"


def test_different_parsed_name_is_kept_out_of_name_and_added_to_aliases(store):
    fid = old_food(store, "chicken portion")
    run(store, FakeBrain({**PARSED, "name": "Chicken Breast", "aliases": "chook, Chicken Breast"}))
    food = store.food(fid)
    assert food["name"] == "chicken portion"
    assert food["aliases"] == "chook, Chicken Breast"


def test_identity_collision_skips_brand_and_variant_with_warning(store, capsys):
    store.save_food(TORTILLA)
    fid = old_food(store)
    run(store, FakeBrain(PARSED))
    food = store.food(fid)
    assert food["brand"] is None and food["serving_qty"] == 55
    assert "warning" in capsys.readouterr().out


def test_non_brain_failure_skips_the_row_and_continues(store, capsys):
    bad, good = old_food(store, "a food"), old_food(store, "b food")
    results = [ValueError("boom"), PARSED]

    class Brain:
        async def interpret(self, prompt, system=None, images=(), schema=None):
            r = results.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    rows = run(store, Brain())
    assert [r["id"] for r in rows] == [good] and store.food(bad)["brand"] is None
    assert "boom" in capsys.readouterr().out


def test_bad_serving_qty_becomes_null(store):
    fid = old_food(store)
    run(store, FakeBrain({**PARSED, "serving_qty": "lots"}))
    assert store.food(fid)["serving_qty"] is None
