# backend/journal/config.py
from decimal import Decimal

LOT_SIZES: dict[str, int] = {
    "NIFTY":      75,
    "BANKNIFTY":  35,
    "FINNIFTY":   65,
    "MIDCPNIFTY": 120,
    "SENSEX":     20,
    "BANKEX":     20,
}

def get_lot_size(underlying: str) -> int:
    return LOT_SIZES.get(underlying.upper(), 1)

BROKERAGE_MODELS: dict[str, dict] = {
    "zerodha": {"type": "flat_per_order", "amount": Decimal("20")},
    "kite":    {"type": "flat_per_order", "amount": Decimal("20")},
    "upstox":  {"type": "flat_per_order", "amount": Decimal("20")},
    "lemonn":  {"type": "flat_per_order", "amount": Decimal("20")},
    "mstock":  {"type": "per_unit",       "amount": Decimal("0.25")},
    "pdf":     {"type": "from_data"},
}

# STT on SELL side only. Options = on premium (0.15% eff 1-Apr-2026). Futures = on turnover.
STT_RATES = {
    "FO_OPT_SELL": Decimal("0.0015"),
    "FO_FUT_SELL": Decimal("0.0005"),
    "EQ_DELIVERY": Decimal("0.001"),
    "EQ_INTRADAY": Decimal("0.00025"),
}

# Exchange transaction charges. OPT keys = on premium (much higher); FUT = on turnover.
EXCHANGE_TXN = {
    "NSE_OPT": Decimal("0.0003503"),
    "BSE_OPT": Decimal("0.000325"),
    "NSE_FUT": Decimal("0.000053"),
    "BSE_FUT": Decimal("0.000047"),
    "NSE_EQ":  Decimal("0.0000322"),
    "BSE_EQ":  Decimal("0.0000375"),
}

SEBI_FEE   = Decimal("0.000001")
GST_RATE   = Decimal("0.18")
STAMP_DUTY = {
    "FO":           Decimal("0.00003"),
    "EQ_INTRADAY":  Decimal("0.00003"),
    "EQ_DELIVERY":  Decimal("0.00015"),
}
