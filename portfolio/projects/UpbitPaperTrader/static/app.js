const state = { market: "KRW-BTC", department: "crypto", data: null, signalMode: "buy", loading: false };
const $ = (id) => document.getElementById(id);
const krw = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
const qtyFormat = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 8 });

function money(value) {
  return `${krw.format(Number(value || 0))}원`;
}

function colorPnl(element, value) {
  element.classList.remove("positive", "negative");
  if (value > 0) element.classList.add("positive");
  if (value < 0) element.classList.add("negative");
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 2500);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[character]));
}

function renderAgentCards(rootId, agents) {
  const root = $(rootId);
  if (!root) return;
  root.innerHTML = (agents || []).map((agent) => {
    const blocked = ["VETO", "BLOCK", "OFFLINE"].includes(agent.state);
    return `
      <article class="agent-card ${agent.approved ? "approved" : ""} ${blocked ? "blocked" : ""}">
        <header><strong>${escapeHtml(agent.name)}</strong><b>${escapeHtml(agent.state)}</b></header>
        <span class="agent-role">${escapeHtml(agent.role)}</span>
        <p>${escapeHtml(agent.reason)}</p>
        <div class="confidence-track"><i style="width:${Number(agent.confidence || 0)}%"></i></div>
      </article>`;
  }).join("");
}

function officeState(agent) {
  if (["VETO", "BLOCK", "OFFLINE"].includes(agent.state)) return "blocked";
  if (agent.approved || ["BUY", "READY", "PASS"].includes(agent.state)) return "working";
  return "waiting";
}

function renderOffice(crypto) {
  const root = $("officeWorkers");
  if (!root || !crypto) return;
  const positions = [
    [13, 35], [34, 34], [55, 35],
    [13, 66], [34, 65], [55, 66],
  ];
  const spriteX = [0, 16.667, 33.333, 50, 66.667, 83.333];
  root.innerHTML = (crypto.agents || []).map((agent, index) => {
    const visualState = officeState(agent);
    const delay = (index * -0.61).toFixed(2);
    const [x, y] = positions[index] || [12 + (index % 3) * 21, 35 + Math.floor(index / 3) * 31];
    return `
      <article class="office-actor ${visualState}" style="--x:${x}%;--y:${y}%;--delay:${delay}s;--sprite-x:${spriteX[index] ?? 0}%">
        <div class="actor-bubble">${escapeHtml(agent.reason)}</div>
        <div class="actor-sprite" aria-hidden="true"></div>
        <div class="actor-name">
          <strong>${escapeHtml(agent.name)}</strong>
          <span>${escapeHtml(agent.state)}</span>
        </div>
      </article>`;
  }).join("");
  const decision = crypto.chief.decision;
  $("officeBoardDecision").textContent = decision;
  $("chiefMonitor").textContent = decision;
  const chief = $("chiefActor");
  chief.className = `office-actor chief-actor ${decision === "BUY" || decision === "SELL" ? "working reporting" : "waiting"}`;
  chief.querySelector(".actor-bubble").textContent =
    decision === "WAIT" ? "최종 판단 대기" : `${decision} 모의주문 승인`;
}

function renderDepartments(departments) {
  if (!departments) return;
  const crypto = departments.crypto;
  const stocks = departments.stocks;
  $("cryptoDepartmentStatus").textContent =
    crypto.status === "ACTIVE" ? "WebSocket 실시간 운영" : "재연결 중";
  $("cryptoChiefMini").textContent = crypto.chief.decision;
  $("chiefDecision").textContent = crypto.chief.decision;
  $("chiefDecision").className = crypto.chief.decision.toLowerCase();
  $("chiefReason").textContent = crypto.chief.reason;
  $("paperOnlyBadge").textContent = crypto.chief.paper_only ? "PAPER ONLY" : "검증 통과";
  renderAgentCards("coinAgents", crypto.agents);
  renderAgentCards("stockAgents", stocks.agents);
  renderOffice(crypto);
}

function switchDepartment(department) {
  state.department = department;
  document.querySelectorAll(".department-card").forEach((button) => {
    button.classList.toggle("active", button.dataset.department === department);
  });
  $("coinDepartment").classList.toggle("hidden", department !== "crypto");
  $("stockDepartment").classList.toggle("hidden", department !== "stocks");
  $("autoControl").classList.toggle("hidden", department !== "crypto");
  if (department === "stocks") {
    $("connection").textContent = "KIS 연결 대기";
    $("connection").className = "status waiting";
  } else if (state.data) {
    renderConnection(state.data.realtime);
  }
}

function resizeCanvas(canvas) {
  const width = Math.max(300, canvas.clientWidth);
  const height = canvas.clientHeight;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return canvas.getContext("2d");
}

function line(ctx, rows, field, xAt, yAt, color, width = 1.2) {
  ctx.beginPath();
  let started = false;
  rows.forEach((row, index) => {
    if (row[field] == null) return;
    const x = xAt(index);
    const y = yAt(row[field]);
    started ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    started = true;
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
}

function drawPriceChart(rows) {
  const canvas = $("priceChart");
  const ctx = resizeCanvas(canvas);
  const width = canvas.width;
  const height = canvas.height;
  const padding = { left: 14, right: 72, top: 15, bottom: 24 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  ctx.clearRect(0, 0, width, height);
  if (!rows.length) return;

  const values = rows.flatMap((r) => [r.low, r.high, r.bb_lower, r.bb_upper]).filter(Number.isFinite);
  let min = Math.min(...values);
  let max = Math.max(...values);
  const margin = (max - min) * 0.08 || 1;
  min -= margin; max += margin;
  const xStep = chartW / rows.length;
  const xAt = (i) => padding.left + xStep * (i + 0.5);
  const yAt = (v) => padding.top + ((max - v) / (max - min)) * chartH;

  ctx.strokeStyle = "#1a2434";
  ctx.fillStyle = "#718097";
  ctx.font = "11px system-ui";
  for (let i = 0; i <= 5; i += 1) {
    const y = padding.top + (chartH * i) / 5;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    const price = max - ((max - min) * i) / 5;
    ctx.fillText(krw.format(price), width - padding.right + 8, y + 4);
  }

  line(ctx, rows, "bb_upper", xAt, yAt, "#55647b");
  line(ctx, rows, "bb_mid", xAt, yAt, "#35435a");
  line(ctx, rows, "bb_lower", xAt, yAt, "#55647b");
  line(ctx, rows, "ema_fast", xAt, yAt, "#ffc857", 1.5);
  line(ctx, rows, "ema_slow", xAt, yAt, "#58d7e8", 1.5);

  const candleWidth = Math.max(2, Math.min(7, xStep * 0.62));
  rows.forEach((row, index) => {
    const x = xAt(index);
    const rising = row.close >= row.open;
    const color = rising ? "#ff5364" : "#4d8dff";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.moveTo(x, yAt(row.high)); ctx.lineTo(x, yAt(row.low)); ctx.stroke();
    const top = yAt(Math.max(row.open, row.close));
    const bottom = yAt(Math.min(row.open, row.close));
    ctx.fillRect(x - candleWidth / 2, top, candleWidth, Math.max(1, bottom - top));
  });
}

function drawRsiChart(rows) {
  const canvas = $("rsiChart");
  const ctx = resizeCanvas(canvas);
  const width = canvas.width;
  const height = canvas.height;
  const padding = { left: 14, right: 42, top: 10, bottom: 12 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  ctx.clearRect(0, 0, width, height);
  const xAt = (i) => padding.left + (chartW * i) / Math.max(1, rows.length - 1);
  const yAt = (v) => padding.top + ((100 - v) / 100) * chartH;
  [30, 50, 70].forEach((level) => {
    ctx.strokeStyle = level === 50 ? "#253044" : "#39445a";
    ctx.setLineDash(level === 50 ? [2, 5] : [5, 4]);
    ctx.beginPath(); ctx.moveTo(padding.left, yAt(level)); ctx.lineTo(width - padding.right, yAt(level)); ctx.stroke();
    ctx.fillStyle = "#718097"; ctx.font = "10px system-ui"; ctx.fillText(String(level), width - padding.right + 8, yAt(level) + 3);
  });
  ctx.setLineDash([]);
  line(ctx, rows, "rsi", xAt, yAt, "#b18cff", 1.7);
}

function drawBacktestChart(points) {
  const canvas = $("backtestChart");
  const ctx = resizeCanvas(canvas);
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  if (!points?.length) return;
  const padding = { left: 12, right: 76, top: 14, bottom: 20 };
  const chartW = width - padding.left - padding.right;
  const chartH = height - padding.top - padding.bottom;
  const values = points.map((point) => Number(point.equity));
  let min = Math.min(...values);
  let max = Math.max(...values);
  const margin = (max - min) * 0.1 || max * 0.01 || 1;
  min -= margin; max += margin;
  const xAt = (index) => padding.left + (chartW * index) / Math.max(1, points.length - 1);
  const yAt = (value) => padding.top + ((max - value) / (max - min)) * chartH;
  ctx.strokeStyle = "#1d293b";
  ctx.fillStyle = "#718097";
  ctx.font = "10px system-ui";
  for (let index = 0; index <= 3; index += 1) {
    const y = padding.top + (chartH * index) / 3;
    ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(width - padding.right, y); ctx.stroke();
    const value = max - ((max - min) * index) / 3;
    ctx.fillText(krw.format(value), width - padding.right + 7, y + 3);
  }
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = xAt(index);
    const y = yAt(Number(point.equity));
    index ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = values.at(-1) >= values[0] ? "#ff5364" : "#4d8dff";
  ctx.lineWidth = 2;
  ctx.stroke();
}

function renderSignals(signal) {
  const buying = state.signalMode === "buy";
  const checks = buying ? signal.buy_checks : signal.sell_checks;
  const score = buying ? signal.buy_score : signal.sell_score;
  const labels = buying
    ? {
      market_mode: "매매 가능 국면",
      entry_setup: "전략 진입 준비",
      confirmation: "가격 확인",
      volume: "거래량 확인",
      timeframes: "장기 시장 방향",
      market_guard: "손실 종목 안전장치",
    }
    : { bollinger: "상단 반전", ema: "EMA 하락 전환", rsi: "RSI 과열 반전" };
  $("signalScore").textContent = `${score} / ${Object.keys(checks).length}`;
  document.querySelectorAll(".check").forEach((element) => {
    const available = Object.hasOwn(checks, element.dataset.key);
    element.classList.toggle("hidden", !available);
    if (!available) return;
    const active = Boolean(checks[element.dataset.key]);
    element.classList.toggle("on", active);
    element.querySelector("span").textContent = labels[element.dataset.key];
    element.querySelector("b").textContent = active ? "충족" : "대기";
  });
  const regimeLabels = { bullish: "상승장", sideways: "횡보장", bearish: "하락장" };
  const strategyLabels = {
    trend_pullback: "상승 추세 눌림목",
    trend_breakout: "거래량 돌파",
    sideways_mean_reversion: "횡보장 평균회귀",
    validated_multi_timeframe: "검증 유지: 다중시간봉형",
    cash: "하락·불확실장 현금 대기",
  };
  $("signalHelp").textContent = buying
    ? `필수조건 포함 5/6 매수 · 현재 ${regimeLabels[signal.regime] || "국면 확인 중"} · 선택 전략: ${strategyLabels[signal.strategy_mode] || "판정 중"} · ADX ${Number(signal.adx).toFixed(1)}`
    : "보유 중에는 ATR 손절·목표수익·추적손절과 하락 전환 신호로 매도합니다.";
}

function renderPositions(positions) {
  const body = $("positions");
  if (!positions.length) {
    body.innerHTML = '<tr><td colspan="5" class="empty">보유자산 없음</td></tr>';
    return;
  }
  body.innerHTML = positions.map((p) => `
    <tr>
      <td>${p.market}</td>
      <td>${qtyFormat.format(p.quantity)}</td>
      <td>${money(p.entry_price)}</td>
      <td>${money(p.current_price)}</td>
      <td class="${p.unrealized_pnl >= 0 ? "positive" : "negative"}">
        ${money(p.unrealized_pnl)} (${(p.return_rate * 100).toFixed(2)}%)
      </td>
    </tr>`).join("");
}

function renderTrades(trades) {
  const root = $("trades");
  if (!trades.length) {
    root.innerHTML = '<p class="empty">거래 기록 없음</p>';
    return;
  }
  root.innerHTML = trades.map((t) => `
    <div class="trade">
      <div class="trade-head">
        <strong class="${t.side === "BUY" ? "buy-side" : "sell-side"}">${t.side === "BUY" ? "매수" : "매도"} · ${t.market}</strong>
        <span>${money(t.price)}</span>
      </div>
      <div class="trade-meta">
        <span>${t.reason}</span>
        <span>${new Date(t.time).toLocaleString("ko-KR")}</span>
      </div>
    </div>`).join("");
}

function renderAlerts(alerts) {
  const root = $("alerts");
  if (!alerts?.length) {
    root.innerHTML = '<p class="empty">알림 없음</p>';
    return;
  }
  root.innerHTML = alerts.slice(0, 10).map((alert) => `
    <div class="trade alert-${alert.level}">
      <div class="trade-meta">
        <span>${alert.message}</span>
        <span>${new Date(alert.time).toLocaleString("ko-KR")}</span>
      </div>
    </div>`).join("");
}

function render(data) {
  state.data = data;
  const { account, signal, candles, settings } = data;
  renderAccount(account);
  renderConnection(data.realtime);
  const live = data.realtime?.markets?.[state.market];
  $("currentPrice").textContent = money(live?.price ?? signal.price);
  if (live?.received_at) $("updatedAt").textContent = `실시간 ${new Date(live.received_at).toLocaleTimeString("ko-KR")}`;
  $("rsiValue").textContent = signal.rsi.toFixed(1);
  $("marketLabel").textContent = `${state.market.replace("KRW-", "")}/KRW · ${settings.candle_minutes}분봉`;
  $("autoToggle").checked = account.auto_enabled;
  if (account.risk_locked) {
    $("universeText").textContent = `연속손실 안전정지: ${account.risk_reason}`;
  } else if (account.daily_locked) {
    $("universeText").textContent = "일일 손실 한도 도달: 신규 모의매수가 잠겼습니다.";
  } else if (data.universe?.markets?.length) {
    const symbols = data.universe.markets.map((market) => market.replace("KRW-", "")).join(" · ");
    $("universeText").textContent = `자동 감시: ${symbols}`;
  }
  drawPriceChart(candles);
  drawRsiChart(candles);
  renderSignals(signal);
  renderTrades(account.trades);
  renderAlerts(account.alerts);
  renderDepartments(data.departments);
}

function renderAccount(account) {
  $("equity").textContent = money(account.equity);
  $("cash").textContent = money(account.cash);
  $("totalPnl").textContent = money(account.total_pnl);
  $("realizedPnl").textContent = money(account.realized_pnl);
  colorPnl($("totalPnl"), account.total_pnl);
  colorPnl($("realizedPnl"), account.realized_pnl);
  renderPositions(account.positions);
  renderAlerts(account.alerts);
}

function renderConnection(realtime) {
  if (state.department !== "crypto") return;
  const connected = Boolean(realtime?.connected);
  $("connection").textContent = connected ? "WebSocket 실시간" : "WebSocket 재연결 중";
  $("connection").className = `status ${connected ? "ok" : "waiting"}`;
}

async function loadRealtimePrices() {
  try {
    const response = await fetch("/api/prices");
    const data = await response.json();
    if (!response.ok) throw new Error("실시간 가격을 불러오지 못했습니다.");
    if (state.department === "crypto") {
      renderConnection(data.stream);
      renderAccount(data.account);
    }
    const live = data.stream?.markets?.[state.market];
    if (live) {
      $("currentPrice").textContent = money(live.price);
      $("updatedAt").textContent = `실시간 ${new Date(live.received_at).toLocaleTimeString("ko-KR")}`;
    }
  } catch (_error) {
    $("connection").textContent = "실시간 연결 오류";
    $("connection").className = "status error";
  }
}

function formatPercent(value) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
}

function renderBacktest(status) {
  state.backtestStatus = status;
  $("backtestStatus").querySelector("span").textContent =
    status.error ? `오류: ${status.error}` : status.message;
  $("backtestProgress").style.width = `${Number(status.progress || 0)}%`;
  $("backtestStart").disabled = Boolean(status.running);
  $("backtestCompare").disabled = Boolean(status.running);
  const result = status.result;
  if (result) {
    $("backtestResult").classList.remove("hidden");
    $("btReturn").textContent = formatPercent(result.total_return);
    $("btWinRate").textContent = formatPercent(result.win_rate);
    $("btDrawdown").textContent = formatPercent(result.max_drawdown);
    $("btProfitFactor").textContent =
      result.profit_factor == null ? "—" : Number(result.profit_factor).toFixed(2);
    $("btTrades").textContent = krw.format(result.trades);
    $("btFees").textContent = money(result.total_fees);
    colorPnl($("btReturn"), result.total_return);
    $("btDrawdown").classList.add("negative");
    drawBacktestChart(result.equity_curve);
    $("backtestMarkets").innerHTML = result.per_market.map((item) => `
      <tr>
        <td>${item.market}</td>
        <td>${item.trades}</td>
        <td>${item.wins}</td>
        <td>${formatPercent(item.win_rate)}</td>
        <td class="${item.pnl >= 0 ? "positive" : "negative"}">${money(item.pnl)}</td>
      </tr>`).join("");
    $("backtestCaption").textContent =
      `최근 ${result.days}일 · ${result.markets.join(", ")} · 생성 ${new Date(result.generated_at).toLocaleString("ko-KR")} · 과거 결과는 미래 수익을 보장하지 않습니다.`;
  }
  renderStrategyComparison(status.comparison);
}

function renderStrategyComparison(comparison) {
  if (!comparison) return;
  $("backtestResult").classList.remove("hidden");
  $("strategyComparison").classList.remove("hidden");
  $("comparisonVerdict").textContent = comparison.recommended_label
    ? `추천 후보: ${comparison.recommended_label}`
    : "안전 기준을 통과한 전략 없음";
  $("comparisonVerdict").className = comparison.recommended_label ? "positive" : "negative";
  $("comparisonRows").innerHTML = comparison.profiles.map((profile) => {
    const periods = Object.fromEntries(profile.periods.map((item) => [item.days, item]));
    const longPeriod = periods[180];
    return `
      <tr>
        <td>${profile.label}</td>
        <td class="${periods[30].total_return >= 0 ? "positive" : "negative"}">${formatPercent(periods[30].total_return)}</td>
        <td class="${periods[90].total_return >= 0 ? "positive" : "negative"}">${formatPercent(periods[90].total_return)}</td>
        <td class="${longPeriod.total_return >= 0 ? "positive" : "negative"}">${formatPercent(longPeriod.total_return)}</td>
        <td>${longPeriod.trades}</td>
        <td>${profile.robust ? "통과" : "보류"}</td>
      </tr>`;
  }).join("");
  if (comparison.walk_forward && comparison.execution_stress) {
    const walk = comparison.walk_forward;
    const stress = comparison.execution_stress;
    $("validationSummary").classList.remove("hidden");
    $("walkForwardWrap").classList.remove("hidden");
    $("validationData").textContent = comparison.data_quality?.valid
      ? (comparison.data_quality.complete_coverage === false ? "정상·일부 기간 제한" : "정상")
      : "오류 확인";
    $("validationData").className = comparison.data_quality?.valid ? "positive" : "negative";
    $("validationFolds").textContent = `${walk.profitable_folds} / ${walk.folds} 수익`;
    $("validationReturn").textContent = formatPercent(walk.cumulative_return);
    colorPnl($("validationReturn"), walk.cumulative_return);
    $("validationStress").textContent =
      `${stress.profitable} / ${stress.count} 수익 · 최저 ${formatPercent(stress.worst_return)}`;
    $("walkForwardRows").innerHTML = walk.results.map((row) => `
      <tr>
        <td>${row.fold}</td>
        <td>${row.selected_label}</td>
        <td class="${row.return >= 0 ? "positive" : "negative"}">${formatPercent(row.return)}</td>
        <td>${row.trades}</td>
        <td>${formatPercent(row.max_drawdown)}</td>
      </tr>`).join("");
  }
}

async function loadBacktestStatus() {
  try {
    const response = await fetch("/api/backtest/status");
    const status = await response.json();
    if (!response.ok) throw new Error("백테스트 상태를 확인하지 못했습니다.");
    renderBacktest(status);
  } catch (error) {
    $("backtestStatus").querySelector("span").textContent = error.message;
  }
}

async function startBacktest() {
  try {
    const days = Number($("backtestDays").value);
    await post("/api/backtest/start", { days });
    showToast(`${days}일 백테스트를 시작했습니다.`);
    await loadBacktestStatus();
  } catch (error) {
    showToast(error.message);
  }
}

async function compareBacktests() {
  try {
    await post("/api/backtest/compare", {});
    showToast("6개 전략과 20개 검증 시뮬레이션을 시작했습니다.");
    await loadBacktestStatus();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadSnapshot() {
  if (state.loading) return;
  state.loading = true;
  try {
    const response = await fetch(`/api/snapshot?market=${encodeURIComponent(state.market)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "데이터를 불러오지 못했습니다.");
    render(data);
  } catch (error) {
    $("connection").textContent = "연결 오류";
    $("connection").className = "status error";
    showToast(error.message);
  } finally {
    state.loading = false;
  }
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "요청에 실패했습니다.");
  return data;
}

document.querySelectorAll(".market-tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".market-tab").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.market = button.dataset.market;
    loadSnapshot();
  });
});

document.querySelectorAll(".department-card").forEach((button) => {
  button.addEventListener("click", () => switchDepartment(button.dataset.department));
});

$("buyMode").addEventListener("click", () => {
  state.signalMode = "buy";
  $("buyMode").classList.add("active"); $("sellMode").classList.remove("active");
  if (state.data) renderSignals(state.data.signal);
});
$("sellMode").addEventListener("click", () => {
  state.signalMode = "sell";
  $("sellMode").classList.add("active"); $("buyMode").classList.remove("active");
  if (state.data) renderSignals(state.data.signal);
});
$("autoToggle").addEventListener("change", async (event) => {
  try {
    await post("/api/auto", { enabled: event.target.checked });
    showToast(event.target.checked ? "자동 모의매매 시작" : "자동 모의매매 정지");
    await loadSnapshot();
  } catch (error) { showToast(error.message); }
});
$("manualBuy").addEventListener("click", async () => {
  try { await post("/api/order", { market: state.market, side: "BUY" }); showToast("수동 모의매수 완료"); await loadSnapshot(); }
  catch (error) { showToast(error.message); }
});
$("manualSell").addEventListener("click", async () => {
  try { await post("/api/order", { market: state.market, side: "SELL" }); showToast("수동 모의매도 완료"); await loadSnapshot(); }
  catch (error) { showToast(error.message); }
});
$("resetButton").addEventListener("click", async () => {
  if (!confirm("가상 잔고와 모든 모의거래 기록을 초기화할까요?")) return;
  try { await post("/api/reset"); showToast("가상 계좌 초기화 완료"); await loadSnapshot(); }
  catch (error) { showToast(error.message); }
});
$("riskUnlock").addEventListener("click", async () => {
  try {
    await post("/api/risk/unlock");
    showToast("위험정지를 해제했습니다.");
    await loadSnapshot();
  } catch (error) { showToast(error.message); }
});
$("backtestStart").addEventListener("click", startBacktest);
$("backtestCompare").addEventListener("click", compareBacktests);

window.addEventListener("resize", () => {
  if (state.data) { drawPriceChart(state.data.candles); drawRsiChart(state.data.candles); }
  if (state.backtestStatus?.result) {
    drawBacktestChart(state.backtestStatus.result.equity_curve);
  }
});

loadSnapshot();
loadBacktestStatus();
setInterval(loadSnapshot, 30_000);
setInterval(loadRealtimePrices, 1_000);
setInterval(loadBacktestStatus, 3_000);
setInterval(() => {
  const clock = $("officeClock");
  if (clock) clock.textContent = new Date().toLocaleTimeString("ko-KR", { hour12: false });
}, 1_000);
