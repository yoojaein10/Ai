from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from config import CANDLE_REFRESH_SECONDS, HOST, POLL_SECONDS, PORT, SYMBOLS
from market_data import NaverDomesticMarket
from paper_trader import StockPaperTrader
from strategy import chart, snapshot as strategy_snapshot


BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
market = NaverDomesticMarket()
trader = StockPaperTrader(BASE_DIR / "data" / "paper_state.json")
cache: dict[str, dict] = {}
cache_lock = threading.RLock()
stop_event = threading.Event()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "stock_paper.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("stock-paper")


def _quote_is_fresh(quote: dict) -> bool:
    try:
        traded_at = datetime.fromisoformat(quote["traded_at"])
        age = (datetime.now().astimezone() - traded_at).total_seconds()
        return -10 <= age <= 90
    except (ValueError, TypeError, KeyError):
        return False


def refresh_symbol(symbol: str, force_candles: bool = False) -> dict:
    now_monotonic = time.monotonic()
    with cache_lock:
        previous = dict(cache.get(symbol, {}))
    quote = market.quote(symbol)
    should_refresh = force_candles or (
        now_monotonic - float(previous.get("candle_updated_monotonic", 0))
        >= CANDLE_REFRESH_SECONDS
    )
    if should_refresh or "signal" not in previous:
        candles = market.candles(symbol)
        signal = strategy_snapshot(candles)
        chart_data = chart(candles)
        previous.update(
            {
                "signal": signal,
                "chart": chart_data,
                "candle_updated_monotonic": now_monotonic,
            }
        )
    fresh = _quote_is_fresh(quote)
    action = trader.evaluate(
        symbol,
        quote["name"],
        float(quote["price"]),
        previous["signal"],
        quote["market_status"] == "OPEN",
        fresh,
    )
    previous.update(
        {
            "quote": quote,
            "quote_fresh": fresh,
            "last_action": action,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    )
    with cache_lock:
        cache[symbol] = previous
    return previous


def worker() -> None:
    while not stop_event.is_set():
        for symbol in SYMBOLS:
            try:
                refresh_symbol(symbol)
            except Exception:
                logger.exception("시세 갱신 실패: %s", symbol)
        stop_event.wait(POLL_SECONDS)


@app.get("/")
def index():
    return render_template("index.html", symbols=SYMBOLS)


@app.get("/api/snapshot")
def api_snapshot():
    symbol = request.args.get("symbol", next(iter(SYMBOLS)))
    if symbol not in SYMBOLS:
        return jsonify({"error": "지원하지 않는 종목입니다."}), 400
    try:
        data = refresh_symbol(symbol)
    except Exception as exc:
        with cache_lock:
            data = cache.get(symbol)
        if not data:
            return jsonify({"error": str(exc)}), 503
        data = {**data, "error": str(exc)}
    data = {key: value for key, value in data.items() if key != "candle_updated_monotonic"}
    return jsonify(
        {
            "symbol": symbol,
            "name": SYMBOLS[symbol],
            "account": trader.snapshot(),
            **data,
        }
    )


@app.post("/api/auto")
def api_auto():
    body = request.get_json(silent=True) or {}
    trader.set_auto(bool(body.get("enabled")))
    return jsonify({"ok": True, "account": trader.snapshot()})


@app.post("/api/order")
def api_order():
    body = request.get_json(silent=True) or {}
    symbol = str(body.get("symbol") or "")
    side = str(body.get("side") or "").upper()
    if symbol not in SYMBOLS or side not in {"BUY", "SELL"}:
        return jsonify({"error": "잘못된 모의주문입니다."}), 400
    try:
        data = refresh_symbol(symbol)
        quote = data["quote"]
        if quote["market_status"] != "OPEN" or not data["quote_fresh"]:
            raise RuntimeError("정규장 실시간 시세일 때만 모의체결할 수 있습니다.")
        executed = (
            trader.buy(
                symbol,
                SYMBOLS[symbol],
                float(quote["price"]),
                float(data["signal"]["atr"]),
                "수동 모의매수",
            )
            if side == "BUY"
            else trader.sell(symbol, float(quote["price"]), "수동 모의매도")
        )
        if not executed:
            return jsonify({"error": "보유 상태 또는 가상 잔고를 확인하세요."}), 409
        return jsonify({"ok": True, "account": trader.snapshot()})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.post("/api/reset")
def api_reset():
    trader.reset()
    return jsonify({"ok": True, "account": trader.snapshot()})


if __name__ == "__main__":
    background = threading.Thread(target=worker, daemon=True)
    background.start()
    try:
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
    finally:
        stop_event.set()
