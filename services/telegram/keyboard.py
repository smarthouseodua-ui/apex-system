from telegram import ReplyKeyboardMarkup, KeyboardButton


def get_main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📊 Статус"),    KeyboardButton("⚡ ВАУ+")],
            [KeyboardButton("🟢 Старт"),     KeyboardButton("🔴 Стоп")],
            [KeyboardButton("📍 Позиции"),    KeyboardButton("♻️ Сброс")],
            [KeyboardButton("⚙️ Настройка бота")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )


def get_vau_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("◀️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )


def get_settings_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🎯 Стоп-лосс")],
            [KeyboardButton("🎯 ТП1"), KeyboardButton("🎯 ТП2"), KeyboardButton("🎯 ТП3")],
            [KeyboardButton("⚡ Плечо")],
            [KeyboardButton("➕ Позиция+"), KeyboardButton("➖ Позиция-")],
            [KeyboardButton("◀️ Назад")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )


def get_reset_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("♻️ Сброс"), KeyboardButton("◀️ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        is_persistent=True
    )
