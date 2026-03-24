from telegram import ReplyKeyboardMarkup, KeyboardButton


def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Статус"),   KeyboardButton("⚡ ВАУ+"),     KeyboardButton("📍 Позиции")],
            [KeyboardButton("➕ Депозит"),   KeyboardButton("➖ Снять")],
            [KeyboardButton("♻️ Сброс"),    KeyboardButton("✅ Подтвердить")],
            [KeyboardButton("🟢 Старт"),    KeyboardButton("🔴 Стоп")],
            [KeyboardButton("▶️ NY 5M START"), KeyboardButton("🚀 5M СТАРТ")],
        ],
        resize_keyboard=True
    )


def get_vau_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 SL/TP"), KeyboardButton("⚡ Плечо"), KeyboardButton("📦 Позиция")],
            [KeyboardButton("← Назад")],
        ],
        resize_keyboard=True
    )


def get_sltp_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 SL"),  KeyboardButton("🎯 TP1")],
            [KeyboardButton("🎯 TP2"), KeyboardButton("🎯 TP3")],
            [KeyboardButton("← Назад")],
        ],
        resize_keyboard=True
    )
