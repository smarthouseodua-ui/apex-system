import os, sys, sqlite3, logging
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
        r = conn.execute(sql, params).fetchone()
        conn.close()
        return r[0] if r else 0
    except:
        return 0

def db_rows(sql, params=()):
    try:
        conn = sqlite3.connect(DB)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return rows
    except:
        return []

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != CHAT_ID:
        await update.message.reply_text("Access denied")
        return
    await update.message.reply_text("⚡ APEX PROTOCOL™ активен", reply_markup=KB)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    if uid != CHAT_ID:
        await update.message.reply_text("Access denied")
        return

    if text == "⚡ ВАУ+":
        await update.message.reply_text("⚡ APEX PROTOCOL™\nСистема работает. Всё под контролем.", reply_markup=KB)

    elif text == "📊 Статус":
        total = db_query("SELECT COUNT(*) FROM trades") or 0
        open_pos = db_query("SELECT COUNT(*) FROM positions WHERE status='open'") or 0
        msg = (
            f"📊 *Статус системы*\n"
            f"├ Сделок всего: {total}\n"
            f"└ Открытых позиций: {open_pos}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KB)

    elif text == "🟢 Старт":
        await update.message.reply_text("🟢 Команда Старт получена.\n(Pipeline запуск — в разработке)", reply_markup=KB)

    elif text == "🟡 Стоп сканера":
        await update.message.reply_text("🟡 Команда Стоп сканера получена.\n(В разработке)", reply_markup=KB)

    elif text == "📍 Позиции":
        rows = db_rows("SELECT symbol, side, entry_price, qty FROM positions WHERE status='open' LIMIT 10")
        if not rows:
            msg = "📍 *Открытых позиций нет*"
        else:
            lines = ["📍 *Открытые позиции:*"]
            for r in rows:
                lines.append(f"• {r[0]} | {r[1]} | вход: {r[2]} | qty: {r[3]}")
            msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KB)

    elif text == "🗂 Сделки":
        rows = db_rows("SELECT symbol, side, pnl, closed_at FROM trades ORDER BY closed_at DESC LIMIT 10")
        if not rows:
            msg = "🗂 *Сделок пока нет*"
        else:
            lines = ["🗂 *Последние сделки:*"]
            for r in rows:
                pnl = r[2] or 0
                sign = "🟢" if pnl >= 0 else "🔴"
                lines.append(f"{sign} {r[0]} | {r[1]} | PnL: {pnl:.2f}")
            msg = "\n".join(lines)
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KB)

    elif text == "🟠 Закрыть всё":
        await update.message.reply_text("🟠 Команда получена. Закрытие всех позиций — в разработке.", reply_markup=KB)

    elif text == "🔴 PANIC":
        await update.message.reply_text("🔴 PANIC нажат.\nЭкстренное закрытие — в разработке.", reply_markup=KB)

    else:
        await update.message.reply_text(f"Неизвестная команда: {text}", reply_markup=KB)

def main():
    logger.info(f"Starting bot token={TOKEN[:15]}... chat_id={CHAT_ID}")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == "__main__":
    main()
