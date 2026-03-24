import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from services.telegram.handlers import start, handle_text


def create_app():
    token = os.getenv("APPS_SYSTEM_BOT_TOKEN")

    if not token:
        raise ValueError("APPS_SYSTEM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
