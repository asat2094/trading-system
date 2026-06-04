# backend/journal/force_square.py
_PATTERNS = {
    "lemonn":  ["squaring off", "non-compliance of margin"],
    "zerodha": ['"'],
    "kite":    ["autosquareoff", "auto square"],
    "upstox":  ["auto square", "autosquare"],
    "mstock":  [],
}

def is_force_squared(remark: str | None, broker: str) -> bool:
    if not remark: return False
    r = remark.lower().strip()
    return any(p.lower() in r for p in _PATTERNS.get(broker, []))
