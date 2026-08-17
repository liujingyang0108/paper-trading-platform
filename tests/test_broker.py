import tempfile
import unittest
from datetime import datetime, timezone

from paper_trading_platform.broker import Broker
from paper_trading_platform.store import Store


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = Broker(Store(self.tmp.name + "/db.sqlite"), {"initial_cash": 100000, "max_order_value": 50000})
        self.broker.ingest_quote({"symbol": "TEST", "bid": 9.99, "ask": 10.01, "last": 10, "bid_size": 1000, "ask_size": 1000, "timestamp": datetime.now(timezone.utc).isoformat()})

    def tearDown(self):
        self.tmp.cleanup()

    def test_market_order_and_idempotency(self):
        raw = {"symbol": "TEST", "side": "buy", "quantity": 100, "client_order_id": "once"}
        first, created = self.broker.submit(raw)
        second, created_again = self.broker.submit(raw)
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "FILLED")
        self.assertEqual(self.broker.account()["positions"]["TEST"]["quantity"], 100)

    def test_limit_waits_for_cross(self):
        order, _ = self.broker.submit({"symbol": "TEST", "side": "buy", "quantity": 10, "order_type": "limit", "limit_price": 9.5})
        self.assertEqual(order["status"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()

