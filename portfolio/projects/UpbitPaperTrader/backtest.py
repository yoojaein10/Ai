from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from config import (
    BACKTEST_ALLOWED_DAYS,
    BACKTEST_SLIPPAGE_RATE,
    CANDLE_UNIT_MINUTES,
    COOLDOWN_MINUTES,
    DAILY_LOSS_LIMIT_RATE,
    EXECUTION_LATENCY_SLIPPAGE_RATE,
    FEE_RATE,
    GLOBAL_LOSS_STREAK_LIMIT,
    INITIAL_CASH_KRW,
    MARKET_BLOCK_HOURS,
    MARKET_LOSS_STREAK_LIMIT,
    MAX_OPEN_POSITIONS,
    REGIME_MIN_ADX,
    REGIME_MIN_ATR_RATE,
    REGIME_SLOPE_CANDLES,
    SETUP_LOOKBACK_CANDLES,
    STOP_ATR_MULTIPLE,
    TAKE_PROFIT_ATR_MULTIPLE,
    TRADE_FRACTION,
    TRAILING_ACTIVATION_ATR,
    TRAILING_ATR_MULTIPLE,
)
from indicators import calculate_indicators
from upbit_public import UpbitPublicClient, completed_candles


STRATEGY_PROFILES: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "현재 전략",
        "bb_max": 0.25,
        "rsi_max": 45,
        "setup_lookback": SETUP_LOOKBACK_CANDLES,
        "ema_slope_lookback": 0,
        "minimum_volume_ratio": 0.0,
        "bullish_candle": False,
        "require_regime": False,
        "require_mtf": False,
        "stop_atr": STOP_ATR_MULTIPLE,
        "target_atr": TAKE_PROFIT_ATR_MULTIPLE,
        "trailing_activation_atr": TRAILING_ACTIVATION_ATR,
        "trailing_atr": TRAILING_ATR_MULTIPLE,
    },
    "balanced": {
        "label": "균형형",
        "bb_max": 0.25,
        "rsi_max": 45,
        "setup_lookback": 4,
        "ema_slope_lookback": 3,
        "minimum_volume_ratio": 0.8,
        "bullish_candle": False,
        "require_regime": False,
        "require_mtf": False,
        "stop_atr": 1.2,
        "target_atr": 2.2,
        "trailing_activation_atr": 1.2,
        "trailing_atr": 1.0,
    },
    "confirmed": {
        "label": "추세확인형",
        "bb_max": 0.30,
        "rsi_max": 48,
        "setup_lookback": 5,
        "ema_slope_lookback": 2,
        "minimum_volume_ratio": 1.0,
        "bullish_candle": True,
        "require_regime": False,
        "require_mtf": False,
        "stop_atr": 1.3,
        "target_atr": 2.5,
        "trailing_activation_atr": 1.4,
        "trailing_atr": 1.1,
    },
    "regime": {
        "label": "시장국면형",
        "bb_max": 0.25,
        "rsi_max": 45,
        "setup_lookback": SETUP_LOOKBACK_CANDLES,
        "ema_slope_lookback": 0,
        "minimum_volume_ratio": 0.0,
        "bullish_candle": False,
        "require_regime": True,
        "require_mtf": False,
        "stop_atr": STOP_ATR_MULTIPLE,
        "target_atr": TAKE_PROFIT_ATR_MULTIPLE,
        "trailing_activation_atr": TRAILING_ACTIVATION_ATR,
        "trailing_atr": TRAILING_ATR_MULTIPLE,
    },
    "advanced": {
        "label": "다중시간봉형",
        "bb_max": 0.25,
        "rsi_max": 45,
        "setup_lookback": SETUP_LOOKBACK_CANDLES,
        "ema_slope_lookback": 0,
        "minimum_volume_ratio": 0.0,
        "bullish_candle": False,
        "require_regime": True,
        "require_mtf": True,
        "stop_atr": STOP_ATR_MULTIPLE,
        "target_atr": TAKE_PROFIT_ATR_MULTIPLE,
        "trailing_activation_atr": TRAILING_ACTIVATION_ATR,
        "trailing_atr": TRAILING_ATR_MULTIPLE,
    },
    "adaptive": {
        "label": "국면전환형",
        "bb_max": 0.25,
        "rsi_max": 45,
        "setup_lookback": SETUP_LOOKBACK_CANDLES,
        "ema_slope_lookback": 0,
        "minimum_volume_ratio": 0.0,
        "bullish_candle": False,
        "require_regime": False,
        "require_mtf": True,
        "adaptive": True,
        "stop_atr": 1.0,
        "target_atr": 4.0,
        "trailing_activation_atr": 2.0,
        "trailing_atr": 1.5,
    },
}


def _higher_timeframe_flags(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    source = frame[["time", "open", "high", "low", "close", "volume"]].copy()
    source["_time"] = pd.to_datetime(source["time"])
    aggregated = (
        source.set_index("_time")
        .resample(f"{minutes}min", closed="left", label="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna()
        .reset_index()
    )
    if len(aggregated) < 60:
        return pd.DataFrame(
            {
                "trend_ok": pd.Series(False, index=frame.index),
                "bearish": pd.Series(False, index=frame.index),
                "sideways": pd.Series(True, index=frame.index),
            }
        )
    candles = [
        {
            "candle_date_time_kst": row["_time"].isoformat(),
            "opening_price": row["open"],
            "high_price": row["high"],
            "low_price": row["low"],
            "trade_price": row["close"],
            "candle_acc_trade_volume": row["volume"],
        }
        for _, row in aggregated.iterrows()
    ]
    higher = calculate_indicators(candles)
    higher["_time"] = pd.to_datetime(higher["time"])
    higher["trend_ok"] = (
        (higher["close"] > higher["ema_regime"])
        & (
            higher["ema_regime"]
            > higher["ema_regime"].shift(REGIME_SLOPE_CANDLES)
        )
    )
    strong = (higher["adx"] >= REGIME_MIN_ADX) & (
        higher["atr_rate"] >= REGIME_MIN_ATR_RATE
    )
    higher["bearish"] = (
        strong
        & (higher["close"] < higher["ema_regime"])
        & (
            higher["ema_regime"]
            <= higher["ema_regime"].shift(REGIME_SLOPE_CANDLES)
        )
    )
    higher["sideways"] = ~strong
    aligned = pd.merge_asof(
        source[["_time"]].sort_values("_time"),
        higher[["_time", "trend_ok", "bearish", "sideways"]].sort_values("_time"),
        on="_time",
        direction="backward",
    )
    return aligned[["trend_ok", "bearish", "sideways"]].fillna(
        {"trend_ok": False, "bearish": False, "sideways": True}
    ).astype(bool).reset_index(drop=True)


def apply_market_context(
    frames: dict[str, pd.DataFrame],
    profile: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    require_mtf = bool(profile.get("require_mtf"))
    for frame in frames.values():
        if require_mtf:
            flags_60 = _higher_timeframe_flags(frame, 60)
            flags_240 = _higher_timeframe_flags(frame, 240)
            frame["mtf_60_ok"] = flags_60["trend_ok"]
            frame["mtf_60_bearish"] = flags_60["bearish"]
            frame["mtf_60_sideways"] = flags_60["sideways"]
            frame["mtf_240_ok"] = flags_240["trend_ok"]
            frame["mtf_240_bearish"] = flags_240["bearish"]
            frame["mtf_240_sideways"] = flags_240["sideways"]
        else:
            frame["mtf_60_ok"] = True
            frame["mtf_240_ok"] = True
            frame["mtf_60_bearish"] = False
            frame["mtf_240_bearish"] = False
            frame["mtf_60_sideways"] = False
            frame["mtf_240_sideways"] = False
        strong = (frame["adx"] >= REGIME_MIN_ADX) & (
            frame["atr_rate"] >= REGIME_MIN_ATR_RATE
        )
        bullish = (
            strong
            & (frame["close"] > frame["ema_regime"])
            & (
                frame["ema_regime"]
                > frame["ema_regime"].shift(REGIME_SLOPE_CANDLES)
            )
        )
        frame["entry_regime"] = "bearish"
        frame.loc[~strong, "entry_regime"] = "sideways"
        frame.loc[bullish, "entry_regime"] = "bullish"

    if require_mtf and "KRW-BTC" in frames:
        benchmark = frames["KRW-BTC"][
            ["time", "mtf_240_ok", "mtf_240_bearish", "mtf_240_sideways"]
        ].rename(
            columns={
                "mtf_240_ok": "btc_240_ok",
                "mtf_240_bearish": "btc_240_bearish",
                "mtf_240_sideways": "btc_240_sideways",
            }
        )
        benchmark["_time"] = pd.to_datetime(benchmark["time"])
        for market, frame in frames.items():
            base = frame.copy()
            base["_time"] = pd.to_datetime(base["time"])
            merged = pd.merge_asof(
                base.sort_values("_time"),
                benchmark[
                    [
                        "_time",
                        "btc_240_ok",
                        "btc_240_bearish",
                        "btc_240_sideways",
                    ]
                ].sort_values("_time"),
                on="_time",
                direction="backward",
            ).sort_index()
            frame["btc_240_ok"] = merged["btc_240_ok"].fillna(False).to_numpy()
            frame["btc_240_bearish"] = merged["btc_240_bearish"].fillna(
                False
            ).to_numpy()
            frame["btc_240_sideways"] = merged["btc_240_sideways"].fillna(
                True
            ).to_numpy()
            frame["multi_timeframe_ok"] = frame["btc_240_ok"] & (
                frame["mtf_60_ok"] | frame["mtf_240_ok"]
            )
            if bool(profile.get("adaptive")):
                trend_mode = frame["multi_timeframe_ok"]
                sideways_mode = (
                    ~trend_mode
                    & ~frame["btc_240_bearish"]
                    & ~frame["mtf_240_bearish"]
                    & frame["mtf_60_sideways"]
                )
                frame["strategy_mode"] = "cash"
                frame.loc[
                    trend_mode & frame["pullback_entry_candidate"],
                    "strategy_mode",
                ] = "trend_pullback"
                frame.loc[
                    trend_mode & frame["breakout_entry_candidate"],
                    "strategy_mode",
                ] = "trend_breakout"
                frame.loc[
                    sideways_mode & frame["mean_entry_candidate"],
                    "strategy_mode",
                ] = "sideways_mean_reversion"
                frame["buy_signal"] = (
                    trend_mode & frame["trend_entry_candidate"]
                ) | (
                    sideways_mode & frame["mean_entry_candidate"]
                )
                frame["sell_signal"] |= (
                    frame["btc_240_bearish"]
                    | frame["mtf_240_bearish"]
                    | (
                        sideways_mode
                        & (
                            (frame["close"] >= frame["bb_mid"])
                            | (frame["rsi"] >= 55)
                        )
                    )
                )
                frame["entry_regime"] = frame["strategy_mode"]
            else:
                frame["buy_signal"] &= frame["multi_timeframe_ok"]
    return frames


def prepare_strategy_frame(
    candles: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
) -> pd.DataFrame:
    settings = profile or STRATEGY_PROFILES["baseline"]
    frame = calculate_indicators(completed_candles(candles, CANDLE_UNIT_MINUTES))
    previous = frame.shift(1)
    setup = (
        (frame["bb_position"] <= float(settings["bb_max"]))
        & (frame["rsi"] <= float(settings["rsi_max"]))
    )
    lookback = int(settings["setup_lookback"])
    slope_lookback = int(settings["ema_slope_lookback"])
    trend_confirmed = (
        frame["ema_slow"] > frame["ema_slow"].shift(slope_lookback)
        if slope_lookback > 0
        else pd.Series(True, index=frame.index)
    )
    volume_average = frame["volume"].rolling(20, min_periods=1).mean()
    volume_confirmed = (
        frame["volume"] >= volume_average * float(settings["minimum_volume_ratio"])
    )
    candle_confirmed = (
        frame["close"] > frame["open"]
        if bool(settings["bullish_candle"])
        else pd.Series(True, index=frame.index)
    )
    regime_confirmed = (
        (frame["close"] > frame["ema_regime"])
        & (
            frame["ema_regime"]
            > frame["ema_regime"].shift(REGIME_SLOPE_CANDLES)
        )
        & (frame["adx"] >= REGIME_MIN_ADX)
        & (frame["atr_rate"] >= REGIME_MIN_ATR_RATE)
        if bool(settings["require_regime"])
        else pd.Series(True, index=frame.index)
    )
    frame["buy_signal"] = (
        setup.rolling(lookback, min_periods=1).max().astype(bool)
        & (frame["close"] > previous["close"])
        & (frame["rsi"] > previous["rsi"])
        & (frame["ema_fast"] > frame["ema_slow"])
        & trend_confirmed
        & volume_confirmed
        & candle_confirmed
        & regime_confirmed
    )
    bollinger_reversal = (
        (previous["bb_position"] >= 0.90)
        & (frame["close"] < previous["close"])
    )
    ema_cross = (
        (previous["ema_fast"] >= previous["ema_slow"])
        & (frame["ema_fast"] < frame["ema_slow"])
    )
    rsi_reversal = (previous["rsi"] >= 70) & (frame["rsi"] < previous["rsi"])
    frame["sell_signal"] = ema_cross | (bollinger_reversal & rsi_reversal)
    prior_high = frame["high"].shift(1).rolling(96, min_periods=96).max()
    prior_volume = frame["volume"].shift(1).rolling(96, min_periods=96).mean()
    frame["pullback_entry_candidate"] = (
        (previous["close"] <= previous["ema_fast"])
        & (frame["close"] > frame["ema_fast"])
        & (frame["ema_fast"] > frame["ema_slow"])
        & (frame["ema_slow"] > frame["ema_slow"].shift(3))
        & (frame["adx"] >= 18)
        & frame["rsi"].between(45, 60)
        & (frame["close"] > previous["close"])
        & (frame["rsi"] > previous["rsi"])
        & (frame["close"] > frame["open"])
        & (frame["volume"] >= prior_volume)
    )
    frame["breakout_entry_candidate"] = (
        (frame["close"] > prior_high)
        & (frame["ema_fast"] > frame["ema_slow"])
        & (frame["adx"] >= 20)
        & frame["rsi"].between(55, 72, inclusive="left")
        & (frame["close"] > frame["open"])
        & (frame["volume"] >= prior_volume * 2.0)
    )
    frame["trend_entry_candidate"] = (
        frame["pullback_entry_candidate"] | frame["breakout_entry_candidate"]
    )
    frame["mean_entry_candidate"] = (
        (previous["bb_position"] <= 0.10)
        & (previous["rsi"] <= 32)
        & (frame["adx"] < 15)
        & (frame["close"] > previous["close"])
        & (frame["rsi"] > previous["rsi"])
    )
    return frame


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def simulate_portfolio(
    frames: dict[str, pd.DataFrame],
    initial_cash: float = INITIAL_CASH_KRW,
    profile: dict[str, Any] | None = None,
    execution: dict[str, float] | None = None,
) -> dict[str, Any]:
    settings = profile or STRATEGY_PROFILES["baseline"]
    execution_settings = {
        "spread_rate": 0.0004,
        "latency_slippage_rate": EXECUTION_LATENCY_SLIPPAGE_RATE,
        "fill_rate": 1.0,
    }
    if execution:
        execution_settings.update(execution)
    adverse_rate = (
        BACKTEST_SLIPPAGE_RATE
        + float(execution_settings["spread_rate"]) / 2
        + float(execution_settings["latency_slippage_rate"])
    )
    fill_rate = max(0.0, min(1.0, float(execution_settings["fill_rate"])))
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    all_times: set[str] = set()
    for market, frame in frames.items():
        records = frame.to_dict("records")
        indexed[market] = {str(row["time"]): row for row in records}
        all_times.update(indexed[market])
    timeline = sorted(all_times)
    if len(timeline) < 3:
        raise ValueError("백테스트 데이터가 부족합니다.")

    cash = float(initial_cash)
    positions: dict[str, dict[str, Any]] = {}
    previous_rows: dict[str, dict[str, Any]] = {}
    last_rows: dict[str, dict[str, Any]] = {}
    last_sell_time: dict[str, datetime] = {}
    closed_trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    total_fees = 0.0
    current_day: str | None = None
    daily_start_equity = cash
    daily_locked = False
    consecutive_losses = 0
    market_losses: dict[str, int] = defaultdict(int)
    market_blocked_until: dict[str, datetime] = {}
    global_blocked_until: datetime | None = None
    safety_stops = 0

    def marked_equity() -> float:
        value = cash
        for market, position in positions.items():
            row = last_rows.get(market)
            price = float(row["close"]) if row else float(position["entry_price"])
            value += float(position["quantity"]) * price * (1 - FEE_RATE)
        return value

    def close_position(market: str, price: float, time_text: str, reason: str) -> None:
        nonlocal cash, total_fees, consecutive_losses, global_blocked_until, safety_stops
        position = positions.pop(market)
        execution_price = max(0.00000001, price * (1 - adverse_rate))
        gross = float(position["quantity"]) * execution_price
        fee = gross * FEE_RATE
        net = gross - fee
        pnl = net - float(position["cost_basis"])
        cash += net
        total_fees += fee
        sold_at = datetime.fromisoformat(time_text)
        last_sell_time[market] = sold_at
        closed_trades.append(
            {
                "market": market,
                "entry_time": position["entry_time"],
                "exit_time": time_text,
                "entry_price": position["entry_price"],
                "exit_price": execution_price,
                "pnl": pnl,
                "return_rate": pnl / float(position["cost_basis"]),
                "reason": reason,
                "entry_regime": position.get("entry_regime", "unknown"),
            }
        )
        if pnl > 0:
            consecutive_losses = 0
            market_losses[market] = 0
        else:
            consecutive_losses += 1
            market_losses[market] += 1
            if market_losses[market] >= MARKET_LOSS_STREAK_LIMIT:
                market_blocked_until[market] = sold_at + timedelta(
                    hours=MARKET_BLOCK_HOURS
                )
                safety_stops += 1
            if consecutive_losses >= GLOBAL_LOSS_STREAK_LIMIT:
                global_blocked_until = sold_at + timedelta(hours=MARKET_BLOCK_HOURS)
                consecutive_losses = 0
                safety_stops += 1

    for time_text in timeline:
        rows = {
            market: by_time[time_text]
            for market, by_time in indexed.items()
            if time_text in by_time
        }
        if not rows:
            continue
        last_rows.update(rows)
        day = time_text[:10]
        if day != current_day:
            current_day = day
            daily_start_equity = marked_equity()
            daily_locked = False

        for market in list(positions):
            row = rows.get(market)
            if not row:
                continue
            position = positions[market]
            entry = float(position["entry_price"])
            atr = float(position["entry_atr"])
            position["high_water"] = max(float(position["high_water"]), float(row["high"]))
            high_water = float(position["high_water"])
            stop_price = entry - (float(settings["stop_atr"]) * atr)
            target_price = entry + (float(settings["target_atr"]) * atr)
            trailing_active = high_water >= entry + (
                float(settings["trailing_activation_atr"]) * atr
            )
            trailing_price = high_water - (float(settings["trailing_atr"]) * atr)
            previous = previous_rows.get(market)

            if float(row["low"]) <= stop_price:
                close_position(market, min(float(row["open"]), stop_price), time_text, "ATR 손절")
            elif float(row["high"]) >= target_price:
                close_position(market, target_price, time_text, "ATR 목표수익")
            elif trailing_active and float(row["low"]) <= trailing_price:
                close_position(market, min(float(row["open"]), trailing_price), time_text, "ATR 추적손절")
            elif previous and bool(previous.get("sell_signal")):
                close_position(market, float(row["open"]), time_text, "추세 매도")

        equity_now = marked_equity()
        if daily_start_equity > 0 and (
            (equity_now - daily_start_equity) / daily_start_equity
        ) <= -DAILY_LOSS_LIMIT_RATE:
            daily_locked = True

        if not daily_locked and len(positions) < MAX_OPEN_POSITIONS:
            for market in sorted(rows):
                if market in positions or len(positions) >= MAX_OPEN_POSITIONS:
                    continue
                previous = previous_rows.get(market)
                if not previous or not bool(previous.get("buy_signal")):
                    continue
                sold_at = last_sell_time.get(market)
                now = datetime.fromisoformat(time_text)
                if global_blocked_until and now < global_blocked_until:
                    continue
                if (
                    market_blocked_until.get(market)
                    and now >= market_blocked_until[market]
                ):
                    market_blocked_until.pop(market, None)
                    market_losses[market] = 0
                if market_blocked_until.get(market) and now < market_blocked_until[market]:
                    continue
                if sold_at and now - sold_at < timedelta(minutes=COOLDOWN_MINUTES):
                    continue
                row = rows[market]
                execution_price = float(row["open"]) * (1 + adverse_rate)
                budget = cash * TRADE_FRACTION * fill_rate
                if budget < 5_000:
                    continue
                quantity = budget / (execution_price * (1 + FEE_RATE))
                gross = quantity * execution_price
                fee = gross * FEE_RATE
                cost = gross + fee
                cash -= cost
                total_fees += fee
                positions[market] = {
                    "quantity": quantity,
                    "entry_price": execution_price,
                    "cost_basis": cost,
                    "entry_atr": float(previous["atr"]),
                    "high_water": execution_price,
                    "entry_time": time_text,
                    "entry_regime": previous.get("entry_regime", "unknown"),
                }

        equity_curve.append({"time": time_text, "equity": marked_equity()})
        previous_rows.update(rows)

    final_time = timeline[-1]
    for market in list(positions):
        row = last_rows[market]
        close_position(market, float(row["close"]), final_time, "기간 종료")
    final_equity = cash
    if equity_curve:
        equity_curve[-1]["equity"] = final_equity

    peak = float(initial_cash)
    max_drawdown = 0.0
    daily_curve: list[dict[str, Any]] = []
    last_day = None
    for point in equity_curve:
        value = float(point["equity"])
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, (value / peak) - 1)
        day = point["time"][:10]
        if day != last_day:
            daily_curve.append({"date": day, "equity": value})
            last_day = day
        else:
            daily_curve[-1]["equity"] = value

    wins = [trade for trade in closed_trades if trade["pnl"] > 0]
    losses = [trade for trade in closed_trades if trade["pnl"] <= 0]
    gross_profit = sum(float(trade["pnl"]) for trade in wins)
    gross_loss = abs(sum(float(trade["pnl"]) for trade in losses))
    per_market: list[dict[str, Any]] = []
    per_regime: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in closed_trades:
        grouped[trade["market"]].append(trade)
    for market in sorted(frames):
        trades = grouped.get(market, [])
        market_wins = [trade for trade in trades if trade["pnl"] > 0]
        per_market.append(
            {
                "market": market,
                "trades": len(trades),
                "wins": len(market_wins),
                "win_rate": _safe_ratio(len(market_wins), len(trades)),
                "pnl": sum(float(trade["pnl"]) for trade in trades),
            }
        )
    regime_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in closed_trades:
        regime_groups[str(trade.get("entry_regime", "unknown"))].append(trade)
    for regime in sorted(regime_groups):
        trades = regime_groups.get(regime, [])
        if not trades:
            continue
        regime_wins = [trade for trade in trades if trade["pnl"] > 0]
        per_regime.append(
            {
                "regime": regime,
                "trades": len(trades),
                "win_rate": _safe_ratio(len(regime_wins), len(trades)),
                "pnl": sum(float(trade["pnl"]) for trade in trades),
            }
        )

    return {
        "initial_cash": float(initial_cash),
        "final_equity": final_equity,
        "total_return": (final_equity / float(initial_cash)) - 1,
        "total_pnl": final_equity - float(initial_cash),
        "max_drawdown": max_drawdown,
        "trades": len(closed_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": _safe_ratio(len(wins), len(closed_trades)),
        "profit_factor": _safe_ratio(gross_profit, gross_loss),
        "total_fees": total_fees,
        "per_market": per_market,
        "per_regime": per_regime,
        "safety_stops": safety_stops,
        "execution": execution_settings,
        "equity_curve": daily_curve,
        "recent_trades": list(reversed(closed_trades[-50:])),
    }


def _slice_frames(
    frames: dict[str, pd.DataFrame],
    start: datetime,
    end: datetime,
) -> dict[str, pd.DataFrame]:
    sliced: dict[str, pd.DataFrame] = {}
    for market, frame in frames.items():
        times = pd.to_datetime(frame["time"])
        sliced[market] = frame.loc[(times >= start) & (times < end)].reset_index(
            drop=True
        )
    return sliced


def validate_candle_histories(
    histories: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    markets: list[dict[str, Any]] = []
    valid = True
    complete_coverage = True
    for market, candles in histories.items():
        times = [
            datetime.fromisoformat(row["candle_date_time_utc"])
            for row in candles
        ]
        duplicates = len(times) - len(set(times))
        invalid_ohlc = sum(
            1
            for row in candles
            if (
                float(row["high_price"])
                < max(float(row["opening_price"]), float(row["trade_price"]))
                or float(row["low_price"])
                > min(float(row["opening_price"]), float(row["trade_price"]))
                or float(row["low_price"]) > float(row["high_price"])
                or float(row["candle_acc_trade_volume"]) < 0
            )
        )
        gaps = [
            (right - left).total_seconds() / 60
            for left, right in zip(times, times[1:])
            if right > left
        ]
        max_gap = max(gaps, default=0.0)
        ordered = all(right > left for left, right in zip(times, times[1:]))
        market_valid = ordered and duplicates == 0 and invalid_ohlc == 0
        coverage_days = (
            (times[-1] - times[0]).total_seconds() / 86400
            if len(times) > 1
            else 0
        )
        coverage_complete = coverage_days >= max(BACKTEST_ALLOWED_DAYS) - 2
        valid = valid and market_valid
        complete_coverage = complete_coverage and coverage_complete
        markets.append(
            {
                "market": market,
                "rows": len(candles),
                "ordered": ordered,
                "duplicates": duplicates,
                "invalid_ohlc": invalid_ohlc,
                "max_gap_minutes": max_gap,
                "coverage_days": coverage_days,
                "coverage_complete": coverage_complete,
                "valid": market_valid,
            }
        )
    return {
        "valid": valid,
        "complete_coverage": complete_coverage,
        "markets": markets,
        "warning": (
            None
            if complete_coverage
            else "신규 상장 종목은 상장 이후 데이터만 검증했습니다."
        ),
    }


def walk_forward_validation(
    frames_by_profile: dict[str, dict[str, pd.DataFrame]],
    folds: int = 10,
) -> dict[str, Any]:
    reference = next(iter(next(iter(frames_by_profile.values())).values()))
    latest = pd.to_datetime(reference["time"]).max().to_pydatetime()
    test_days = 12
    training_days = 45
    first_test = latest - timedelta(days=test_days * folds)
    rows: list[dict[str, Any]] = []
    for index in range(folds):
        test_start = first_test + timedelta(days=test_days * index)
        test_end = test_start + timedelta(days=test_days)
        train_start = test_start - timedelta(days=training_days)
        candidates: list[tuple[float, str]] = []
        for profile_id, profile_frames in frames_by_profile.items():
            train = simulate_portfolio(
                _slice_frames(profile_frames, train_start, test_start),
                profile=STRATEGY_PROFILES[profile_id],
            )
            score = (
                float(train["total_return"])
                - abs(float(train["max_drawdown"])) * 0.35
                if train["trades"] >= 3
                else -999.0
            )
            candidates.append((score, profile_id))
        _, selected = max(candidates)
        test = simulate_portfolio(
            _slice_frames(frames_by_profile[selected], test_start, test_end),
            profile=STRATEGY_PROFILES[selected],
        )
        rows.append(
            {
                "fold": index + 1,
                "train_days": training_days,
                "test_start": test_start.date().isoformat(),
                "test_end": test_end.date().isoformat(),
                "selected_profile": selected,
                "selected_label": STRATEGY_PROFILES[selected]["label"],
                "return": test["total_return"],
                "max_drawdown": test["max_drawdown"],
                "trades": test["trades"],
                "profit_factor": test["profit_factor"],
            }
        )
    cumulative = 1.0
    for row in rows:
        cumulative *= 1 + float(row["return"])
    return {
        "folds": folds,
        "profitable_folds": sum(1 for row in rows if row["return"] > 0),
        "cumulative_return": cumulative - 1,
        "average_return": sum(float(row["return"]) for row in rows) / len(rows),
        "worst_drawdown": min(float(row["max_drawdown"]) for row in rows),
        "total_trades": sum(int(row["trades"]) for row in rows),
        "results": rows,
    }


def execution_stress_simulations(
    frames: dict[str, pd.DataFrame],
    profile: dict[str, Any],
    count: int = 10,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for index in range(count):
        assumptions = {
            "spread_rate": 0.0002 + index * 0.00008,
            "latency_slippage_rate": 0.00005 + index * 0.00003,
            "fill_rate": 1.0 - index * 0.035,
        }
        result = simulate_portfolio(
            frames,
            profile=profile,
            execution=assumptions,
        )
        rows.append(
            {
                "simulation": index + 1,
                **assumptions,
                "total_return": result["total_return"],
                "max_drawdown": result["max_drawdown"],
                "trades": result["trades"],
                "profit_factor": result["profit_factor"],
            }
        )
    return {
        "count": count,
        "profitable": sum(1 for row in rows if row["total_return"] > 0),
        "best_return": max(float(row["total_return"]) for row in rows),
        "worst_return": min(float(row["total_return"]) for row in rows),
        "results": rows,
    }


class BacktestManager:
    def __init__(self, result_path: Path) -> None:
        self.result_path = result_path
        self.comparison_path = result_path.with_name("backtest_comparison.json")
        self.lock = threading.RLock()
        self.status_data: dict[str, Any] = {
            "running": False,
            "progress": 0,
            "message": "백테스트를 실행해주세요.",
            "error": None,
            "result": self._load_result(),
            "comparison": self._load_json(self.comparison_path),
        }

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def _load_result(self) -> dict[str, Any] | None:
        return self._load_json(self.result_path)

    @staticmethod
    def _save_json(path: Path, result: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _save_result(self, result: dict[str, Any]) -> None:
        self._save_json(self.result_path, result)

    def status(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.status_data, ensure_ascii=False))

    def start(self, markets: tuple[str, ...], days: int) -> bool:
        if days not in BACKTEST_ALLOWED_DAYS:
            raise ValueError("지원하지 않는 백테스트 기간입니다.")
        with self.lock:
            if self.status_data["running"]:
                return False
            self.status_data.update(
                {
                    "running": True,
                    "progress": 0,
                    "message": "과거 시세를 준비하고 있습니다.",
                    "error": None,
                }
            )
        thread = threading.Thread(
            target=self._run,
            args=(tuple(markets), days),
            daemon=True,
            name="paper-backtest",
        )
        thread.start()
        return True

    def start_comparison(self, markets: tuple[str, ...]) -> bool:
        with self.lock:
            if self.status_data["running"]:
                return False
            self.status_data.update(
                {
                    "running": True,
                    "progress": 0,
                    "message": "전략 비교용 180일 시세를 준비하고 있습니다.",
                    "error": None,
                }
            )
        thread = threading.Thread(
            target=self._run_comparison,
            args=(tuple(markets),),
            daemon=True,
            name="paper-backtest-comparison",
        )
        thread.start()
        return True

    def _run(self, markets: tuple[str, ...], days: int) -> None:
        try:
            client = UpbitPublicClient(timeout=12)
            histories: dict[str, list[dict[str, Any]]] = {}
            total = max(len(markets), 1)
            for index, market in enumerate(markets):
                def report(fraction: float, index: int = index, market: str = market) -> None:
                    with self.lock:
                        self.status_data["progress"] = round(
                            ((index + fraction) / total) * 80
                        )
                        self.status_data["message"] = f"{market} 시세 수집 중"

                histories[market] = client.historical_candles(
                    market,
                    CANDLE_UNIT_MINUTES,
                    days,
                    progress=report,
                )
            with self.lock:
                self.status_data.update({"progress": 85, "message": "전략을 계산하고 있습니다."})
            profile = STRATEGY_PROFILES["advanced"]
            frames = apply_market_context(
                {
                    market: prepare_strategy_frame(candles, profile)
                    for market, candles in histories.items()
                },
                profile,
            )
            result = simulate_portfolio(frames, profile=profile)
            result.update(
                {
                    "days": days,
                    "markets": list(markets),
                    "profile": "advanced",
                    "profile_label": profile["label"],
                    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "assumptions": {
                        "fee_rate": FEE_RATE,
                        "slippage_rate": BACKTEST_SLIPPAGE_RATE,
                        "position_fraction": TRADE_FRACTION,
                        "max_positions": MAX_OPEN_POSITIONS,
                    },
                }
            )
            self._save_result(result)
            with self.lock:
                self.status_data.update(
                    {
                        "running": False,
                        "progress": 100,
                        "message": "백테스트 완료",
                        "error": None,
                        "result": result,
                    }
                )
        except Exception as exc:
            with self.lock:
                self.status_data.update(
                    {
                        "running": False,
                        "message": "백테스트 실패",
                        "error": str(exc),
                    }
                )

    def _run_comparison(self, markets: tuple[str, ...]) -> None:
        try:
            client = UpbitPublicClient(timeout=12)
            histories: dict[str, list[dict[str, Any]]] = {}
            total = max(len(markets), 1)
            for index, market in enumerate(markets):
                def report(fraction: float, index: int = index, market: str = market) -> None:
                    with self.lock:
                        self.status_data["progress"] = round(
                            ((index + fraction) / total) * 75
                        )
                        self.status_data["message"] = f"{market} 180일 시세 수집 중"

                histories[market] = client.historical_candles(
                    market,
                    CANDLE_UNIT_MINUTES,
                    max(BACKTEST_ALLOWED_DAYS),
                    progress=report,
                )

            data_quality = validate_candle_histories(histories)
            comparison_rows: list[dict[str, Any]] = []
            profile_items = list(STRATEGY_PROFILES.items())
            work_total = len(profile_items) * len(BACKTEST_ALLOWED_DAYS)
            work_done = 0
            frames_by_profile: dict[str, dict[str, pd.DataFrame]] = {}
            for profile_id, profile in profile_items:
                full_frames = apply_market_context(
                    {
                        market: prepare_strategy_frame(candles, profile)
                        for market, candles in histories.items()
                    },
                    profile,
                )
                frames_by_profile[profile_id] = full_frames
                reference = next(iter(full_frames.values()))
                latest = pd.to_datetime(reference["time"]).max().to_pydatetime()
                period_results: list[dict[str, Any]] = []
                for days in BACKTEST_ALLOWED_DAYS:
                    frames = _slice_frames(
                        full_frames,
                        latest - timedelta(days=days),
                        latest + timedelta(minutes=CANDLE_UNIT_MINUTES),
                    )
                    result = simulate_portfolio(frames, profile=profile)
                    period_results.append(
                        {
                            "days": days,
                            "total_return": result["total_return"],
                            "max_drawdown": result["max_drawdown"],
                            "win_rate": result["win_rate"],
                            "profit_factor": result["profit_factor"],
                            "trades": result["trades"],
                        }
                    )
                    work_done += 1
                    with self.lock:
                        self.status_data["progress"] = 75 + round(
                            (work_done / work_total) * 24
                        )
                        self.status_data["message"] = (
                            f"{profile['label']} {days}일 검증 중"
                        )

                returns = [float(item["total_return"]) for item in period_results]
                drawdowns = [abs(float(item["max_drawdown"])) for item in period_results]
                score = min(returns) * 0.6 + (sum(returns) / len(returns)) * 0.4
                score -= (sum(drawdowns) / len(drawdowns)) * 0.15
                robust = (
                    all(value > 0 for value in returns)
                    and all(
                        item["profit_factor"] is not None
                        and float(item["profit_factor"]) >= 1
                        for item in period_results
                    )
                    and period_results[-1]["trades"] >= 20
                )
                comparison_rows.append(
                    {
                        "profile": profile_id,
                        "label": profile["label"],
                        "score": score,
                        "robust": robust,
                        "periods": period_results,
                    }
                )

            comparison_rows.sort(key=lambda item: item["score"], reverse=True)
            robust_rows = [item for item in comparison_rows if item["robust"]]
            with self.lock:
                self.status_data.update(
                    {
                        "progress": 98,
                        "message": "10구간 검증과 체결 스트레스 테스트 중",
                    }
                )
            walk_forward = walk_forward_validation(frames_by_profile, folds=10)
            advanced_frames = frames_by_profile["adaptive"]
            stress = execution_stress_simulations(
                advanced_frames,
                STRATEGY_PROFILES["adaptive"],
                count=10,
            )
            regime_result = simulate_portfolio(
                advanced_frames,
                profile=STRATEGY_PROFILES["adaptive"],
            )
            comparison = {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "markets": list(markets),
                "recommended_profile": robust_rows[0]["profile"] if robust_rows else None,
                "recommended_label": robust_rows[0]["label"] if robust_rows else None,
                "profiles": comparison_rows,
                "data_quality": data_quality,
                "walk_forward": walk_forward,
                "execution_stress": stress,
                "regime_performance": regime_result["per_regime"],
                "note": (
                    "모든 기간에서 수익과 손익비 1 이상을 만족한 전략만 추천합니다."
                ),
            }
            self._save_json(self.comparison_path, comparison)
            with self.lock:
                self.status_data.update(
                    {
                        "running": False,
                        "progress": 100,
                        "message": "전략 비교 완료",
                        "error": None,
                        "comparison": comparison,
                    }
                )
        except Exception as exc:
            with self.lock:
                self.status_data.update(
                    {
                        "running": False,
                        "message": "전략 비교 실패",
                        "error": str(exc),
                    }
                )
