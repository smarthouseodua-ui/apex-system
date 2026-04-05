"""
APEX PROTOCOL™ — Database Init
Таблицы с префиксами SKL01 (Skeleton 01) и SYS (системные).
"""

import sqlite3
import logging
import os

logger = logging.getLogger("apex.db")

DB_PATH = "/root/apex-system/storage/db/sqlite/apex.db"


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""

        -- ══════════════════════════════════════
        -- СИСТЕМНЫЕ ТАБЛИЦЫ (SYS)
        -- ══════════════════════════════════════

        CREATE TABLE IF NOT EXISTS SYS_skeleton_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skeleton_id TEXT NOT NULL,
            name TEXT NOT NULL,
            strategy TEXT,
            mode TEXT DEFAULT 'simulation',
            exchange TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS SYS_system_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module TEXT NOT NULL,
            server TEXT,
            status TEXT,
            version TEXT,
            updated_at TEXT
        );

        -- ══════════════════════════════════════
        -- SKELETON 01 — Session ORB 5m (тест)
        -- ══════════════════════════════════════

        -- T01 — Scanner
        CREATE TABLE IF NOT EXISTS APEX_MASTER_SCANNER (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            price REAL,
            volume REAL,
            volatility REAL,
            session TEXT,
            scanned_at TEXT
        );

        -- T08 — System Events
        CREATE TABLE IF NOT EXISTS APEX_MASTER_ERRORS (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT,
            module TEXT,
            message TEXT,
            level TEXT DEFAULT 'INFO',
            created_at TEXT
        );

        -- T09 — Pre-session SMC log
        CREATE TABLE IF NOT EXISTS APEX_MASTER_MARKET (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name            TEXT,
            timezone                TEXT,
            pre_session_start_time  TEXT,
            session_open_time       TEXT,
            analysis_time           TEXT,
            premium_zone_status     TEXT,
            discount_zone_status    TEXT,
            market_structure_state  TEXT,
            bos_detected            INTEGER,
            choch_detected          INTEGER,
            order_block_present     INTEGER,
            fvg_present             INTEGER,
            liquidity_pool_present  INTEGER,
            mitigation_present      INTEGER,
            displacement_present    INTEGER,
            sweep_present           INTEGER,
            analyst_comment_short   TEXT,
            created_at              TEXT
        );

        -- T10 — Archive log
        CREATE TABLE IF NOT EXISTS APEX_MASTER_ARCHIVE (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name      TEXT,
            timezone          TEXT,
            symbol            TEXT,
            direction         TEXT,
            entry_time        TEXT,
            close_time        TEXT,
            close_event_type  TEXT,
            result_label      TEXT,
            minutes_to_close  INTEGER,
            archived_at       TEXT,
            archive_reason    TEXT
        );

        -- T11 — Session stats
        CREATE TABLE IF NOT EXISTS APEX_MASTER_SESSIONS (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_name                TEXT,
            stat_date                   TEXT,
            total_trades                INTEGER DEFAULT 0,
            total_wins                  INTEGER DEFAULT 0,
            total_losses                INTEGER DEFAULT 0,
            winrate                     REAL DEFAULT 0.0,
            avg_minutes_to_close        REAL DEFAULT 0.0,
            avg_R_result                REAL DEFAULT 0.0,
            count_tp1                   INTEGER DEFAULT 0,
            count_tp2                   INTEGER DEFAULT 0,
            count_tp3                   INTEGER DEFAULT 0,
            count_stop_loss             INTEGER DEFAULT 0,
            count_force_close           INTEGER DEFAULT 0,
            count_observation_entered   INTEGER DEFAULT 0,
            updated_at                  TEXT,
            UNIQUE(session_name, stat_date)
        );

        -- T12 — Pair session participation
        CREATE TABLE IF NOT EXISTS APEX_MASTER_PAIRS (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT,
            session_name  TEXT,
            status        TEXT,
            stat_date     TEXT,
            updated_at    TEXT,
            UNIQUE(symbol, session_name, stat_date)
        );

        -- ══════════════════════════════════════
        -- APEX MASTER TRADE — единая таблица сделок
        -- ══════════════════════════════════════

        CREATE TABLE IF NOT EXISTS APEX_MASTER_TRADE (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id              TEXT UNIQUE,
            symbol                TEXT,
            direction             TEXT,
            strategy              TEXT,
            mode                  TEXT,
            session_name          TEXT,
            session_hour          INTEGER,
            opened_at             TEXT,
            closed_at             TEXT,
            duration_minutes      INTEGER,
            entry                 REAL,
            sl                    REAL,
            tp1                   REAL,
            tp2                   REAL,
            tp3                   REAL,
            size                  REAL,
            leverage              INTEGER,
            risk_pct              REAL,
            risk_usdt             REAL,
            rr                    REAL,
            fill_price            REAL,
            slippage              REAL,
            commission            REAL,
            close_price           REAL,
            close_reason          TEXT,
            exit_route            TEXT,
            tp_level_reached_max  INTEGER,
            minutes_to_tp1        INTEGER,
            minutes_to_sl         INTEGER,
            minutes_to_close      INTEGER,
            pnl_pct               REAL,
            pnl_usdt              REAL,
            result_label          TEXT,
            finalized_at          TEXT,
            market_phase          TEXT,
            bos_present           INTEGER,
            choch_present         INTEGER,
            entry_in_discount     INTEGER,
            entry_near_ob         INTEGER,
            entry_near_fvg        INTEGER,
            orb_high              REAL,
            orb_low               REAL,
            orb_mid               REAL,
            retest_price          REAL,
            created_at            TEXT DEFAULT (datetime('now'))
        );

    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialized: {DB_PATH}")
    print(f"Database initialized: {DB_PATH}")
    print("Tables created:")
    print("  SYS_skeleton_registry")
    print("  SYS_system_registry")
    print("  APEX_MASTER_SCANNER")
    print("  APEX_MASTER_ERRORS")
    print("  APEX_MASTER_MARKET")
    print("  APEX_MASTER_ARCHIVE")
    print("  APEX_MASTER_SESSIONS")
    print("  APEX_MASTER_PAIRS")
    print("  APEX_MASTER_TRADE")


if __name__ == "__main__":
    init_db()
