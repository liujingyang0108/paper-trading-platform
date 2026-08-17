from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .api import serve
from .broker import Broker
from .store import Store


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def synthetic_feed(broker: Broker, symbols: list, interval: float, seed: int) -> None:
    rng = random.Random(seed)
    prices = {symbol: 10.0 + index * 7 for index, symbol in enumerate(symbols)}
    step = 0
    while True:
        for index, symbol in enumerate(symbols):
            drift = 0.0008 if (step // 30 + index) % 2 == 0 else -0.0006
            prices[symbol] = max(1, prices[symbol] * (1 + drift + rng.gauss(0, 0.0015)))
            spread = max(0.01, prices[symbol] * 0.0005)
            broker.ingest_quote({
                "symbol": symbol, "bid": round(prices[symbol] - spread / 2, 4),
                "ask": round(prices[symbol] + spread / 2, 4), "last": round(prices[symbol], 4),
                "bid_size": 10000, "ask_size": 10000, "volume": step * 10000,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            })
        step += 1
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading platform")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--synthetic", action="store_true", help="run deterministic demo market feed")
    parser.add_argument("--symbols", default="510300.SH,510500.SH,159915.SZ")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    cfg = load_config(args.config)
    broker = Broker(Store(cfg["database"]), cfg)
    if args.synthetic:
        threading.Thread(target=synthetic_feed, args=(broker, args.symbols.split(","), args.interval, 7), daemon=True).start()
    serve(broker, cfg.get("host", "127.0.0.1"), int(cfg.get("port", 8800)))


if __name__ == "__main__":
    main()

