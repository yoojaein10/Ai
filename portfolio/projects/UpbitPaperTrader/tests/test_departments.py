import unittest

from departments import build_departments


def sample_signal(**overrides):
    signal = {
        "buy_checks": {
            "market_mode": True,
            "entry_setup": True,
            "confirmation": True,
            "volume": True,
            "timeframes": True,
            "market_guard": True,
        },
        "buy_score": 6,
        "buy_signal": True,
        "sell_signal": False,
    }
    signal.update(overrides)
    return signal


class DepartmentTests(unittest.TestCase):
    def setUp(self):
        self.realtime = {
            "connected": True,
            "subscribed_markets": ["KRW-BTC", "KRW-ETH"],
        }
        self.account = {
            "equity": 10_000_000,
            "total_pnl": 0,
            "positions": [],
            "daily_locked": False,
            "risk_locked": False,
        }
        self.backtest = {
            "result": {
                "days": 180,
                "trades": 28,
                "total_return": -0.01,
                "profit_factor": 0.2,
            }
        }

    def test_departments_are_separated_and_real_orders_disabled(self):
        result = build_departments(
            sample_signal(), self.realtime, self.account, self.backtest, {"units": []}
        )
        self.assertTrue(result["hq"]["capital_separated"])
        self.assertFalse(result["hq"]["real_order_enabled"])
        self.assertEqual(result["crypto"]["mode"], "PAPER")
        self.assertEqual(result["stocks"]["status"], "WAITING_KIS")
        self.assertFalse(result["stocks"]["real_order_enabled"])

    def test_six_agents_and_chief_follow_existing_signal(self):
        result = build_departments(
            sample_signal(), self.realtime, self.account, self.backtest, {"units": []}
        )
        self.assertEqual(len(result["crypto"]["agents"]), 6)
        self.assertEqual(result["crypto"]["chief"]["decision"], "BUY")
        self.assertTrue(result["crypto"]["chief"]["paper_only"])

    def test_risk_lock_prevents_chief_buy(self):
        self.account["daily_locked"] = True
        result = build_departments(
            sample_signal(), self.realtime, self.account, self.backtest, {"units": []}
        )
        self.assertEqual(result["crypto"]["chief"]["decision"], "WAIT")
        risk = next(
            agent for agent in result["crypto"]["agents"] if agent["key"] == "risk"
        )
        self.assertEqual(risk["state"], "VETO")


if __name__ == "__main__":
    unittest.main()
