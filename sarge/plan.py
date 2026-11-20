"""Your diet plan, in words: the food context and food rules Claude reads (e.g. vegetarian, favourite meals).

This is an example. Edit PLAN_TEXT, or keep your own plan in sarge/plan_local.py (gitignored) defining
PLAN_TEXT, and it will be used instead. The goals stored in the bot (change them from chat) override any
numbers in the plan text.
"""

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
    from .plan_local import PLAN_TEXT  # type: ignore  # noqa: F401,F811
except ImportError:
    pass
