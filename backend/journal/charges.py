# backend/journal/charges.py
from decimal import Decimal, ROUND_HALF_UP
from .models import Charges
from .config import STT_RATES, EXCHANGE_TXN, SEBI_FEE, GST_RATE, STAMP_DUTY

def _r(v): return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def compute_pair_charges(
    segment: str, exchange: str, qty: int,
    entry_px: Decimal, exit_px: Decimal,
    entry_brok: Decimal = Decimal(0), exit_brok: Decimal = Decimal(0),
    intraday: bool = True, is_option: bool = True,
) -> Charges:
    def _side(trade_type: str, px: Decimal, brok: Decimal):
        tv = Decimal(qty) * px
        if segment == "FO":
            sell_key = "FO_OPT_SELL" if is_option else "FO_FUT_SELL"
            stt = _r(tv * STT_RATES[sell_key]) if trade_type == "SELL" else Decimal(0)
        elif intraday:
            stt = _r(tv * STT_RATES["EQ_INTRADAY"]) if trade_type == "SELL" else Decimal(0)
        else:
            stt = _r(tv * STT_RATES["EQ_DELIVERY"])
        stamp_k = "FO" if segment == "FO" else ("EQ_INTRADAY" if intraday else "EQ_DELIVERY")
        stamp = _r(tv * STAMP_DUTY[stamp_k]) if trade_type == "BUY" else Decimal(0)
        if segment == "FO":
            exch_k = f"{exchange}_{'OPT' if is_option else 'FUT'}"
        else:
            exch_k = f"{exchange}_EQ"
        etxn = _r(tv * EXCHANGE_TXN.get(exch_k, EXCHANGE_TXN["NSE_OPT"]))
        sebi = _r(tv * SEBI_FEE)
        gst = _r((brok + etxn + sebi) * GST_RATE)
        return stt, stamp, etxn, sebi, gst

    b_stt, b_stmp, b_etxn, b_sebi, b_gst = _side("BUY",  entry_px, entry_brok)
    s_stt, s_stmp, s_etxn, s_sebi, s_gst = _side("SELL", exit_px,  exit_brok)
    return Charges(
        brokerage=entry_brok + exit_brok,
        stt=b_stt + s_stt,
        stamp_duty=b_stmp + s_stmp,
        exchange_txn=b_etxn + s_etxn,
        sebi_fee=b_sebi + s_sebi,
        gst=b_gst + s_gst,
    )
