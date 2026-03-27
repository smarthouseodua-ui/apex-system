# telegram_control.py

from datetime import datetime
from modules.risk_manager import get_state
from modules.analytics_engine import compute_stats, load_results

MODE = {
    "status": "RUN"  # RUN / STOP
}


def set_mode(value: str):
    MODE["status"] = value


def get_mode():
    return MODE["status"]


def format_status():
    from modules.execution_engine import OPEN_POSITIONS
    state = get_state()

    return (
        f"📊 APEX STATUS\n"
        f"Mode: {MODE['status']}\n"
        f"Positions: {len(OPEN_POSITIONS)}\n"
        f"Daily PnL: {round(state['daily_pnl'], 2)}\n"
        f"Total PnL: {round(state['total_pnl'], 2)}\n"
        f"Loss Streak: {state['loss_streak']}\n"
        f"Blocked: {state['blocked']}"
    )


def format_positions():
    from modules.execution_engine import OPEN_POSITIONS
    if not OPEN_POSITIONS:
        return "No open positions"

    lines = []
    for s, p in OPEN_POSITIONS.items():
        lines.append(
            f"{s} | {p['side']} | entry={p['entry_price']} size={p['size']}"
        )

    return "\n".join(lines)


def format_analytics():
    results = load_results()
    stats = compute_stats(results)

    if not stats:
        return "No analytics data"

    return (
        f"Trades: {stats['total_trades']}\n"
        f"Winrate: {stats['winrate']}%\n"
        f"Total PnL: {stats['total_pnl']}\n"
        f"PF: {stats['profit_factor']}"
    )
