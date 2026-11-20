class ScaleError(Exception):
    pass


def scale(food: dict, servings: float = 0, amount: float = 0, unit: str = "") -> dict:
    """Scale a label record to what was eaten, by servings or by amount in the label's unit."""
    qty = food.get("serving_qty")
    if servings > 0:
        factor, grams = servings, servings * qty if qty else 0
    elif amount > 0 and unit and unit == food.get("serving_unit") and qty:
        factor, grams = amount / qty, amount
    else:
        raise ScaleError(f"need {food['name']} in servings ({food['serving_desc']})")
    return {
        "grams": round(grams, 1),
        **{k: round((food.get(k) or 0) * factor, 1) for k in ("kcal", "protein", "carbs", "fat")},
    }
