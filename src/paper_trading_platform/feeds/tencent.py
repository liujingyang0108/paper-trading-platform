from __future__ import annotations

import time
import urllib.request
from datetime import datetime
from typing import Dict, Iterable, List
from zoneinfo import ZoneInfo


def vendor_symbol(symbol: str) -> str:
    code, _, exchange = symbol.partition(".")
    prefix = "sh" if exchange.upper() == "SH" or code.startswith(("5", "6", "9")) else "sz"
    return prefix + code


def parse_quote_line(line: str) -> Dict:
    if '="' not in line:
        raise ValueError("invalid Tencent quote line")
    raw = line.split('="', 1)[1].rstrip('";\r\n')
    parts = raw.split("~")
    if len(parts) < 49:
        raise ValueError("incomplete Tencent quote")
    code = parts[2].zfill(6)
    exchange = "SH" if line.startswith("v_sh") else "SZ"
    stamp = datetime.strptime(parts[30], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    previous_close = float(parts[4])
    return {
        "symbol": f"{code}.{exchange}",
        "bid": float(parts[9] or parts[3]), "ask": float(parts[19] or parts[3]),
        "last": float(parts[3]), "bid_size": float(parts[10] or 0) * 100,
        "ask_size": float(parts[20] or 0) * 100, "volume": float(parts[6] or 0) * 100,
        "previous_close": previous_close,
        "upper_limit": float(parts[47]) if parts[47] else round(previous_close * 1.1, 3),
        "lower_limit": float(parts[48]) if parts[48] else round(previous_close * 0.9, 3),
        "trading_status": "TRADING" if float(parts[3] or 0) > 0 else "HALTED",
        "source": "public_web", "timestamp": stamp.isoformat(timespec="seconds"),
    }


def fetch_quotes(symbols: Iterable[str], timeout: int = 10) -> List[Dict]:
    query = ",".join(vendor_symbol(symbol) for symbol in symbols)
    request = urllib.request.Request(
        "https://qt.gtimg.cn/q=" + query,
        headers={"User-Agent": "Mozilla/5.0 paper-trading-platform/0.2", "Referer": "https://gu.qq.com/"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        text = response.read().decode("gbk", errors="replace")
    quotes = []
    for line in text.splitlines():
        try:
            quotes.append(parse_quote_line(line))
        except (ValueError, IndexError):
            continue
    if not quotes:
        raise RuntimeError("Tencent quote source returned no valid quotes")
    return quotes


def run_feed(broker, symbols: List[str], interval: float) -> None:
    while True:
        try:
            for quote in fetch_quotes(symbols):
                broker.ingest_quote(quote)
        except Exception as exc:
            print(f"Tencent feed error: {exc}")
        time.sleep(max(interval, 1.0))

