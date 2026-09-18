from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    relative = gain / loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative))
    return result.fillna(50)


def add_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    frame = candles.copy()
    close = frame["close"].astype(float)
    frame["ema9"] = close.ewm(span=9, adjust=False).mean()
    frame["ema21"] = close.ewm(span=21, adjust=False).mean()
    frame["ema60"] = close.ewm(span=60, adjust=False).mean()
    frame["bb_mid"] = close.rolling(20).mean()
    deviation = close.rolling(20).std(ddof=0)
    frame["bb_upper"] = frame["bb_mid"] + 2 * deviation
    frame["bb_lower"] = frame["bb_mid"] - 2 * deviation
    frame["rsi"] = _rsi(close)
    previous = close.shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    session = frame["time"].dt.date
    cumulative_value = (typical * frame["volume"]).groupby(session).cumsum()
    cumulative_volume = frame["volume"].groupby(session).cumsum().replace(0, np.nan)
    frame["vwap"] = cumulative_value / cumulative_volume
    frame["volume_average"] = frame["volume"].rolling(20).mean()
    return frame


def snapshot(candles: pd.DataFrame) -> dict:
    closed = candles[candles["closed"]].copy()
    if len(closed) < 60:
        raise RuntimeError("지표 계산에 필요한 완료된 15분봉이 부족합니다.")
    frame = add_indicators(closed)
    current = frame.iloc[-1]
    previous = frame.iloc[-2]

    checks = {
        "vwap": bool(current["close"] > current["vwap"]),
        "ema": bool(current["ema9"] > current["ema21"]),
        "rsi": bool(45 <= current["rsi"] <= 68 and current["rsi"] > previous["rsi"]),
        "bollinger": bool(
            current["close"] > current["bb_mid"]
            and current["close"] < current["bb_upper"]
        ),
        "trend": bool(current["close"] > current["ema60"]),
    }
    score = sum(checks.values())
    sell_checks = {
        "ema": bool(current["ema9"] < current["ema21"]),
        "rsi": bool(current["rsi"] >= 72 and current["rsi"] < previous["rsi"]),
        "bollinger": bool(
            previous["close"] >= previous["bb_upper"]
            and current["close"] < current["bb_upper"]
        ),
    }
    return {
        "time": current["time"].isoformat(),
        "price": float(current["close"]),
        "atr": float(current["atr"]),
        "rsi": float(current["rsi"]),
        "ema9": float(current["ema9"]),
        "ema21": float(current["ema21"]),
        "ema60": float(current["ema60"]),
        "vwap": float(current["vwap"]),
        "bb_upper": float(current["bb_upper"]),
        "bb_mid": float(current["bb_mid"]),
        "bb_lower": float(current["bb_lower"]),
        "buy_checks": checks,
        "buy_score": score,
        "buy_signal": bool(score >= 4 and checks["ema"] and checks["vwap"]),
        "sell_checks": sell_checks,
        "sell_signal": bool(sum(sell_checks.values()) >= 2),
    }


def chart(candles: pd.DataFrame, limit: int = 80) -> list[dict]:
    frame = add_indicators(candles).tail(limit)
    columns = [
        "time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "ema9",
        "ema21",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "vwap",
    ]
    result = []
    for row in frame[columns].to_dict("records"):
        row["time"] = row["time"].isoformat()
        result.append(
            {
                key: (None if pd.isna(value) else float(value))
                if key != "time"
                else value
                for key, value in row.items()
            }
        )
    return result
