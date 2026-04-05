# telegram_bot.py

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from modules.telegram_control import (
    format_status,
    format_positions,
    format_analytics,
    set_mode,
    get_mode
)

TOKEN = "PUT_YOUR_TOKEN_HERE"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("APEX BOT READY")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_status())


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_positions())


async def analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_analytics())


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_mode("STOP")
    await update.message.reply_text("⛔ STOPPED")


async def start_trading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_mode("RUN")
    await update.message.reply_text("✅ RUNNING")


def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("analytics", analytics))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("run", start_trading))

    app.run_polling(poll_interval=60)
