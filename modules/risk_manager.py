"""
APEX PROTOCOL™ — Risk Manager
Рассчитывает параметры сделки. Пишет в SKL01_T04_risk_manager_log.
"""

import logging
from core.event_bus import EventBus
from storage.db.repository import Repository

logger = logging.getLogger("apex.risk_manager")


class RiskManager:

    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()

    async def calculate(self, signals: list) -> list:
        try:
            orders = []
            for signal in signals:
                order = self._calculate_order(signal)
                if order:
                    self.repo.log_risk_manager(order)
                    orders.append(order)

            logger.info(f"RiskManager: {len(orders)} orders calculated")
            await self.event_bus.publish("risk_manager.done", {"orders": orders})
            return orders
        except Exception as e:
            logger.error(f"RiskManager error: {e}", exc_info=True)
            return []

    def _calculate_order(self, signal: dict) -> dict | None:
        # Копируем cfg, чтобы не мутировать shared config
        cfg = dict(self.config.get("risk", {}))

        # Применяем overrides из test_control (если есть)
        try:
            from services.test_control import read as tc_read
            tc = tc_read()
            if tc.get("param_sl_pct") is not None:
                cfg["sl_pct"] = float(tc["param_sl_pct"])
            if tc.get("param_tp1_pct") is not None:
                cfg["tp1_pct"] = float(tc["param_tp1_pct"])
            if tc.get("param_tp2_pct") is not None:
                cfg["tp2_pct"] = float(tc["param_tp2_pct"])
            if tc.get("param_tp3_pct") is not None:
                cfg["tp3_pct"] = float(tc["param_tp3_pct"])
            if tc.get("param_leverage") is not None:
                cfg["leverage"] = int(tc["param_leverage"])
            if tc.get("param_size_usdt") is not None:
                cfg["fixed_size_usdt"] = float(tc["param_size_usdt"])
        except Exception:
            pass

        balance = cfg.get("balance_usdt", 1000)
        leverage = cfg.get("leverage", 1)
        rr = cfg.get("rr_ratio", 2.0)
        direction = signal.get("direction", "long")

        entry = signal.get("entry")
        if not entry:
            return None

        # --- Размер позиции ---
        fixed_size_usdt = cfg.get("fixed_size_usdt")
        if fixed_size_usdt:
            size = round(fixed_size_usdt / entry, 6)
            risk_usdt = fixed_size_usdt
        else:
            risk_pct = cfg.get("risk_per_trade_pct", 1.0)
            risk_usdt = balance * (risk_pct / 100)
            size = round((risk_usdt * leverage) / entry, 6)

        # --- SL ---
        sl_pct = cfg.get("sl_pct")
        if sl_pct:
            if direction == "long":
                sl = round(entry * (1 - sl_pct / 100), 6)
            else:
                sl = round(entry * (1 + sl_pct / 100), 6)
        else:
            sl = signal.get("sl")
            if not sl:
                return None
            sl_distance = abs(entry - sl)
            if sl_distance == 0:
                return None

        # --- TP ---
        tp1_pct = cfg.get("tp1_pct")
        tp2_pct = cfg.get("tp2_pct")
        tp3_pct = cfg.get("tp3_pct")
        if tp1_pct and tp2_pct and tp3_pct:
            if direction == "long":
                tp1 = round(entry * (1 + tp1_pct / 100), 6)
                tp2 = round(entry * (1 + tp2_pct / 100), 6)
                tp3 = round(entry * (1 + tp3_pct / 100), 6)
            else:
                tp1 = round(entry * (1 - tp1_pct / 100), 6)
                tp2 = round(entry * (1 - tp2_pct / 100), 6)
                tp3 = round(entry * (1 - tp3_pct / 100), 6)
        else:
            sl_distance = abs(entry - sl)
            tp1 = entry + sl_distance * 1.0 if direction == "long" else entry - sl_distance * 1.0
            tp2 = entry + sl_distance * 2.0 if direction == "long" else entry - sl_distance * 2.0
            tp3 = entry + sl_distance * 3.0 if direction == "long" else entry - sl_distance * 3.0
            tp1, tp2, tp3 = round(tp1, 6), round(tp2, 6), round(tp3, 6)

        # --- Дополнительные расчёты ---
        position_size_usdt = round(size * entry, 4)
        risk_pct = round((risk_usdt / balance) * 100, 4) if balance > 0 else 0
        stop_distance_pct = round((abs(entry - sl) / entry) * 100, 4) if entry > 0 else 0

        return {
            **signal,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "size": size,
            "leverage": leverage,
            "rr": rr,
            "risk_usdt": risk_usdt,
            "risk_pct": risk_pct,
            "position_size_usdt": position_size_usdt,
            "stop_distance_pct": stop_distance_pct,
            "daily_risk_state": "OK",
            "drawdown_state": "OK",
            "risk_filter_status": "APPROVED",
            "trade_id": signal.get("trade_id", "")
        }
