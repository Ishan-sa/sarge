import asyncio
import logging
import os
from datetime import timedelta
from html import escape

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, Defaults, CommandHandler, ContextTypes, MessageHandler, filters

from . import reminders, render
from .brain import BrainError, ClaudeBrain
from .config import ROOT, TARGET_KCAL, TARGET_PROTEIN, env, load_env
from .core import handle_text
from .store import Store, day_of, now

log = logging.getLogger("sarge")

HELP = (
    "🫡 <b>Sarge.</b> Tell me everything you eat, with quantities.\n\n"
    "💧 \"1L water\" · 👟 \"9200 steps\" · 💊 \"took vit D\"\n"
    "📌 Give label values once and I remember them.\n\n"
    "/today · /week · /undo · /foods"
)


class Sarge:
    def __init__(self, store: Store, brain: ClaudeBrain):
        self.store = store
        self.brain = brain
        self.lock = asyncio.Lock()  # one message at a time: log order stays sane

    def is_owner(self, update: Update) -> bool:
        owner = self.store.get("owner_id")
        user = update.effective_user
        if owner is not None and user is not None and str(user.id) == owner:
            return True
        log.info("ignoring update from user %s (owner is %s)", user.id if user else None, owner)
        return False

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if self.store.get("owner_id") is None:
            self.store.set("owner_id", str(update.effective_user.id))
            self.store.set("chat_id", str(update.effective_chat.id))
            log.info("claimed by user %s", update.effective_user.id)
        if not self.is_owner(update):
            return
        await update.message.reply_text(HELP)

    async def today(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_owner(update):
            return
        day = day_of(now())
        await update.message.reply_text(render.day_view(self.store.day_entries(day), self.store.totals(day)))

    async def week(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_owner(update):
            return
        today = day_of(now())
        lines = [f"{'':7} {'kcal':>5} {'prot':>5}"]
        for back in range(6, -1, -1):
            d = today - timedelta(days=back)
            t = self.store.totals(d)
            if t["entries"] == 0:
                lines.append(f"{d:%a %d}     —")
                continue
            ok = t["kcal"] <= TARGET_KCAL + 100 and t["protein"] >= TARGET_PROTEIN - 10
            lines.append(f"{d:%a %d} {t['kcal']:>5.0f} {t['protein']:>4.0f}g {'ok' if ok else 'X'}")
        await update.message.reply_text("📅 <b>Last 7 days</b>\n<pre>" + escape("\n".join(lines)) + "</pre>")

    async def undo(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_owner(update):
            return
        day = day_of(now())
        entry_id = self.store.last_entry_id(day)
        if entry_id is None:
            await update.message.reply_text("Nothing to undo today.")
            return
        self.store.delete_entry(entry_id)
        await update.message.reply_text(f"🗑 <b>Deleted your last entry</b>\n{render.left_line(self.store.totals(day))}")

    async def foods(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_owner(update):
            return
        rows = self.store.foods()
        text = "\n".join(
            f"📌 <b>{escape(f['name'])}</b>: {f['kcal']:.0f} kcal, {f['protein']:.0f}g protein\n     <i>{escape(f['description'])}</i>"
            for f in rows
        )
        await update.message.reply_text(text or "No saved foods yet. Give me label values and I'll keep them.")

    async def text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not self.is_owner(update):
            return
        await update.effective_chat.send_action(ChatAction.TYPING)
        async with self.lock:
            try:
                reply = await handle_text(self.store, self.brain, update.message.text, now())
            except BrainError as e:
                log.warning("brain failed: %s", e)
                reply = "⚠️ Brain failed on that one. Nothing logged. Send it again."
        await update.message.reply_text(reply)

    async def tick(self, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = self.store.get("chat_id")
        if chat_id is None:
            return
        async with self.lock:
            due = reminders.due(self.store, now())
        for r in due:
            try:
                text = await self.brain.write(r.brief)
            except BrainError as e:
                log.warning("reminder %s: brain failed, using fallback: %s", r.kind, e)
                text = None
            await ctx.bot.send_message(chat_id=int(chat_id), text=r.compose(text))
            log.info("sent %s reminder", r.kind)


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
    sarge = Sarge(store, ClaudeBrain(env("CLAUDE_BIN"), env("CLAUDE_MODEL", "sonnet")))

    app = Application.builder().token(env("TELEGRAM_TOKEN")).defaults(Defaults(parse_mode=ParseMode.HTML)).build()
    app.add_handler(CommandHandler(["start", "help"], sarge.start))
    app.add_handler(CommandHandler("today", sarge.today))
    app.add_handler(CommandHandler("week", sarge.week))
    app.add_handler(CommandHandler("undo", sarge.undo))
    app.add_handler(CommandHandler("foods", sarge.foods))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, sarge.text))
    app.job_queue.run_repeating(sarge.tick, interval=60, first=15)
    log.info("Sarge up")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
