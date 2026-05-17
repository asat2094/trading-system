-- QuestDB OHLCV tables with WAL + DEDUP for idempotent re-ingestion
-- Execute each statement separately (QuestDB doesn't support multi-statement in one call)

CREATE TABLE IF NOT EXISTS ohlcv_1min (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE,
  high    DOUBLE,
  low     DOUBLE,
  close   DOUBLE,
  volume  LONG
) TIMESTAMP(ts)
  PARTITION BY DAY
  WAL
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS ohlcv_hourly (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE,
  high    DOUBLE,
  low     DOUBLE,
  close   DOUBLE,
  volume  LONG
) TIMESTAMP(ts)
  PARTITION BY MONTH
  WAL
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
  ts             TIMESTAMP,
  symbol         SYMBOL CAPACITY 4096 CACHE,
  open           DOUBLE,
  high           DOUBLE,
  low            DOUBLE,
  close          DOUBLE,
  volume         LONG,
  adjusted_close DOUBLE
) TIMESTAMP(ts)
  PARTITION BY YEAR
  WAL
  DEDUP UPSERT KEYS(ts, symbol);
