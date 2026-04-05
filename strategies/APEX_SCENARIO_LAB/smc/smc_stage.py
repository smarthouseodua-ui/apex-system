"""
APEX PROTOCOL™ — APEX_SCENARIO_LAB
smc_stage.py — получение SMC-контекста перед входом в сделку.
Три режима: SKIP | REQUIRED_SOFT | REQUIRED_STRICT
"""
import sys
import logging

sys.path.insert(0, '/root/apex-system')
logger = logging.getLogger("apex.scenario_lab.smc_stage")

DEFAULT_CONTEXT = {
    "market_phase": None, "bos_present": 0, "choch_present": 0,
    "entry_in_discount": 0, "entry_near_ob": 0, "entry_near_fvg": 0,
    "premium_zone": None, "discount_zone": None,
    "orb_high": None, "orb_low": None, "orb_mid": None, "source": "DEFAULT",
}


def _from_master_market(symbol: str) -> dict | None:
    try:
        from storage.db.init_db import get_connection
        conn = get_connection()
        row = conn.execute("""
            SELECT market_structure_state, bos_detected, choch_detected,
                   order_block_present, fvg_present,
                   premium_zone_status, discount_zone_status
            FROM APEX_MASTER_MARKET
            WHERE symbol = ?
            ORDER BY id DESC LIMIT 1
        """, (symbol,)).fetchone()
        if not row:
            return None
        return {
            "market_phase":      row["market_structure_state"],
            "bos_present":       row["bos_detected"] or 0,
            "choch_present":     row["choch_detected"] or 0,
            "entry_in_discount": 1 if (row["discount_zone_status"] or "").upper() == "DISCOUNT" else 0,
            "entry_near_ob":     row["order_block_present"] or 0,
            "entry_near_fvg":    row["fvg_present"] or 0,
            "premium_zone":      row["premium_zone_status"],
            "discount_zone":     row["discount_zone_status"],
            "orb_high": None, "orb_low": None, "orb_mid": None,
            "source": "APEX_MASTER_MARKET",
        }
    except Exception as e:
        logger.warning(f"smc_stage._from_master_market({symbol}): {e}")
        return None


def _from_smc_analyzer(symbol: str) -> dict | None:
    try:
        from modules.smc_analyzer import analyze
        result = analyze(symbol)
        if not result:
            return None
        return {
            "market_phase":      result.get("market_phase"),
            "bos_present":       result.get("bos", 0),
            "choch_present":     result.get("choch", 0),
            "entry_in_discount": result.get("entry_in_discount", 0),
            "entry_near_ob":     result.get("ob", 0),
            "entry_near_fvg":    result.get("fvg", 0),
            "premium_zone":      result.get("premium_zone_status"),
            "discount_zone":     result.get("discount_zone_status"),
            "orb_high": result.get("orb_high"),
            "orb_low":  result.get("orb_low"),
            "orb_mid":  result.get("orb_mid"),
            "source": "SMC_ANALYZER",
        }
    except Exception as e:
        logger.warning(f"smc_stage._from_smc_analyzer({symbol}): {e}")
        return None


def _log_unavailable(symbol: str, mode: str):
    try:
        from storage.db.repository import Repository
        Repository().log_system_event(
            event="SMC_CONTEXT_UNAVAILABLE",
            module="scenario_lab.smc_stage",
            message=f"symbol={symbol} mode={mode}",
            level="WARNING",
        )
    except Exception:
        pass


def get_context(symbol: str, mode: str) -> dict | None:
    if mode == "SKIP":
        return {}
    ctx = _from_master_market(symbol)
    if ctx is None:
        ctx = _from_smc_analyzer(symbol)
    if ctx is not None:
        return ctx
    _log_unavailable(symbol, mode)
    if mode == "REQUIRED_SOFT":
        logger.warning(f"smc_stage: no context for {symbol} → DEFAULT_CONTEXT")
        return {**DEFAULT_CONTEXT, "source": "DEFAULT"}
    if mode == "REQUIRED_STRICT":
        logger.warning(f"smc_stage: no context for {symbol} → None (skip)")
        return None
    return {}
