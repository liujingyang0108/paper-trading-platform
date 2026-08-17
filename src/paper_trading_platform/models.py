from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    bid_size: float = 0
    ask_size: float = 0
    volume: float = 0
    previous_close: Optional[float] = None
    upper_limit: Optional[float] = None
    lower_limit: Optional[float] = None
    trading_status: str = "TRADING"
    source: str = "unknown"
    timestamp: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Quote":
        return cls(**{k: raw[k] for k in cls.__dataclass_fields__ if k in raw})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Order:
    symbol: str
    side: str
    quantity: int
    order_type: str = "market"
    limit_price: Optional[float] = None
    client_order_id: str = ""
    strategy_id: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "NEW"
    filled_quantity: int = 0
    average_price: float = 0
    reason: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_request(cls, raw: Dict[str, Any]) -> "Order":
        allowed = {"symbol", "side", "quantity", "order_type", "limit_price", "client_order_id", "strategy_id"}
        return cls(**{key: raw[key] for key in allowed if key in raw})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
