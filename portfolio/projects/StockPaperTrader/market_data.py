from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from config import CANDLE_MINUTES, HISTORY_DAYS


class NaverDomesticMarket:
    """Read-only public quote client. It contains no brokerage/order API."""

    BASE = "https://polling.finance.naver.com/api/realtime/domestic/stock/{symbol}"
    CHART = "https://api.stock.naver.com/chart/domestic/item/{symbol}/minute"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 StockPaperTrader/1.0",
                "Referer": "https://finance.naver.com/",
            }
        )

    def quote(self, symbol: str) -> dict[str, Any]:
        response = self.session.get(self.BASE.format(symbol=symbol), timeout=10)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("datas"):
            raise RuntimeError("국내주식 시세 응답이 비어 있습니다.")
        item = payload["datas"][0]
        return {
            "symbol": str(item["itemCode"]),
            "name": str(item["stockName"]),
            "price": float(item["closePriceRaw"]),
            "previous_close": float(item["closePriceRaw"])
            - float(item.get("compareToPreviousClosePriceRaw") or 0),
            "change": float(item.get("compareToPreviousClosePriceRaw") or 0),
            "change_rate": float(item.get("fluctuationsRatioRaw") or 0),
            "open": float(item.get("openPriceRaw") or 0),
            "high": float(item.get("highPriceRaw") or 0),
            "low": float(item.get("lowPriceRaw") or 0),
            "volume": int(item.get("accumulatedTradingVolumeRaw") or 0),
            "market_status": str(item.get("marketStatus") or "UNKNOWN"),
            "traded_at": str(item.get("localTradedAt") or ""),
            "exchange": str(item.get("stockExchangeType", {}).get("nameKor") or ""),
            "source": "NAVER_KRX",
        }

    def minute_bars(self, symbol: str, now: datetime | None = None) -> pd.DataFrame:
        now = now or datetime.now().astimezone()
        start = now - timedelta(days=HISTORY_DAYS)
        params = {
            "startDateTime": start.strftime("%Y%m%d%H%M"),
            "endDateTime": now.strftime("%Y%m%d%H%M"),
        }
        response = self.session.get(
            self.CHART.format(symbol=symbol), params=params, timeout=15
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise RuntimeError("분봉 데이터가 없습니다.")
        frame = pd.DataFrame(rows).rename(
            columns={
                "localDateTime": "time",
                "currentPrice": "close",
                "openPrice": "open",
                "highPrice": "high",
                "lowPrice": "low",
                "accumulatedTradingVolume": "volume",
            }
        )
        frame["time"] = pd.to_datetime(frame["time"], format="%Y%m%d%H%M%S")
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna().sort_values("time").reset_index(drop=True)

    def candles(self, symbol: str, now: datetime | None = None) -> pd.DataFrame:
        now = now or datetime.now().astimezone()
        minute = self.minute_bars(symbol, now)
        minute["bucket"] = minute["time"].dt.floor(f"{CANDLE_MINUTES}min")
        closing_auction = (minute["time"].dt.hour == 15) & (
            minute["time"].dt.minute == 30
        )
        minute.loc[closing_auction, "bucket"] -= pd.Timedelta(
            minutes=CANDLE_MINUTES
        )
        candle = (
            minute.groupby("bucket", as_index=False)
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .rename(columns={"bucket": "time"})
        )
        current_bucket = pd.Timestamp(now.replace(tzinfo=None)).floor(
            f"{CANDLE_MINUTES}min"
        )
        candle["closed"] = candle["time"] < current_bucket
        return candle.reset_index(drop=True)
