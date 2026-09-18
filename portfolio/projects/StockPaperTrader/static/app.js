const $=id=>document.getElementById(id);
const won=value=>`${Math.round(Number(value)||0).toLocaleString("ko-KR")}원`;
const number=value=>Math.round(Number(value)||0).toLocaleString("ko-KR");
let busy=false;

function pnlClass(value){return Number(value)>=0?"positive":"negative"}
function render(data){
  const q=data.quote, a=data.account, s=data.signal;
  $("connection").textContent=data.quote_fresh?"실시간 연결":"시세 확인 필요";
  $("connection").className=data.quote_fresh?"ok":"";
  $("name").textContent=q.name;
  $("price").textContent=won(q.price);
  $("change").textContent=`${q.change>=0?"+":""}${number(q.change)}원 (${q.change_rate}%)`;
  $("change").className=pnlClass(q.change);
  $("marketStatus").textContent=q.market_status==="OPEN"?"정규장 진행 중":"장 마감";
  $("equity").textContent=won(a.equity); $("cash").textContent=won(a.cash);
  $("totalPnl").textContent=won(a.total_pnl); $("totalPnl").className=pnlClass(a.total_pnl);
  $("realizedPnl").textContent=won(a.realized_pnl); $("realizedPnl").className=pnlClass(a.realized_pnl);
  $("auto").checked=a.auto_enabled; $("score").textContent=`${s.buy_score}/5`;
  $("rsi").textContent=s.rsi.toFixed(1); $("vwap").textContent=won(s.vwap);
  $("ema").textContent=`${number(s.ema9)} / ${number(s.ema21)}`; $("bb").textContent=won(s.bb_mid);
  const labels={vwap:"VWAP",ema:"EMA 추세",rsi:"RSI 반등",bollinger:"볼린저",trend:"장기 추세"};
  $("checks").innerHTML=Object.entries(s.buy_checks).map(([k,v])=>`<div class="check ${v?"on":""}">${labels[k]} ${v?"충족":"대기"}</div>`).join("");
  $("positions").innerHTML=a.positions.length?a.positions.map(p=>`<div class="position"><b>${p.name} ${p.quantity}주</b><br>매수가 ${won(p.entry_price)} · 현재가 ${won(p.current_price)}<br>평가손익 <span class="${pnlClass(p.unrealized_pnl)}">${won(p.unrealized_pnl)}</span><br>손절 ${won(p.stop_price)} · 목표 ${won(p.target_price)}</div>`).join(""):'<div class="empty">보유 종목 없음</div>';
  $("trades").innerHTML=a.trades.length?a.trades.map(t=>`<tr><td>${new Date(t.time).toLocaleString("ko-KR")}</td><td>${t.side}</td><td>${won(t.price)}</td><td>${t.quantity}주</td><td>${won(t.costs)}</td><td class="${pnlClass(t.pnl)}">${won(t.pnl)}</td><td>${t.reason}</td></tr>`).join(""):'<tr><td colspan="7">거래 없음</td></tr>';
}
async function load(){
  if(busy)return;
  try{const r=await fetch("/api/snapshot?symbol=005930");const d=await r.json();if(!r.ok)throw Error(d.error);render(d)}
  catch(e){$("connection").textContent=e.message;$("connection").className=""}
}
async function post(url,body={}){
  busy=true;
  try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error);await load()}
  catch(e){alert(e.message)}finally{busy=false;await load()}
}
$("auto").addEventListener("change",e=>post("/api/auto",{enabled:e.target.checked}));
$("buy").addEventListener("click",()=>post("/api/order",{symbol:"005930",side:"BUY"}));
$("sell").addEventListener("click",()=>post("/api/order",{symbol:"005930",side:"SELL"}));
$("reset").addEventListener("click",()=>{if(confirm("가상 잔고와 모의거래 기록을 초기화할까요?"))post("/api/reset")});
load();setInterval(load,5000);
