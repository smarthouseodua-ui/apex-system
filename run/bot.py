import os, sys, logging, sqlite3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv("/root/apex-system/.env")
sys.path.insert(0, "/root/apex-system")

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("bot")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

KB = ReplyKeyboardMarkup([
    [KeyboardButton("⚡ ВАУ+"),        KeyboardButton("📊 Статус")],
    [KeyboardButton("🟢 Старт"),       KeyboardButton("🟡 Стоп сканера")],
    [KeyboardButton("📍 Позиции"),     KeyboardButton("🗂 Сделки")],
    [KeyboardButton("🟠 Закрыть всё"), KeyboardButton("🔴 PANIC")],
], resize_keyboard=True)

DB = "/root/apex-system/storage/db/sqlite/apex.db"

def db_query(sql, params=()):
    try:
        conn = sqlite3.connect(DB)
        r = conn.execute(sql, params).fetchone()[0]
        conn.close()
        return r or 0
    except:
        return 0

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    logger.info(f"/start from user_id={uid}")
    if uid != CHAT_ID:
        await update.message.reply_text("Access denied")
        return
    await update.message.reply_text("APEX PROTOCOL запущен", reply_markup=KB)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    logger.info(f"MSG uid={uid} text={text}")
    if uid != CHAT_ID:
        await update.message.reply_text("Access denied")
        return
    await update.message.reply_text(f"OK: {text}", reply_markup=KB)

def main():
    logger.info(f"Starting bot token={TOKEN[:15]}... chat_id={CHAT_ID}")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()