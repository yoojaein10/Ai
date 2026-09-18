import tempfile
import unittest
from pathlib import Path

from paper_trader import PaperTrader


class PaperTraderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.trader = PaperTrader(Path(self.temp.name) / "state.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_manual_buy_and_sell_updates_equity(self):
        self.assertTrue(self.trader.buy("KRW-BTC", 100_000_000, "test"))
        self.assertFalse(self.trader.buy("KRW-BTC", 100_000_000, "duplicate"))
        self.assertTrue(self.trader.sell("KRW-BTC", 104_000_000, "test"))
        snapshot = self.trader.snapshot()
        self.assertEqual(snapshot["positions"], [])
        self.assertGreater(snapshot["realized_pnl"], 0)

    def test_three_confirmations_trigger_buy(self):
        signal = {
            "time": "2026-01-01T00:00:00",
            "price": 100_000_000,
            "atr": 1_000_000,
            "buy_score": 3,
            "sell_score": 0,
            "buy_signal": True,
            "sell_signal": False,
        }
        self.assertEqual(self.trader.evaluate("KRW-BTC", signal), "BUY")
        self.assertEqual(self.trader.evaluate("KRW-BTC", signal), None)

    def test_live_price_triggers_stop_loss(self):
        self.assertTrue(self.trader.buy("KRW-BTC", 100_000_000, "test", atr=1_000_000))
        self.assertEqual(self.trader.update_live_price("KRW-BTC", 97_000_000), "SELL")
        self.assertEqual(self.trader.snapshot()["positions"], [])

    def test_live_price_triggers_atr_target(self):
        self.assertTrue(self.trader.buy("KRW-BTC", 100_000_000, "test", atr=1_000_000))
        self.assertEqual(self.trader.update_live_price("KRW-BTC", 102_100_000), "SELL")

    def test_maximum_three_positions(self):
        self.assertTrue(self.trader.buy("KRW-BTC", 100_000_000, "test"))
        self.assertTrue(self.trader.buy("KRW-ETH", 3_000_000, "test"))
        self.assertTrue(self.trader.buy("KRW-XRP", 1_000, "test"))
        self.assertFalse(self.trader.buy("KRW-SOL", 200_000, "blocked"))

    def test_daily_loss_lock_blocks_new_buy(self):
        self.trader.state["daily"]["locked"] = True
        self.assertFalse(self.trader.buy("KRW-BTC", 100_000_000, "blocked"))

    def test_three_market_losses_temporarily_block_market(self):
        for _ in range(3):
            self.assertTrue(self.trader.buy("KRW-BTC", 100_000_000, "test"))
            self.assertTrue(self.trader.sell("KRW-BTC", 99_000_000, "loss"))
        guard = self.trader.entry_guard("KRW-BTC")
        self.assertFalse(guard["allowed"])
        self.assertIsNotNone(guard["blocked_until"])

    def test_five_global_losses_lock_new_entries(self):
        for market in ("KRW-A", "KRW-B", "KRW-C", "KRW-D", "KRW-E"):
            self.assertTrue(self.trader.buy(market, 1000, "test"))
            self.assertTrue(self.trader.sell(market, 995, "loss"))
        snapshot = self.trader.snapshot()
        self.assertTrue(snapshot["risk_locked"])
        self.assertFalse(self.trader.buy("KRW-F", 1000, "blocked"))
        self.trader.unlock_risk()
        self.assertFalse(self.trader.snapshot()["risk_locked"])


if __name__ == "__main__":
    unittest.main()
