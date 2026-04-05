# execution_engine.py

from datetime import datetime
from modules.position_monitor import add_position
from services.telegram_notifier import get_notifier
from modules.risk_manager import can_trade, get_state
from modules.telegram_control import get_mode
from modules.config import MODE, DEFAULT_BALANCE, get_exchange_name
from modules.exchange_client import ExchangeClient
from core.id_manager import IdManager
from storage.db.repository import Repository

OPEN_POSITIONS = {}

_ghost_state_active = False
_last_ghost_alert_time: datetime | None = None
_GHOST_ALERT_COOLDOWN_SEC = 300  # 5 минут

MAX_POSITIONS = 500
RISK_PER_TRADE = 0.01  # 1%

client = ExchangeClient()
client.connect()
id_manager = IdManager()


def sync_open_positions_with_db():
    """
    Двусторонняя синхронизация OPEN_POSITIONS (execution_engine + position_monitor) с БД.
    БД = единственный источник истины.
    1) Удаляет из памяти позиции, которых нет в БД (stale/ghost).
    2) Добавляет в память позиции, которые есть в БД, но отсутствуют в памяти (DB extra).
    """
    try:
        from modules.position_monitor import OPEN_POSITIONS as MON_POS

        repo = Repository()
        active_trade_ids = repo.get_active_trade_ids()
        active_symbols = repo.get_open_symbols()

        def _is_stale(pos):
            tid = pos.get("trade_id") if isinstance(pos, dict) else None
            sym = pos.get("symbol") if isinstance(pos, dict) else None
            if tid:
                return tid not in active_trade_ids
            return sym not in active_symbols if sym else True

        # --- Phase 1: Remove stale (memory-only) positions ---
        removed = 0

        stale_ee = [s for s, p in OPEN_POSITIONS.items() if _is_stale(p)]
        for symbol in stale_ee:
            pos = OPEN_POSITIONS.pop(symbol, None)
            tid = pos.get("trade_id") if pos else None
            print(f"[SYNC] removing stale EE position: {symbol} trade_id={tid}")
            removed += 1

        stale_mon = [s for s, p in MON_POS.items() if _is_stale(p)]
        for symbol in stale_mon:
            pos = MON_POS.pop(symbol, None)
            tid = pos.get("trade_id") if pos else None
            print(f"[SYNC] removing stale MON position: {symbol} trade_id={tid}")
            removed += 1

        # --- Phase 2: Add DB positions missing from memory ---
        ee_symbols = set(OPEN_POSITIONS.keys())
        missing_symbols = active_symbols - ee_symbols
        added = 0

        if missing_symbols:
            db_positions = repo.get_open_positions()
            db_by_symbol = {p["symbol"]: p for p in db_positions}

            for symbol in missing_symbols:
                pos = db_by_symbol.get(symbol)
                if not pos:
                    continue

                direction = str(pos.get("direction", "long")).lower()
                side = "SHORT" if direction == "short" else "LONG"
                entry = float(pos.get("entry") or pos.get("fill_price") or 0)

                restored_pos = {
                    **pos,
                    "symbol": symbol,
                    "side": side,
                    "direction": direction,
                    "entry": entry,
                    "entry_price": entry,
                    "fill_price": entry,
                    "current_price": entry,
                    "status": "open",
                    "size_usdt": pos.get("size_usdt") or pos.get("risk_usdt"),
                    "notional": pos.get("notional") or pos.get("risk_usdt"),
                }

                OPEN_POSITIONS[symbol] = restored_pos
                if symbol not in MON_POS:
                    MON_POS[symbol] = {
                        **restored_pos,
                        "opened_at": pos.get("opened_at", datetime.now()),
                    }
                added += 1

        db_active = len(active_trade_ids)
        ee_count = len(OPEN_POSITIONS)
        mon_count = len(MON_POS)

        print(f"[SYNC] DB={db_active} EE={ee_count} MON={mon_count} → FIXED: +{added} / -{removed}")


    except Exception as e:
        print(f"[SYNC ERROR] {e}")
        try:
            Repository().log_system_event(
                event="OPEN_POS_SYNC_ERROR",
                module="execution_engine",
                message=f"sync_open_positions_with_db failed: {e}",
                level="ERROR",
            )
        except Exception:
            pass


def log_health_pre_sync(ee_count: int, mon_count: int, orch_count: int, db_active: int):
    """Диагностический лог ДО sync — показывает рассинхрон между контурами."""
    msg = (
        f"[HEALTH_PRE_SYNC] ee={ee_count} mon={mon_count} "
        f"orch={orch_count} db_active={db_active}"
    )
    print(msg)


def log_health_post_sync(ee_count: int, mon_count: int, orch_count: int, db_active: int):
    """Диагностический лог ПОСЛЕ полного sync всех контуров."""
    msg = (
        f"[HEALTH_POST_SYNC] ee={ee_count} mon={mon_count} "
        f"orch={orch_count} db_active={db_active}"
    )
    print(msg)


def log_health(ee_count: int, mon_count: int, orch_count: int, db_active: int):
    """Печатает HEALTH-строку, пишет ERROR и шлёт Telegram если ghost-state."""
    global _ghost_state_active, _last_ghost_alert_time

    msg = f"[HEALTH] ee={ee_count} mon={mon_count} orch={orch_count} db_active={db_active}"
    memory_has_positions = ee_count > 0 or mon_count > 0 or orch_count > 0
    is_ghost = db_active == 0 and memory_has_positions

    if is_ghost:
        print(f"[ERROR] {msg} — STALE POSITIONS IN MEMORY, DB HAS NONE ACTIVE")
        try:
            Repository().log_system_event(
                event="OPEN_POS_SYNC_ERROR",
                module="execution_engine",
                message=f"HEALTH MISMATCH: {msg}",
                level="ERROR",
            )
        except Exception:
            pass

        # Telegram-алерт с анти-спамом 5 мин
        now = datetime.now()
        send_alert = False
        if _last_ghost_alert_time is None:
            send_alert = True
        else:
            elapsed = (now - _last_ghost_alert_time).total_seconds()
            if elapsed >= _GHOST_ALERT_COOLDOWN_SEC:
                send_alert = True

        if send_alert:
            _last_ghost_alert_time = now
            try:
                notifier = get_notifier()
                if notifier:
                    import asyncio
                    alert_text = (
                        f"⚠️ APEX ALERT\n"
                        f"Ghost-state detected\n\n"
                        f"EE={ee_count} MON={mon_count} ORCH={orch_count} but DB_active=0\n"
                        f"Positions resynced automatically"
                    )
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.ensure_future(notifier.send(alert_text))
                        else:
                            loop.run_until_complete(notifier.send(alert_text))
                    except Exception:
                        asyncio.run(notifier.send(alert_text))
            except Exception as e:
                print(f"[GHOST_ALERT_ERROR] {e}")

        _ghost_state_active = True

    else:
        print(msg)

        # Если ghost-state был и теперь исправился — логируем recovery
        if _ghost_state_active:
            _ghost_state_active = False
            print(f"[RECOVERY] OPEN_POS_SYNC_RECOVERED — {msg}")
            try:
                Repository().log_system_event(
                    event="OPEN_POS_SYNC_RECOVERED",
                    module="execution_engine",
                    message=f"Ghost-state resolved: {msg}",
                    level="WARNING",
                )
            except Exception:
                pass


def can_open(symbol: str) -> bool:
    # БД = источник истины. Перед проверкой всегда чистим stale-позиции из памяти.
    sync_open_positions_with_db()

    if symbol in OPEN_POSITIONS:
        return False
    if len(OPEN_POSITIONS) >= MAX_POSITIONS:
        return False
    return True


# ── APEX PROTOCOL™ — Position Sizing ─────────────────────────────────────

# Safe-cap: risk-normalized size не может превышать param_size_usdt * этот множитель
RISK_NORM_CAP_MULT = 10.0


def calculate_position_size(balance: float, price: float) -> float:
    """Режим FIXED_NOTIONAL: size = param_size_usdt / price (обратная совместимость)."""
    if price <= 0:
        return 0.0

    try:
        from services.test_control import read as tc_read
        tc = tc_read()
        fixed_size = float(tc.get("param_size_usdt", 0) or 0)
        if fixed_size > 0:
            return round(fixed_size / price, 6)
    except Exception as e:
        print(f"[EE] calculate_position_size test_control error: {e}")

    risk_amount = balance * RISK_PER_TRADE
    size = risk_amount / price
    return round(size, 6)


def calculate_risk_normalized_size(
    risk_usdt: float,
    entry: float,
    sl: float,
    size_usdt_cap: float = 0.0
) -> tuple:
    """
    Режим RISK_NORMALIZED: size = param_risk_usdt / abs(entry - sl)

    Returns: (size, risk_distance, sizing_mode, reject_reason)
    reject_reason = None если OK, иначе строка с причиной отказа.
    """
    # Guard: входные значения
    if not entry or entry <= 0:
        return 0.0, 0.0, "RISK_NORMALIZED", "INVALID_ENTRY"
    if not sl or sl <= 0:
        return 0.0, 0.0, "RISK_NORMALIZED", "INVALID_SL"
    if not risk_usdt or risk_usdt <= 0:
        return 0.0, 0.0, "RISK_NORMALIZED", "INVALID_RISK_USDT"

    risk_distance = abs(entry - sl)

    if risk_distance <= 0:
        return 0.0, 0.0, "RISK_NORMALIZED", "SL_EQUALS_ENTRY"

    size = round(risk_usdt / risk_distance, 6)

    if size <= 0:
        return 0.0, risk_distance, "RISK_NORMALIZED", "SIZE_ZERO_AFTER_CALC"

    # Safe-cap: ограничение notional сверху
    if size_usdt_cap > 0:
        max_size = round((size_usdt_cap * RISK_NORM_CAP_MULT) / entry, 6)
        if size > max_size:
            return 0.0, risk_distance, "RISK_NORMALIZED", (
                f"SIZE_CAP_EXCEEDED: calc={size} max={max_size} "
                f"(cap={size_usdt_cap}*{RISK_NORM_CAP_MULT}/entry={entry})"
            )

    return size, risk_distance, "RISK_NORMALIZED", None


def build_order(signal: dict, balance: float) -> dict:
    symbol = signal["symbol"]

    price = float(signal.get("entry_price") or signal.get("entry") or signal.get("price") or 0)
    if price <= 0:
        raise ValueError(f"INVALID PRICE for {symbol} -> {price}")

    direction = str(signal.get("direction", "long")).lower()
    side = direction.upper()

    sl = float(signal.get("sl") or 0)
    tp1 = float(signal.get("tp1") or 0)
    tp2 = float(signal.get("tp2") or 0)
    tp3 = float(signal.get("tp3") or 0)

    opened_at = datetime.utcnow().isoformat()
    trade_id = id_manager.next_trade_id()

    try:
        from services.test_control import read as tc_read
        tc = tc_read()
        leverage       = int(tc.get("param_leverage", 1) or 1)
        size_usdt_cfg  = float(tc.get("param_size_usdt", 500) or 500)
        risk_usdt_cfg  = float(tc.get("param_risk_usdt", 0) or 0)
    except Exception as e:
        print(f"[EE] build_order test_control error: {e}")
        leverage      = 1
        size_usdt_cfg = 500.0
        risk_usdt_cfg = 0.0

    # ── APEX PROTOCOL™ — Sizing Mode Selection ───────────────────────────
    sl_dist    = 0.0
    sizing_mode = "FIXED_NOTIONAL"

    if risk_usdt_cfg > 0 and price > 0 and sl > 0:
        # Режим RISK_NORMALIZED: size = param_risk_usdt / abs(entry - sl)
        size, sl_dist, sizing_mode, reject_reason = calculate_risk_normalized_size(
            risk_usdt=risk_usdt_cfg,
            entry=price,
            sl=sl,
            size_usdt_cap=size_usdt_cfg
        )
        if reject_reason is not None:
            raise ValueError(
                f"RISK_NORM_REJECT [{symbol}]: {reject_reason} "
                f"entry={price} sl={sl} risk_usdt={risk_usdt_cfg}"
            )
    else:
        # Режим FIXED_NOTIONAL: size = param_size_usdt / price (обратная совместимость)
        size = calculate_position_size(balance, price)
        sl_dist = abs(price - sl) if (price and sl) else 0.0
    # ─────────────────────────────────────────────────────────────────────

    if size <= 0:
        raise ValueError(f"INVALID SIZE [{sizing_mode}] for {symbol} -> {size}")

    notional = round(price * size, 2)

    # Реальный риск считаем одинаково для обоих режимов: distance_to_sl * size
    risk_usdt = round(sl_dist * size, 2) if sl_dist > 0 else 0.0
    risk_pct = round((risk_usdt / balance) * 100, 2) if balance > 0 else 0

    tp1_val  = float(signal.get("tp1") or 0)
    tp1_dist = abs(tp1_val - price) if (price and tp1_val) else 0

    rr = round(tp1_dist / sl_dist, 2) if sl_dist > 0 else 0

    # RC-7: entry_delay_sec — время от генерации сигнала до исполнения
    entry_delay_sec = 0
    generated_at_str = signal.get("generated_at")
    if generated_at_str:
        try:
            gen_dt = datetime.fromisoformat(str(generated_at_str).replace("Z", ""))
            now_dt = datetime.utcnow()
            entry_delay_sec = max(0, int((now_dt - gen_dt).total_seconds()))
        except Exception:
            entry_delay_sec = 0

    # RC-7: session_open_minutes_from_start
    session_open_minutes = None
    session_open_str = signal.get("session_open_time")
    if session_open_str:
        try:
            sot = datetime.fromisoformat(str(session_open_str).replace("Z", "+00:00"))
            now_utc = datetime.utcnow()
            if sot.tzinfo is not None:
                from datetime import timezone as _tz
                now_utc = now_utc.replace(tzinfo=_tz.utc)
            session_open_minutes = max(0, int((now_utc - sot).total_seconds() / 60))
        except Exception:
            session_open_minutes = None

    # RC-7: pre_session_flag
    pre_session_flag = 0
    if session_open_minutes is not None and session_open_minutes < 0:
        pre_session_flag = 1
        session_open_minutes = 0

    # RC-7: tick_size, step_size, min_notional — из ccxt markets (если доступны)
    tick_size_val = None
    step_size_val = None
    min_notional_val = None
    try:
        if client.exchange and hasattr(client.exchange, 'markets') and client.exchange.markets:
            mkt = client.exchange.markets.get(symbol)
            if mkt:
                prec = mkt.get("precision", {})
                lims = mkt.get("limits", {})
                tick_size_val = prec.get("price")
                step_size_val = prec.get("amount")
                cost_limits = lims.get("cost", {})
                min_notional_val = cost_limits.get("min")
                amount_limits = lims.get("amount", {})
                min_qty_val = amount_limits.get("min")
                price_precision_val = len(str(tick_size_val).rstrip("0").split(".")[1]) if tick_size_val and "." in str(tick_size_val) else None
                qty_precision_val = len(str(step_size_val).rstrip("0").split(".")[1]) if step_size_val and "." in str(step_size_val) else None
                # APEX_MASTER_PAIRS — автозаполнение справочника
                try:
                    from datetime import datetime as _dt
                    _now = _dt.utcnow().isoformat()
                    _repo = Repository()
                    _repo.conn.execute("""
                        INSERT OR IGNORE INTO APEX_MASTER_PAIRS
                        (symbol, exchange, market_type, base_asset, quote_asset,
                         tick_size, step_size, min_notional, min_qty,
                         price_precision, qty_precision, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        symbol,
                        get_exchange_name(),
                        mkt.get("type", "FUTURES").upper(),
                        mkt.get("base", ""),
                        mkt.get("quote", ""),
                        tick_size_val,
                        step_size_val,
                        min_notional_val,
                        min_qty_val,
                        price_precision_val,
                        qty_precision_val,
                        "ACTIVE",
                        _now,
                        _now,
                    ))
                    _repo.conn.commit()
                except Exception:
                    pass
    except Exception:
        pass

    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "side": side,
        "strategy": signal.get("strategy", "APEX_ORB"),
        "session_name": signal.get("session_name"),
        "session_hour": signal.get("entry_hour"),
        "entry": price,
        "entry_price": price,
        "fill_price": price,
        "opened_at": opened_at,
        "timestamp": opened_at,
        "size": size,
        "notional": notional,
        "size_usdt": notional,
        "risk_usdt": risk_usdt,
        "risk_pct": risk_pct,
        "rr": rr,
        "leverage": leverage,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "mode": MODE,
        "exchange_name": signal.get("exchange_name") or get_exchange_name(),
        "entry_signal_score": signal.get("score"),
        "scanner_score": signal.get("score"),
        "session_open_time": signal.get("session_open_time"),
        "entry_reason_code": signal.get("entry_reason_code"),
        "entry_reason_text": signal.get("entry_reason_text"),
        "setup_name": signal.get("setup_name", "APEX_ORB_5M"),
        "strategy_family": signal.get("strategy_family", "ORB"),
        "strategy_version": signal.get("strategy_version", "v1"),
        "setup_variant": signal.get("setup_variant", "A"),
        "market_type": signal.get("market_type", "FUTURES"),
        "instrument_type": signal.get("instrument_type", "PERPETUAL"),
        "calc_version": signal.get("calc_version", "v2.0"),
        "source_pipeline": signal.get("source_pipeline"),
        "event_context": signal.get("event_context"),
        "account_balance_snapshot": signal.get("account_balance_snapshot") or balance,
        "risk_model_name": signal.get("risk_model_name"),
        "filter_score": signal.get("filter_score"),
        "confidence_score": signal.get("confidence_score"),
        "setup_grade": signal.get("setup_grade"),
        "entry_quality_flag": signal.get("entry_quality_flag"),
        "market_phase": signal.get("market_phase"),
        # RC-7: новые поля
        "entry_delay_sec": entry_delay_sec,
        "session_open_minutes_from_start": session_open_minutes,
        "pre_session_flag": pre_session_flag,
        "tick_size": tick_size_val,
        "step_size": step_size_val,
        "min_notional": min_notional_val,
        "orb_high": signal.get("orb_high"),
        "orb_low":  signal.get("orb_low"),
        "orb_mid":  signal.get("orb_mid"),
        "risk_per_trade_pct_plan": round(RISK_PER_TRADE * 100, 4),
        "risk_per_trade_usdt_plan": round(balance * RISK_PER_TRADE, 4),
    }


def execute(signal: dict, balance: float = DEFAULT_BALANCE):
    symbol = signal["symbol"]
    print(f"[EXECUTION TRY] {symbol}")

    if get_mode() != "RUN":
        print(f"[BLOCKED] {symbol} (mode={get_mode()})")
        return None

    if not can_open(symbol):
        print(f"[BLOCKED] {symbol} (already open or max positions)")
        return None

    if not can_trade(len(OPEN_POSITIONS)):
        print(f"[BLOCKED] {symbol} (risk manager)")
        return None

    # Safety check for LIVE
    if MODE == "LIVE":
        state = get_state()
        if state["blocked"]:
            print(f"[BLOCKED] {symbol} (risk blocked)")
            return None
        if balance <= 0:
            print(f"[BLOCKED] {symbol} (no balance)")
            return None

    order = build_order(signal, balance)

    # Запись в БД при успешном открытии
    def _persist_order(order_data):
        try:
            repo = Repository()
            repo.log_execution(order_data)
        except Exception as e:
            import traceback as _tb
            print(f"[DB ERROR] {order_data.get('symbol')}: {e}")
            try:
                _repo_err = Repository()
                _repo_err.log_system_event(
                    event="DB_WRITE_ERROR",
                    module="execution_engine",
                    message=f"log_execution failed for {order_data.get('symbol')}: {e}",
                    level="ERROR",
                    traceback=_tb.format_exc(),
                )
            except Exception as e2:
                print(f"[EE] log_system_event fallback also failed: {e2}")

    # SIMULATION
    if MODE == "SIMULATION":
        OPEN_POSITIONS[symbol] = order
        add_position(order)
        _persist_order(order)
        print(f"[OPENED] {symbol} [SIM]")

        try:
            import asyncio
            notifier = get_notifier()
            if notifier:
                asyncio.ensure_future(notifier.notify_open(order))
        except Exception as e:
            print(f"[EE] Telegram notify error: {e}")

        return order

    # PAPER
    if MODE == "PAPER":
        OPEN_POSITIONS[symbol] = order
        add_position(order)
        _persist_order(order)
        print(f"[OPENED] {symbol} [PAPER]")

        try:
            import asyncio
            notifier = get_notifier()
            if notifier:
                asyncio.ensure_future(notifier.notify_open(order))
        except Exception as e:
            print(f"[EE] Telegram notify error: {e}")

        return order

    # LIVE
    if MODE == "LIVE":
        success = client.place_order(
            symbol,
            order["side"],
            order["size"]
        )

        if success:
            OPEN_POSITIONS[symbol] = order
            add_position(order)
            _persist_order(order)
            print(f"[OPENED] {symbol} [LIVE]")

            try:
                import asyncio
                notifier = get_notifier()
                if notifier:
                    asyncio.ensure_future(notifier.notify_open(order))
            except Exception as e:
                print(f"[EE] Telegram notify error: {e}")

            return order

        print(f"[BLOCKED] {symbol} (live order failed)")
        return None

    print(f"[BLOCKED] {symbol} (unknown mode={MODE})")
    return None
