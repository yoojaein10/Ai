from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime
from typing import Callable

import websocket


WEBSOCKET_URL = "wss://api.upbit.com/websocket/v1"


class PublicTickerStream:
    """Resilient, read-only Upbit ticker stream."""

    def __init__(
        self,
        markets: tuple[str, ...],
        on_price: Callable[[str, float, int | None], None],
    ) -> None:
        self.markets = markets
        self.on_price = on_price
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.socket: websocket.WebSocketApp | None = None
        self.connected = False
        self.last_error: str | None = None
        self.connection_count = 0
        self.last_message_at: str | None = None
        self.prices: dict[str, dict] = {}

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="upbit-ticker")
        self.thread.start()

    def set_markets(self, markets: tuple[str, ...]) -> None:
        normalized = tuple(dict.fromkeys(markets))
        if not normalized:
            raise ValueError("구독할 마켓이 없습니다.")
        socket_to_close: websocket.WebSocketApp | None = None
        with self.lock:
            if normalized == self.markets:
                return
            self.markets = normalized
            self.prices = {
                market: item for market, item in self.prices.items() if market in normalized
            }
            socket_to_close = self.socket
        if socket_to_close:
            socket_to_close.close()

    def stop(self) -> None:
        self.stop_event.set()
        if self.socket:
            self.socket.close()
        if self.thread:
            self.thread.join(timeout=3)

    def latest_price(self, market: str) -> float | None:
        with self.lock:
            item = self.prices.get(market)
            return float(item["price"]) if item else None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "connected": self.connected,
                "last_error": self.last_error,
                "connection_count": self.connection_count,
                "last_message_at": self.last_message_at,
                "subscribed_markets": list(self.markets),
                "markets": {key: dict(value) for key, value in self.prices.items()},
            }

    def _run(self) -> None:
        retry_delay = 1
        while not self.stop_event.is_set():
            received_message = False
            with self.lock:
                subscribed_markets = tuple(self.markets)

            def on_open(ws: websocket.WebSocketApp) -> None:
                with self.lock:
                    self.connected = True
                    self.last_error = None
                    self.connection_count += 1
                request = [
                    {"ticket": str(uuid.uuid4())},
                    {"type": "ticker", "codes": list(subscribed_markets), "is_only_realtime": True},
                    {"format": "DEFAULT"},
                ]
                ws.send(json.dumps(request))

            def on_message(_ws: websocket.WebSocketApp, message: bytes | str) -> None:
                nonlocal received_message
                received_message = True
                try:
                    text = message.decode("utf-8") if isinstance(message, bytes) else message
                    payload = json.loads(text)
                    market = payload.get("code")
                    price = float(payload["trade_price"])
                    trade_timestamp = payload.get("trade_timestamp")
                    if market not in subscribed_markets or price <= 0:
                        return
                    with self.lock:
                        received_at = datetime.now().astimezone().isoformat(
                            timespec="milliseconds"
                        )
                        self.prices[market] = {
                            "price": price,
                            "trade_timestamp": trade_timestamp,
                            "received_at": received_at,
                        }
                        self.last_message_at = received_at
                    self.on_price(market, price, trade_timestamp)
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                    with self.lock:
                        self.last_error = f"메시지 처리 오류: {exc}"

            def on_error(_ws: websocket.WebSocketApp, error: object) -> None:
                with self.lock:
                    self.last_error = str(error)

            def on_close(
                _ws: websocket.WebSocketApp,
                _status_code: int | None,
                _message: str | None,
            ) -> None:
                with self.lock:
                    self.connected = False

            self.socket = websocket.WebSocketApp(
                WEBSOCKET_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            self.socket.run_forever(ping_interval=30, ping_timeout=10)
            with self.lock:
                self.connected = False
            if self.stop_event.is_set():
                break
            retry_delay = 1 if received_message else min(retry_delay * 2, 30)
            self.stop_event.wait(retry_delay)
