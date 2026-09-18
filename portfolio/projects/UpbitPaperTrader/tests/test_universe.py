import unittest

from upbit_public import select_liquid_krw_markets


class UniverseTests(unittest.TestCase):
    def test_core_markets_and_liquidity_ranking_exclude_warnings(self):
        markets = [
            {"market": "KRW-BTC", "korean_name": "비트코인", "market_event": {"warning": False, "caution": {}}},
            {"market": "KRW-ETH", "korean_name": "이더리움", "market_event": {"warning": False, "caution": {}}},
            {"market": "KRW-XRP", "korean_name": "리플", "market_event": {"warning": False, "caution": {}}},
            {"market": "KRW-BAD", "korean_name": "경보", "market_event": {"warning": True, "caution": {}}},
            {"market": "KRW-USDT", "korean_name": "테더", "market_event": {"warning": False, "caution": {}}},
            {"market": "KRW-HOT", "korean_name": "급등", "market_event": {"warning": False, "caution": {}}},
        ]
        tickers = [
            {"market": "KRW-XRP", "trade_price": 1_000, "acc_trade_price_24h": 90_000_000_000},
            {"market": "KRW-BAD", "trade_price": 10, "acc_trade_price_24h": 100_000_000_000},
            {"market": "KRW-BTC", "trade_price": 100_000_000, "acc_trade_price_24h": 50_000_000_000},
            {"market": "KRW-ETH", "trade_price": 3_000_000, "acc_trade_price_24h": 40_000_000_000},
            {"market": "KRW-USDT", "trade_price": 1_400, "acc_trade_price_24h": 120_000_000_000},
            {"market": "KRW-HOT", "trade_price": 100, "acc_trade_price_24h": 110_000_000_000, "signed_change_rate": 0.25},
        ]
        selected = select_liquid_krw_markets(
            markets,
            tickers,
            ("KRW-BTC", "KRW-ETH"),
            3,
            5_000_000_000,
            ("KRW-USDT",),
            0.15,
        )
        self.assertEqual(
            [item["market"] for item in selected],
            ["KRW-BTC", "KRW-ETH", "KRW-XRP"],
        )


if __name__ == "__main__":
    unittest.main()
