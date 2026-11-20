from sarge.store import Store
from tests.conftest import EGGS, at


def test_draft_accumulates_and_expires(store):
    store.draft_add(at(12), [EGGS[0]], "wrap")
    store.draft_add(at(12, 5), [EGGS[1]], None)
    assert [i["name"] for i in store.draft(at(12, 6))] == ["eggs", "butter"] and store.draft_title() == "wrap"
    assert store.draft(at(18, 6)) == [] and store.draft(at(12, 7)) == []


def test_draft_survives_restart(tmp_path):
    s = Store(tmp_path / "d.db")
    s.draft_add(at(12), [EGGS[0]], "wrap")
    assert len(Store(tmp_path / "d.db").draft(at(12, 1))) == 1


def test_draft_edit_remove_clear(store):
    store.draft_add(at(12), EGGS, "wrap")
    first, second = store.draft(at(12, 1))
    assert store.draft_item(first["id"])["name"] == "eggs" and store.draft_item(999) is None
    assert store.draft_edit(first["id"], {"kcal": 100, "bogus": 1}) and store.draft_item(first["id"])["kcal"] == 100
    assert not store.draft_edit(first["id"], {"bogus": 1}) and not store.draft_edit(999, {"kcal": 1})
    assert store.draft_remove(second["id"]) and not store.draft_remove(second["id"])
    store.draft_clear()
    assert store.draft(at(12, 2)) == [] and store.draft_title() == ""
    assert store.get("draft_ts") is None


def test_draft_title_only_set_when_empty_or_given(store):
    store.draft_add(at(12), [EGGS[0]], None)
    assert store.draft_title() == ""
    store.draft_add(at(12, 1), [EGGS[1]], "wrap")
    assert store.draft_title() == "wrap"
    store.draft_add(at(12, 2), [EGGS[0]], None)
    assert store.draft_title() == "wrap"


def test_draft_add_after_expiry_drops_stale_draft(store):
    store.draft_add(at(12), [EGGS[0]], "wrap")
    store.draft_add(at(20), [EGGS[1]], None)
    assert [i["name"] for i in store.draft(at(20, 1))] == ["butter"] and store.draft_title() == ""
    store.draft_add(at(21), [EGGS[0]], None)
    store.draft_add(at(4, d=23), [EGGS[1]], "fresh")
    assert [i["name"] for i in store.draft(at(4, 1, d=23))] == ["butter"] and store.draft_title() == "fresh"
