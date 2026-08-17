import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from paper_trading_platform.broker import Broker
from paper_trading_platform.store import Store


class BrokerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.broker = Broker(Store(self.tmp.name + "/db.sqlite"), {"initial_cash": 100000, "max_order_value": 50000, "enforce_trading_hours": False})
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
        self.assertEqual(self.broker.account()["positions"]["TEST"]["available_quantity"], 0)

    def test_limit_waits_for_cross(self):
        order, _ = self.broker.submit({"symbol": "TEST", "side": "buy", "quantity": 100, "order_type": "limit", "limit_price": 9.5})
        self.assertEqual(order["status"], "ACCEPTED")

    def test_t_plus_one_blocks_same_day_sale(self):
        self.broker.submit({"symbol": "TEST", "side": "buy", "quantity": 100})
        order, _ = self.broker.submit({"symbol": "TEST", "side": "sell", "quantity": 100})
        self.assertEqual(order["status"], "REJECTED")
        self.assertIn("T+1", order["reason"])

    def test_next_day_settlement_unlocks_position(self):
        self.broker.submit({"symbol": "TEST", "side": "buy", "quantity": 100})
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        self.broker.ingest_quote({"symbol": "TEST", "bid": 10.09, "ask": 10.11, "last": 10.10, "bid_size": 1000, "ask_size": 1000, "timestamp": tomorrow.isoformat()})
        self.assertEqual(self.broker.account()["positions"]["TEST"]["available_quantity"], 100)
        order, _ = self.broker.submit({"symbol": "TEST", "side": "sell", "quantity": 100})
        self.assertEqual(order["status"], "FILLED")

    def test_star_market_and_buy_lot_are_blocked(self):
        with self.assertRaisesRegex(Exception, "multiple of 100"):
            self.broker.submit({"symbol": "TEST", "side": "buy", "quantity": 99})
        self.broker.ingest_quote({"symbol": "688001.SH", "bid": 9.99, "ask": 10.01, "last": 10, "timestamp": datetime.now(timezone.utc).isoformat()})
        with self.assertRaisesRegex(Exception, "STAR"):
            self.broker.submit({"symbol": "688001.SH", "side": "buy", "quantity": 100})


if __name__ == "__main__":
    unittest.main()
