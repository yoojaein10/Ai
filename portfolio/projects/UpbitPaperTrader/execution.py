from __future__ import annotations

from typing import Any

from config import (
    EXECUTION_DEPTH_LEVELS,
    EXECUTION_LATENCY_MS,
    EXECUTION_LATENCY_SLIPPAGE_RATE,
    MIN_PARTIAL_FILL_RATE,
)


def estimate_execution(
    side: str,
    fallback_price: float,
    orderbook: dict[str, Any] | None,
    *,
    desired_krw: float | None = None,
    desired_quantity: float | None = None,
) -> dict[str, float]:
    """Estimate a deterministic paper fill from the current public order book."""
    side = side.upper()
    if side not in {"BUY", "SELL"} or fallback_price <= 0:
        raise ValueError("올바른 모의체결 요청이 아닙니다.")

    units = list((orderbook or {}).get("orderbook_units") or [])[:EXECUTION_DEPTH_LEVELS]
    best_ask = float(units[0]["ask_price"]) if units else fallback_price
    best_bid = float(units[0]["bid_price"]) if units else fallback_price
    mid = (best_ask + best_bid) / 2 if best_ask > 0 and best_bid > 0 else fallback_price
    spread_rate = max(0.0, (best_ask - best_bid) / mid) if mid > 0 else 0.0

    requested = float(desired_krw if side == "BUY" else desired_quantity or 0)
    remaining = requested
    filled = 0.0
    filled_quantity = 0.0
    weighted_value = 0.0
    for unit in units:
        price = float(unit["ask_price"] if side == "BUY" else unit["bid_price"])
        size = float(unit["ask_size"] if side == "BUY" else unit["bid_size"])
        capacity = size * price if side == "BUY" else size
        take = min(remaining, capacity)
        if take <= 0:
            continue
        quantity = take / price if side == "BUY" else take
        weighted_value += quantity * price
        filled_quantity += quantity
        filled += take
        remaining -= take
        if remaining <= 0:
            break

    if requested <= 0:
        fill_rate = 1.0
    elif units:
        fill_rate = min(1.0, filled / requested)
    else:
        fill_rate = 1.0
    if fill_rate < MIN_PARTIAL_FILL_RATE:
        fill_rate = 0.0

    book_price = (
        weighted_value / filled_quantity
        if filled_quantity > 0
        else (best_ask if side == "BUY" else best_bid)
    )
    latency_move = EXECUTION_LATENCY_SLIPPAGE_RATE * (1 if side == "BUY" else -1)
    execution_price = max(1e-12, book_price * (1 + latency_move))
    return {
        "price": execution_price,
        "fill_rate": fill_rate,
        "spread_rate": spread_rate,
        "latency_ms": float(EXECUTION_LATENCY_MS),
    }
