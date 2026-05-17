from prometheus_client import Counter, Histogram

ingestion_rows = Counter(
    "ingestion_rows_written_total",
    "Rows written per ingestion run",
    ["source", "timeframe"],
)
ingestion_failures = Counter(
    "ingestion_failures_total",
    "Failed data fetches per source",
    ["source"],
)
scanner_duration = Histogram(
    "scanner_run_duration_seconds",
    "Scanner execution time",
    ["scan_name"],
)
signals_fired = Counter(
    "signals_fired_total",
    "Signals detected per type",
    ["signal_name", "timeframe", "direction"],
)
cache_hits = Counter("redis_cache_hits_total", "Redis cache hits")
cache_misses = Counter("redis_cache_misses_total", "Redis cache misses")
