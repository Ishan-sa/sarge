"""One-way mirror of the SQLite log into a Google Sheet via an Apps Script web app (deploy/sheet.gs).

Each sync sends a full snapshot of one day, so it's idempotent: a failed push is fixed by the next one.
"""

import logging
from datetime import date

import httpx

from .config import TARGET_KCAL, TARGET_PROTEIN
from .render import SLOT_LABELS
from .store import Store

log = logging.getLogger("sarge.sheets")


def snapshot(store: Store, day: date) -> dict:
    t = store.totals(day)
    items = [
        {
            "time": e["ts"][11:16],
            "meal": e.get("title") or SLOT_LABELS.get(e["slot"], "Extra"),
            "name": i["name"],
            "grams": round(i["grams"]) if i["grams"] else None,
            **{k: round(i[k], 1) for k in ("kcal", "protein", "carbs", "fat")},
        }
        for e in store.day_entries(day)
        for i in e["items"]
    ]
    return {
        "daily": {
            "date": day.isoformat(),
            **{k: round(t[k], 1) for k in ("kcal", "protein", "carbs", "fat")},
            "water_l": round(t["water_ml"] / 1000, 2),
            "steps": int(t["steps"]) if t["steps"] is not None else "",
            "vitd": t["vitd"],
            "kcal_ok": t["kcal"] <= TARGET_KCAL,
            "protein_ok": t["protein"] >= TARGET_PROTEIN,
        },
        "items": items,
    }


class SheetMirror:
    def __init__(self, url: str, secret: str):
        self.url = url
        self.secret = secret

    async def sync(self, store: Store, day: date) -> None:
        payload = {"secret": self.secret, **snapshot(store, day)}
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                r = await client.post(self.url, json=payload)
            if r.status_code != 200 or not r.json().get("ok"):
                log.warning("sheet sync failed: %s %s", r.status_code, r.text[:200])
        except Exception as e:  # never let the sheet break logging
            log.warning("sheet sync error: %s", e)
