# analytics_engine.py

import logging
from datetime import datetime

logger = logging.getLogger("apex.analytics_engine")


def load_results():
    try:
        from storage.db.repository import Repository
        repo = Repository()
        rows = repo.conn.execute(
            "SELECT * FROM APEX_MASTER_TRADE ORDER BY opened_at DESC"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["pnl"] = float(d.get("pnl_usdt") or 0)
            d["close_reason"] = d.get("close_reason") or "UNKNOWN"
            results.append(d)
        return results
    except Exception as e:
        logger.error(f"load_results error: {e}")
        return []


def compute_stats(results):
    if not results:
        return {}

    total = len(results)

    wins = [r for r in results if r["pnl"] > 0]
    losses = [r for r in results if r["pnl"] <= 0]

    win_count = len(wins)
    loss_count = len(losses)

    winrate = round((win_count / total) * 100, 2)

    total_pnl = sum(r["pnl"] for r in results)
    avg_pnl = round(total_pnl / total, 4)

    gross_profit = sum(r["pnl"] for r in wins)
    gross_loss = sum(r["pnl"] for r in losses)

    profit_factor = (
        round(abs(gross_profit / gross_loss), 2)
        if gross_loss != 0 else 0
    )

    reasons = {}
    for r in results:
        reason = r["close_reason"]
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "total_trades": total,
        "wins": win_count,
        "losses": loss_count,
        "winrate": winrate,
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": avg_pnl,
        "profit_factor": profit_factor,
        "reasons": reasons
    }


def print_report(stats):
    if not stats:
        print("[ANALYTICS] no data")
        return

    print("\n=== ANALYTICS REPORT ===")

    print(f"Total trades: {stats['total_trades']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Winrate: {stats['winrate']}%")

    print(f"Total PnL: {stats['total_pnl']}")
    print(f"Avg PnL: {stats['avg_pnl']}")
    print(f"Profit Factor: {stats['profit_factor']}")

    print("\nClose reasons:")
    for k, v in stats["reasons"].items():
        print(f"  {k}: {v}")

    print("========================\n")


def run():
    results = load_results()
    stats = compute_stats(results)
    print_report(stats)


def generate_session_stats() -> dict:
    """
    Читает T07, группирует по session_name, считает метрики,
    записывает в T11. Возвращает {session_name: stats_dict}.
    """
    try:
        from storage.db.repository import Repository
        repo = Repository()
    except Exception as e:
        logger.error(f"generate_session_stats: DB error: {e}")
        return {}

    today = datetime.now().strftime("%Y-%m-%d")
    rows = repo.conn.execute(
        "SELECT * FROM APEX_MASTER_TRADE WHERE finalized_at >= ?",
        (today,)
    ).fetchall()

    if not rows:
        return {}

    # Группировка по session_name
    by_session: dict[str, list] = {}
    for row in rows:
        d = dict(row)
        sn = d.get("session_name") or "UNKNOWN"
        by_session.setdefault(sn, []).append(d)

    result = {}
    for session_name, trades in by_session.items():
        total = len(trades)
        wins = sum(1 for t in trades if (t.get("result_label") or "").upper() == "WIN")
        losses = sum(1 for t in trades if (t.get("result_label") or "").upper() == "LOSS")
        winrate = round((wins / total) * 100, 2) if total else 0.0

        mtc_values = [t["minutes_to_close"] for t in trades if t.get("minutes_to_close")]
        avg_mtc = round(sum(mtc_values) / len(mtc_values), 1) if mtc_values else 0.0

        pnl_values = [t["pnl_pct"] for t in trades if t.get("pnl_pct") is not None]
        avg_r = round(sum(pnl_values) / len(pnl_values), 4) if pnl_values else 0.0

        stats = {
            "session_name": session_name,
            "stat_date": today,
            "total_trades": total,
            "total_wins": wins,
            "total_losses": losses,
            "winrate": winrate,
            "avg_minutes_to_close": avg_mtc,
            "avg_R_result": avg_r,
            "count_tp1": sum(1 for t in trades if (t.get("close_reason") or "").upper() in ("TP1",)),
            "count_tp2": sum(1 for t in trades if (t.get("close_reason") or "").upper() in ("TP2",)),
            "count_tp3": sum(1 for t in trades if (t.get("close_reason") or "").upper() in ("TP3", "SESSION_PROFIT_TAKE")),
            "count_stop_loss": sum(1 for t in trades if (t.get("close_reason") or "").upper() == "SL"),
            "count_force_close": sum(1 for t in trades if (t.get("close_reason") or "").upper() in ("FORCE_CLOSE_120M", "TIMEOUT", "SESSION_END")),
            "count_observation_entered": sum(1 for t in trades if t.get("entered_observation")),
        }
        repo.upsert_session_stats(stats)
        result[session_name] = stats
        logger.info(f"[SESSION_STATS] {session_name}: {total} trades, WR={winrate}%")

    return result
