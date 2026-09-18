from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from backtest import BacktestManager
from departments import build_departments
from config import (
    ACTIVE_STRATEGY_PROFILE,
    ATR_PERIOD,
    BACKTEST_ALLOWED_DAYS,
    BUY_MIN_SCORE,
    CANDLE_COUNT,
    CANDLE_UNIT_MINUTES,
    COOLDOWN_MINUTES,
    CORE_MARKETS,
    DAILY_LOSS_LIMIT_RATE,
    EXCLUDED_MARKETS,
    FEE_RATE,
    HIGHER_TIMEFRAME_CACHE_SECONDS,
    HIGHER_TIMEFRAME_UNITS,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    MAX_ABS_24H_CHANGE_RATE,
    MAX_OPEN_POSITIONS,
    MIN_24H_TRADE_VALUE_KRW,
    REGIME_EMA_PERIOD,
    REGIME_MIN_ADX,
    REGIME_MIN_ATR_RATE,
    REGIME_SLOPE_CANDLES,
    REFRESH_SECONDS,
    SETUP_LOOKBACK_CANDLES,
    STOP_ATR_MULTIPLE,
    TAKE_PROFIT_ATR_MULTIPLE,
    TRADE_FRACTION,
    TRAILING_ACTIVATION_ATR,
    TRAILING_ATR_MULTIPLE,
    UNIVERSE_REFRESH_MINUTES,
    UNIVERSE_SIZE,
)
from indicators import (
    adaptive_signal_snapshot,
    buy_threshold_met,
    calculate_indicators,
    chart_payload,
    regime_snapshot,
    signal_snapshot,
)
from paper_trader import PaperTrader
from upbit_public import UpbitPublicClient, completed_candles
from upbit_stream import PublicTickerStream


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("paper-trader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
app = Flask(__name__)
client = UpbitPublicClient()
trader = PaperTrader(BASE_DIR / "data" / "paper_state.json")
backtest_manager = BacktestManager(BASE_DIR / "data" / "backtest_result.json")
market_cache: dict[str, dict] = {}
cache_lock = threading.RLock()
universe_lock = threading.RLock()
selected_markets: tuple[str, ...] = CORE_MARKETS
universe_details: list[dict] = []
universe_updated_at: str | None = None
last_universe_refresh = 0.0
higher_cache: dict[str, dict] = {}
higher_cache_lock = threading.RLock()


def higher_timeframe_regimes(market: str) -> dict[str, dict]:
    now = time.monotonic()
    with higher_cache_lock:
        cached = higher_cache.get(market)
        if cached and now - float(cached["updated_monotonic"]) < HIGHER_TIMEFRAME_CACHE_SECONDS:
            return cached["regimes"]
    regimes: dict[str, dict] = {}
    for unit in HIGHER_TIMEFRAME_UNITS:
        candles = client.candles(market, unit, CANDLE_COUNT)
        closed = completed_candles(candles, unit)
        if len(closed) < 60:
            regimes[str(unit)] = {
                "state": "insufficient",
                "trend_ok": False,
                "adx": 0.0,
                "atr_rate": 0.0,
                "ema_rising": False,
                "above_ema": False,
                "time": closed[-1]["candle_date_time_kst"] if closed else None,
            }
        else:
            regimes[str(unit)] = regime_snapshot(closed)
    with higher_cache_lock:
        higher_cache[market] = {
            "updated_monotonic": now,
            "regimes": regimes,
        }
    return regimes


def handle_realtime_price(market: str, price: float, _trade_timestamp: int | None) -> None:
    trader.update_live_price(market, price)


stream = PublicTickerStream(CORE_MARKETS, handle_realtime_price)


def current_markets(include_positions: bool = True) -> tuple[str, ...]:
    with universe_lock:
        markets = list(selected_markets)
    if include_positions:
        for position in trader.snapshot()["positions"]:
            if position["market"] not in markets:
                markets.append(position["market"])
    return tuple(markets)


def refresh_universe(force: bool = False) -> None:
    global selected_markets, universe_details, universe_updated_at, last_universe_refresh
    now = time.monotonic()
    if not force and now - last_universe_refresh < UNIVERSE_REFRESH_MINUTES * 60:
        return
    details = client.liquid_krw_markets(
        CORE_MARKETS,
        UNIVERSE_SIZE,
        MIN_24H_TRADE_VALUE_KRW,
        EXCLUDED_MARKETS,
        MAX_ABS_24H_CHANGE_RATE,
    )
    if len(details) < len(CORE_MARKETS):
        raise RuntimeError("안전한 감시 종목을 충분히 선정하지 못했습니다.")
    with universe_lock:
        universe_details = details
        selected_markets = tuple(item["market"] for item in details)
        universe_updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        last_universe_refresh = now
    stream.set_markets(current_markets(include_positions=True))


def update_market(market: str) -> dict:
    candles = client.candles(market, CANDLE_UNIT_MINUTES, CANDLE_COUNT)
    chart_frame = calculate_indicators(candles)
    closed = completed_candles(candles, CANDLE_UNIT_MINUTES)
    signal_frame = calculate_indicators(closed)
    market_regimes = higher_timeframe_regimes(market)
    bitcoin_regimes = higher_timeframe_regimes("KRW-BTC")
    guard = trader.entry_guard(market)
    if ACTIVE_STRATEGY_PROFILE == "adaptive":
        signal = adaptive_signal_snapshot(
            signal_frame,
            market_regimes,
            bitcoin_regimes,
            bool(guard["allowed"]),
        )
    else:
        signal = signal_snapshot(signal_frame)
        original_checks = signal["buy_checks"]
        own_hour = market_regimes["60"]
        own_four_hour = market_regimes["240"]
        bitcoin_four_hour = bitcoin_regimes["240"]
        timeframe_ok = bool(
            bitcoin_four_hour["trend_ok"]
            and (own_hour["trend_ok"] or own_four_hour["trend_ok"])
        )
        checks = {
            "market_mode": bool(signal["regime_ok"]),
            "entry_setup": bool(original_checks["bollinger"]),
            "confirmation": bool(
                original_checks["ema"] and original_checks["rsi"]
            ),
            "volume": True,
            "timeframes": timeframe_ok,
            "market_guard": bool(guard["allowed"]),
        }
        signal.update(
            {
                "strategy_mode": "validated_multi_timeframe",
                "buy_checks": checks,
                "buy_score": sum(checks.values()),
                "buy_signal": buy_threshold_met(checks),
                "timeframes": {
                    "market_1h": own_hour,
                    "market_4h": own_four_hour,
                    "bitcoin_4h": bitcoin_four_hour,
                    "ok": timeframe_ok,
                },
            }
        )
    signal["market_guard"] = guard
    live_price = stream.latest_price(market)
    try:
        orderbook = client.orderbook(market)
    except Exception as exc:
        logger.warning("orderbook fallback %s: %s", market, exc)
        orderbook = None
    trader.evaluate(
        market,
        signal,
        execution_price=live_price,
        orderbook=orderbook,
    )
    payload = {
        "signal": signal,
        "candles": chart_payload(chart_frame),
        "signal_candle_closed": True,
        "orderbook": orderbook,
    }
    with cache_lock:
        market_cache[market] = payload
    return payload


def background_worker(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            refresh_universe()
        except Exception:
            logger.exception("universe refresh failed")
        for market in current_markets(include_positions=True):
            try:
                update_market(market)
            except Exception as exc:  # Network failures are displayed without trading.
                logger.exception("market update failed: %s", market)
                with cache_lock:
                    market_cache.setdefault(market, {})["error"] = str(exc)
        stop_event.wait(REFRESH_SECONDS)


@app.get("/")
def index():
    return render_template("index.html", markets=current_markets(include_positions=False))


@app.get("/api/snapshot")
def snapshot():
    markets = current_markets(include_positions=True)
    market = request.args.get("market", markets[0])
    if market not in markets:
        return jsonify({"error": "지원하지 않는 마켓입니다."}), 400
    try:
        market_data = update_market(market)
    except Exception as exc:
        with cache_lock:
            market_data = market_cache.get(market, {})
        if not market_data:
            return jsonify({"error": f"업비트 시세를 불러오지 못했습니다: {exc}"}), 503
        market_data = {**market_data, "error": str(exc)}

    account = trader.snapshot()
    realtime = stream.snapshot()
    departments = build_departments(
        market_data["signal"],
        realtime,
        account,
        backtest_manager.status(),
        market_data.get("orderbook"),
    )
    return jsonify(
        {
            "market": market,
            "account": account,
            "realtime": realtime,
            "departments": departments,
            "universe": {
                "markets": list(current_markets(include_positions=False)),
                "details": universe_details,
                "updated_at": universe_updated_at,
            },
            **market_data,
            "settings": {
                "candle_minutes": CANDLE_UNIT_MINUTES,
                "refresh_seconds": REFRESH_SECONDS,
                "trade_fraction": TRADE_FRACTION,
                "fee_rate": FEE_RATE,
                "max_open_positions": MAX_OPEN_POSITIONS,
                "daily_loss_limit_rate": DAILY_LOSS_LIMIT_RATE,
                "maximum_abs_change_rate": MAX_ABS_24H_CHANGE_RATE,
                "setup_lookback_candles": SETUP_LOOKBACK_CANDLES,
                "buy_min_score": BUY_MIN_SCORE,
                "cooldown_minutes": COOLDOWN_MINUTES,
                "atr_period": ATR_PERIOD,
                "regime_ema_period": REGIME_EMA_PERIOD,
                "regime_slope_candles": REGIME_SLOPE_CANDLES,
                "regime_min_adx": REGIME_MIN_ADX,
                "regime_min_atr_rate": REGIME_MIN_ATR_RATE,
                "stop_atr_multiple": STOP_ATR_MULTIPLE,
                "take_profit_atr_multiple": TAKE_PROFIT_ATR_MULTIPLE,
                "trailing_activation_atr": TRAILING_ACTIVATION_ATR,
                "trailing_atr_multiple": TRAILING_ATR_MULTIPLE,
            },
        }
    )


@app.get("/api/prices")
def realtime_prices():
    return jsonify({"stream": stream.snapshot(), "account": trader.snapshot()})


@app.get("/api/backtest/status")
def backtest_status():
    return jsonify(backtest_manager.status())


@app.post("/api/backtest/start")
def start_backtest():
    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get("days", 90))
        if days not in BACKTEST_ALLOWED_DAYS:
            raise ValueError("지원하지 않는 백테스트 기간입니다.")
        started = backtest_manager.start(
            current_markets(include_positions=False),
            days,
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    if not started:
        return jsonify({"error": "백테스트가 이미 실행 중입니다."}), 409
    return jsonify({"ok": True, "status": backtest_manager.status()})


@app.post("/api/backtest/compare")
def compare_backtests():
    started = backtest_manager.start_comparison(
        current_markets(include_positions=False)
    )
    if not started:
        return jsonify({"error": "백테스트가 이미 실행 중입니다."}), 409
    return jsonify({"ok": True, "status": backtest_manager.status()})


@app.post("/api/auto")
def toggle_auto():
    body = request.get_json(silent=True) or {}
    trader.set_auto_enabled(bool(body.get("enabled")))
    return jsonify({"ok": True, "account": trader.snapshot()})


@app.post("/api/order")
def manual_order():
    body = request.get_json(silent=True) or {}
    market = body.get("market")
    side = str(body.get("side", "")).upper()
    if market not in current_markets(include_positions=True) or side not in {"BUY", "SELL"}:
        return jsonify({"error": "잘못된 주문 요청입니다."}), 400
    try:
        data = update_market(market)
        price = stream.latest_price(market) or float(data["signal"]["price"])
        atr = float(data["signal"]["atr"])
        orderbook = data.get("orderbook")
        executed = (
            trader.buy(market, price, "수동 모의매수", atr=atr, orderbook=orderbook)
            if side == "BUY"
            else trader.sell(market, price, "수동 모의매도", orderbook=orderbook)
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503
    if not executed:
        return jsonify({"error": "이미 보유 중이거나 매도할 가상 자산이 없습니다."}), 409
    return jsonify({"ok": True, "account": trader.snapshot()})


@app.post("/api/reset")
def reset():
    trader.reset()
    return jsonify({"ok": True, "account": trader.snapshot()})


@app.post("/api/risk/unlock")
def unlock_risk():
    trader.unlock_risk()
    return jsonify({"ok": True, "account": trader.snapshot()})


if __name__ == "__main__":
    stop = threading.Event()
    worker = threading.Thread(target=background_worker, args=(stop,), daemon=True)
    try:
        refresh_universe(force=True)
    except Exception:
        pass  # Core BTC/ETH remain available when initial ranking is unavailable.
    stream.start()
    worker.start()
    try:
        app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)
    finally:
        stop.set()
        stream.stop()
