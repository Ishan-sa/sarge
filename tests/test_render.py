from sarge.render import bars, extras_line, item_line, left_line, macro_line, summary_fallback, summary_footer

G = {"kcal": 1500, "protein": 100, "water_ml": 3000, "steps": 8000}
T = {"kcal": 500, "protein": 40, "carbs": 0, "fat": 0, "water_ml": 0, "steps": None, "vitd": False}


def test_render_uses_given_goals():
    assert left_line(T, G) == "Left today: 1,000 cal · 60g protein"
    assert "500 / 1,500 cal" in bars(T, G)
    assert "40 / 100g protein" in bars(T, G)
    assert "0.0 / 3L water" in extras_line(T, G)


def test_summary_fallback_judges_against_given_goals():
    out = summary_fallback({**T, "kcal": 1700, "water_ml": 1000, "steps": 5000}, {**G, "steps": 6000})
    assert "protein short by 60g" in out and "200 cal over" in out and "steps under 6k" in out


def test_summary_footer_has_macros_bars_extras_and_streak():
    out = summary_footer({**T, "carbs": 30, "fat": 10}, G, 3)
    assert out.startswith("🌙 <b>500 cal · 40g P · 30g C · 10g F</b>")
    assert "500 / 1,500 cal" in out and "no steps logged" in out and out.endswith("🔥 Streak: 3 days")
    assert "Streak" not in summary_footer(T, G, 0) and "1 day" in summary_footer(T, G, 1)


def test_macro_line_rounds_all_four():
    assert macro_line({"kcal": 568.6, "protein": 58.2, "carbs": 40.4, "fat": 11.9}) == "569 cal · 58g P · 40g C · 12g F"


def test_item_line_name_carries_quantity():
    i = {"name": "Rice 150g", "emoji": "🍚", "grams": 150, "kcal": 195, "protein": 4}
    assert item_line(i) == "🍚 Rice 150g · 195 cal · 💪4g"


def test_estimated_item_marked():
    assert item_line({"name": "Fries", "emoji": "🍟", "kcal": 300, "protein": 4, "estimated": 1}).startswith("🍟 ~Fries")


def test_day_view_untitled_entry_falls_back_to_slot():
    from sarge.render import day_view
    e = {"ts": "2026-09-22T11:00:00", "slot": "extra", "title": None,
         "items": [{"kcal": 100, "protein": 5, "carbs": 1, "fat": 1}]}
    assert "11:00  Extra · 100 cal" in day_view([e], {**T, "slots": set(), "entries": 1}, G)
