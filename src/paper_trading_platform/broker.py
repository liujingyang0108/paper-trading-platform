from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

from .models import Order, Quote, utc_now
from .store import Store


DEFAULT_CONFIG = {
    "initial_cash": 100_000,
    "commission_rate": 0.0003,
    "minimum_commission": 5,
    "sell_tax_rate": 0.0005,
    "slippage_bps": 2,
    "max_order_value": 20_000,
    "max_symbol_weight": 0.2,
    "max_gross_exposure": 0.8,
    "max_daily_loss": 0.03,
    "quote_stale_seconds": 30,
    "buy_lot_size": 100,
    "t_plus_one": True,
    "block_star_market": True,
    "enforce_trading_hours": True,
    "timezone": "Asia/Shanghai",
}


class ValidationError(Exception):
    pass


class Broker:
    def __init__(self, store: Store, config: Dict[str, Any]):
        self.store = store
        self.config = {**DEFAULT_CONFIG, **config}
        if self.store.state_get("account", None) is None:
            self.store.state_set("account", {
                "cash": float(self.config["initial_cash"]), "positions": {},
                "realized_pnl": 0.0, "fees": 0.0,
                "settlement_date": self._market_now().date().isoformat(),
            })

    def _market_now(self) -> datetime:
        return datetime.now(ZoneInfo(self.config["timezone"]))

    def _market_date_from_timestamp(self, timestamp: str) -> str:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.astimezone(ZoneInfo(self.config["timezone"])).date().isoformat()

    def _settle_positions(self, market_date: str) -> None:
        account = self.store.state_get("account", {})
        last = account.get("settlement_date", market_date)
        changed = False
        if market_date > last:
            for position in account.get("positions", {}).values():
                position["available_quantity"] = position.get("available_quantity", 0) + position.get("today_bought", 0)
                position["today_bought"] = 0
            account["settlement_date"] = market_date
            changed = True
        if changed:
            self.store.state_set("account", account)
            self.store.event("DAILY_SETTLEMENT", {"market_date": market_date}, utc_now())

    def ingest_quote(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        quote = Quote.from_dict(raw)
        if not quote.symbol or min(quote.bid, quote.ask, quote.last) <= 0 or quote.ask < quote.bid:
            raise ValidationError("invalid quote")
        self._settle_positions(self._market_date_from_timestamp(quote.timestamp))
        self.store.save_quote(quote.to_dict())
        self.store.event("QUOTE", quote.to_dict(), utc_now())
        self._match_open_orders(quote)
        return quote.to_dict()

    def account(self) -> Dict[str, Any]:
        state = self.store.state_get("account", {})
        positions = state.get("positions", {})
        market_value = 0.0
        enriched = {}
        for symbol, position in positions.items():
            quote = self.store.quote(symbol)
            mark = quote["last"] if quote else position["average_cost"]
            value = position["quantity"] * mark
            market_value += value
            enriched[symbol] = {**position, "mark": mark, "market_value": round(value, 4), "unrealized_pnl": round((mark - position["average_cost"]) * position["quantity"], 4)}
        equity = state["cash"] + market_value
        return {**state, "positions": enriched, "market_value": round(market_value, 4), "equity": round(equity, 4), "gross_exposure": round(market_value / equity, 6) if equity else 0}

    def submit(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        order = Order.from_request(raw)
        order.side = order.side.lower()
        order.order_type = order.order_type.lower()
        existing = self.store.order_by_client_id(order.client_order_id)
        if existing:
            return existing, False
        self._validate_order(order)
        self._validate_market_session()
        quote_raw = self.store.quote(order.symbol)
        if not quote_raw:
            raise ValidationError("no quote for symbol")
        self._validate_quote_age(quote_raw)
        order.status = "ACCEPTED"
        order.updated_at = utc_now()
        self.store.save_order(order.to_dict())
        self.store.event("ORDER_ACCEPTED", order.to_dict(), order.updated_at)
        self._try_fill(order, Quote.from_dict(quote_raw))
        return order.to_dict(), True

    def cancel(self, order_id: str) -> Dict[str, Any]:
        found = next((item for item in self.store.orders() if item["id"] == order_id), None)
        if not found:
            raise ValidationError("order not found")
        if found["status"] not in {"ACCEPTED", "PARTIALLY_FILLED"}:
            raise ValidationError("order is not cancellable")
        found["status"] = "CANCELLED"
        found["updated_at"] = utc_now()
        self.store.save_order(found)
        self.store.event("ORDER_CANCELLED", found, found["updated_at"])
        return found

    def _validate_order(self, order: Order) -> None:
        if not order.symbol or order.side not in {"buy", "sell"}:
            raise ValidationError("symbol and side are required")
        if not isinstance(order.quantity, int) or order.quantity <= 0:
            raise ValidationError("quantity must be a positive integer")
        if order.order_type not in {"market", "limit"}:
            raise ValidationError("unsupported order type")
        if order.order_type == "limit" and (order.limit_price is None or order.limit_price <= 0):
            raise ValidationError("positive limit_price required")
        code = order.symbol.split(".", 1)[0]
        if self.config["block_star_market"] and code.startswith(("688", "689")):
            raise ValidationError("STAR Market trading is disabled")
        if order.side == "buy" and order.quantity % int(self.config["buy_lot_size"]) != 0:
            raise ValidationError(f"buy quantity must be a multiple of {self.config['buy_lot_size']}")

    def _validate_market_session(self) -> None:
        if not self.config["enforce_trading_hours"]:
            return
        now = self._market_now()
        current = now.time().replace(tzinfo=None)
        morning = time(9, 30) <= current <= time(11, 30)
        afternoon = time(13, 0) <= current <= time(15, 0)
        if now.weekday() >= 5 or not (morning or afternoon):
            raise ValidationError("outside A-share continuous trading session")

    def _validate_quote_age(self, quote: Dict[str, Any]) -> None:
        timestamp = datetime.fromisoformat(quote["timestamp"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
        if age > self.config["quote_stale_seconds"]:
            raise ValidationError("stale quote")

    def _fill_price(self, order: Order, quote: Quote) -> float:
        base = quote.ask if order.side == "buy" else quote.bid
        direction = 1 if order.side == "buy" else -1
        return round(base * (1 + direction * self.config["slippage_bps"] / 10000), 4)

    def _risk_check(self, order: Order, price: float) -> None:
        account = self.account()
        today = datetime.now(timezone.utc).date().isoformat()
        risk_day = self.store.state_get("risk_day", {})
        if risk_day.get("date") != today:
            risk_day = {"date": today, "start_equity": account["equity"]}
            self.store.state_set("risk_day", risk_day)
        if account["equity"] <= risk_day["start_equity"] * (1 - self.config["max_daily_loss"]):
            raise ValidationError("daily loss circuit breaker active")
        value = price * order.quantity
        if value > self.config["max_order_value"]:
            raise ValidationError("max order value exceeded")
        current = account["positions"].get(order.symbol, {"quantity": 0})["quantity"]
        resulting = current + order.quantity if order.side == "buy" else current - order.quantity
        if resulting < 0:
            raise ValidationError("short selling disabled or insufficient position")
        if order.side == "sell":
            available = account["positions"].get(order.symbol, {}).get("available_quantity", current)
            if order.quantity > available:
                raise ValidationError("T+1 restriction: sell quantity exceeds available quantity")
        equity = account["equity"]
        if order.side == "buy":
            fee = max(value * self.config["commission_rate"], self.config["minimum_commission"])
            if value + fee > account["cash"]:
                raise ValidationError("insufficient cash")
            if resulting * price > equity * self.config["max_symbol_weight"]:
                raise ValidationError("max symbol weight exceeded")
            if account["market_value"] + value > equity * self.config["max_gross_exposure"]:
                raise ValidationError("max gross exposure exceeded")

    def _try_fill(self, order: Order, quote: Quote) -> None:
        crosses = order.order_type == "market" or (order.side == "buy" and order.limit_price >= quote.ask) or (order.side == "sell" and order.limit_price <= quote.bid)
        if not crosses:
            return
        price = self._fill_price(order, quote)
        try:
            self._risk_check(order, price)
        except ValidationError as exc:
            order.status, order.reason, order.updated_at = "REJECTED", str(exc), utc_now()
            self.store.save_order(order.to_dict())
            self.store.event("ORDER_REJECTED", order.to_dict(), order.updated_at)
            return
        visible = int(quote.ask_size if order.side == "buy" else quote.bid_size)
        remaining = order.quantity - order.filled_quantity
        fill_quantity = min(remaining, visible) if visible > 0 else remaining
        self._apply_fill(order, fill_quantity, price)

    def _apply_fill(self, order: Order, quantity: int, price: float) -> None:
        account = self.store.state_get("account", {})
        positions = account.setdefault("positions", {})
        position = positions.setdefault(order.symbol, {
            "quantity": 0, "average_cost": 0.0,
            "available_quantity": 0, "today_bought": 0,
        })
        value = price * quantity
        commission = max(value * self.config["commission_rate"], self.config["minimum_commission"])
        tax = value * self.config["sell_tax_rate"] if order.side == "sell" else 0
        fee = commission + tax
        if order.side == "buy":
            old_value = position["quantity"] * position["average_cost"]
            position["quantity"] += quantity
            if self.config["t_plus_one"]:
                position["today_bought"] = position.get("today_bought", 0) + quantity
            else:
                position["available_quantity"] = position.get("available_quantity", 0) + quantity
            position["average_cost"] = round((old_value + value) / position["quantity"], 6)
            account["cash"] -= value + fee
        else:
            account["cash"] += value - fee
            account["realized_pnl"] += (price - position["average_cost"]) * quantity - fee
            position["quantity"] -= quantity
            position["available_quantity"] -= quantity
        account["fees"] += fee
        if position["quantity"] == 0:
            positions.pop(order.symbol)
        previous = order.filled_quantity
        order.filled_quantity += quantity
        order.average_price = round(((order.average_price * previous) + price * quantity) / order.filled_quantity, 6)
        order.status = "FILLED" if order.filled_quantity == order.quantity else "PARTIALLY_FILLED"
        order.updated_at = utc_now()
        self.store.state_set("account", account)
        self.store.save_order(order.to_dict())
        fill = {"order_id": order.id, "symbol": order.symbol, "side": order.side, "quantity": quantity, "price": price, "fee": round(fee, 4), "strategy_id": order.strategy_id}
        self.store.event("FILL", fill, order.updated_at)

    def _match_open_orders(self, quote: Quote) -> None:
        for raw in self.store.orders():
            if raw["symbol"] == quote.symbol and raw["status"] in {"ACCEPTED", "PARTIALLY_FILLED"}:
                self._try_fill(Order(**raw), quote)
