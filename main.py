import logging
import os
from typing import Optional, Set

from dotenv import load_dotenv
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_support_bot")


def parse_admin_ids(raw_ids: Optional[str]) -> Set[int]:
    ids: Set[int] = set()
    if not raw_ids:
        return ids

    for chunk in raw_ids.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ValueError(f"ADMIN_IDS contains non-numeric value: {chunk!r}") from exc

    return ids


def message_kind(message) -> str:
    if message.text:
        return "text"
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.document:
        return "document"
    if message.voice:
        return "voice"
    if message.audio:
        return "audio"
    if message.sticker:
        return "sticker"
    return "other"


def message_preview(message) -> str:
    if message.text:
        return message.text[:900]
    if message.caption:
        return message.caption[:900]
    return "(no text)"


def build_header(update: Update) -> str:
    user = update.effective_user
    message = update.effective_message

    username = f"@{user.username}" if user and user.username else "-"
    full_name = user.full_name if user else "Unknown"
    user_id = user.id if user else "Unknown"
    kind = message_kind(message)
    preview = message_preview(message)

    return (
        "Нове повідомлення для модераторів\n"
        f"ID користувача: {user_id}\n"
        f"Ім'я: {full_name}\n"
        f"Username: {username}\n"
        f"Тип: {kind}\n\n"
        f"Текст/підпис:\n{preview}"
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    welcome_text = context.bot_data["welcome_text"]
    if update.effective_message:
        await update.effective_message.reply_text(welcome_text)


async def myid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user and update.effective_message:
        await update.effective_message.reply_text(f"Your Telegram ID: {update.effective_user.id}")


async def send_to_admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    admin_ids = context.bot_data["admin_ids"]
    if not admin_ids:
        logger.error("ADMIN_IDS is empty, moderators will not receive messages")
        return

    header = build_header(update)

    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=header)
            await context.bot.forward_message(
                chat_id=admin_id,
                from_chat_id=message.chat_id,
                message_id=message.message_id,
            )
        except TelegramError:
            logger.exception("Failed to forward message to admin_id=%s", admin_id)
            try:
                await context.bot.copy_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id,
                )
            except TelegramError:
                logger.exception("Failed to copy message to admin_id=%s", admin_id)


async def inbound_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return

    await send_to_admins(update, context)

    ack_text = context.bot_data["ack_text"]
    await update.effective_message.reply_text(ack_text)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)


def main() -> None:
    load_dotenv()

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env")

    admin_ids = parse_admin_ids(os.getenv("ADMIN_IDS"))
    if not admin_ids:
        raise RuntimeError("ADMIN_IDS is missing. Add at least one Telegram user ID")

    welcome_text = os.getenv(
        "WELCOME_TEXT",
        "Привіт! Надішліть текст, фото або відео, і я передам це модераторам.",
    )
    ack_text = os.getenv(
        "ACK_TEXT",
        "Дякуємо. Ваше повідомлення надіслано модераторам.",
    )

    app = Application.builder().token(token).build()
    app.bot_data["admin_ids"] = admin_ids
    app.bot_data["welcome_text"] = welcome_text
    app.bot_data["ack_text"] = ack_text

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("myid", myid_handler))
    app.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, inbound_handler)
    )
    app.add_error_handler(error_handler)

    logger.info("Bot started with %s admin(s)", len(admin_ids))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
