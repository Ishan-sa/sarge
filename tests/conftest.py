import os

# Tests run against the defaults, whatever the local .env says (load_env never overrides these).
# Set before importing sarge, since its config reads the environment at import time.
for key, value in {
    "TARGET_KCAL": "1800", "TARGET_PROTEIN": "130", "TARGET_WATER_ML": "3000", "TARGET_STEPS": "8000",
    "SARGE_PRONOUNS": "he", "SARGE_TZ": "America/Vancouver",
}.items():
    os.environ[key] = value

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402

from sarge.config import TZ  # noqa: E402
from sarge.store import Store  # noqa: E402

TORTILLA = {"name": "protein tortilla", "brand": "acme", "variant": "", "serving_desc": "1 tortilla (55 g)",
            "serving_qty": 55, "serving_unit": "g", "kcal": 150, "protein": 13, "carbs": 18, "fat": 4}
SHAKE = {"name": "protein shake", "brand": "", "variant": "", "serving_desc": "1 bottle (414 ml)",
         "serving_qty": 414, "serving_unit": "ml", "kcal": 150, "protein": 30, "carbs": 6, "fat": 3}

EGGS = [
    {"name": "eggs", "grams": 150, "kcal": 215, "protein": 19, "carbs": 1, "fat": 15},
    {"name": "butter", "grams": 5, "kcal": 36, "protein": 0, "carbs": 0, "fat": 4},
]


def at(h, m=0, d=22):
    return datetime(2026, 9, d, h, m, tzinfo=TZ)


class FakeBrain:
    """Stands in for the LLM. Returns queued results in order; the last one repeats."""

    def __init__(self, *results):
        self.results = list(results)
        self.prompts, self.systems, self.images = [], [], []

    def _next(self):
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    async def interpret(self, prompt, system=None, images=(), schema=None):
        self.prompts.append(prompt)
        self.systems.append(system)
        self.images.append(list(images))
        return self._next()


@pytest.fixture
def store():
    return Store(":memory:")
