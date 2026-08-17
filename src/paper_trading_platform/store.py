from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS quotes(
                    symbol TEXT PRIMARY KEY, payload TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quote_history(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
                    payload TEXT NOT NULL, timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quote_history_symbol_id
                    ON quote_history(symbol, id DESC);
                CREATE TABLE IF NOT EXISTS orders(
                    id TEXT PRIMARY KEY, client_order_id TEXT UNIQUE, payload TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                """
            )

    def state_get(self, key: str, default: Any) -> Any:
        with self.lock:
            row = self.connection.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def state_set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, payload),
            )

    def save_quote(self, quote: Dict[str, Any]) -> None:
        payload = json.dumps(quote, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO quotes(symbol,payload,timestamp) VALUES(?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET payload=excluded.payload,timestamp=excluded.timestamp",
                (quote["symbol"], payload, quote["timestamp"]),
            )
            self.connection.execute(
                "INSERT INTO quote_history(symbol,payload,timestamp) VALUES(?,?,?)",
                (quote["symbol"], payload, quote["timestamp"]),
            )

    def quotes(self) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute("SELECT payload FROM quotes ORDER BY symbol").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            row = self.connection.execute("SELECT payload FROM quotes WHERE symbol=?", (symbol,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def history(self, symbol: str, limit: int = 200) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload FROM quote_history WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol, min(max(limit, 1), 5000)),
            ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def save_order(self, order: Dict[str, Any]) -> None:
        payload = json.dumps(order, ensure_ascii=False, separators=(",", ":"))
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO orders(id,client_order_id,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,status=excluded.status,updated_at=excluded.updated_at",
                (order["id"], order.get("client_order_id") or None, payload, order["status"], order["created_at"], order["updated_at"]),
            )

    def order_by_client_id(self, client_order_id: str) -> Optional[Dict[str, Any]]:
        if not client_order_id:
            return None
        with self.lock:
            row = self.connection.execute("SELECT payload FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def orders(self) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute("SELECT payload FROM orders ORDER BY created_at").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def event(self, kind: str, payload: Dict[str, Any], created_at: str) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO events(kind,payload,created_at) VALUES(?,?,?)",
                (kind, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), created_at),
            )

    def events(self, after_id: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT id,kind,payload,created_at FROM events WHERE id>? ORDER BY id LIMIT ?",
                (after_id, min(max(limit, 1), 5000)),
            ).fetchall()
        return [{"id": r["id"], "kind": r["kind"], "payload": json.loads(r["payload"]), "created_at": r["created_at"]} for r in rows]

