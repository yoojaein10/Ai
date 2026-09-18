from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import threading
import time
from typing import Any, Callable

import requests


BASE_URL = "https://api.upbit.com/v1"
MARKET_PATTERN = re.compile(r"^KRW-[A-Z0-9]+$")


def select_liquid_krw_markets(
    market_rows: list[dict[str, Any]],
    ticker_rows: list[dict[str, Any]],
    core_markets: tuple[str, ...],
    limit: int,
    minimum_trade_value: float,
    excluded_markets: tuple[str, ...] = (),
    maximum_abs_change_rate: float = 1.0,
) -> list[dict[str, Any]]:
    metadata = {row.get("market"): row for row in market_rows}
    safe_tickers: list[dict[str, Any]] = []
    for ticker in ticker_rows:
        market = str(ticker.get("market", ""))
        meta = metadata.get(market, {})
        event = meta.get("market_event") or {}
        caution = event.get("caution") or {}
        has_warning = bool(event.get("warning")) or any(bool(value) for value in caution.values())
        trade_value = float(ticker.get("acc_trade_price_24h") or 0)
        change_rate = float(ticker.get("signed_change_rate") or 0)
        if (
            MARKET_PATTERN.fullmatch(market)
            and not has_warning
            and market not in excluded_markets
            and trade_value >= minimum_trade_value
            and abs(change_rate) <= maximum_abs_change_rate
        ):
            safe_tickers.append(
                {
                    "market": market,
                    "korean_name": meta.get("korean_name") or market,
                    "english_name": meta.get("english_name") or market,
                    "trade_price": float(ticker.get("trade_price") or 0),
                    "trade_value_24h": trade_value,
                    "signed_change_rate": change_rate,
                }
            )

    safe_tickers.sort(key=lambda item: item["trade_value_24h"], reverse=True)
    by_market = {item["market"]: item for item in safe_tickers}
    selected: list[dict[str, Any]] = []
    for market in core_markets:
        if market in by_market:
            selected.append(by_market[market])
    for item in safe_tickers:
        if len(selected) >= limit:
            break
        if item["market"] not in {selected_item["market"] for selected_item in selected}:
            selected.append(item)
    return selected[:limit]


class UpbitPublicClient:
    """Read-only Upbit market data client. It never accepts or sends API keys."""

    _rate_lock = threading.Lock()
    _last_request_at = 0.0
    _minimum_request_interval = 0.15

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "UpbitPaperTrader/1.0"})

    def _get(self, path: str, params: dict[str, Any]) -> requests.Response:
        response: requests.Response | None = None
        for attempt in range(6):
            with self._rate_lock:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self._minimum_request_interval:
                    time.sleep(self._minimum_request_interval - elapsed)
                response = self.session.get(
                    f"{BASE_URL}{path}",
                    params=params,
                    timeout=self.timeout,
                )
                type(self)._last_request_at = time.monotonic()
            if response.status_code != 429:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else min(0.5 * (2**attempt), 5.0)
            time.sleep(max(delay, self._minimum_request_interval))
        assert response is not None
        response.raise_for_status()
        return response

    def candles(self, market: str, unit: int = 15, count: int = 200) -> list[dict[str, Any]]:
        if not MARKET_PATTERN.fullmatch(market):
            raise ValueError("지원하지 않는 마켓입니다.")
        if unit not in {1, 3, 5, 10, 15, 30, 60, 240}:
            raise ValueError("지원하지 않는 캔들 단위입니다.")
        count = max(30, min(int(count), 200))
        response = self._get(
            f"/candles/minutes/{unit}",
            {"market": market, "count": count},
        )
        rows = response.json()
        rows.reverse()  # Upbit returns newest first; indicators need oldest first.
        return rows

    def orderbook(self, market: str) -> dict[str, Any]:
        if not MARKET_PATTERN.fullmatch(market):
            raise ValueError("지원하지 않는 마켓입니다.")
        response = self._get("/orderbook", {"markets": market, "level": 0})
        rows = response.json()
        if not rows:
            raise RuntimeError("호가 데이터를 받지 못했습니다.")
        return rows[0]

    def liquid_krw_markets(
        self,
        core_markets: tuple[str, ...],
        limit: int,
        minimum_trade_value: float,
        excluded_markets: tuple[str, ...] = (),
        maximum_abs_change_rate: float = 1.0,
    ) -> list[dict[str, Any]]:
        market_response = self._get("/market/all", {"is_details": "true"})
        ticker_response = self._get("/ticker/all", {"quote_currencies": "KRW"})
        return select_liquid_krw_markets(
            market_response.json(),
            ticker_response.json(),
            core_markets,
            limit,
            minimum_trade_value,
            excluded_markets,
            maximum_abs_change_rate,
        )

    def historical_candles(
        self,
        market: str,
        unit: int,
        days: int,
        progress: Callable[[float], None] | None = None,
    ) -> list[dict[str, Any]]:
        if not MARKET_PATTERN.fullmatch(market):
            raise ValueError("지원하지 않는 마켓입니다.")
        if unit not in {1, 3, 5, 10, 15, 30, 60, 240}:
            raise ValueError("지원하지 않는 캔들 단위입니다.")
        target_count = int(days * 24 * 60 / unit) + 5
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        rows: list[dict[str, Any]] = []
        to: str | None = None
        while len(rows) < target_count:
            params: dict[str, Any] = {"market": market, "count": 200}
            if to:
                params["to"] = to
            response = self._get(f"/candles/minutes/{unit}", params)
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            oldest = datetime.fromisoformat(batch[-1]["candle_date_time_utc"])
            if oldest <= cutoff:
                break
            to = f"{batch[-1]['candle_date_time_utc']}Z"
            if progress:
                progress(min(len(rows) / target_count, 1.0))
        unique = {row["candle_date_time_utc"]: row for row in rows}
        ordered = [unique[key] for key in sorted(unique)]
        filtered = [
            row
            for row in ordered
            if datetime.fromisoformat(row["candle_date_time_utc"]) >= cutoff
        ]
        if progress:
            progress(1.0)
        return filtered


def completed_candles(candles: list[dict[str, Any]], unit_minutes: int) -> list[dict[str, Any]]:
    """Exclude the currently forming candle so strategy signals cannot repaint."""
    if not candles:
        return []
    latest_start = datetime.fromisoformat(candles[-1]["candle_date_time_kst"])
    now_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).replace(tzinfo=None)
    if latest_start + timedelta(minutes=unit_minutes) > now_kst:
        return candles[:-1]
    return candles
