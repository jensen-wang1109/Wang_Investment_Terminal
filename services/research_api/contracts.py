"""Provider-neutral contracts. None means unavailable, never an invented zero."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class InstrumentRef:
    symbol: str
    exchange: str
    currency: str
    timezone: str


@dataclass(frozen=True)
class DailyPrice:
    symbol: str
    observation_date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    adjusted_close: float | None
    volume: int | None
    currency: str
    provider: str
    fetched_at: str
    available_at: str | None = None
    is_final: bool = False
    dividend: float | None = None
    split_ratio: float | None = None


class MarketDataProvider(Protocol):
    name: str
    def history(self, instrument: InstrumentRef, start: str, end: str) -> list[DailyPrice]: ...
    def latest(self, instrument: InstrumentRef) -> dict: ...
    def company(self, instrument: InstrumentRef) -> dict: ...
    def statements(self, instrument: InstrumentRef) -> list[dict]: ...
    def actions(self, instrument: InstrumentRef, start: str, end: str) -> list[dict]: ...
    def index_history(self, instrument: InstrumentRef, start: str, end: str) -> list[DailyPrice]: ...
    def classification(self, instrument: InstrumentRef) -> dict: ...
    def indicators(self, identifiers: list[str], start: str, end: str) -> list[dict]: ...


class PermissionDenied(Exception):
    pass


class UnsupportedCapability(Exception):
    pass
