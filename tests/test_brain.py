import asyncio
import json
import re
import sys

import pytest

from sarge import config
from sarge.brain import ITEM, SCHEMA, BrainError, ClaudeBrain, build_prompt, system_prompt, writer_prompt
from sarge.store import day_of
from tests.conftest import EGGS, TORTILLA, at

GOALS = {"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000, "summary_time": "22:00"}


def capture_brain(monkeypatch, output=None):
    calls = []

    async def fake_run(self, prompt, *extra, model, timeout, stream=False):
        calls.append(((prompt, *extra, "--model", model, "--timeout", timeout), stream))
        return {"structured_output": output or {"reply": "ok</reply>"}}

    monkeypatch.setattr(ClaudeBrain, "_run", fake_run)
    return ClaudeBrain("claude"), calls


def test_images_go_to_photo_model_in_one_message(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("p", "sys", [(b"a", "image/jpeg"), (b"b", "image/png")]))
    args, stream = calls[0]
    msg = json.loads(args[0])
    assert [c["type"] for c in msg["message"]["content"]] == ["image", "image", "text"]
    assert "opus" in args and stream


def test_images_are_base64_in_order_and_use_photo_timeout(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("look", "sys", [(b"a", "image/jpeg"), (b"b", "image/png")]))
    args, _ = calls[0]
    content = json.loads(args[0])["message"]["content"]
    assert [c["source"] for c in content[:2]] == [
        {"type": "base64", "media_type": "image/jpeg", "data": "YQ=="},
        {"type": "base64", "media_type": "image/png", "data": "Yg=="},
    ]
    assert content[2] == {"type": "text", "text": "look"}
    assert "--input-format" in args and args[-1] == 180


def test_text_uses_text_model(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("p", "sys"))
    assert "sonnet" in calls[0][0] and not calls[0][1]


def test_interpret_sends_system_and_schema_and_cleans_reply(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    out = asyncio.run(brain.interpret("p", "the system"))
    args, _ = calls[0]
    assert args[0] == "p" and args[-1] == 90
    assert args[args.index("--system-prompt") + 1] == "the system"
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert out["reply"] == "ok"


def test_interpret_takes_another_schema(monkeypatch):
    brain, calls = capture_brain(monkeypatch)
    other = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    asyncio.run(brain.interpret("p", "sys", schema=other))
    args, _ = calls[0]
    assert json.loads(args[args.index("--json-schema") + 1]) == other


def test_interpret_without_structured_output_fails(monkeypatch):
    async def fake_run(self, prompt, *extra, model, timeout, stream=False):
        return {"result": "I can't"}

    monkeypatch.setattr(ClaudeBrain, "_run", fake_run)
    with pytest.raises(BrainError):
        asyncio.run(ClaudeBrain("claude").interpret("p", "sys"))


def test_write_uses_text_model_and_given_system(monkeypatch):
    calls = []

    async def fake_run(self, prompt, *extra, model, timeout, stream=False):
        calls.append((prompt, extra, model))
        return {"result": "Solid day.</reply>"}

    monkeypatch.setattr(ClaudeBrain, "_run", fake_run)
    text = asyncio.run(ClaudeBrain("claude").write("brief", "night system"))
    assert text == "Solid day."
    assert calls == [("brief", ("--system-prompt", "night system"), "sonnet")]


def fake_claude(tmp_path, body):
    path = tmp_path / "claude"
    path.write_text(f"#!{sys.executable}\nimport json, sys, time\n{body}\n")
    path.chmod(0o755)
    return str(path)


def test_run_calls_claude_with_model_and_locked_down_flags(tmp_path):
    bin_ = fake_claude(tmp_path, 'sys.stdin.read(); print(json.dumps({"structured_output": {"argv": sys.argv[1:]}}))')
    out = asyncio.run(ClaudeBrain(bin_, model="haiku").interpret("p", "sys"))
    argv = out["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"
    for flag in ("--strict-mcp-config", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--output-format") + 1] == "json"


def test_failed_run_surfaces_the_cli_error_from_stdout(tmp_path):
    bin_ = fake_claude(tmp_path, 'sys.stdin.read(); print(json.dumps({"is_error": True, "result": "Failed to authenticate"})); sys.exit(1)')
    with pytest.raises(BrainError, match="exit 1: Failed to authenticate"):
        asyncio.run(ClaudeBrain(bin_).interpret("p", "sys"))


def test_run_times_out(tmp_path):
    bin_ = fake_claude(tmp_path, "time.sleep(5)")
    with pytest.raises(BrainError, match="timed out"):
        asyncio.run(ClaudeBrain(bin_, timeout=0.3).interpret("p", "sys"))


def test_prompt_lists_foods_with_ids_and_draft(store):
    fid, _ = store.save_food(TORTILLA)
    store.draft_add(at(12), [EGGS[0]], "wrap")
    p = build_prompt("x", "now", [], store.foods(), store.draft(at(12)), [], store.totals(day_of(at(12))), store.goals(day_of(at(12))), [])
    assert f'food {fid}: protein tortilla — brand "acme" variant ""' in p and "1 tortilla (55 g) [55g]" in p
    assert "DRAFT" in p and "draft item" in p and "GOALS" in p


def test_prompt_sections_in_order(store):
    day = day_of(at(12))
    p = build_prompt("hi", "Tuesday 12:00", [], [], [], [], store.totals(day), GOALS, [])
    heads = ["NOW", "GOALS", "TOTALS SO FAR", "YESTERDAY'S LOG", "TODAY'S LOG", "DRAFT", "MY FOODS",
             "RECENT CONVERSATION", "NEW MESSAGE"]
    positions = [p.index(h) for h in heads]
    assert positions == sorted(positions)
    assert "1500 kcal" in p.split("GOALS")[1] and p.endswith("NEW MESSAGE:\nhi")


def test_prompt_shows_food_references_and_default(store):
    fid, _ = store.save_food({**TORTILLA, "variant": "low carb", "aliases": "wrap", "notes": "keep cold", "make_default": True})
    store.draft_add(at(12), [{"name": "2 tortillas", "kcal": 300, "protein": 26, "carbs": 36, "fat": 8, "grams": 110,
                              "food_id": fid, "servings": 2}], "wrap")
    store.log_entry(at(9), "40g tortilla", True, "breakfast",
                    [{"name": "Tortilla 40g", "kcal": 109, "protein": 9.5, "carbs": 13, "fat": 3, "grams": 40,
                      "food_id": fid, "amount": 40, "unit": "g"},
                     {**EGGS[0], "estimated": 1}], "breakfast")
    day = day_of(at(12))
    p = build_prompt("x", "now", store.day_entries(day), store.foods(), store.draft(at(12)), [], store.totals(day), GOALS, [])
    assert (f'food {fid}: protein tortilla — brand "acme" variant "low carb" (default) — 1 tortilla (55 g) [55g] '
            "= 150 kcal P13 C18 F4") in p
    assert "aliases: wrap" in p and "notes: keep cold" in p
    draft_line = next(line for line in p.splitlines() if line.startswith("draft item"))
    assert f"food {fid} × 2 servings" in draft_line
    assert f"food {fid}, 40 g" in p and "eggs 150g" in p and "(estimate)" in p


def test_food_without_size_says_servings_only(store):
    store.save_food({**TORTILLA, "serving_qty": None, "serving_unit": None})
    p = build_prompt("x", "now", [], store.foods(), [], [], store.totals(day_of(at(12))), GOALS, [])
    assert "1 tortilla (55 g) [servings only]" in p


def test_brandless_food_keeps_brand_and_variant_separate(store):
    fid, _ = store.save_food({**TORTILLA, "brand": None, "variant": None})
    p = build_prompt("x", "now", [], store.foods(), [], [], store.totals(day_of(at(12))), GOALS, [])
    assert f'food {fid}: protein tortilla — brand "" variant "" — 1 tortilla' in p and "no brand" not in p


def test_system_prompt_states_goals():
    assert "1500 kcal" in system_prompt({"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000, "summary_time": "22:00"})


def test_system_prompt_is_built_from_the_goals_given():
    s = system_prompt({**GOALS, "kcal": 2100.0, "protein": 160.0})
    assert "2100 kcal" in s and "160 g protein" in s and "1500 kcal" not in s
    assert "override" in s.lower()


def test_voice_example_states_no_numbers_left():
    assert "300 cal left" not in system_prompt(GOALS)


def test_writer_prompt_states_goals():
    w = writer_prompt(GOALS)
    assert "1500 kcal" in w and "100 g protein" in w


def test_prompts_and_schema_follow_pronouns(monkeypatch):
    monkeypatch.setattr(config, "PRONOUNS", "she")
    he = re.compile(r"\b(he|him|his)\b", re.IGNORECASE)
    assert not he.search(system_prompt(GOALS)) and not he.search(writer_prompt(GOALS))
    brain, calls = capture_brain(monkeypatch)
    asyncio.run(brain.interpret("p", "sys"))
    args, _ = calls[0]
    assert not he.search(args[args.index("--json-schema") + 1])


def test_schema_requires_every_field():
    def check(obj):
        assert set(obj["required"]) == set(obj["properties"])
        for prop in obj["properties"].values():
            if prop.get("type") == "object":
                check(prop)
            if prop.get("type") == "array" and prop["items"].get("type") == "object":
                check(prop["items"])
    check(SCHEMA)
    assert SCHEMA["properties"]["items"]["items"] is ITEM
    assert "include quantity, e.g. 'Rice 150g', '2 eggs', 'Olive oil 5g'" in ITEM["properties"]["name"]["description"]
    assert SCHEMA["properties"]["items_to"]["enum"] == ["log", "draft", "none"]
    assert ITEM["properties"]["unit"]["enum"] == ["g", "ml", ""]
