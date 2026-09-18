from __future__ import annotations

from typing import Any


def _agent(
    key: str,
    name: str,
    role: str,
    state: str,
    confidence: int,
    reason: str,
    approved: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "role": role,
        "state": state,
        "confidence": max(0, min(100, int(confidence))),
        "reason": reason,
        "approved": bool(approved),
    }


def _validation_agent(backtest_status: dict[str, Any]) -> dict[str, Any]:
    result = backtest_status.get("result") or {}
    total_return = float(result.get("total_return") or 0)
    profit_factor = float(result.get("profit_factor") or 0)
    trades = int(result.get("trades") or 0)
    passed = total_return > 0 and profit_factor >= 1.2 and trades >= 50
    if not result:
        reason = "백테스트 결과가 없어 실전 승인을 보류합니다."
    else:
        reason = (
            f"{int(result.get('days') or 0)}일 {trades}회 · "
            f"수익률 {total_return * 100:.2f}% · 손익비 {profit_factor:.2f}"
        )
    return _agent(
        "validation",
        "성과 검증가",
        "백테스트·워크포워드",
        "PASS" if passed else "PAPER ONLY",
        100 if passed else 25,
        reason,
        passed,
    )


def build_departments(
    signal: dict[str, Any],
    realtime: dict[str, Any],
    account: dict[str, Any],
    backtest_status: dict[str, Any],
    orderbook: dict[str, Any] | None,
) -> dict[str, Any]:
    checks = signal.get("buy_checks") or {}
    technical_score = int(bool(checks.get("entry_setup"))) + int(
        bool(checks.get("confirmation"))
    )
    trend_score = int(bool(checks.get("market_mode"))) + int(
        bool(checks.get("timeframes"))
    )
    flow_ok = bool(checks.get("volume"))
    risk_ok = bool(checks.get("market_guard")) and not bool(
        account.get("daily_locked") or account.get("risk_locked")
    )
    execution_ok = bool(realtime.get("connected")) and orderbook is not None

    agents = [
        _agent(
            "technical",
            "차트 분석가",
            "볼린저·EMA·RSI",
            "BUY" if technical_score == 2 else "WATCH" if technical_score else "WAIT",
            technical_score * 50,
            f"진입 준비와 가격 확인 {technical_score}/2 충족",
            technical_score == 2,
        ),
        _agent(
            "trend",
            "추세 분석가",
            "1시간·4시간·시장 국면",
            "BUY" if trend_score == 2 else "WATCH" if trend_score else "WAIT",
            trend_score * 50,
            f"시장 국면과 장기 방향 {trend_score}/2 충족",
            trend_score == 2,
        ),
        _agent(
            "flow",
            "수급 분석가",
            "거래량·호가 흐름",
            "BUY" if flow_ok else "WAIT",
            100 if flow_ok else 30,
            "거래량 조건 충족" if flow_ok else "거래량 확정을 기다리는 중",
            flow_ok,
        ),
        _agent(
            "risk",
            "위험 관리자",
            "손실한도·연속손실",
            "READY" if risk_ok else "VETO",
            100 if risk_ok else 0,
            "신규 모의매수 허용"
            if risk_ok
            else str(account.get("risk_reason") or "위험 안전장치 작동"),
            risk_ok,
        ),
        _agent(
            "execution",
            "체결 관리자",
            "WebSocket·호가 검증",
            "READY" if execution_ok else "BLOCK",
            100 if execution_ok else 0,
            "실시간 시세와 공개 호가 정상"
            if execution_ok
            else "실시간 시세 또는 호가 확인 필요",
            execution_ok,
        ),
        _validation_agent(backtest_status),
    ]

    validation_passed = agents[-1]["approved"]
    if bool(signal.get("buy_signal")) and risk_ok and execution_ok:
        decision = "BUY"
        reason = "6개 기존 진입 조건이 모두 충족되어 모의매수를 승인합니다."
    elif bool(signal.get("sell_signal")) and account.get("positions"):
        decision = "SELL"
        reason = "매도 전환 조건이 충족되어 보유 포지션 정리를 승인합니다."
    else:
        decision = "WAIT"
        reason = (
            f"매수 조건 {int(signal.get('buy_score') or 0)}/"
            f"{len(checks)} 충족 · 추가 확인을 기다립니다."
        )

    crypto = {
        "key": "crypto",
        "name": "코인부서",
        "status": "ACTIVE" if realtime.get("connected") else "RECONNECTING",
        "data_source": "Upbit Public WebSocket",
        "markets": list(realtime.get("subscribed_markets") or []),
        "mode": "PAPER",
        "real_order_enabled": False,
        "agents": agents,
        "chief": {
            "name": "코인 수석 트레이더",
            "decision": decision,
            "reason": reason,
            "paper_only": not validation_passed,
        },
        "account": {
            "equity": float(account.get("equity") or 0),
            "total_pnl": float(account.get("total_pnl") or 0),
            "positions": len(account.get("positions") or []),
        },
    }
    stocks = {
        "key": "stocks",
        "name": "국내주식부서",
        "status": "WAITING_KIS",
        "data_source": None,
        "markets": [],
        "mode": "DISABLED",
        "real_order_enabled": False,
        "agents": [
            _agent(
                key,
                name,
                role,
                "OFFLINE",
                0,
                "한국투자 API 연결 후 활성화됩니다.",
                False,
            )
            for key, name, role in (
                ("technical", "차트 분석가", "기술지표"),
                ("market", "시장 분석가", "코스피·업종"),
                ("flow", "수급 분석가", "외국인·기관"),
                ("fundamental", "기업 분석가", "실적·공시"),
                ("risk", "위험 관리자", "손실한도"),
                ("execution", "체결 관리자", "KIS 시세·호가"),
            )
        ],
        "chief": {
            "name": "주식 수석 트레이더",
            "decision": "OFFLINE",
            "reason": "한국투자 계좌와 KIS API가 연결되지 않아 데이터와 주문을 차단했습니다.",
            "paper_only": True,
        },
        "requirements": [
            "한국투자 계좌 개설",
            "KIS 모의투자 App Key·App Secret",
            "실시간 WebSocket 시세 연결",
            "코인부서와 분리된 가상계좌",
        ],
        "account": {"equity": 0.0, "total_pnl": 0.0, "positions": 0},
    }
    return {
        "hq": {
            "mode": "PAPER",
            "real_order_enabled": False,
            "capital_separated": True,
            "active_departments": 1,
        },
        "crypto": crypto,
        "stocks": stocks,
    }
