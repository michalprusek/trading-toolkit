from __future__ import annotations
from datetime import datetime
from pydantic import AliasChoices, BaseModel, Field


class InstrumentRate(BaseModel):
    instrument_id: int = Field(validation_alias=AliasChoices("InstrumentID", "instrumentID"))
    ask: float = Field(validation_alias=AliasChoices("Ask", "ask"))
    bid: float = Field(validation_alias=AliasChoices("Bid", "bid"))
    last_price: float | None = Field(default=None, validation_alias=AliasChoices("LastExecution", "lastExecution"))

    @property
    def mid(self) -> float:
        return (self.ask + self.bid) / 2

    @property
    def spread_pct(self) -> float:
        if self.bid == 0:
            return 0.0
        return (self.ask - self.bid) / self.bid * 100


class Position(BaseModel):
    position_id: int = Field(validation_alias=AliasChoices("PositionID", "positionID", "positionId"))
    instrument_id: int = Field(validation_alias=AliasChoices("InstrumentID", "instrumentID", "instrumentId"))
    is_buy: bool = Field(validation_alias=AliasChoices("IsBuy", "isBuy"))
    amount: float = Field(validation_alias=AliasChoices("Amount", "amount"))
    open_rate: float = Field(validation_alias=AliasChoices("OpenRate", "openRate"))
    current_rate: float | None = Field(default=None, validation_alias=AliasChoices("CurrentRate", "currentRate"))
    net_profit: float = Field(default=0, validation_alias=AliasChoices("NetProfit", "netProfit"))
    leverage: float = Field(default=1, validation_alias=AliasChoices("Leverage", "leverage"))
    stop_loss_rate: float | None = Field(default=None, validation_alias=AliasChoices("StopLossRate", "stopLossRate"))
    take_profit_rate: float | None = Field(default=None, validation_alias=AliasChoices("TakeProfitRate", "takeProfitRate"))
    open_date: str | None = Field(default=None, validation_alias=AliasChoices("OpenDateTime", "openDateTime"))

    @property
    def direction(self) -> str:
        return "BUY" if self.is_buy else "SELL"

    @property
    def pnl_pct(self) -> float:
        if self.amount == 0:
            return 0.0
        return (self.net_profit / self.amount) * 100


class PortfolioSummary(BaseModel):
    positions: list[Position] = []
    total_invested: float = 0.0
    total_pnl: float = 0.0
    cash_available: float = 0.0

    @property
    def total_value(self) -> float:
        return self.total_invested + self.total_pnl + self.cash_available


class Instrument(BaseModel):
    instrument_id: int = Field(alias="InstrumentID")
    symbol: str = Field(alias="SymbolFull")
    name: str = Field(default="", alias="InstrumentDisplayName")
    instrument_type: str = Field(default="", alias="InstrumentTypeID")
    exchange: str = Field(default="", alias="ExchangeID")


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0


class TradeResult(BaseModel):
    success: bool
    position_id: int | None = None
    order_id: int | None = None
    message: str = ""
    raw: dict | None = None
