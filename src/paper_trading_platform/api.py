from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .broker import Broker, ValidationError


def handler_factory(broker: Broker):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PaperTradingPlatform/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            print("api", self.address_string(), fmt % args)

        def send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/health":
                    self.send_json(200, {"status": "ok", "service": "paper-trading-platform"})
                elif parsed.path == "/v1/account":
                    self.send_json(200, broker.account())
                elif parsed.path == "/v1/quotes":
                    self.send_json(200, broker.store.quotes())
                elif parsed.path.startswith("/v1/quotes/"):
                    symbol = parsed.path.rsplit("/", 1)[-1]
                    quote = broker.store.quote(symbol)
                    self.send_json(200 if quote else 404, quote or {"error": "quote not found"})
                elif parsed.path.startswith("/v1/history/"):
                    symbol = parsed.path.rsplit("/", 1)[-1]
                    self.send_json(200, broker.store.history(symbol, int(query.get("limit", [200])[0])))
                elif parsed.path == "/v1/orders":
                    self.send_json(200, broker.store.orders())
                elif parsed.path == "/v1/events":
                    self.send_json(200, broker.store.events(int(query.get("after_id", [0])[0]), int(query.get("limit", [500])[0])))
                else:
                    self.send_json(404, {"error": "not found"})
            except (ValidationError, ValueError) as exc:
                self.send_json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            try:
                if self.path == "/v1/market/ticks":
                    self.send_json(201, broker.ingest_quote(self.body()))
                elif self.path == "/v1/orders":
                    order, created = broker.submit(self.body())
                    self.send_json(201 if created else 200, order)
                elif self.path.startswith("/v1/orders/") and self.path.endswith("/cancel"):
                    order_id = self.path.split("/")[3]
                    self.send_json(200, broker.cancel(order_id))
                else:
                    self.send_json(404, {"error": "not found"})
            except (ValidationError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})

    return Handler


def serve(broker: Broker, host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), handler_factory(broker))
    print(f"paper trading API listening on http://{host}:{port}")
    server.serve_forever()

