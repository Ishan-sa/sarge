import importlib
import sys
import types

from sarge import plan


def test_plan_local_with_only_plan_text_is_used():
    saved = sys.modules.get("sarge.plan_local")
    mod = types.ModuleType("sarge.plan_local")
    mod.PLAN_TEXT = "Vegetarian. Lunch is always a salad."
    sys.modules["sarge.plan_local"] = mod
    try:
        assert importlib.reload(plan).PLAN_TEXT == "Vegetarian. Lunch is always a salad."
    finally:
        if saved is None:
            sys.modules.pop("sarge.plan_local", None)
        else:
            sys.modules["sarge.plan_local"] = saved
        importlib.reload(plan)
