"""
APEX PROTOCOL™ — Finalizer
Закрывает позиции, считает PnL, пишет в таблицы.
"""

import logging
from datetime import datetime
from pytz import timezone as tz
from core.event_bus import EventBus

PODGORICA = tz("Europe/Podgorica")

logger = logging.getLogger("apex.finalizer")


class Finalizer:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus

    async def finalize(self, positions: list) -> None:
        """Финализация позиций со статусом 'closing'."""
        try:
            closing = [p for p in positions if p.get("status") == "closing"]
            for position in closing:
                result = self._calculate_pnl(position)
                await self._save(result)
                await self.event_bus.publish("trade.closed", {"result": result})
                logger.info(f"Trade closed: {result['symbol']} | {result['close_reason']} | PnL: {result['pnl_usdt']} USDT")
        except Exception as e:
            logger.error(f"Finalizer error: {e}", exc_info=True)

    def _calculate_pnl(self, position: dict) -> dict:
        """Расчёт PnL сделки."""
        entry = position.get("fill_price", position.get("entry", 0))
        close_reason = position.get("close_reason", "UNKNOWN")
        direction = position.get("direction", "long")
        size = position.get("size", 0)

        # Определяем цену закрытия по причине
        price_map = {
            "TP1":     position.get("tp1"),
            "TP2":     position.get("tp2"),
            "TP3":     position.get("tp3"),
            "SL":      position.get("sl"),
            "TIMEOUT": position.get("current_price"),
        }
        close_price = price_map.get(close_reason) or position.get("current_price") or entry

        # ── close_event_type / result_label / archive_reason ──
        _close_event_type_map = {
            "SL":               "STOP_LOSS",
            "TP1":              "TP1",
            "TP2":              "TP2",
            "TP3":              "TP3",
            "FORCE_CLOSE_120M": "FORCE_CLOSE_120M",
            "TIMEOUT":          "FORCE_CLOSE_120M",
            "TIMEOUT_PROFIT_60":"FORCE_CLOSE_120M",
        }
        _result_label_map = {
            "STOP_LOSS":        "loss",
            "TP1":              "tp1_hit",
            "TP2":              "tp2_hit",
            "TP3":              "tp3_hit",
            "FORCE_CLOSE_120M": "force_close",
        }
        _archive_reason_map = {
            "STOP_LOSS":        "closed_by_stop_loss",
            "TP1":              "closed_by_tp1",
            "TP2":              "closed_by_tp2",
            "TP3":              "closed_by_tp3",
            "FORCE_CLOSE_120M": "closed_by_force_close_120m",
        }
        close_event_type = _close_event_type_map.get(close_reason, close_reason)
        result_label = _result_label_map.get(close_event_type, "unknown")
        archive_reason = _archive_reason_map.get(close_event_type, "unknown")

        if direction == "long":
            pnl_pct = ((close_price - entry) / entry) * 100
        else:
            pnl_pct = ((entry - close_price) / entry) * 100

        pnl_usdt = round(size * entry * (pnl_pct / 100), 4)

        finalized_at = datetime.now(PODGORICA).strftime("%Y-%m-%dT%H:%M:%S")

        duration_minutes = None
        opened_at_str = position.get("opened_at")
        closed_at_str = position.get("closed_at") or finalized_at
        if opened_at_str and closed_at_str:
            try:
                opened_dt = datetime.fromisoformat(opened_at_str.replace("Z", ""))
                closed_dt = datetime.fromisoformat(closed_at_str.replace("Z", ""))
                duration_minutes = int((closed_dt - opened_dt).total_seconds() / 60)
            except Exception:
                pass

        try:
            from services.test_control import read as tc_read
            strategy_name = tc_read().get("active_filter")
        except Exception:
            strategy_name = None

        return {
            **position,
            "close_price": close_price,
            "pnl_pct": round(pnl_pct, 4),
            "pnl_usdt": pnl_usdt,
            "status": "closed",
            "finalized_at": finalized_at,
            "trade_id": position.get("trade_id"),
            "session_name": position.get("session_name"),
            "duration_minutes": duration_minutes,
            "minutes_to_close": duration_minutes,
            "strategy_name": strategy_name,
            "close_event_type": close_event_type,
            "result_label": result_label,
            "archive_reason": archive_reason,
            "orb_high": position.get("orb_high"),
            "orb_low": position.get("orb_low"),
            "orb_mid": position.get("orb_mid"),
            "orb_size": position.get("orb_size"),
            "retest_price": position.get("retest_price"),
            "confirmation_type": position.get("confirmation_type"),
        }

    async def _save(self, result: dict) -> None:
        from storage.db.repository import Repository
        repo = Repository()
        repo.log_final_trade(result)
        repo.close_execution(result.get("trade_id"))
        logger.info(f"Finalizer: saved {result.get('symbol')} → SKL01_T07, T05 status=closed [{result.get('trade_id')}]")
        # Archive log — T10
        try:
            repo.log_archive({
                "session_name":     result.get("session_name"),
                "symbol":           result.get("symbol"),
                "direction":        result.get("direction"),
                "entry_time":       result.get("opened_at"),
                "close_time":       result.get("closed_at"),
                "close_event_type": result.get("close_event_type"),
                "result_label":     result.get("result_label"),
                "minutes_to_close": result.get("minutes_to_close"),
                "archived_at":      result.get("closed_at"),
                "archive_reason":   result.get("archive_reason"),
            })
        except Exception as e:
            logger.warning(f"log_archive error: {e}")
        # Pair freeze — блокировать пару до конца сессии
        try:
            from modules.signal_gate import archive_pair_for_session
            archive_pair_for_session(
                symbol=result.get("symbol", ""),
                session_name=result.get("session_name", "UNKNOWN"),
            )
        except Exception as e:
            logger.warning(f"archive_pair_for_session error: {e}")
        # Session stats — T11
        try:
            from modules.analytics_engine import generate_session_stats
            generate_session_stats()
        except Exception as e:
            logger.warning(f"generate_session_stats error: {e}")
        try:
            from services.telegram_notifier import get_notifier
            notifier = get_notifier()
            if notifier:
                await notifier.notify_close(result)
        except Exception as e:
            logger.warning(f"notify_close error: {e}")
