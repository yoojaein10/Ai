from __future__ import annotations

import json
import math
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from config import (
    ATR_STOP_MULTIPLE,
    ATR_TARGET_MULTIPLE,
    ATR_TRAILING_MULTIPLE,
    BUY_COMMISSION_RATE,
    DAILY_LOSS_LIMIT_RATE,
    INITIAL_CASH_KRW,
    MAX_OPEN_POSITIONS,
    SELL_COMMISSION_RATE,
    SELL_TAX_RATE,
    SLIPPAGE_RATE,
    TRADE_FRACTION,
    TRAILING_ACTIVATION_ATR,
)


class StockPaperTrader:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.lock = threading.RLock()
        self.state = self._load()

    @staticmethod
    def default_state() -> dict[str, Any]:
        return {
            "version": 1,
            "initial_cash": float(INITIAL_CASH_KRW),
            "cash": float(INITIAL_CASH_KRW),
            "realized_pnl": 0.0,
            "positions": {},
            "trades": [],
            "last_prices": {},
            "last_action_candle": {},
            "auto_enabled": True,
            "daily": {
                "date": datetime.now().astimezone().date().isoformat(),
                "start_equity": float(INITIAL_CASH_KRW),
                "locked": False,
            },
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self.default_state()
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            return loaded if loaded.get("version") == 1 else self.default_state()
        except (OSError, ValueError, TypeError):
            return self.default_state()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.state_path)

    def _equity(self) -> float:
        holdings = sum(
            float(position["quantity"])
            * float(self.state["last_prices"].get(symbol, position["entry_price"]))
            for symbol, position in self.state["positions"].items()
        )
        return float(self.state["cash"]) + holdings

    def _refresh_daily(self) -> None:
        today = datetime.now().astimezone().date().isoformat()
        if self.state["daily"]["date"] != today:
            self.state["daily"] = {
                "date": today,
                "start_equity": self._equity(),
                "locked": False,
            }
        start = max(float(self.state["daily"]["start_equity"]), 1)
        if (self._equity() - start) / start <= -DAILY_LOSS_LIMIT_RATE:
            self.state["daily"]["locked"] = True

    def update_price(self, symbol: str, price: float) -> None:
        with self.lock:
            if price > 0:
                self.state["last_prices"][symbol] = float(price)
                position = self.state["positions"].get(symbol)
                if position:
                    position["high_water"] = max(
                        float(position["high_water"]), float(price)
                    )
                self._refresh_daily()
                self._save()

    def buy(self, symbol: str, name: str, price: float, atr: float, reason: str) -> bool:
        with self.lock:
            self._refresh_daily()
            if (
                price <= 0
                or symbol in self.state["positions"]
                or len(self.state["positions"]) >= MAX_OPEN_POSITIONS
                or self.state["daily"]["locked"]
            ):
                return False
            fill_price = float(price) * (1 + SLIPPAGE_RATE)
            budget = float(self.state["cash"]) * TRADE_FRACTION
            quantity = math.floor(budget / (fill_price * (1 + BUY_COMMISSION_RATE)))
            if quantity < 1:
                return False
            gross = quantity * fill_price
            fee = gross * BUY_COMMISSION_RATE
            total = gross + fee
            entry_atr = max(float(atr), fill_price * 0.005)
            self.state["cash"] -= total
            self.state["positions"][symbol] = {
                "symbol": symbol,
                "name": name,
                "quantity": quantity,
                "entry_price": fill_price,
                "cost_basis": total,
                "entry_atr": entry_atr,
                "high_water": fill_price,
                "stop_price": fill_price - ATR_STOP_MULTIPLE * entry_atr,
                "target_price": fill_price + ATR_TARGET_MULTIPLE * entry_atr,
                "opened_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._record(symbol, name, "BUY", fill_price, quantity, fee, 0, reason)
            self._save()
            return True

    def sell(self, symbol: str, price: float, reason: str) -> bool:
        with self.lock:
            position = self.state["positions"].get(symbol)
            if not position or price <= 0:
                return False
            fill_price = float(price) * (1 - SLIPPAGE_RATE)
            quantity = int(position["quantity"])
            gross = quantity * fill_price
            fee = gross * SELL_COMMISSION_RATE
            tax = gross * SELL_TAX_RATE
            net = gross - fee - tax
            pnl = net - float(position["cost_basis"])
            self.state["cash"] += net
            self.state["realized_pnl"] += pnl
            del self.state["positions"][symbol]
            self._record(
                symbol,
                str(position["name"]),
                "SELL",
                fill_price,
                quantity,
                fee + tax,
                pnl,
                reason,
            )
            self._refresh_daily()
            self._save()
            return True

    def evaluate(
        self,
        symbol: str,
        name: str,
        live_price: float,
        signal: dict,
        market_open: bool,
        quote_fresh: bool,
    ) -> str | None:
        self.update_price(symbol, live_price)
        if not market_open or not quote_fresh:
            return None
        with self.lock:
            position = self.state["positions"].get(symbol)
            auto = bool(self.state["auto_enabled"])
            candle = str(signal["time"])
            already_acted = self.state["last_action_candle"].get(symbol) == candle

        if position and auto:
            entry = float(position["entry_price"])
            atr = float(position["entry_atr"])
            high = float(position["high_water"])
            stop = float(position["stop_price"])
            target = float(position["target_price"])
            trailing = high - ATR_TRAILING_MULTIPLE * atr
            if live_price <= stop:
                reason = "ATR 손절"
            elif live_price >= target:
                reason = "ATR 목표수익"
            elif high >= entry + TRAILING_ACTIVATION_ATR * atr and live_price <= trailing:
                reason = "ATR 추적손절"
            elif signal["sell_signal"] and not already_acted:
                reason = "지표 매도"
            else:
                return None
            if self.sell(symbol, live_price, reason):
                with self.lock:
                    self.state["last_action_candle"][symbol] = candle
                    self._save()
                return "SELL"

        if (
            not position
            and auto
            and not already_acted
            and signal["buy_signal"]
            and not self.state["daily"]["locked"]
        ):
            if self.buy(
                symbol, name, live_price, float(signal["atr"]), "4/5 지표 매수"
            ):
                with self.lock:
                    self.state["last_action_candle"][symbol] = candle
                    self._save()
                return "BUY"
        return None

    def _record(
        self,
        symbol: str,
        name: str,
        side: str,
        price: float,
        quantity: int,
        costs: float,
        pnl: float,
        reason: str,
    ) -> None:
        self.state["trades"].append(
            {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "symbol": symbol,
                "name": name,
                "side": side,
                "price": price,
                "quantity": quantity,
                "costs": costs,
                "pnl": pnl,
                "reason": reason,
            }
        )
        self.state["trades"] = self.state["trades"][-200:]

    def set_auto(self, enabled: bool) -> None:
        with self.lock:
            self.state["auto_enabled"] = bool(enabled)
            self._save()

    def reset(self) -> None:
        with self.lock:
            self.state = self.default_state()
            self._save()

    def snapshot(self) -> dict:
        with self.lock:
            self._refresh_daily()
            equity = self._equity()
            positions = []
            unrealized = 0.0
            for symbol, position in self.state["positions"].items():
                current = float(
                    self.state["last_prices"].get(symbol, position["entry_price"])
                )
                item = dict(position)
                item["current_price"] = current
                item["market_value"] = current * int(position["quantity"])
                item["unrealized_pnl"] = item["market_value"] - float(
                    position["cost_basis"]
                )
                unrealized += item["unrealized_pnl"]
                positions.append(item)
            return {
                "initial_cash": self.state["initial_cash"],
                "cash": self.state["cash"],
                "equity": equity,
                "realized_pnl": self.state["realized_pnl"],
                "unrealized_pnl": unrealized,
                "total_pnl": equity - float(self.state["initial_cash"]),
                "positions": positions,
                "trades": list(reversed(self.state["trades"][-30:])),
                "auto_enabled": self.state["auto_enabled"],
                "daily": dict(self.state["daily"]),
            }
