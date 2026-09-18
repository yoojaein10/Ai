from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import (
    COOLDOWN_MINUTES,
    DAILY_LOSS_LIMIT_RATE,
    FEE_RATE,
    GLOBAL_LOSS_STREAK_LIMIT,
    INITIAL_CASH_KRW,
    MARKET_BLOCK_HOURS,
    MARKET_LOSS_STREAK_LIMIT,
    MAX_OPEN_POSITIONS,
    STOP_ATR_MULTIPLE,
    TAKE_PROFIT_ATR_MULTIPLE,
    TRADE_FRACTION,
    TRAILING_ACTIVATION_ATR,
    TRAILING_ATR_MULTIPLE,
)
from execution import estimate_execution


class PaperTrader:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.lock = threading.RLock()
        self.state = self._load()
        self._last_live_save = 0.0

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
            "last_sell_at": {},
            "alerts": [],
            "risk": {
                "locked": False,
                "reason": None,
                "consecutive_losses": 0,
                "market_losses": {},
                "blocked_markets": {},
            },
            "daily": {
                "date": datetime.now().astimezone().date().isoformat(),
                "start_equity": float(INITIAL_CASH_KRW),
                "locked": False,
            },
            "auto_enabled": True,
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self.default_state()
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if loaded.get("version") != 1:
                return self.default_state()
            defaults = self.default_state()
            for key, value in defaults.items():
                loaded.setdefault(key, value)
            for key, value in defaults["daily"].items():
                loaded["daily"].setdefault(key, value)
            return loaded
        except (OSError, ValueError, TypeError):
            return self.default_state()

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)

    def reset(self) -> None:
        with self.lock:
            self.state = self.default_state()
            self._save()

    def set_auto_enabled(self, enabled: bool) -> None:
        with self.lock:
            self.state["auto_enabled"] = bool(enabled)
            self._save()

    def unlock_risk(self) -> None:
        with self.lock:
            risk = self.state["risk"]
            risk["locked"] = False
            risk["reason"] = None
            risk["consecutive_losses"] = 0
            self._alert("위험 정지가 수동으로 해제되었습니다.", "info")
            self._save()

    def _alert(self, message: str, level: str = "info") -> None:
        self.state.setdefault("alerts", []).append(
            {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "level": level,
                "message": message,
            }
        )
        self.state["alerts"] = self.state["alerts"][-100:]

    def entry_guard(self, market: str) -> dict[str, Any]:
        with self.lock:
            risk = self.state["risk"]
            blocked_until_text = risk["blocked_markets"].get(market)
            blocked_until = (
                datetime.fromisoformat(blocked_until_text)
                if blocked_until_text
                else None
            )
            now = datetime.now().astimezone()
            if blocked_until and blocked_until <= now:
                risk["blocked_markets"].pop(market, None)
                risk["market_losses"][market] = 0
                blocked_until = None
                self._save()
            allowed = not bool(risk["locked"]) and blocked_until is None
            reason = risk.get("reason") if risk["locked"] else None
            if blocked_until:
                reason = f"{MARKET_LOSS_STREAK_LIMIT}연속 손실로 {blocked_until.isoformat(timespec='minutes')}까지 제외"
            return {
                "allowed": allowed,
                "reason": reason,
                "blocked_until": blocked_until.isoformat() if blocked_until else None,
            }

    def _update_loss_guards_locked(self, market: str, pnl: float) -> None:
        risk = self.state["risk"]
        if pnl > 0:
            risk["consecutive_losses"] = 0
            risk["market_losses"][market] = 0
            return
        risk["consecutive_losses"] = int(risk.get("consecutive_losses", 0)) + 1
        market_losses = int(risk["market_losses"].get(market, 0)) + 1
        risk["market_losses"][market] = market_losses
        if market_losses >= MARKET_LOSS_STREAK_LIMIT:
            blocked_until = datetime.now().astimezone() + timedelta(hours=MARKET_BLOCK_HOURS)
            risk["blocked_markets"][market] = blocked_until.isoformat(timespec="seconds")
            self._alert(
                f"{market} {market_losses}연속 손실: {MARKET_BLOCK_HOURS}시간 신규 매수 제외",
                "warning",
            )
        if int(risk["consecutive_losses"]) >= GLOBAL_LOSS_STREAK_LIMIT:
            risk["locked"] = True
            risk["reason"] = f"전체 {risk['consecutive_losses']}연속 손실"
            self._alert(
                f"{risk['reason']}: 자동 신규 매수를 정지했습니다.",
                "danger",
            )

    def _equity_locked(self) -> float:
        holdings = 0.0
        for market, position in self.state["positions"].items():
            price = float(self.state["last_prices"].get(market, position["entry_price"]))
            holdings += float(position["quantity"]) * price * (1 - FEE_RATE)
        return float(self.state["cash"]) + holdings

    def _refresh_daily_guard_locked(self) -> tuple[float, float]:
        today = datetime.now().astimezone().date().isoformat()
        daily = self.state.setdefault("daily", {})
        equity = self._equity_locked()
        if daily.get("date") != today:
            daily.clear()
            daily.update({"date": today, "start_equity": equity, "locked": False})
        start_equity = float(daily.get("start_equity") or equity or 1)
        pnl = equity - start_equity
        loss_rate = pnl / start_equity
        if loss_rate <= -DAILY_LOSS_LIMIT_RATE:
            daily["locked"] = True
        return pnl, loss_rate

    def _record(
        self,
        market: str,
        side: str,
        price: float,
        quantity: float,
        fee: float,
        reason: str,
        pnl: float = 0.0,
        execution: dict[str, float] | None = None,
    ) -> None:
        self.state["trades"].append(
            {
                "time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "market": market,
                "side": side,
                "price": price,
                "quantity": quantity,
                "fee": fee,
                "reason": reason,
                "pnl": pnl,
                "execution": execution or {},
            }
        )
        self.state["trades"] = self.state["trades"][-200:]

    def buy(
        self,
        market: str,
        price: float,
        reason: str,
        atr: float | None = None,
        orderbook: dict[str, Any] | None = None,
    ) -> bool:
        with self.lock:
            self._refresh_daily_guard_locked()
            guard = self.entry_guard(market)
            if (
                market in self.state["positions"]
                or price <= 0
                or len(self.state["positions"]) >= MAX_OPEN_POSITIONS
                or bool(self.state["daily"].get("locked"))
                or not guard["allowed"]
            ):
                return False
            budget = self.state["cash"] * TRADE_FRACTION
            if budget < 5_000:
                return False
            execution = estimate_execution(
                "BUY",
                price,
                orderbook,
                desired_krw=budget,
            )
            if execution["fill_rate"] <= 0:
                self._alert(f"{market} 매수 호가 부족으로 모의주문 미체결", "warning")
                return False
            budget *= execution["fill_rate"]
            price = execution["price"]
            quantity = budget / (price * (1 + FEE_RATE))
            gross = quantity * price
            fee = gross * FEE_RATE
            total_cost = gross + fee
            entry_atr = float(atr if atr and atr > 0 else price * 0.01)
            self.state["cash"] -= total_cost
            self.state["positions"][market] = {
                "quantity": quantity,
                "entry_price": price,
                "cost_basis": total_cost,
                "high_water": price,
                "entry_atr": entry_atr,
                "stop_price": price - (STOP_ATR_MULTIPLE * entry_atr),
                "target_price": price + (TAKE_PROFIT_ATR_MULTIPLE * entry_atr),
                "opened_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            self._record(market, "BUY", price, quantity, fee, reason, execution=execution)
            self._alert(
                f"{market} 모의매수 {execution['fill_rate'] * 100:.0f}% 체결",
                "trade",
            )
            self._save()
            return True

    def sell(
        self,
        market: str,
        price: float,
        reason: str,
        orderbook: dict[str, Any] | None = None,
    ) -> bool:
        with self.lock:
            position = self.state["positions"].get(market)
            if not position or price <= 0:
                return False
            execution = estimate_execution(
                "SELL",
                price,
                orderbook,
                desired_quantity=float(position["quantity"]),
            )
            if execution["fill_rate"] <= 0:
                self._alert(f"{market} 매도 호가 부족으로 모의주문 미체결", "danger")
                return False
            price = execution["price"]
            total_quantity = float(position["quantity"])
            quantity = total_quantity * execution["fill_rate"]
            cost_basis = float(position["cost_basis"]) * (quantity / total_quantity)
            gross = quantity * price
            fee = gross * FEE_RATE
            net = gross - fee
            pnl = net - cost_basis
            self.state["cash"] += net
            self.state["realized_pnl"] += pnl
            remainder = total_quantity - quantity
            if remainder <= total_quantity * 0.001:
                del self.state["positions"][market]
                self.state.setdefault("last_sell_at", {})[market] = (
                    datetime.now().astimezone().isoformat(timespec="seconds")
                )
            else:
                position["quantity"] = remainder
                position["cost_basis"] = float(position["cost_basis"]) - cost_basis
            self._record(
                market,
                "SELL",
                price,
                quantity,
                fee,
                reason,
                pnl,
                execution=execution,
            )
            self._update_loss_guards_locked(market, pnl)
            self._alert(
                f"{market} 모의매도 {execution['fill_rate'] * 100:.0f}% 체결 · 손익 {pnl:,.0f}원",
                "trade" if pnl >= 0 else "warning",
            )
            self._save()
            return True

    def update_live_price(self, market: str, price: float) -> str | None:
        """Mark to live price and execute risk exits without waiting for a candle refresh."""
        if price <= 0:
            return None
        reason: str | None = None
        with self.lock:
            self.state["last_prices"][market] = price
            self._refresh_daily_guard_locked()
            position = self.state["positions"].get(market)
            if position:
                position["high_water"] = max(float(position["high_water"]), price)
                entry = float(position["entry_price"])
                high_water = float(position["high_water"])
                entry_atr = float(position.get("entry_atr") or entry * 0.01)
                stop_price = float(
                    position.get("stop_price") or entry - (STOP_ATR_MULTIPLE * entry_atr)
                )
                target_price = float(
                    position.get("target_price")
                    or entry + (TAKE_PROFIT_ATR_MULTIPLE * entry_atr)
                )
                trailing_active = high_water >= entry + (
                    TRAILING_ACTIVATION_ATR * entry_atr
                )
                trailing_price = high_water - (TRAILING_ATR_MULTIPLE * entry_atr)
                if self.state["auto_enabled"]:
                    if price <= stop_price:
                        reason = "ATR 실시간 손절"
                    elif price >= target_price:
                        reason = "ATR 목표수익"
                    elif trailing_active and price <= trailing_price:
                        reason = "ATR 추적손절"
            now = time.monotonic()
            if now - self._last_live_save >= 5:
                self._save()
                self._last_live_save = now

        if reason and self.sell(market, price, reason):
            return "SELL"
        return None

    def evaluate(
        self,
        market: str,
        signal: dict[str, Any],
        execution_price: float | None = None,
        orderbook: dict[str, Any] | None = None,
    ) -> str | None:
        price = float(execution_price if execution_price is not None else signal["price"])
        candle_time = str(signal["time"])
        risk_action = self.update_live_price(market, price)
        if risk_action:
            return risk_action
        with self.lock:
            position = self.state["positions"].get(market)
            action: str | None = None
            reason: str | None = None
            if position:
                if signal.get("sell_signal"):
                    reason = "EMA/반전 매도 신호"
                if reason:
                    action = "SELL"
            elif signal.get("buy_signal"):
                last_sell = self.state.setdefault("last_sell_at", {}).get(market)
                cooldown_active = False
                if last_sell:
                    sold_at = datetime.fromisoformat(last_sell)
                    now = datetime.now().astimezone()
                    cooldown_active = (now - sold_at).total_seconds() < COOLDOWN_MINUTES * 60
                if not cooldown_active:
                    action = "BUY"
                    strategy_reasons = {
                        "trend_pullback": "상승 추세 눌림목",
                        "trend_breakout": "거래량 돌파",
                        "sideways_mean_reversion": "횡보장 평균회귀",
                    }
                    reason = strategy_reasons.get(
                        str(signal.get("strategy_mode")),
                        "국면전환 매수",
                    )

            already_acted = self.state["last_action_candle"].get(market) == candle_time
            auto_enabled = bool(self.state["auto_enabled"])
            self._save()

        if not action or already_acted or not auto_enabled:
            return None
        executed = (
            self.buy(
                market,
                price,
                reason,
                atr=float(signal.get("atr") or price * 0.01),
                orderbook=orderbook,
            )
            if action == "BUY"
            else self.sell(market, price, reason, orderbook=orderbook)
        )
        if executed:
            with self.lock:
                self.state["last_action_candle"][market] = candle_time
                self._save()
            return action
        return None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            daily_pnl, daily_loss_rate = self._refresh_daily_guard_locked()
            state = deepcopy(self.state)

        positions: list[dict[str, Any]] = []
        holdings_value = 0.0
        unrealized_pnl = 0.0
        for market, position in state["positions"].items():
            price = float(state["last_prices"].get(market, position["entry_price"]))
            market_value = float(position["quantity"]) * price * (1 - FEE_RATE)
            pnl = market_value - float(position["cost_basis"])
            holdings_value += market_value
            unrealized_pnl += pnl
            positions.append(
                {
                    "market": market,
                    **position,
                    "current_price": price,
                    "market_value": market_value,
                    "unrealized_pnl": pnl,
                    "return_rate": pnl / float(position["cost_basis"]),
                }
            )

        equity = float(state["cash"]) + holdings_value
        return {
            "initial_cash": state["initial_cash"],
            "cash": state["cash"],
            "equity": equity,
            "total_pnl": equity - float(state["initial_cash"]),
            "realized_pnl": state["realized_pnl"],
            "unrealized_pnl": unrealized_pnl,
            "auto_enabled": state["auto_enabled"],
            "daily_pnl": daily_pnl,
            "daily_loss_rate": daily_loss_rate,
            "daily_locked": bool(state["daily"].get("locked")),
            "risk_locked": bool(state["risk"].get("locked")),
            "risk_reason": state["risk"].get("reason"),
            "consecutive_losses": int(state["risk"].get("consecutive_losses", 0)),
            "blocked_markets": state["risk"].get("blocked_markets", {}),
            "alerts": list(reversed(state.get("alerts", [])[-20:])),
            "max_open_positions": MAX_OPEN_POSITIONS,
            "positions": positions,
            "trades": list(reversed(state["trades"][-30:])),
        }
