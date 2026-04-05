"""
APEX PROTOCOL™ — Signal Gate
Фильтрует сигналы перед execution.
Пишет в APEX_MASTER_TRADE (через repository).

Логика:
- already_open: символ уже имеет открытую позицию (память + DB)
- duplicate_in_cycle: символ уже approved в этом цикле
- cooldown: символ недавно торговался (cross-cycle protection)
- max_positions: достигнут лимит открытых позиций
- Каждый символ проверяется индивидуально, batch не блокируется целиком
"""

import sys
import logging
import traceback
from datetime import datetime, date
from enum import Enum

from core.event_bus import EventBus
from storage.db.repository import Repository

try:
    sys.path.insert(0, "/root/data-core")
    from app import write_filter_results_batch
except Exception:
    def write_filter_results_batch(entries):
        pass

from modules.execution_engine import execute

logger = logging.getLogger("apex.signal_gate")


class PairSessionStatus(Enum):
    NOT_USED = "NOT_USED"
    IN_ANALYSIS = "IN_ANALYSIS"
    SIGNAL_FOUND = "SIGNAL_FOUND"
    TRADE_OPENED = "TRADE_OPENED"
    OBSERVATION_MODE = "OBSERVATION_MODE"
    CLOSED = "CLOSED"
    SESSION_ARCHIVED = "SESSION_ARCHIVED"


# key = (symbol, session_name), value = PairSessionStatus
_pair_session_status: dict[tuple, PairSessionStatus] = {}
# key = (symbol, session_name), value = date
_pair_session_date: dict[tuple, date] = {}


def get_pair_status(symbol: str, session_name: str) -> PairSessionStatus:
    key = (symbol, session_name)
    return _pair_session_status.get(key, PairSessionStatus.NOT_USED)


def set_pair_status(symbol: str, session_name: str, status: PairSessionStatus):
    key = (symbol, session_name)
    _pair_session_status[key] = status
    _pair_session_date[key] = date.today()


def reset_pair_if_new_session(symbol: str, session_name: str):
    """Сбросить статус если началась новая торговая дата."""
    key = (symbol, session_name)
    if _pair_session_date.get(key) != date.today():
        _pair_session_status.pop(key, None)
        _pair_session_date.pop(key, None)


def archive_pair_for_session(symbol: str, session_name: str):
    """Вызывается после закрытия сделки. Блокирует пару до конца сессии."""
    set_pair_status(symbol, session_name, PairSessionStatus.SESSION_ARCHIVED)
    logger.info(f"[PAIR FREEZE] {symbol} → SESSION_ARCHIVED в сессии {session_name}")


class SignalGate:
    def __init__(self, config: dict, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.repo = Repository()
        # Cross-cycle cooldown: symbol → datetime последнего approved
        self._recent_signals: dict[str, datetime] = {}
        self._last_session: str = ""

    def reset(self, session_name: str = ""):
        """Начало нового цикла. Cooldown сбрасывается при смене сессии."""
        if session_name and session_name != self._last_session:
            self._recent_signals.clear()
            logger.info(f"SignalGate: cooldown CLEARED — new session {session_name}")
            self._last_session = session_name
        logger.info(f"SignalGate: reset — cooldown entries: {len(self._recent_signals)}")

    def _get_max_positions(self) -> int:
        """Берёт max_positions. Приоритет: risk.yaml → top-level → 100."""
        risk_max = self.config.get("risk", {}).get("max_positions")
        if risk_max is not None:
            return int(risk_max)
        top_max = self.config.get("max_positions")
        if top_max is not None:
            return int(top_max)
        return 100

    def _get_cooldown_minutes(self) -> int:
        """Берёт cooldown_minutes. Приоритет: signal_gate → top-level → 5."""
        gate_cd = self.config.get("signal_gate", {}).get("cooldown_minutes")
        if gate_cd is not None:
            return int(gate_cd)
        top_cd = self.config.get("cooldown_minutes")
        if top_cd is not None:
            return int(top_cd)
        return 5

    async def filter(self, signals: list, open_symbols: set = None) -> list:
        try:
            open_symbols = open_symbols or set()

            # Один SQL-запрос — все открытые символы из DB
            db_open = self.repo.get_open_symbols()

            # all_open — единый set: открытые + approved в этом цикле
            all_open = open_symbols | db_open
            open_before_cycle = len(all_open)

            max_pos = self._get_max_positions()
            cooldown_minutes = self._get_cooldown_minutes()

            # --- Session trade limit ---
            session_trades = self.repo.get_session_trade_count()
            max_trades = self.config.get("max_trades_per_session", 9999)
            if session_trades >= max_trades:
                logger.warning(f"[GATE] Session limit reached: {session_trades}/{max_trades}")
                for signal in signals:
                    sym = signal.get("symbol", "?")
                    self.repo.log_signal_gate(sym, "SIGNAL_GATE", "SESSION_LIMIT", f"Session trade limit reached: {session_trades}/{max_trades}")
                    logger.info(f"[GATE_REJECT] symbol={sym} stage=SIGNAL_GATE code=SESSION_LIMIT text=Session trade limit reached")
                return []

            # cycle_approved — только для защиты от дублей внутри batch
            cycle_approved: set[str] = set()
            approved = []
            reject_reasons: dict[str, int] = {}
            rejected_symbols: dict[str, list] = {}

            for signal in signals:
                symbol = signal.get("symbol", "?")
                session_name = signal.get("session_name", "")

                ok, reason = self._check(
                    signal,
                    all_open,
                    cycle_approved,
                    max_pos,
                    cooldown_minutes,
                    session_name,
                )

                if not ok:
                    reason_map = {
                        "duplicate_in_cycle": ("SIGNAL_GATE", "DUPLICATE_IN_CYCLE", "Symbol already approved in this cycle"),
                        "already_open": ("SIGNAL_GATE", "ALREADY_OPEN", "Symbol already has an open position"),
                        "cooldown": ("SIGNAL_GATE", "COOLDOWN", "Symbol is in cooldown period after recent trade"),
                        "max_positions": ("SIGNAL_GATE", "MAX_POSITIONS", "Maximum open positions limit reached"),
                    }
                    stage, code, text = reason_map.get(reason, ("SIGNAL_GATE", reason.upper() or "UNKNOWN", reason or "Unknown rejection"))
                    self.repo.log_signal_gate(symbol, stage, code, text)
                    logger.info(f"[GATE_REJECT] symbol={symbol} stage={stage} code={code} text={text}")

                if ok:
                    signal["entry_reason_code"] = "GATE_APPROVED"
                    signal["entry_reason_text"] = "Passed all gate checks"
                    approved.append(signal)
                    cycle_approved.add(symbol)
                    all_open.add(symbol)
                    self._recent_signals[symbol] = datetime.now()

                    if session_name:
                        set_pair_status(symbol, session_name, PairSessionStatus.SIGNAL_FOUND)

                    # Execution call for APPROVED signals
                    try:
                        from services.test_control import read as _tc
                        _bal = float(_tc().get("test_balance", 1000))
                    except Exception:
                        _bal = 1000

                    try:
                        order = execute(signal, balance=_bal)
                        if order:
                            logger.info(
                                f"[EXECUTION] Order created: {order['symbol']} "
                                f"{order['side']} size={order['size']} mode={order['mode']}"
                            )
                        if order and order.get('trade_id'):
                            try:
                                from storage.db.repository import Repository as _R
                                _r = _R()
                                _r.conn.execute(
                                    'UPDATE APEX_AGS_ANALYTICS '
                                    'SET trade_id=?, trade_opened_flag=1, execution_status=? '
                                    'WHERE symbol=? AND trade_id IS NULL '
                                    'ORDER BY created_at DESC LIMIT 1',
                                    (order.get('trade_id'), 'EXECUTED', order.get('symbol'))
                                )
                                _r.conn.commit()
                            except Exception as _age:
                                logger.warning(f'[AGS] UPDATE failed: {_age}')
                        if not order:
                            logger.warning(f"[EXECUTION] Order skipped: {symbol} (can_open=False)")
                    except Exception as e:
                        logger.error(f"[EXECUTION] Failed for {symbol}: {e}", exc_info=True)
                        self.repo.log_system_event(event="SIGNAL_GATE_ERROR", module="signal_gate", message=f"Execution failed for {symbol}: {str(e)}", level="ERROR", traceback=traceback.format_exc())
                else:
                    reject_reasons[reason] = reject_reasons.get(reason, 0) + 1
                    rejected_symbols.setdefault(reason, []).append(symbol)

            # --- Детальный лог ---
            total = len(signals)
            n_approved = len(approved)
            n_rejected = total - n_approved

            logger.info(
                f"SignalGate: {n_approved}/{total} approved, "
                f"{n_rejected} rejected | "
                f"open_positions: {open_before_cycle}+{n_approved}/{max_pos}, "
                f"cooldown: {cooldown_minutes}m"
            )

            if reject_reasons:
                parts = []
                for reason, count in reject_reasons.items():
                    syms = rejected_symbols.get(reason, [])
                    sym_preview = ", ".join(s.split("/")[0] for s in syms[:5])
                    if len(syms) > 5:
                        sym_preview += f" (+{len(syms) - 5})"
                    parts.append(f"{reason}: {count} [{sym_preview}]")
                logger.info(f"SignalGate reject breakdown: {' | '.join(parts)}")

            if approved:
                sym_list = ", ".join(s.get("symbol", "?").split("/")[0] for s in approved)
                logger.info(f"SignalGate approved: {sym_list}")

            # ── DATA CORE: batch write filter results ─────────────
            try:
                entries = []
                for signal in signals:
                    symbol = signal.get("symbol", "?")
                    gate_passed = symbol in cycle_approved

                    if gate_passed:
                        decision = "APPROVED"
                    else:
                        reason = next(
                            (r for r, syms in rejected_symbols.items() if symbol in syms),
                            "unknown",
                        )
                        decision = f"REJECTED:{reason}"

                    entries.append(
                        {
                            "ts": signal.get("scanned_at"),
                            "symbol": symbol,
                            "score": signal.get("score"),
                            "reasons": signal.get("reasons", []),
                            "candidate_status": signal.get("candidate_status"),
                            "filter_decision": decision,
                        }
                    )

                write_filter_results_batch(entries)
                logger.info(f"[FILTER] DATA CORE: {len(entries)} results written")
            except Exception as e:
                logger.error(f"[FILTER] DATA CORE write failed: {e}")
                self.repo.log_system_event(event="SIGNAL_GATE_ERROR", module="signal_gate", message=f"DATA CORE write failed: {str(e)}", level="ERROR", traceback=traceback.format_exc())

            await self.event_bus.publish("signal_gate.done", {"approved": approved})
            return approved

        except Exception as e:
            logger.error(f"SignalGate error: {e}", exc_info=True)
            self.repo.log_system_event(event="SIGNAL_GATE_ERROR", module="signal_gate", message=str(e), level="ERROR", traceback=traceback.format_exc())
            return []

    def _check(
        self,
        signal: dict,
        all_open: set,
        cycle_approved: set,
        max_pos: int,
        cooldown_minutes: int,
        session_name: str = "",
    ) -> tuple[bool, str]:
        symbol = signal.get("symbol")

        # 0. SESSION_ARCHIVED — временно отключено:
        # разрешаем паре повторно участвовать в той же сессии
        if session_name:
            reset_pair_if_new_session(symbol, session_name)

        # 1. Символ уже approved в этом цикле
        if symbol in cycle_approved:
            return False, "duplicate_in_cycle"

        # 2. Символ уже открыт (память orchestrator + DB)
        if symbol in all_open:
            return False, "already_open"

        # 3. Cross-cycle cooldown по конкретному символу
        if symbol in self._recent_signals:
            elapsed = (datetime.now() - self._recent_signals[symbol]).total_seconds() / 60
            if elapsed < cooldown_minutes:
                return False, "cooldown"

        # 4. Лимит позиций
        if len(all_open) >= max_pos:
            return False, "max_positions"

        return True, ""
