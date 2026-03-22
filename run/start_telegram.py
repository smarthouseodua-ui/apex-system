import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv("/root/apex-system/.env")

TOKEN = os.getenv("APPS_SYSTEM_BOT_TOKEN")
CHAT_ID = int(os.getenv("APPS_SYSTEM_BOT_CHAT_ID", "0"))

if not TOKEN:
    raise ValueError("APPS_SYSTEM_BOT_TOKEN not set")


KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("⚡ ВАУ+"), KeyboardButton("📊 Статус")],
        [KeyboardButton("🟢 Старт"), KeyboardButton("🟡 Стоп")],
        [KeyboardButton("📍 Позиции"), KeyboardButton("🗂 Сделки")],
        [KeyboardButton("🟠 Закрыть всё"), KeyboardButton("🔴 PANIC")],
    ],
    resize_keyboard=True,
)


def is_allowed(update: Update) -> bool:
    user = update.effective_user
    return bool(user and user.id == CHAT_ID)


async def deny(update: Update) -> None:
    if update.message:
        await update.message.reply_text("⛔ Доступ запрещён.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await deny(update)
        return

    await update.message.reply_text(
        "🚀 <b>APPS SYSTEM CONTROL</b>\n\nВыбери действие:",
        reply_markup=KEYBOARD,
        parse_mode="HTML",
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await deny(update)
        return

    text = (update.message.text or "").strip()

    if text == "⚡ ВАУ+":
        reply = (
            "⚡ <b>ВАУ+</b>\n\n"
            "Быстрый ответ работает.\n"
            "Логика будет подключена следующим этапом."
        )

    elif text == "📊 Статус":
        reply = (
            "📊 <b>Статус</b>\n\n"
            "Бот онлайн.\n"
            "PM2-процесс активен.\n"
            "Кнопка отвечает корректно."
        )

    elif text == "🟢 Старт":
        reply = (
            "🟢 <b>Старт</b>\n\n"
            "Команда принята.\n"
            "Пока это тестовая заглушка."
        )

    elif text == "🟡 Стоп":
        reply = (
            "🟡 <b>Стоп</b>\n\n"
            "Команда принята.\n"
            "Пока это тестовая заглушка."
        )

    elif text == "📍 Позиции":
        reply = (
            "📍 <b>Позиции</b>\n\n"
            "Секция отвечает.\n"
            "Подключение реальных позиций будет следующим этапом."
        )

    elif text == "🗂 Сделки":
        reply = (
            "🗂 <b>Сделки</b>\n\n"
            "Секция отвечает.\n"
            "История сделок будет подключена следующим этапом."
        )

    elif text == "🟠 Закрыть всё":
        reply = (
            "🟠 <b>Закрыть всё</b>\n\n"
            "Пока это безопасная заглушка без реального действия."
        )

    elif text == "🔴 PANIC":
        reply = (
            "🔴 <b>PANIC</b>\n\n"
            "Пока это безопасная заглушка без реального действия."
        )

    else:
        reply = (
            "❓ <b>Неизвестная команда</b>\n\n"
            "Используй кнопки на клавиатуре."
        )

    await update.message.reply_text(
        reply,
        reply_markup=KEYBOARD,
        parse_mode="HTML",
    )


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()
