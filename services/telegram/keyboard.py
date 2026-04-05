from telegram import ReplyKeyboardMarkup


# ─────────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────────
def main_menu():
    try:
        import json
        tc = json.load(open("/root/apex-system/storage/test_control.json"))
        trading_on = tc.get("trading_enabled", False) and tc.get("scanner_enabled", False)
    except Exception:
        trading_on = False

    stop_start = "🔴 Стоп" if trading_on else "🟢 Старт"
    keyboard = [
        ["📊 Статус", "⚡ ВАУ+"],
        ["♻️ Сброс", stop_start, "⚙️ Настройка бота"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# СТАТУС
# ─────────────────────────────────────────────
def status_menu():
    keyboard = [
        ["💰 Торговля", "🛠 Состояние"],
        ["📍 Позиции", "🔍 Диагностика"],
        ["🔭 Сканер", "📈 Аналитика"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# СКАНЕР
# ─────────────────────────────────────────────
def scanner_menu():
    keyboard = [
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ПРЕСЕТЫ СКАНЕРА
# ─────────────────────────────────────────────
def scanner_mode_menu():
    keyboard = [
        ["🟢 Пресет А"],
        ["🟡 Пресет Б"],
        ["🔴 Пресет В"],
        ["✍️ Ручной режим"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ЛИМИТ ПАР ДЛЯ СКАНЕРА
# ─────────────────────────────────────────────
def scanner_pairs_menu():
    keyboard = [
        ["10 пар", "20 пар"],
        ["100 пар", "500 пар"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ФИЛЬТРЫ СКАНЕРА
# ─────────────────────────────────────────────
def scanner_filters_menu():
    keyboard = [
        ["Фильтр ликв."],
        ["Фильтр волат."],
        ["Фильтр структуры"],
        ["Фильтр объёма"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ВАУ+ / АНАЛИТИКА
# ─────────────────────────────────────────────
def wau_menu():
    keyboard = [
        ["📈 Рынок сейчас"],
        ["📊 Сессия", "✂️ Срез"],
        ["💼 Итоги дня"],
        ["🧠 AI (скоро)"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# НАСТРОЙКА БОТА
# ─────────────────────────────────────────────
def settings_menu():
    keyboard = [
        ["🎯 Риск-менеджер", "⚡ Плечо"],
        ["💵 Позиция", "💰 Биржи"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def risk_menu():
    keyboard = [
        ["🛑 SL", "🎯 TP1"],
        ["🎯 TP2", "🎯 TP3"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# АВТОРЕЖИМ
# ─────────────────────────────────────────────
def auto_menu():
    keyboard = [
        ["Защита 1", "Защита 2"],
        ["Защита 3"],
        ["Трейлинг", "Выход по времени"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ЛИМИТЫ
# ─────────────────────────────────────────────
def limits_menu():
    keyboard = [
        ["Макс. позиций"],
        ["Кулдаун"],
        ["Макс. сделок / сессия"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# БИРЖИ / ЖИВЫЕ ДЕНЬГИ
# ─────────────────────────────────────────────
def exchange_menu(active_exchanges=None):
    if active_exchanges is None:
        try:
            import json
            tc = json.load(open("/root/apex-system/storage/test_control.json"))
            active_exchanges = tc.get("active_exchanges", [])
        except Exception:
            active_exchanges = []
    b_icon = "✅" if "binance" in active_exchanges else "❌"
    by_icon = "✅" if "bybit" in active_exchanges else "❌"
    keyboard = [
        [f"{b_icon} Binance", f"{by_icon} Bybit", "OKX"],
        ["📊 Статус бирж"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ВЫБОР СТРАТЕГИИ
# ─────────────────────────────────────────────
def strategy_menu():
    keyboard = [
        ["TOP20 1M BREAKOUT"],
        ["(будущая стратегия)"],
        ["◀️ Назад"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ СТОПА
# ─────────────────────────────────────────────
def confirm_stop_menu():
    keyboard = [
        ["✅ Да, остановить"],
        ["❌ Отмена"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ СТАРТА
# ─────────────────────────────────────────────
def confirm_start_menu():
    keyboard = [
        ["✅ Да, запустить"],
        ["❌ Отмена"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ СБРОСА
# ─────────────────────────────────────────────
def confirm_reset_menu():
    keyboard = [
        ["✅ Да, сбросить"],
        ["❌ Отмена"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ─────────────────────────────────────────────
# ПОДТВЕРЖДЕНИЕ ВКЛЮЧЕНИЯ/ОТКЛЮЧЕНИЯ БИРЖИ
# ─────────────────────────────────────────────
def confirm_exchange_on_menu():
    keyboard = [
        ["✅ Да, включить"],
        ["❌ Отмена"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def confirm_exchange_off_menu():
    keyboard = [
        ["✅ Да, отключить"],
        ["❌ Отмена"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
