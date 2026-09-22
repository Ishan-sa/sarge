"""Your diet plan: what Claude reads, and the meal slots Sarge tracks and suggests next.

This is an example. Edit it, or keep your own plan in sarge/plan_local.py (gitignored) with the
same two names, SLOTS and PLAN_TEXT, and it will be used instead.

SLOTS: key -> label (shown in the log), next (shown as "⏭ Next: ..."), plan (what Claude is told).
"""

SLOTS = {
    "breakfast": {
        "label": "Breakfast",
        "next": "Breakfast — Greek yogurt, berries, granola",
        "plan": "Breakfast: 250g 0% Greek yogurt, 100g mixed berries, 30g granola",
    },
    "lunch": {
        "label": "Lunch",
        "next": "Lunch — chicken burrito bowl",
        "plan": "Lunch: burrito bowl, 150g grilled chicken, 150g cooked rice, 80g black beans, salsa, lettuce",
    },
    "snack": {
        "label": "Snack",
        "next": "Snack — protein shake + a banana",
        "plan": "Snack: 1 scoop whey in water, 1 banana",
    },
    "dinner": {
        "label": "Dinner",
        "next": "Dinner — salmon, potatoes, greens",
        "plan": "Dinner: 150g salmon, 200g baby potatoes, 200g green veggies, 5g olive oil",
    },
}

PLAN_TEXT = """\
Diet plan — 1800 calories, 130g+ protein

Breakfast: 250g 0% Greek yogurt, 100g mixed berries, 30g granola
Lunch: burrito bowl, 150g grilled chicken, 150g cooked rice, 80g black beans, salsa, lettuce
Snack: 1 scoop whey in water, 1 banana
Dinner: 150g salmon, 200g baby potatoes, 200g green veggies, 5g olive oil

3-4 L water and 8-10k steps daily. Vitamin D with dinner.

Notes:
1. Order and timing of meals don't matter as long as the day adds up.
2. Zero-calorie drinks (black coffee, green tea, diet soda) are fine when hungry.
3. Eating out? Skip a planned meal to make room, and pick the leanest protein on the menu.
"""

try:  # personal plan, never committed
    from .plan_local import PLAN_TEXT, SLOTS  # type: ignore  # noqa: F401,F811
except ImportError:
    pass
