import asyncio
import logging
import os
from datetime import timedelta
from html import escape

from collections.abc import Awaitable, Callable

from telegram import Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import NetworkError, TelegramError
from telegram.ext import Application, Defaults, CommandHandler, ContextTypes, MessageHandler, filters

from . import goals, render, summary
from .brain import BrainError, ClaudeBrain, writer_prompt
from .config import ROOT, env, load_env
from .core import handle
from .sheets import SheetMirror
from .store import Store, day_of, now

log = logging.getLogger("sarge")

HELP = (
    "🫡 <b>Sarge.</b> Tell me what you eat, or send a photo.\n\n"
    "📸 Photos of labels, packs and plates: I read them and log what you ate. Send several as an album and I read them together.\n"
    "✅ Say \"ate it\" and I log the meal I just showed you.\n"
    "❓ Questions never log anything. Ask away.\n"
    "🎯 Change goals any time: \"new goal: 1500 cal, 100g protein\".\n"
    "💧 \"1L water\" · 👟 \"9200 steps\" · 💊 \"took vit D\"\n\n"
    "/today · /week · /undo · /foods · /goals"
)

IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif")
NOT_AN_IMAGE = "Send it as a normal photo (JPEG or PNG) and I'll take a look."
BROKE = "⚠️ Something broke on that one. Nothing logged. Send it again."
MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters


def chunks(lines: list[str], limit: int = MAX_MESSAGE) -> list[str]:
    """Join lines into messages under the limit, splitting only between lines."""
    out, cur = [], ""
    for line in lines:
        if cur and len(cur) + 1 + len(line) > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return out + [cur] if cur else out


class AlbumBuffer:
    """Collects the messages of one Telegram album (same media_group_id) into a single call."""

    def __init__(self, on_ready: Callable[[list[Message]], Awaitable[None]], delay: float = 2.0):
        self.on_ready = on_ready
        self.delay = delay
        self._groups: dict[str, list[Message]] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._running: set[asyncio.Task] = set()

    async def add(self, msg: Message) -> None:
        gid = msg.media_group_id
        if not gid:
            await self._run([msg])
            return
        self._groups.setdefault(gid, []).append(msg)
        if (old := self._timers.get(gid)) is not None:
            old.cancel()  # each new photo restarts the wait
        task = asyncio.create_task(self._flush(gid))
        self._timers[gid] = task
        self._running.add(task)
        task.add_done_callback(self._running.discard)

    async def flush_all(self) -> None:
        """Handle every album now, waiting ones and in-flight ones, so a text sent right after goes second."""
        for gid in list(self._groups):
            if (msgs := self._groups.pop(gid, None)) is None:
                continue  # its own timer already flushed it while an earlier album was being handled
            if (timer := self._timers.pop(gid, None)) is not None:
                timer.cancel()
            await self._run(msgs)
        await asyncio.gather(*list(self._running), return_exceptions=True)

    async def _flush(self, gid: str) -> None:
        await asyncio.sleep(self.delay)
        msgs = self._groups.pop(gid)  # popped before on_ready, so a late photo starts a new group
        self._timers.pop(gid, None)
        await self._run(msgs)

    async def _run(self, msgs: list[Message]) -> None:
        try:
            await self.on_ready(msgs)
        except Exception:
            log.exception("photo handler failed")


class Sarge:
    def __init__(self, store: Store, brain: ClaudeBrain, sheet: SheetMirror | None = None):
        self.store = store
        self.brain = brain
        self.sheet = sheet
        self.lock = asyncio.Lock()  # one message at a time: log order stays sane
        self._bg: set[asyncio.Task] = set()
        self.albums = AlbumBuffer(self.photos)

    def mirror(self) -> None:
        """Push today's snapshot to the sheet without delaying the reply."""
        if self.sheet is None:
            return
        task = asyncio.create_task(self.sheet.sync(self.store, day_of(now())))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def is_owner(self, update: Update) -> bool:
        owner = self.store.get("owner_id")
        user = update.effective_user
        if owner is not None and user is not None and str(user.id) == owner:
            return True
        log.info("ignoring update from user %s (owner is %s)", user.id if user else None, owner)
        return False

    def message(self, update: Update) -> Message | None:
        """The owner's new message. None for anyone else, and for edits (update.message is None then)."""
        if update.message is None or not self.is_owner(update):
            return None
        return update.message

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        if self.store.get("owner_id") is None:
            self.store.set("owner_id", str(update.effective_user.id))
            self.store.set("chat_id", str(update.effective_chat.id))
            log.info("claimed by user %s", update.effective_user.id)
        if (msg := self.message(update)) is None:
            return
        await msg.reply_text(HELP)

    async def today(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        day = day_of(now())
        await msg.reply_text(render.day_view(self.store.day_entries(day), self.store.totals(day), self.store.goals(day)))

    async def week(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        today = day_of(now())
        lines = [f"{'':7} {'kcal':>5} {'prot':>5}"]
        for back in range(6, -1, -1):
            d = today - timedelta(days=back)
            t = self.store.totals(d)
            if t["entries"] == 0:
                lines.append(f"{d:%a %d}     —")
                continue
            ok = self.store.day_ok(d)
            lines.append(f"{d:%a %d} {t['kcal']:>5.0f} {t['protein']:>4.0f}g {'ok' if ok else 'X'}")
        await msg.reply_text("📅 <b>Last 7 days</b>\n<pre>" + escape("\n".join(lines)) + "</pre>")

    async def undo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        day = day_of(now())
        entry_id = self.store.last_entry_id(day)
        if entry_id is None:
            await msg.reply_text("Nothing to undo today.")
            return
        self.store.delete_entry(entry_id)
        self.mirror()
        await msg.reply_text(f"🗑 <b>Deleted your last entry</b>\n{render.left_line(self.store.totals(day), self.store.goals(day))}")

    async def foods(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        lines = []
        for f in self.store.foods():
            variant = " ".join(x for x in (f["brand"], f["variant"]) if x)
            lines.append(
                f"📌 <b>{escape(f['name'])}</b>" + (f" · {escape(variant)}" if variant else "")
                + (" ⭐" if f["is_default"] else "")
                + f": {escape(f['serving_desc'])} = {f['kcal']:g} cal · {f['protein']:g}g P"
            )
        for part in chunks(lines) or ["No saved foods yet. Send a photo of a label and I'll keep it."]:
            await msg.reply_text(part)

    async def goals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        g = self.store.goals(day_of(now()))
        await msg.reply_text(f"🎯 {goals.describe(g)}\n🌙 Summary at {g['summary_time']}")

    async def text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is None:
            return
        handled = False
        try:
            await self.albums.flush_all()  # an album sent just before this text is handled first (outside the lock: photos() takes it)
            await update.effective_chat.send_action(ChatAction.TYPING)
            async with self.lock:
                reply = await handle(self.store, self.brain, msg.text, [], now())
            handled = True
        except BrainError as e:
            log.warning("brain failed: %s", e)
            reply = "⚠️ Brain failed on that one. Nothing logged. Send it again."
        except Exception:
            log.exception("text handling crashed")
            reply = BROKE
        try:
            await msg.reply_text(reply)
        except Exception:
            log.exception("could not deliver the text reply")
        if handled:
            self.mirror()

    async def photo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if (msg := self.message(update)) is not None:  # checked per message, before buffering
            await self.albums.add(msg)

    async def _download(self, msg: Message) -> tuple[bytes, str] | None:
        if msg.photo:
            file, media_type = await msg.photo[-1].get_file(), "image/jpeg"  # largest size
        elif msg.document and msg.document.mime_type in IMAGE_TYPES:
            file, media_type = await msg.document.get_file(), msg.document.mime_type
        else:
            return None
        return bytes(await file.download_as_bytearray()), media_type

    async def photos(self, msgs: list[Message]) -> None:
        """One photo or a whole album: one brain call, one status message edited into the reply."""
        first = msgs[0]
        status = await first.reply_text("📸 Reading your photos…")
        images = []
        for m in msgs:
            try:
                if (img := await self._download(m)) is not None:
                    images.append(img)
            except TelegramError as e:
                log.warning("photo download failed: %s", e)
        caption = next((m.caption for m in msgs if m.caption), "")
        logged = False
        if not images:
            reply = NOT_AN_IMAGE
        else:
            async with self.lock:
                try:
                    reply = await handle(self.store, self.brain, caption, images, now())
                    logged = True
                except BrainError as e:
                    log.warning("brain failed on photos: %s", e)
                    reply = "⚠️ Couldn't read that. Nothing logged. Send it again."
                except Exception:
                    log.exception("photo handling crashed")
                    reply = BROKE
            if logged and len(images) < len(msgs):
                reply += f"\n\n⚠️ Read {len(images)} of {len(msgs)} photos."
        try:
            try:
                await status.edit_text(reply)
            except NetworkError:  # too long, unchanged (BadRequest), or a timeout
                await first.reply_text(reply)
        except Exception:
            log.exception("could not deliver the photo reply")
        if logged:
            self.mirror()

    async def tick(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = self.store.get("chat_id")
        if chat_id is None:
            return
        async with self.lock:
            s = summary.due(self.store, now())
            g = self.store.goals(day_of(now()))
        if s is None:
            return
        try:
            text = await self.brain.write(s.brief, writer_prompt(g))
        except BrainError as e:
            log.warning("night summary: brain failed, using fallback: %s", e)
            text = None
        await ctx.bot.send_message(chat_id=int(chat_id), text=s.compose(text))
        log.info("sent night summary")


def main() -> None:
    load_env()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    db_path = env("SARGE_DB", str(ROOT / "data" / "sarge.db"))
    (ROOT / "data").mkdir(exist_ok=True)
    store = Store(db_path)
    owner_id = os.environ.get("OWNER_ID")
    if owner_id:  # private chat id == user id
        store.set("owner_id", owner_id)
        store.set("chat_id", owner_id)
    sheet_url = os.environ.get("SHEET_WEBHOOK_URL")
    sheet = SheetMirror(sheet_url, env("SHEET_SECRET")) if sheet_url else None
    sarge = Sarge(store, ClaudeBrain(env("CLAUDE_BIN"), env("CLAUDE_MODEL", "sonnet"), env("CLAUDE_PHOTO_MODEL", "opus")), sheet)

    app = Application.builder().token(env("TELEGRAM_TOKEN")).defaults(Defaults(parse_mode=ParseMode.HTML)).build()
    app.add_handler(CommandHandler(["start", "help"], sarge.start))
    app.add_handler(CommandHandler("today", sarge.today))
    app.add_handler(CommandHandler("week", sarge.week))
    app.add_handler(CommandHandler("undo", sarge.undo))
    app.add_handler(CommandHandler("foods", sarge.foods))
    app.add_handler(CommandHandler("goals", sarge.goals))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sarge.text))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, sarge.photo))
    app.job_queue.run_repeating(sarge.tick, interval=60, first=15)
    log.info("Sarge up")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
