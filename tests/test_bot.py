import asyncio
from types import SimpleNamespace

from telegram.error import BadRequest, TimedOut

from sarge import bot, summary
from sarge.bot import AlbumBuffer, Sarge
from sarge.brain import BrainError
from sarge.store import day_of
from tests.conftest import TORTILLA, at


class FakeStatus:
    def __init__(self, fail=False):
        self.fail, self.edits = fail, []

    async def edit_text(self, text):
        if self.fail:
            raise BadRequest("Message is not modified")
        self.edits.append(text)


class FakeFile:
    def __init__(self, data):
        self.data = data

    async def download_as_bytearray(self):
        return bytearray(self.data)


class FakeSize:
    def __init__(self, data):
        self.data = data

    async def get_file(self):
        return FakeFile(self.data)


class FakeDoc(FakeSize):
    def __init__(self, data, mime_type):
        super().__init__(data)
        self.mime_type = mime_type


class FakeMsg:
    def __init__(self, data=b"", gid=None, caption=None, doc=None, status=None):
        self.media_group_id, self.caption, self.document = gid, caption, doc
        self.photo = [FakeSize(b"small"), FakeSize(data)] if data else []
        self.status = status or FakeStatus()
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)
        return self.status


def sarge_with(store, brain=None):
    return Sarge(store, brain)


def run_handle(monkeypatch, result="REPLY"):
    calls = []

    async def fake_handle(store, brain, text, images, ts):
        calls.append((text, images))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(bot, "handle", fake_handle)
    return calls


# --- AlbumBuffer ---

def test_album_grouped_once_caption_from_any_photo():
    async def go():
        got = []

        async def record(msgs):
            got.append(msgs)

        buf = AlbumBuffer(record, delay=0.01)
        m1, m2, s = FakeMsg(gid="A"), FakeMsg(gid="A", caption="1 tbsp"), FakeMsg()
        await buf.add(m1)
        await buf.add(m2)
        await buf.add(s)
        await asyncio.sleep(0.1)
        return got, m1, m2, s

    got, m1, m2, s = asyncio.run(go())
    assert got == [[s], [m1, m2]]


def test_two_albums_back_to_back_stay_separate():
    async def go():
        got = []

        async def record(msgs):
            got.append(msgs)

        buf = AlbumBuffer(record, delay=0.01)
        a1, b1, a2, b2 = FakeMsg(gid="A"), FakeMsg(gid="B"), FakeMsg(gid="A"), FakeMsg(gid="B")
        for m in (a1, b1, a2, b2):
            await buf.add(m)
        await asyncio.sleep(0.1)
        return got, (a1, a2, b1, b2)

    got, (a1, a2, b1, b2) = asyncio.run(go())
    assert sorted(got, key=lambda g: g[0].media_group_id) == [[a1, a2], [b1, b2]]


def test_album_timer_restarts_on_each_photo():
    async def go():
        got = []

        async def record(msgs):
            got.append(len(msgs))

        buf = AlbumBuffer(record, delay=0.05)
        for _ in range(3):
            await buf.add(FakeMsg(gid="A"))
            await asyncio.sleep(0.03)  # always under the delay: never flushes early
        assert got == []
        await asyncio.sleep(0.15)
        return got

    assert asyncio.run(go()) == [3]


def test_on_ready_raising_is_logged_and_later_albums_still_flush(caplog):
    async def go():
        got = []

        async def on_ready(msgs):
            got.append(msgs)
            if len(got) == 1:
                raise RuntimeError("boom")

        buf = AlbumBuffer(on_ready, delay=0.01)
        await buf.add(FakeMsg())  # ungrouped, inline: must not raise
        await buf.add(FakeMsg(gid="A"))
        await asyncio.sleep(0.1)
        return got

    assert len(asyncio.run(go())) == 2
    assert "photo handler failed" in caplog.text


def test_grouped_on_ready_raising_is_logged_and_next_group_flushes(caplog):
    async def go():
        got = []

        async def on_ready(msgs):
            got.append(msgs)
            if len(got) == 1:
                raise RuntimeError("boom")

        buf = AlbumBuffer(on_ready, delay=0.01)
        await buf.add(FakeMsg(gid="A"))
        await asyncio.sleep(0.05)
        await buf.add(FakeMsg(gid="B"))
        await asyncio.sleep(0.05)
        return got

    assert len(asyncio.run(go())) == 2
    assert "photo handler failed" in caplog.text


def test_late_photo_during_handler_starts_second_group_without_cancelling():
    async def go():
        got, started, release = [], asyncio.Event(), asyncio.Event()

        async def on_ready(msgs):
            got.append(list(msgs))
            started.set()
            await release.wait()

        buf = AlbumBuffer(on_ready, delay=0.01)
        m1, m2 = FakeMsg(gid="A"), FakeMsg(gid="A")
        await buf.add(m1)
        await started.wait()
        await buf.add(m2)  # first handler still in flight
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.sleep(0.05)
        return got, m1, m2

    got, m1, m2 = asyncio.run(go())
    assert got == [[m1], [m2]]


def test_photo_handler_ignores_non_owner(store):
    async def go():
        s = Sarge(store, None)
        s.albums = AlbumBuffer(lambda msgs: (_ for _ in ()).throw(AssertionError("buffered")), delay=0.01)
        store.set("owner_id", "1")
        msg = FakeMsg(b"x", gid="A")
        await s.photo(SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=2)), None)
        assert s.albums._groups == {} and msg.replies == []

    asyncio.run(go())


def test_end_to_end_album_through_buffer_one_call_one_status(store, monkeypatch):
    calls = run_handle(monkeypatch)

    async def go():
        s = Sarge(store, None)
        s.albums.delay = 0.01
        store.set("owner_id", "1")
        msgs = [FakeMsg(b"a", gid="A"), FakeMsg(b"b", gid="A"), FakeMsg(b"c", gid="A")]
        for m in msgs:
            await s.photo(SimpleNamespace(message=m, effective_user=SimpleNamespace(id=1)), None)
        await asyncio.sleep(0.1)
        return msgs

    msgs = asyncio.run(go())
    assert len(calls) == 1 and len(calls[0][1]) == 3
    assert msgs[0].replies == ["📸 Reading your photos…"] and msgs[1].replies == msgs[2].replies == []
    assert msgs[0].status.edits == ["REPLY"]


# --- Sarge.photos ---

def test_photos_one_call_for_album_with_status_edit(store, monkeypatch):
    calls = run_handle(monkeypatch)
    m1, m2 = FakeMsg(b"one", gid="A"), FakeMsg(b"two", gid="A", caption="1 tbsp")
    asyncio.run(sarge_with(store).photos([m1, m2]))
    assert calls == [("1 tbsp", [(b"one", "image/jpeg"), (b"two", "image/jpeg")])]
    assert m1.replies == ["📸 Reading your photos…"] and m2.replies == []
    assert m1.status.edits == ["REPLY"]


def test_photos_skips_non_image_document(store, monkeypatch):
    calls = run_handle(monkeypatch)
    m1, m2 = FakeMsg(b"one", gid="A"), FakeMsg(gid="A", doc=FakeDoc(b"%PDF", "application/pdf"))
    asyncio.run(sarge_with(store).photos([m1, m2]))
    assert calls == [("", [(b"one", "image/jpeg")])]


def test_photos_image_document_uses_its_mime(store, monkeypatch):
    calls = run_handle(monkeypatch)
    asyncio.run(sarge_with(store).photos([FakeMsg(doc=FakeDoc(b"png", "image/png"))]))
    assert calls[0][1] == [(b"png", "image/png")]


def test_photos_no_valid_images_edits_status_without_brain(store, monkeypatch):
    calls = run_handle(monkeypatch)
    m = FakeMsg(doc=FakeDoc(b"%PDF", "application/pdf"))
    asyncio.run(sarge_with(store).photos([m]))
    assert calls == []
    assert m.status.edits == [bot.NOT_AN_IMAGE]


def test_photos_brain_error_edits_status(store, monkeypatch):
    run_handle(monkeypatch, BrainError("boom"))
    m = FakeMsg(b"x")
    asyncio.run(sarge_with(store).photos([m]))
    assert m.status.edits == ["⚠️ Couldn't read that. Nothing logged. Send it again."]


def test_photos_edit_bad_request_falls_back_to_reply(store, monkeypatch):
    run_handle(monkeypatch, "LONG")
    m = FakeMsg(b"x", status=FakeStatus(fail=True))
    asyncio.run(sarge_with(store).photos([m]))
    assert m.replies == ["📸 Reading your photos…", "LONG"]


# --- commands ---

def command(store):
    msg = FakeMsg()
    update = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=1))
    store.set("owner_id", "1")
    return update, msg


def test_goals_command(store):
    update, msg = command(store)
    store.set("summary_time", "23:00")
    asyncio.run(Sarge(store, None).goals(update, None))
    assert msg.replies == ["🎯 1,800 cal · 130g protein · 3L water · 8k steps\n🌙 Summary at 23:00"]


def test_foods_command_one_line_per_product_with_default_star(store):
    update, msg = command(store)
    store.save_food({**TORTILLA, "make_default": True})
    store.save_food({**TORTILLA, "brand": "other", "variant": "spicy", "kcal": 160})
    asyncio.run(Sarge(store, None).foods(update, None))
    lines = msg.replies[0].split("\n")
    assert lines == [
        "📌 <b>protein tortilla</b> · acme ⭐: 1 tortilla (55 g) = 150 cal · 13g P",
        "📌 <b>protein tortilla</b> · other spicy: 1 tortilla (55 g) = 160 cal · 13g P",
    ]


# --- tick ---

class WriterBrain:
    def __init__(self, result):
        self.result, self.briefs = result, []

    async def write(self, brief, system):
        self.briefs.append(brief)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def tick(store, brain, when, monkeypatch):
    monkeypatch.setattr(bot, "now", lambda: when)
    sent = []

    async def send_message(chat_id, text):
        sent.append((chat_id, text))

    ctx = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
    asyncio.run(Sarge(store, brain).tick(ctx))
    return sent


def test_tick_sends_composed_brain_text(store, monkeypatch):
    store.set("chat_id", "42")
    brain = WriterBrain("Solid day.")
    sent = tick(store, brain, at(22, 5), monkeypatch)
    assert sent == [(42, summary.build(store, at(22, 5)).compose("Solid day."))]
    assert len(brain.briefs) == 1


def test_tick_falls_back_when_brain_fails(store, monkeypatch):
    store.set("chat_id", "42")
    sent = tick(store, WriterBrain(BrainError("down")), at(22, 5), monkeypatch)
    assert sent == [(42, summary.build(store, at(22, 5)).compose(None))]


def test_tick_returns_early_without_chat_id(store, monkeypatch):
    brain = WriterBrain("x")
    assert tick(store, brain, at(22, 5), monkeypatch) == []
    assert brain.briefs == [] and store.get("wrap_day") is None


def test_tick_not_due_before_summary_time(store, monkeypatch):
    store.set("chat_id", "42")
    assert tick(store, WriterBrain("x"), at(21, 59), monkeypatch) == []


def test_summary_time_moved_later_after_firing_does_not_resend(store, monkeypatch):
    store.set("chat_id", "42")
    assert len(tick(store, WriterBrain("x"), at(22, 0), monkeypatch)) == 1
    store.set("summary_time", "23:00")
    assert tick(store, WriterBrain("x"), at(22, 30), monkeypatch) == []
    assert tick(store, WriterBrain("x"), at(23, 0), monkeypatch) == []


def test_summary_time_moved_earlier_fires_once(store, monkeypatch):
    store.set("chat_id", "42")
    store.set("summary_time", "23:00")
    assert tick(store, WriterBrain("x"), at(22, 0), monkeypatch) == []
    store.set("summary_time", "21:00")
    assert len(tick(store, WriterBrain("x"), at(22, 0), monkeypatch)) == 1
    assert tick(store, WriterBrain("x"), at(22, 1), monkeypatch) == []
    assert store.get("wrap_day") == day_of(at(22, 0)).isoformat()


def test_photos_unexpected_exception_edits_status_and_does_not_mirror(store, monkeypatch):
    run_handle(monkeypatch, RuntimeError("db"))
    s = Sarge(store, None)
    mirrored = []
    s.mirror = lambda: mirrored.append(1)
    m = FakeMsg(b"x")
    asyncio.run(s.photos([m]))
    assert m.status.edits == ["⚠️ Something broke on that one. Nothing logged. Send it again."]
    assert mirrored == []


def test_photos_telegram_failure_on_delivery_is_swallowed(store, monkeypatch):
    run_handle(monkeypatch)

    class Broken(FakeStatus):
        async def edit_text(self, text):
            raise ConnectionError("net")

    asyncio.run(sarge_with(store).photos([FakeMsg(b"x", status=Broken())]))


def test_photos_partial_read_appends_count(store, monkeypatch):
    run_handle(monkeypatch)
    m1, m2 = FakeMsg(b"one", gid="A"), FakeMsg(gid="A", doc=FakeDoc(b"%PDF", "application/pdf"))
    asyncio.run(sarge_with(store).photos([m1, m2]))
    assert m1.status.edits == ["REPLY\n\n⚠️ Read 1 of 2 photos."]


# --- text, edited messages, /foods chunks, albums before text ---

class FakeChat:
    async def send_action(self, action):
        pass


def text_update(text, owner=1):
    msg = FakeMsg()
    msg.text = text
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=owner), effective_chat=FakeChat()), msg


def test_text_unexpected_exception_replies_and_logs(store, monkeypatch, caplog):
    run_handle(monkeypatch, RuntimeError("db"))
    store.set("owner_id", "1")
    update, msg = text_update("2 eggs")
    asyncio.run(Sarge(store, None).text(update, None))
    assert msg.replies == ["⚠️ Something broke on that one. Nothing logged. Send it again."]
    assert "text handling crashed" in caplog.text


def test_text_reply_failure_is_swallowed(store, monkeypatch, caplog):
    run_handle(monkeypatch)
    store.set("owner_id", "1")
    update, msg = text_update("2 eggs")

    async def broken(text):
        raise ConnectionError("net")

    msg.reply_text = broken
    asyncio.run(Sarge(store, None).text(update, None))
    assert "could not deliver the text reply" in caplog.text


def test_text_while_second_album_timer_fires_during_first_flush(store, monkeypatch):
    calls = run_handle(monkeypatch)
    store.set("owner_id", "1")
    update, msg = text_update("2 eggs")
    got = []

    async def on_ready(msgs):
        got.append(msgs[0].media_group_id)
        if msgs[0].media_group_id == "A":
            await asyncio.sleep(0.15)  # B's own timer fires while A is being handled

    async def go():
        s = Sarge(store, None)
        s.albums = AlbumBuffer(on_ready, delay=0.05)
        await s.albums.add(FakeMsg(gid="A"))
        await s.albums.add(FakeMsg(gid="B"))
        await s.text(update, None)

    asyncio.run(go())
    assert sorted(got) == ["A", "B"]
    assert len(calls) == 1 and msg.replies == ["REPLY"]


def test_edited_messages_are_ignored(store, monkeypatch):
    calls = run_handle(monkeypatch)
    store.set("owner_id", "1")
    s = Sarge(store, None)
    update = SimpleNamespace(message=None, edited_message=FakeMsg(), effective_user=SimpleNamespace(id=1),
                             effective_chat=FakeChat())
    for handler in (s.start, s.today, s.week, s.undo, s.foods, s.goals, s.text, s.photo):
        asyncio.run(handler(update, None))
    assert calls == [] and update.edited_message.replies == []


def test_foods_command_splits_long_lists(store):
    update, msg = command(store)
    for i in range(80):
        store.save_food({**TORTILLA, "name": f"protein tortilla number {i:02d}", "serving_desc": "1 tortilla, large (55 g)"})
    asyncio.run(Sarge(store, None).foods(update, None))
    assert len(msg.replies) > 1 and all(len(r) < 4000 for r in msg.replies)
    lines = "\n".join(msg.replies).split("\n")
    assert len(lines) == 80 and lines[0].startswith("📌 <b>protein tortilla number 00</b>")


def test_text_waits_for_a_pending_album(store, monkeypatch):
    calls = run_handle(monkeypatch)

    async def go():
        s = Sarge(store, None)
        s.albums.delay = 10  # the album timer would fire long after the text
        store.set("owner_id", "1")
        await s.photo(SimpleNamespace(message=FakeMsg(b"a", gid="A"), effective_user=SimpleNamespace(id=1)), None)
        update, msg = text_update("ate it")
        await s.text(update, None)
        return s, msg

    s, msg = asyncio.run(go())
    assert calls == [("", [(b"a", "image/jpeg")]), ("ate it", [])]
    assert msg.replies == ["REPLY"] and s.albums._groups == {} and s.albums._timers == {}


def test_photos_edit_timeout_falls_back_to_reply(store, monkeypatch):
    run_handle(monkeypatch, "DONE")

    class Slow(FakeStatus):
        async def edit_text(self, text):
            raise TimedOut()

    m = FakeMsg(b"x", status=Slow())
    asyncio.run(sarge_with(store).photos([m]))
    assert m.replies == ["📸 Reading your photos…", "DONE"]
