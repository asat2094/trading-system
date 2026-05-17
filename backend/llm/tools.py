TOOL_DEFINITIONS = [
    {
        "name": "set_source",
        "description": "Set the data source for the scan (stock universe or event-based).",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["nse_universe", "premarket_gainers", "custom_list", "watchlist"],
                },
                "top_n": {"type": "integer", "description": "For event-based sources, limit to top N"},
                "date": {"type": "string", "description": "YYYY-MM-DD, default today"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "add_filter",
        "description": "Add a filter condition on stock attributes or exchange.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "operator": {"type": "string", "enum": ["eq", "gt", "lt", "gte", "lte", "in"]},
                "value": {},
            },
            "required": ["field", "operator", "value"],
        },
    },
    {
        "name": "add_indicator",
        "description": "Add indicator condition (RSI, MACD, EMA, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "indicator": {"type": "string"},
                "operator": {
                    "type": "string",
                    "enum": ["gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below"],
                },
                "value": {"type": "number"},
                "period": {"type": "integer"},
            },
            "required": ["indicator", "operator"],
        },
    },
    {
        "name": "add_trend_analysis",
        "description": "Add trend analysis for a specific time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_time": {"type": "string", "description": "HH:MM"},
                "to_time": {"type": "string", "description": "HH:MM"},
                "date": {"type": "string", "description": "today | yesterday | YYYY-MM-DD"},
                "timeframe": {"type": "string", "enum": ["1min", "1h", "1d"]},
                "metrics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["from_time", "to_time"],
        },
    },
    {
        "name": "set_sort",
        "description": "Sort results by a field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "descending": {"type": "boolean", "default": True},
            },
            "required": ["field"],
        },
    },
]
