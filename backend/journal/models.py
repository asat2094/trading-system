# backend/journal/models.py
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Optional

@dataclass
class Trade:
    broker: str; source: str; trade_date: date
    trade_time: Optional[time]
    symbol: str; raw_symbol: str; underlying: str
    exchange: str; segment: str
    trade_type: str; quantity: int; price: Decimal
    id: Optional[int] = None
    source_format: str = "pdf"
    fill_grain: str = "wap"
    order_no: Optional[str] = None; order_time: Optional[time] = None
    trade_id: Optional[str] = None
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None; instrument: Optional[str] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None
    brokerage: Decimal = Decimal(0); closing_rate: Optional[Decimal] = None
    gross_amount: Optional[Decimal] = None
    product_type: Optional[str] = None
    status: str = "filled"; remark: Optional[str] = None
    is_force_squared: bool = False
    source_file: Optional[str] = None
    contract_note_no: Optional[str] = None; is_revised: bool = False

@dataclass
class Charges:
    brokerage: Decimal = Decimal(0); stt: Decimal = Decimal(0)
    stamp_duty: Decimal = Decimal(0); exchange_txn: Decimal = Decimal(0)
    sebi_fee: Decimal = Decimal(0); gst: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return sum([self.brokerage, self.stt, self.stamp_duty,
                    self.exchange_txn, self.sebi_fee, self.gst], Decimal(0))

    def to_dict(self) -> dict:
        return {k: str(getattr(self, k)) for k in
                ["brokerage","stt","stamp_duty","exchange_txn","sebi_fee","gst"]}

@dataclass
class TradePair:
    symbol: str; underlying: str; exchange: str; segment: str
    side: str; quantity: int
    open_date: date; open_time: Optional[time]; entry_price: Decimal
    entry_trade_ids: list[int] = field(default_factory=list)
    id: Optional[int] = None
    broker: Optional[str] = None
    product_type: Optional[str] = None
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None
    close_date: Optional[date] = None; close_time: Optional[time] = None
    exit_price: Optional[Decimal] = None
    exit_trade_ids: list[int] = field(default_factory=list)
    gross_pnl: Optional[Decimal] = None; charges: Optional[Charges] = None
    net_pnl: Optional[Decimal] = None; hold_seconds: Optional[int] = None
    is_intraday: Optional[bool] = None; force_squared: bool = False

@dataclass
class DaySummary:
    trade_date: date; broker: Optional[str]
    fiscal_year: Optional[str]
    total_fills: int; total_orders: int; total_lots: int
    failed_order_count: int; force_squared_count: int
    first_trade_time: Optional[time]; last_trade_time: Optional[time]
    avg_hold_seconds: Optional[int]; time_bucket_pnl: dict
    gross_pnl: Decimal; total_brokerage: Decimal
    total_charges: Decimal; net_pnl: Decimal
    win_pairs: int; loss_pairs: int; open_pairs: int

@dataclass
class Rule:
    id: Optional[int]; name: str; rule_type: str; enabled: bool; config: dict

@dataclass
class RuleViolation:
    rule: Rule; message: str; severity: str
    context: dict = field(default_factory=dict)
