from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from config import (
    ATR_PERIOD,
    BUY_MIN_SCORE,
    BUY_REQUIRED_CHECKS,
    REGIME_EMA_PERIOD,
    REGIME_MIN_ADX,
    REGIME_MIN_ATR_RATE,
    REGIME_SLOPE_CANDLES,
    SETUP_LOOKBACK_CANDLES,
)


def buy_threshold_met(checks: dict[str, bool]) -> bool:
    return bool(
        all(checks.get(name, False) for name in BUY_REQUIRED_CHECKS)
        and sum(bool(value) for value in checks.values()) >= BUY_MIN_SCORE
    )


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50)
    return result.fillna(50)


def calculate_indicators(candles: list[dict[str, Any]]) -> pd.DataFrame:
    if len(candles) < 30:
        raise ValueError("지표 계산에는 최소 30개의 캔들이 필요합니다.")

    frame = pd.DataFrame(
        {
            "time": [row["candle_date_time_kst"] for row in candles],
            "open": [float(row["opening_price"]) for row in candles],
            "high": [float(row["high_price"]) for row in candles],
            "low": [float(row["low_price"]) for row in candles],
            "close": [float(row["trade_price"]) for row in candles],
            "volume": [float(row["candle_acc_trade_volume"]) for row in candles],
        }
    )

    frame["bb_mid"] = frame["close"].rolling(20).mean()
    deviation = frame["close"].rolling(20).std(ddof=0)
    frame["bb_upper"] = frame["bb_mid"] + (deviation * 2)
    frame["bb_lower"] = frame["bb_mid"] - (deviation * 2)
    frame["ema_fast"] = frame["close"].ewm(span=9, adjust=False).mean()
    frame["ema_slow"] = frame["close"].ewm(span=21, adjust=False).mean()
    frame["ema_regime"] = frame["close"].ewm(
        span=REGIME_EMA_PERIOD,
        adjust=False,
    ).mean()
    frame["rsi"] = _rsi(frame["close"], 14)
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean()
    up_move = frame["high"].diff()
    down_move = -frame["low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_range = true_range.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean() / smoothed_range
    minus_di = 100 * minus_dm.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean() / smoothed_range
    directional_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / directional_sum
    frame["adx"] = dx.ewm(
        alpha=1 / ATR_PERIOD,
        adjust=False,
        min_periods=ATR_PERIOD,
    ).mean()
    frame["atr_rate"] = frame["atr"] / frame["close"].replace(0, np.nan)

    band_width = (frame["bb_upper"] - frame["bb_lower"]).replace(0, np.nan)
    frame["bb_position"] = ((frame["close"] - frame["bb_lower"]) / band_width).clip(0, 1)
    frame["bb_width_rate"] = band_width / frame["bb_mid"].replace(0, np.nan)
    return frame.dropna().reset_index(drop=True)


def signal_snapshot(frame: pd.DataFrame) -> dict[str, Any]:
    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    bb_position = float(latest["bb_position"])
    rsi_value = float(latest["rsi"])
    ema_fast = float(latest["ema_fast"])
    ema_slow = float(latest["ema_slow"])
    ema_regime = float(latest["ema_regime"])
    adx = float(latest["adx"])
    atr_rate = float(latest["atr_rate"])

    recent = frame.tail(SETUP_LOOKBACK_CANDLES)
    setup_recent = bool(
        ((recent["bb_position"] <= 0.25) & (recent["rsi"] <= 45)).any()
    )
    price_rebound = bool(latest["close"] > previous["close"])
    momentum_confirmed = bool(
        latest["rsi"] > previous["rsi"] and ema_fast > ema_slow
    )
    regime_ema_rising = bool(
        latest["ema_regime"]
        > frame.iloc[-1 - REGIME_SLOPE_CANDLES]["ema_regime"]
    )
    volatility_ok = bool(adx >= REGIME_MIN_ADX and atr_rate >= REGIME_MIN_ATR_RATE)
    regime_ok = bool(latest["close"] > ema_regime and regime_ema_rising and volatility_ok)
    if not volatility_ok:
        regime_state = "sideways"
    elif regime_ok:
        regime_state = "bullish"
    else:
        regime_state = "bearish"
    buy_checks = {
        "bollinger": setup_recent,
        "ema": price_rebound,
        "rsi": momentum_confirmed,
        "regime": regime_ok,
    }

    bollinger_reversal = bool(
        previous["bb_position"] >= 0.90
        and latest["close"] < previous["close"]
    )
    ema_bearish_cross = bool(
        previous["ema_fast"] >= previous["ema_slow"]
        and ema_fast < ema_slow
    )
    rsi_reversal = bool(previous["rsi"] >= 70 and rsi_value < previous["rsi"])
    sell_checks = {
        "bollinger": bollinger_reversal,
        "ema": ema_bearish_cross,
        "rsi": rsi_reversal,
    }

    return {
        "time": latest["time"],
        "price": float(latest["close"]),
        "bb_position": bb_position,
        "rsi": rsi_value,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "atr": float(latest["atr"]),
        "adx": adx,
        "atr_rate": atr_rate,
        "ema_regime": ema_regime,
        "regime": regime_state,
        "regime_ok": regime_ok,
        "buy_checks": buy_checks,
        "sell_checks": sell_checks,
        "buy_score": sum(buy_checks.values()),
        "sell_score": sum(sell_checks.values()),
        "buy_signal": all(buy_checks.values()),
        "sell_signal": ema_bearish_cross or (bollinger_reversal and rsi_reversal),
    }


def regime_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    frame = calculate_indicators(candles)
    latest = frame.iloc[-1]
    prior = frame.iloc[-1 - REGIME_SLOPE_CANDLES]
    ema_rising = bool(latest["ema_regime"] > prior["ema_regime"])
    above_ema = bool(latest["close"] > latest["ema_regime"])
    strong = bool(latest["adx"] >= REGIME_MIN_ADX)
    volatile = bool(latest["atr_rate"] >= REGIME_MIN_ATR_RATE)
    trend_ok = above_ema and ema_rising
    if not strong or not volatile:
        state = "sideways"
    elif trend_ok:
        state = "bullish"
    else:
        state = "bearish"
    return {
        "state": state,
        "trend_ok": trend_ok,
        "adx": float(latest["adx"]),
        "atr_rate": float(latest["atr_rate"]),
        "ema_rising": ema_rising,
        "above_ema": above_ema,
        "time": str(latest["time"]),
    }


def adaptive_signal_snapshot(
    frame: pd.DataFrame,
    market_regimes: dict[str, dict[str, Any]],
    bitcoin_regimes: dict[str, dict[str, Any]],
    market_guard_allowed: bool,
) -> dict[str, Any]:
    signal = signal_snapshot(frame)
    latest = frame.iloc[-1]
    previous = frame.iloc[-2]
    recent_high = float(frame["high"].shift(1).tail(96).max())
    average_volume = float(frame["volume"].shift(1).tail(96).mean())

    own_hour = market_regimes["60"]
    own_four_hour = market_regimes["240"]
    bitcoin_four_hour = bitcoin_regimes["240"]
    trend_mode = bool(
        bitcoin_four_hour["trend_ok"]
        and (own_hour["trend_ok"] or own_four_hour["trend_ok"])
    )
    sideways_mode = bool(
        not trend_mode
        and bitcoin_four_hour["state"] != "bearish"
        and own_four_hour["state"] != "bearish"
        and own_hour["state"] == "sideways"
    )

    pullback_setup = bool(
        previous["close"] <= previous["ema_fast"]
        and latest["close"] > latest["ema_fast"]
        and latest["ema_fast"] > latest["ema_slow"]
        and latest["ema_slow"] > frame.iloc[-4]["ema_slow"]
        and latest["adx"] >= 18
        and 45 <= latest["rsi"] <= 60
    )
    pullback_confirmation = bool(
        latest["close"] > previous["close"]
        and latest["rsi"] > previous["rsi"]
        and latest["close"] > latest["open"]
    )
    pullback_volume = bool(latest["volume"] >= average_volume)

    breakout_setup = bool(
        latest["close"] > recent_high
        and latest["ema_fast"] > latest["ema_slow"]
        and latest["adx"] >= 20
        and 55 <= latest["rsi"] < 72
    )
    breakout_confirmation = bool(latest["close"] > latest["open"])
    breakout_volume = bool(latest["volume"] >= average_volume * 2.0)

    mean_setup = bool(
        previous["bb_position"] <= 0.10
        and previous["rsi"] <= 32
        and latest["adx"] < 15
    )
    mean_confirmation = bool(
        latest["close"] > previous["close"] and latest["rsi"] > previous["rsi"]
    )

    if trend_mode and breakout_setup:
        mode = "trend_breakout"
        setup_ok = breakout_setup
        confirmation_ok = breakout_confirmation
        volume_ok = breakout_volume
    elif trend_mode:
        mode = "trend_pullback"
        setup_ok = pullback_setup
        confirmation_ok = pullback_confirmation
        volume_ok = pullback_volume
    elif sideways_mode:
        mode = "sideways_mean_reversion"
        setup_ok = mean_setup
        confirmation_ok = mean_confirmation
        volume_ok = True
    else:
        mode = "cash"
        setup_ok = False
        confirmation_ok = False
        volume_ok = False

    checks = {
        "market_mode": trend_mode or sideways_mode,
        "entry_setup": setup_ok,
        "confirmation": confirmation_ok,
        "volume": volume_ok,
        "timeframes": trend_mode or sideways_mode,
        "market_guard": bool(market_guard_allowed),
    }
    bearish_exit = bool(
        bitcoin_four_hour["state"] == "bearish"
        or own_four_hour["state"] == "bearish"
    )
    mean_exit = bool(
        sideways_mode
        and (
            latest["close"] >= latest["bb_mid"]
            or latest["rsi"] >= 55
        )
    )
    trend_exit = bool(
        trend_mode
        and latest["close"] < latest["ema_slow"]
        and latest["rsi"] < previous["rsi"]
    )
    signal.update(
        {
            "strategy_mode": mode,
            "buy_checks": checks,
            "buy_score": sum(checks.values()),
            "buy_signal": buy_threshold_met(checks),
            "sell_signal": bool(
                signal["sell_signal"] or bearish_exit or mean_exit or trend_exit
            ),
            "timeframes": {
                "market_1h": own_hour,
                "market_4h": own_four_hour,
                "bitcoin_4h": bitcoin_four_hour,
                "ok": trend_mode or sideways_mode,
            },
        }
    )
    return signal


def chart_payload(frame: pd.DataFrame, limit: int = 100) -> list[dict[str, Any]]:
    columns = (
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "ema_fast",
        "ema_slow",
        "rsi",
        "atr",
    )
    rows: list[dict[str, Any]] = []
    for _, row in frame.tail(limit).iterrows():
        item: dict[str, Any] = {}
        for column in columns:
            value = row[column]
            item[column] = None if pd.isna(value) else (str(value) if column == "time" else float(value))
        rows.append(item)
    return rows
