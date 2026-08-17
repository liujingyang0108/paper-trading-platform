import tempfile
import unittest

from paper_trading_platform.broker import Broker
from paper_trading_platform.store import Store


class QuoteDeduplicationTest(unittest.TestCase):
    def test_same_exchange_timestamp_is_stored_once(self):
        with tempfile.TemporaryDirectory() as root:
            broker = Broker(Store(root + "/db.sqlite"), {"enforce_trading_hours": False})
            quote = {"symbol": "TEST", "bid": 9.99, "ask": 10.01, "last": 10, "timestamp": "2026-08-17T14:30:00+08:00"}
            broker.ingest_quote(quote)
            broker.ingest_quote(quote)
            self.assertEqual(len(broker.store.history("TEST")), 1)


if __name__ == "__main__": unittest.main()
