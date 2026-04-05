"""
APEX PROTOCOL™ — Repository
Запись и чтение данных из SQLite таблиц APEX_MASTER.
"""

import sqlite3
import logging
from datetime import datetime
from storage.db.init_db import get_connection

logger = logging.getLogger("apex.repository")


class Repository:

    def __init__(self):
        self.conn = get_connection()

    def log_scanner(self, candidate: dict):
        self.conn.execute("""
            INSERT INTO APEX_MASTER_SCANNER
            (symbol, price, volume, volatility, session, scanned_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            candidate.get("symbol"),
            candidate.get("price"),
            candidate.get("volume"),
            candidate.get("volatility"),
            candidate.get("session", ""),
            candidate.get("scanned_at", datetime.now().isoformat())
        ))
        self.conn.commit()

    def log_strategy(self, signal: dict):
        try:
            self.conn.execute("""
                UPDATE APEX_MASTER_TRADE SET
                    market_phase      = ?,
                    bos_present       = ?,
                    choch_present     = ?,
                    entry_in_discount = ?,
                    entry_near_ob     = ?,
                    entry_near_fvg    = ?
                WHERE trade_id = ?
            """, (
                signal.get("market_phase"),
                signal.get("bos_present"),
                signal.get("choch_present"),
                signal.get("entry_in_discount"),
                signal.get("entry_near_ob"),
                signal.get("entry_near_fvg"),
                signal.get("trade_id"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"APEX_MASTER_TRADE update (strategy) error: {e}")

    def log_signal_gate(self, symbol: str, approved: bool, reject_reason: str = ""):
        pass

    def log_risk_manager(self, order: dict):
        try:
            self.conn.execute("""
                UPDATE APEX_MASTER_TRADE SET
                    risk_pct = ?,
                    risk_usdt = ?,
                    rr = ?
                WHERE trade_id = ?
            """, (
                order.get("risk_pct"),
                order.get("risk_usdt"),
                order.get("rr"),
                order.get("trade_id"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"APEX_MASTER_TRADE update (risk) error: {e}")

    def log_execution(self, position: dict):
        now = datetime.now().isoformat()
        opened_at = position.get("opened_at", now)
        mode = position.get("mode", "simulation")
        entry_type = "SIMULATED" if mode.upper() in ("PAPER", "SIMULATION") else "LIVE"
        try:
            self.conn.execute("""
                INSERT INTO APEX_MASTER_TRADE
                (trade_id, symbol, direction, strategy, mode,
                 session_name, session_hour, opened_at, created_at,
                 entry, sl, tp1, tp2, tp3,
                 size, leverage, risk_pct, risk_usdt, rr,
                 fill_price, slippage, commission,
                 exchange_name, entry_type,
                 scanner_passed, filter_passed,
                 execution_attempted, execution_success,
                 entry_signal_score, scanner_score,
                 entry_reason_code, entry_reason_text,
                 is_finalized,
                 session_group, sub_session, overlap_flag,
                 session_date_key, opened_date, opened_hour,
                 trade_day_of_week,
                 entry_distance_to_sl_pct, entry_distance_to_tp1_pct,
                 data_quality_flag, analytics_ready_flag,
                 dashboard_group_date, dashboard_sort_ts,
                 is_visible_in_dashboard, row_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position.get("trade_id"),
                position.get("symbol"),
                position.get("direction"),
                position.get("strategy"),
                mode,
                position.get("session_name"),
                position.get("session_hour"),
                opened_at,
                opened_at,  # created_at
                position.get("fill_price"),
                position.get("sl"),
                position.get("tp1"),
                position.get("tp2"),
                position.get("tp3"),
                position.get("size"),
                position.get("leverage"),
                position.get("risk_pct"),
                position.get("risk_usdt"),
                position.get("rr"),
                position.get("fill_price"),
                position.get("slippage", 0),
                position.get("commission", 0),
                position.get("exchange_name", "Bybit"),
                entry_type,
                1,  # scanner_passed
                1,  # filter_passed
                1,  # execution_attempted
                1,  # execution_success
                position.get("entry_signal_score"),
                position.get("scanner_score"),
                position.get("entry_reason_code"),
                position.get("entry_reason_text"),
                0,  # is_finalized (not yet)
                # session_group
                self._calc_session_group(position.get("session_name")),
                position.get("session_name") or "UNKNOWN",  # sub_session
                1 if "OVERLAP" in (position.get("session_name") or "").upper() else 0,
                # session_date_key
                opened_at[:10] if opened_at and len(opened_at) >= 10 else None,
                opened_at[:10] if opened_at and len(opened_at) >= 10 else None,  # opened_date
                int(opened_at[11:13]) if opened_at and len(opened_at) >= 13 else None,  # opened_hour
                self._calc_day_of_week(opened_at),
                # entry_distance_to_sl_pct
                self._calc_distance_pct(position.get("fill_price"), position.get("sl")),
                # entry_distance_to_tp1_pct
                self._calc_distance_pct(position.get("fill_price"), position.get("tp1")),
                "OK",  # data_quality_flag
                0,  # analytics_ready_flag (no pnl yet)
                opened_at[:10] if opened_at and len(opened_at) >= 10 else None,  # dashboard_group_date
                opened_at,  # dashboard_sort_ts
                1,  # is_visible_in_dashboard
                "active",  # row_status
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"APEX_MASTER_TRADE insert error: {e}")

    @staticmethod
    def _calc_session_group(session_name):
        s = (session_name or "").upper()
        if s in ("ASIA", "HONG_KONG", "TOKYO"):
            return "ASIA"
        if s in ("LONDON", "EUROPE"):
            return "EUROPE"
        if s in ("NEW_YORK", "US", "AMERICA"):
            return "AMERICA"
        return "OTHER"

    @staticmethod
    def _calc_day_of_week(dt_str):
        if not dt_str or len(dt_str) < 10:
            return None
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", ""))
            return ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][dt.weekday()]
        except Exception:
            return None

    @staticmethod
    def _calc_distance_pct(entry, target):
        if entry and target and entry != 0:
            return round(abs(entry - target) / entry * 100, 4)
        return None

    def get_open_symbols(self) -> set:
        rows = self.conn.execute(
            "SELECT DISTINCT symbol FROM APEX_MASTER_TRADE WHERE closed_at IS NULL"
        ).fetchall()
        return {r[0] for r in rows}

    def get_open_positions(self) -> list:
        cursor = self.conn.execute("""
            SELECT symbol, direction, fill_price, sl, tp1, tp2, tp3,
                   size, risk_usdt, mode, opened_at,
                   trade_id, session_name
            FROM APEX_MASTER_TRADE
            WHERE closed_at IS NULL
            ORDER BY opened_at
        """)
        positions = []
        for row in cursor.fetchall():
            d = dict(row)
            d["entry"]         = d["fill_price"]
            d["current_price"] = d["fill_price"]
            d["size_usdt"]     = d.get("risk_usdt")
            d["status"]        = "open"
            positions.append(d)
        return positions

    def get_session_trade_count(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        row = self.conn.execute(
            "SELECT COUNT(*) FROM APEX_MASTER_TRADE WHERE opened_at >= ?",
            (today,)
        ).fetchone()
        return row[0] if row else 0

    def log_position(self, position: dict):
        try:
            self.conn.execute("""
                UPDATE APEX_MASTER_TRADE SET
                    minutes_to_sl = ?,
                    minutes_to_tp1 = ?
                WHERE trade_id = ?
            """, (
                position.get("minutes_to_sl"),
                position.get("minutes_to_tp1"),
                position.get("trade_id"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"APEX_MASTER_TRADE update (position) error: {e}")

    def update_position_sl(self, trade_id: str, sl: float) -> None:
        self.conn.execute(
            "UPDATE APEX_MASTER_TRADE SET sl=? WHERE trade_id=?",
            (sl, trade_id)
        )
        self.conn.commit()

    def close_execution(self, trade_id: str) -> None:
        self.conn.execute(
            "UPDATE APEX_MASTER_TRADE SET closed_at=? WHERE trade_id=?",
            (datetime.now().isoformat(), trade_id)
        )
        self.conn.commit()

    def log_final_trade(self, result: dict):
        close_reason = result.get("close_reason")
        pnl_usdt = result.get("pnl_usdt")
        pnl_pct = result.get("pnl_pct")
        closed_at = result.get("closed_at")
        finalized_at = result.get("finalized_at", datetime.now().isoformat())
        duration = result.get("duration_minutes")

        # Вычисляемые поля при закрытии
        forced = 1 if (close_reason or "").upper() in (
            "TIMEOUT", "MANUAL_STOP", "FORCE_CLOSE", "EMERGENCY_EXIT",
            "FORCE_CLOSE_120M", "SESSION_END", "SESSION_PROFIT_TAKE",
            "TIMEOUT_PROFIT_60", "TIME_EXIT_FORCE", "TIME_EXIT_PROFIT"
        ) else 0
        manual = 1 if (close_reason or "").upper() in ("MANUAL_STOP", "MANUAL_CLOSE") else 0
        net_class = "WIN" if pnl_usdt and pnl_usdt > 0 else ("LOSS" if pnl_usdt and pnl_usdt < 0 else "FLAT")
        color = "GREEN" if pnl_usdt and pnl_usdt > 0 else ("RED" if pnl_usdt and pnl_usdt < 0 else "GRAY")
        priority = 1 if (close_reason or "").upper() in (
            "MANUAL_STOP", "FORCE_CLOSE", "EMERGENCY_EXIT", "FORCE_CLOSE_120M"
        ) else (2 if pnl_usdt and abs(pnl_usdt) > 100 else 5)

        # holding_bucket
        hold = None
        if duration is not None:
            if duration < 5: hold = "0-5m"
            elif duration < 15: hold = "5-15m"
            elif duration < 30: hold = "15-30m"
            elif duration < 60: hold = "30-60m"
            elif duration < 120: hold = "60-120m"
            else: hold = "120m+"

        # pnl_bucket
        pnl_b = None
        if pnl_pct is not None:
            if pnl_pct <= -2: pnl_b = "<=-2%"
            elif pnl_pct <= -1: pnl_b = "-2%..-1%"
            elif pnl_pct < 0: pnl_b = "-1%..0%"
            elif pnl_pct == 0: pnl_b = "0%"
            elif pnl_pct < 1: pnl_b = "0%..1%"
            elif pnl_pct < 2: pnl_b = "1%..2%"
            else: pnl_b = ">=2%"

        try:
            self.conn.execute("""
                UPDATE APEX_MASTER_TRADE SET
                    close_price = ?,
                    close_reason = ?,
                    exit_route = ?,
                    exit_reason_code = ?,
                    exit_reason_text = ?,
                    tp_level_reached_max = ?,
                    minutes_to_close = ?,
                    duration_minutes = CAST((JULIANDAY(?) - JULIANDAY(opened_at)) * 1440 AS INTEGER),
                    holding_bucket = ?,
                    closed_at = ?,
                    closed_date = ?,
                    closed_hour = ?,
                    finalized_at = ?,
                    is_finalized = 1,
                    pnl_pct = ?,
                    pnl_usdt = ?,
                    gross_pnl_pct = ?,
                    net_pnl_pct = ?,
                    gross_pnl_usdt = ?,
                    net_pnl_usdt = ?,
                    result_label = ?,
                    net_result_class = ?,
                    pnl_bucket = ?,
                    forced_exit_flag = ?,
                    manual_intervention_flag = ?,
                    orb_high = ?,
                    orb_low = ?,
                    orb_mid = ?,
                    retest_price = ?,
                    dashboard_sort_ts = ?,
                    dashboard_color_flag = ?,
                    dashboard_priority = ?,
                    dashboard_note = ?,
                    data_quality_flag = CASE
                        WHEN ? IS NULL THEN 'WARN'
                        ELSE 'OK'
                    END,
                    analytics_ready_flag = CASE
                        WHEN ? IS NOT NULL AND ? IS NOT NULL THEN 1
                        ELSE 0
                    END,
                    updated_at = ?
                WHERE trade_id = ?
            """, (
                result.get("close_price"),
                close_reason,
                result.get("close_event_type"),
                close_reason,  # exit_reason_code
                close_reason,  # exit_reason_text
                result.get("tp_level_reached_max"),
                result.get("minutes_to_close"),
                result.get("duration_minutes"),
                hold,
                closed_at,
                closed_at[:10] if closed_at and len(closed_at) >= 10 else None,
                int(closed_at[11:13]) if closed_at and len(closed_at) >= 13 else None,
                finalized_at,
                pnl_pct,
                pnl_usdt,
                pnl_pct,   # gross_pnl_pct
                pnl_pct,   # net_pnl_pct
                pnl_usdt,  # gross_pnl_usdt
                pnl_usdt,  # net_pnl_usdt
                result.get("result_label"),
                net_class,
                pnl_b,
                forced,
                manual,
                result.get("orb_high"),
                result.get("orb_low"),
                result.get("orb_mid"),
                result.get("retest_price"),
                finalized_at,  # dashboard_sort_ts
                color,
                priority,
                (result.get("symbol") or "?") + " | " + (result.get("direction") or "?") + " | " + (close_reason or "CLOSED"),
                result.get("close_price"),  # for data_quality_flag CASE
                pnl_usdt,  # for analytics_ready_flag
                result.get("session_name"),  # for analytics_ready_flag
                datetime.now().isoformat(),  # updated_at
                result.get("trade_id"),
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"APEX_MASTER_TRADE update (final) error: {e}")

    def log_archive(self, record: dict):
        self.conn.execute("""
            INSERT INTO APEX_MASTER_ARCHIVE
            (session_name, timezone, symbol, direction, entry_time, close_time,
             close_event_type, result_label, minutes_to_close, archived_at, archive_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get("session_name"),
            record.get("timezone", ""),
            record.get("symbol"),
            record.get("direction"),
            record.get("entry_time"),
            record.get("close_time"),
            record.get("close_event_type"),
            record.get("result_label"),
            record.get("minutes_to_close"),
            record.get("archived_at"),
            record.get("archive_reason"),
        ))
        self.conn.commit()

    def upsert_session_stats(self, stats: dict):
        self.conn.execute("""
            INSERT INTO APEX_MASTER_SESSIONS
            (session_name, stat_date, total_trades, total_wins, total_losses,
             winrate, avg_minutes_to_close, avg_R_result,
             count_tp1, count_tp2, count_tp3, count_stop_loss,
             count_force_close, count_observation_entered, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_name, stat_date) DO UPDATE SET
             total_trades=excluded.total_trades,
             total_wins=excluded.total_wins,
             total_losses=excluded.total_losses,
             winrate=excluded.winrate,
             avg_minutes_to_close=excluded.avg_minutes_to_close,
             avg_R_result=excluded.avg_R_result,
             count_tp1=excluded.count_tp1,
             count_tp2=excluded.count_tp2,
             count_tp3=excluded.count_tp3,
             count_stop_loss=excluded.count_stop_loss,
             count_force_close=excluded.count_force_close,
             count_observation_entered=excluded.count_observation_entered,
             updated_at=excluded.updated_at
        """, (
            stats.get("session_name"),
            stats.get("stat_date"),
            stats.get("total_trades", 0),
            stats.get("total_wins", 0),
            stats.get("total_losses", 0),
            stats.get("winrate", 0.0),
            stats.get("avg_minutes_to_close", 0.0),
            stats.get("avg_R_result", 0.0),
            stats.get("count_tp1", 0),
            stats.get("count_tp2", 0),
            stats.get("count_tp3", 0),
            stats.get("count_stop_loss", 0),
            stats.get("count_force_close", 0),
            stats.get("count_observation_entered", 0),
            datetime.now().isoformat(),
        ))
        self.conn.commit()

    def log_system_event(self, event: str, module: str, message: str, level: str = "INFO"):
        self.conn.execute("""
            INSERT INTO APEX_MASTER_ERRORS
            (event, module, message, level, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (event, module, message, level, datetime.now().isoformat()))
        self.conn.commit()

    def get_final_trades(self, limit: int = 50) -> list:
        cursor = self.conn.execute("""
            SELECT * FROM APEX_MASTER_TRADE
            WHERE closed_at IS NOT NULL
            ORDER BY finalized_at DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

    def log_pre_session(self, record: dict):
        """Записывает результат предсессионного SMC-анализа в T09."""
        self.conn.execute("""
            INSERT INTO APEX_MASTER_MARKET
            (symbol, session_name, timezone, pre_session_start_time, session_open_time,
             analysis_time, premium_zone_status, discount_zone_status,
             market_structure_state, bos_detected, choch_detected,
             order_block_present, fvg_present, liquidity_pool_present,
             mitigation_present, displacement_present, sweep_present,
             analyst_comment_short, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get("symbol"),
            record.get("session_name"),
            record.get("timezone", "Europe/Podgorica"),
            record.get("pre_session_start_time"),
            record.get("session_open_time"),
            record.get("analysis_time"),
            record.get("premium_zone_status"),
            record.get("discount_zone_status"),
            record.get("market_structure_state"),
            record.get("bos_detected", 0),
            record.get("choch_detected", 0),
            record.get("order_block_present", 0),
            record.get("fvg_present", 0),
            record.get("liquidity_pool_present", 0),
            record.get("mitigation_present", 0),
            record.get("displacement_present", 0),
            record.get("sweep_present", 0),
            record.get("analyst_comment_short"),
            record.get("created_at", datetime.now().isoformat()),
        ))
        self.conn.commit()

    def get_pre_session_done(self, session_name: str, date_str: str) -> bool:
        """Проверяет, выполнен ли предсессионный анализ для сессии за дату."""
        row = self.conn.execute("""
            SELECT COUNT(*) FROM APEX_MASTER_MARKET
            WHERE session_name = ? AND created_at >= ?
        """, (session_name, date_str)).fetchone()
        return row[0] > 0 if row else False


    def update_smc_fields(self, symbol: str, data: dict) -> None:
        """Обновляет SEC16 SMC/ORB поля для открытых позиций по символу."""
        try:
            self.conn.execute("""
                UPDATE APEX_MASTER_TRADE SET
                    market_phase      = ?,
                    bos_present       = ?,
                    choch_present     = ?,
                    entry_in_discount = ?,
                    entry_near_ob     = ?,
                    entry_near_fvg    = ?,
                    orb_high          = ?,
                    orb_low           = ?,
                    orb_mid           = ?,
                    updated_at        = ?
                WHERE symbol = ? AND closed_at IS NULL
            """, (
                data.get("market_phase"),
                data.get("bos_present"),
                data.get("choch_present"),
                data.get("entry_in_discount"),
                data.get("entry_near_ob"),
                data.get("entry_near_fvg"),
                data.get("orb_high"),
                data.get("orb_low"),
                data.get("orb_mid"),
                datetime.now().isoformat(),
                symbol,
            ))
            self.conn.commit()
        except Exception as e:
            logger.error(f"update_smc_fields error: {e}")

    def close(self):
        self.conn.close()
