import unittest

from execution import estimate_execution


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.orderbook = {
            "orderbook_units": [
                {
                    "ask_price": 101.0,
                    "ask_size": 5.0,
                    "bid_price": 99.0,
                    "bid_size": 4.0,
                }
            ]
        }

    def test_buy_uses_ask_and_partial_depth(self):
        result = estimate_execution(
            "BUY",
            100.0,
            self.orderbook,
            desired_krw=1010.0,
        )
        self.assertAlmostEqual(result["fill_rate"], 0.5)
        self.assertGreater(result["price"], 101.0)

    def test_sell_uses_bid_and_partial_depth(self):
        result = estimate_execution(
            "SELL",
            100.0,
            self.orderbook,
            desired_quantity=10.0,
        )
        self.assertAlmostEqual(result["fill_rate"], 0.4)
        self.assertLess(result["price"], 99.0)


if __name__ == "__main__":
    unittest.main()
