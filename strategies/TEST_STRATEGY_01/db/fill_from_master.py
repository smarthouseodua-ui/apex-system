import sqlite3
from datetime import datetime

DB = "/root/apex-system/storage/db/sqlite/apex.db"

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Чистим таблицу перед тестом
cur.execute("DELETE FROM APEX_STRATEGY_TEST_STRATEGY_01")

# Копируем данные из master (scanner)
cur.execute("""
INSERT INTO APEX_STRATEGY_TEST_STRATEGY_01 (
    source_scanner_id,
    symbol,
    price,
    volume,
    volatility,
    session,
    scanned_at,
    scan_run_id,
    score,
    candidate_status,
    trend,
    ema,
    distance_to_ema,
    is_premium_zone,
    is_discount_zone,
    is_equilibrium_zone,
    bos,
    choch,
    liq_sweep,
    fvg,
    ob,
    reason_tags,
    raw_json,

    strategy_name,
    strategy_status,
    copied_at,

    entry_price,
    direction,
    trade_lifetime_min
)
SELECT
    id,
    symbol,
    price,
    volume,
    volatility,
    session,
    scanned_at,
    scan_run_id,
    score,
    candidate_status,
    trend,
    ema,
    distance_to_ema,
    is_premium_zone,
    is_discount_zone,
    is_equilibrium_zone,
    bos,
    choch,
    liq_sweep,
    fvg,
    ob,
    reason_tags,
    raw_json,

    'TEST_STRATEGY_01',
    'COPIED',
    ?,

    price,
    CASE
        WHEN trend = 'bullish' THEN 'LONG'
        WHEN trend = 'bearish' THEN 'SHORT'
        ELSE NULL
    END,
    0
FROM APEX_MASTER_SCANNER
WHERE candidate_status IN ('PASSED','WATCH','SENT_TO_FILTER')
""", (datetime.utcnow().isoformat(),))

conn.commit()

cur.execute("SELECT COUNT(*) FROM APEX_STRATEGY_TEST_STRATEGY_01")
count = cur.fetchone()[0]

print(f"OK: FILLED {count} ROWS")

conn.close()
