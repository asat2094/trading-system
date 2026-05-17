from prometheus_client import Counter, Histogram, Gauge

ingestion_rows = Counter(
    "ingestion_rows_written_total",
    "Rows written per ingestion run",
    ["source", "timeframe"],
)
ingestion_duration = Histogram(
    "ingestion_duration_seconds",
    "Duration of ingestion workflow",
    ["workflow"],
)
ingestion_failures = Counter(
    "ingestion_failures_total",
    "Failed data fetches per source",
    ["source"],
)
data_gaps = Counter(
    "data_gap_detected_total",
    "Missing candles detected",
    ["symbol", "timeframe"],
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
llm_tool_calls = Counter(
    "llm_tool_calls_total",
    "LLM tool use frequency",
    ["tool"],
)
