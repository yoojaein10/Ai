// 개인별 매출실적 — 2026-08-08 전면개편.
//
// 3안 합성 심사로 확정한 구조: 히어로 숫자 1개+칩 4개 → 시간축 카드 하나(좌 월별,
// 우 연도별 5년, 탭 없음) → 발주처 Top7+식은 관계 / 매출 구성(업무·물건종류) →
// 당기 전건 표. 이야기는 '올해'(파랑)이고 전년은 맥락(회색)이다. 정렬·비중·전년
// 비교는 전부 금액 기준 — 가격자문(실측 62건 0.03억)이 증명하듯 건수는 거짓말을
// 공동(수기정산 대기)은 2026-08-10 요청으로 화면에서 뺐다 — 배분 전 건은
// 전체 금액이라 참여자끼리 겹쳐 보여 오해를 불렀다.
// 차트는 외부 라이브러리 없이 SVG 로 직접 그린다 (이 화면엔 빌드 단계가 없다).
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

// 시리즈 색. 올해가 주인공(파랑), 전년은 탈강조 회색 — 카테고리 2색이 아니라
// '강조 + 맥락'이다.
const C_CUR='#2a78d6',C_PREV='#c9d2dc',C_OTHER='#c3cbd4';
// '기타'(접힌 꼬리)는 미배정 축의 회색(C_OTHER)보다 한 단 옅게 — 같은 회색이면
// '보상'(고정색 밖 실체)과 '기타'(여러 축의 합)가 구별이 안 된다.
const C_FOLD='#e2e7ed';
// 전체 추이에 그리는 것은 **매출 하나뿐**이다.
//
// **상여는 여기 없다.** 한 번 얹어 봤다가 뺐다(2026-08-11 같은 날 요청) —
// 지급이 있는 달만 튀는 값이라 '추이' 라는 말과 안 맞고, 상여 탭에 월별 표가 있다.
// **가변비도 뺐다** (2026-08-13 요청 — "차트에는 가변비를 아예 제거").
// 가변비는 가변비 탭의 월별 표에서만 본다 — 축이 달라 매출 옆에 그리면
// 오독을 부르고, 부르는 데 10초가 넘어 차트가 그 값을 물 이유도 없다.
// **켜고 끄는 체크박스도 뺐다** (2026-08-18 요청) — 남은 선이 하나뿐이라
// 끄면 빈 판만 남는다. 켤 것도 끌 것도 없으면 스위치는 자리만 먹는다.
const HASH_EMP=(()=>{const m=location.hash.match(/emp=([^&]+)/);
  try{return m?decodeURIComponent(m[1]):'';}catch(e){return '';}})();

// 색은 실체에 고정한다 — 사람·기간이 바뀌어도 담보는 항상 파랑(순번 재배정 금지).
// 8종은 2026-01~07 전사 금액 상위 실측 순서이고, 밖의 축은 회색 '기타'로 접는다.
// ink 는 세그먼트 안 라벨 색(채도 낮은 칠엔 잉크, 진한 칠엔 흰색).
const WORK_COLORS={
  '담보':['#2a78d6','#fff'],'일반거래':['#eb6834','#fff'],'정비사업':['#1baf7a','#123'],
  '컨설팅':['#eda100','#123'],'기업관련':['#e87ba4','#123'],'법원 및 공매':['#008300','#fff'],
  '국공유재산':['#4a3aa7','#fff'],'유동화자산':['#e34948','#fff'],
};
const PROP_COLORS={
  '토지건물':['#2a78d6','#fff'],'토지':['#eb6834','#fff'],'구분건물':['#1baf7a','#123'],
  '토지건물구분건물':['#eda100','#123'],'영업권':['#e87ba4','#123'],'기계기구':['#008300','#fff'],
  '토지건물기계기구':['#4a3aa7','#fff'],'임료':['#e34948','#fff'],
};
const colorOf=(map,name)=>(map[name]||[C_OTHER,'#123'])[0];

let latest=null;
let yearly=null;           // null=로딩, false=실패, 배열=결과
let tableSort='date';
let tableShown=50;

function query(extra){
  const params=new URLSearchParams({
    office_code:window.A10_OFFICE(),
    date_from:$('dateFrom').value,
    date_to:$('dateTo').value,
    ...extra,
  });
  if(window.A10_USR)params.set('usr_seq',window.A10_USR);
  return params;
}

// 회사 전체 보기 (2026-08-10 요청). 대상 셀렉트가 이 값이면 사람이 아니라
// 지사(또는 전사) 통짜다. **빈 문자열을 쓰면 안 된다** — 이 화면은 빈 값을
// 이미 '본인' 으로 읽고(아래 name?{} 들), 서버도 빈 이름을 세션 이름으로
// 덮는다. 그러면 오류 하나 없이 본인 실적이 뜨고 아무도 못 알아챈다.
const ALL_SCOPE='__ALL__';
const isAll=()=>$('empName').value===ALL_SCOPE;

// 대상 인자 한 벌 — **네 호출부가 전부 이걸 쓴다**(대시보드·연도별·AI·탭).
// 한 곳만 빠지면 히어로·월별은 전체인데 연도별 막대만 본인인 혼합 화면이 되고,
// 제목도 색도 같아 눈으로는 구분이 안 된다.
function target(force){
  if(force==='office'||isAll())return{scope:'office'};
  // 첫 조회에는 셀렉트가 아직 비어 있다 — 그때만 해시(#emp=)가 대신 답한다.
  const name=$('empName').value||HASH_EMP;
  return name?{emp_name:name}:{};
}

// 상여·가변비 탭이 쓰는 질의 — 대시보드와 같은 이름·기간·지사로 묶는다.
function scopeQuery(){
  const params=query(target());
  return params.toString();
}

// 축약은 훑기 좋지만 반올림이라 합이 안 맞아 보인다. 축약을 쓰는 자리마다
// 정확한 원 단위를 title 로 달아 둔다 — 마우스를 올리면 확인할 수 있다.
function won(value){return`${money.format(Math.round(Number(value||0)))}원`;}

function eok(value){
  const n=Number(value||0);
  if(Math.abs(n)>=100000000)return`${(n/100000000).toFixed(1)}억`;
  if(Math.abs(n)>=10000)return`${money.format(Math.round(n/10000))}만`;
  return money.format(n);
}

// ── 툴팁 — 값이 주, 이름이 보조. 라벨은 신뢰하지 않는 데이터라 textContent 로만. ──
const tip=$('msTip');
function tipShow(x,y,title,rows){
  tip.textContent='';
  const t=document.createElement('div');t.className='tip-title';t.textContent=title;
  tip.appendChild(t);
  rows.forEach(r=>{
    const row=document.createElement('div');row.className='tip-row';
    if(r.color){const k=document.createElement('i');k.className='tip-key';
      k.style.background=r.color;row.appendChild(k);}
    const label=document.createElement('span');label.textContent=r.label;row.appendChild(label);
    const val=document.createElement('span');val.className='tip-val';val.textContent=r.value;
    row.appendChild(val);tip.appendChild(row);
  });
  tip.classList.add('show');
  const w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=`${Math.min(x+14,window.innerWidth-w-8)}px`;
  tip.style.top=`${Math.min(y+12,window.innerHeight-h-8)}px`;
}
function tipHide(){tip.classList.remove('show');}

// ── 히어로 — 화면당 큰 숫자는 하나 ──────────────────────────────────────
// 칩 아이콘 — 참고 시안(그라디언트 메시·글래스모피즘)의 스탯 타일 문법.
// 색 그라디언트는 장식이고, 뜻은 옆의 글자가 말한다(색 단독 의미 금지).
const CHIP_ICONS={
  count:['linear-gradient(135deg,#4f7df2,#7a5af0)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M5 20V10M12 20V4M19 20v-8"/></svg>'],
  up:['linear-gradient(135deg,#12b981,#0e9f6e)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8"/><path d="M14 7h7v7"/></svg>'],
  down:['linear-gradient(135deg,#f0546e,#d63b57)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7l6 6 4-4 8 8"/><path d="M14 17h7v-7"/></svg>'],
  avg:['linear-gradient(135deg,#22b0c9,#1a8fb5)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="8.2"/><path d="M8.6 8.5l1.7 6 1.7-5 1.7 5 1.7-6M8 12.4h8"/></svg>'],
  rank:['linear-gradient(135deg,#f0a53a,#e8862c)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0z"/><path d="M6 6H3.5a2.5 2.5 0 0 0 2.6 3M18 6h2.5a2.5 2.5 0 0 1-2.6 3"/></svg>'],
  neutral:['linear-gradient(135deg,#9aa6b8,#7d8a9c)',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M5 12h14"/></svg>'],
};
const chipIc=key=>{
  const[grad,svg]=CHIP_ICONS[key];
  return`<span class="chip-ic" style="background:${grad}">${svg}</span>`;
};

function renderHero(data){
  const k=data.kpi,g=k.growth,r=k.ranking;
  const from=new Date(data.period.from),to=new Date(data.period.to);
  const label=from.getFullYear()===to.getFullYear()
    ?`${from.getFullYear()}년 확정 실적 (${from.getMonth()+1}~${to.getMonth()+1}월)`
    :`확정 실적 ${data.period.from} ~ ${data.period.to}`;
  const chips=[];
  chips.push(`<span class="chip">${chipIc('count')}<span class="chip-tx">`
    +`<b>${money.format(k.single.count)}건</b><span class="chip-sub">확정 건수</span></span></span>`);
  // 전년 비교는 금액이 주, % 는 보조 — 소수 건수 기저에서 % 만 쓰면 +300% 같은
  // 허풍이 남는다. 전년이 0이면 비교 대신 사실을 말한다.
  if(g.prev_amount>0){
    const dir=g.is_positive?'up':'down',arrow=g.is_positive?'▲':'▼';
    chips.push(`<span class="chip ${dir}">${chipIc(dir)}<span class="chip-tx">`
      +`<b>${arrow} ${eok(Math.abs(g.diff))}`
      +`${g.rate!==null?` (${g.is_positive?'+':'-'}${Math.abs(g.rate).toFixed(1)}%)`:''}</b>`
      +`<span class="chip-sub">전년 동기 ${eok(g.prev_amount)}</span></span></span>`);
  }else if(g.prev_count>0){
    chips.push(`<span class="chip muted">${chipIc('neutral')}<span class="chip-tx">`
      +`<b>비교 불가</b>`
      +`<span class="chip-sub">전년 동기 합계가 0 이하 (취소 반영)</span></span></span>`);
  }else{
    chips.push(`<span class="chip muted">${chipIc('neutral')}<span class="chip-tx">`
      +`<b>전년 동기 실적 없음</b></span></span>`);
  }
  // 건당 평균 — 박리다매형/큰건형 정체성과 단가 추세를 칩 하나로.
  if(k.single.count>0){
    const avg=k.single.amount/k.single.count;
    const prevAvg=g.prev_count>0&&g.prev_amount>0?g.prev_amount/g.prev_count:null;
    chips.push(`<span class="chip">${chipIc('avg')}<span class="chip-tx">`
      +`<b>건당 ${eok(avg)}</b>`
      +`${prevAvg!==null?`<span class="chip-sub">전년 ${eok(prevAvg)}</span>`:''}</span></span>`);
  }
  // 전체는 등수를 매길 대상이 아니다. 서버가 null 을 주지만 여기서도 막는다 —
  // ranking.total × group_average 는 '개인 귀속 합' 이라 전체 금액과 미등록
  // 몫만큼 어긋난 두 숫자가 한 화면에 뜨게 된다.
  if(r&&r.rank&&!data.is_all){
    const rankPct=Math.max(4,100-(r.rank-1)/r.total*100);
    // 순위는 같은 소속끼리만 겨룬다 (2026-08-13) — 어느 판의 등수인지 말해준다.
    // 본사 명부에 없는 사람(지사 평가사의 본사 건)은 서버가 ranking 자체를
    // 안 줘서 이 칩이 안 뜬다 — 지사 사람에게 본사 등수를 주면 이상하다.
    const pool=r.group_label?`${escapeHtml(r.group_label)} `:'';
    chips.push(`<span class="chip chip-rank">${chipIc('rank')}<span class="chip-tx">`
      +`<b>${r.rank}위</b>`
      +`<span class="chip-sub">${pool}${r.total}명 중`
      +`${r.percentile!==null&&r.percentile!==undefined?` · 상위 ${r.percentile}%`:''}</span>`
      +`<span class="rank-bar"><i style="width:${rankPct}%"></i></span></span></span>`);
  }
  // 공동 정산 대기 줄은 뺐다 (2026-08-10 요청 — "공동대기 넣지 말래").
  // 배분 전 건은 전체 금액이라 참여자끼리 겹쳐 보이는 게 오해를 불렀다.
  // 유치자(지분) 미등록 몫이 크면 숨기지 않고 말한다 — 지사마다 등록 관행이
  // 달라(실측: 본사 4%, 울산 100%) 화면이 적게 보이는 이유를 화면이 설명해야
  // 한다. 15% 이하면 조용히 넘어간다(본사·강원·동부 수준의 정상 범위).
  // 전체 모드에서는 **같은 숫자의 뜻이 뒤집힌다.** 개인 화면에서는 '빠진 몫'
  // 이지만 전체 금액에는 그 몫이 들어 있다 — 문구를 그대로 두면 정반대의
  // 거짓말이 된다. 그리고 이때는 낮은 비율에서도 말해야 한다: 개인 화면들을
  // 더해 검산하는 사람에게 차이의 이유가 바로 이 숫자다.
  const covRatio=(data.coverage||{}).unassigned_ratio||0;
  const wholeMode=(data.coverage||{}).basis==='whole';
  const coverage=wholeMode
    ?(covRatio>0
      ?`<p class="hero-coverage">ℹ 배분 전 <b>회사 전체</b> 금액입니다. 이 중 `
        +`<b>${(covRatio*100).toFixed(1)}%</b>는 유치자(지분) 미등록 건이라 `
        +`개인 화면 어디에도 안 잡힙니다 — 개인 실적을 다 더해도 이만큼 모자랍니다.</p>`
      :'')
    :(covRatio>0.15
      ?`<p class="hero-coverage">ℹ 이 지사 매출의 <b>${(covRatio*100).toFixed(0)}%</b>는 `
        +`유치자(지분) 미등록 건이라 개인 실적으로 잡히지 않습니다 — `
        +`실제보다 적게 보일 수 있습니다.</p>`
      :'');
  $('hero').innerHTML=`
    <p class="hero-label">${escapeHtml(label)} <span class="muted">· ${wholeMode?'배분 전':'지분 반영'} · 부가세 제외</span></p>
    <p class="hero-value"><span class="hero-num">${eok(k.single.amount)}</span>
      <span class="won">${money.format(k.single.amount)}원</span></p>
    <div class="chips">${chips.join('')}</div>${coverage}`;
}

// ── 시간축 카드: 좌 월별(올해 vs 전년) · 우 연도별 5년. 탭은 없다 ─────────
// 한 달에 몇 번 여는 사용자에게 탭 뒤의 정보는 없는 정보다(설계 심사 확정).

function monthsBetween(fromIso,toIso){
  const out=[];const d=new Date(fromIso+'T00:00:00');const end=new Date(toIso+'T00:00:00');
  d.setDate(1);
  while(d<=end){
    out.push(`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`);
    d.setMonth(d.getMonth()+1);
  }
  return out;
}

// 데이터 끝만 4px 라운드, 기준선은 직각 — 값 0이나 반경보다 작은 막대는 그냥 사각.
function roundTopRect(x,y,w,h,cls,r=3){
  if(h<=0)return'';
  if(h<=r)return`<rect class="${cls}" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
  return`<path class="${cls}" d="M${x},${y+h} L${x},${y+r} Q${x},${y} ${x+r},${y} `
    +`L${x+w-r},${y} Q${x+w},${y} ${x+w},${y+r} L${x+w},${y+h} Z"/>`;
}

// 축 꼭대기. **데이터에 바짝 붙인다** (2026-08-10 요청).
// 사다리가 1·2·2.5·5·10 뿐이면 10.6억이 20억으로 올라가, 곡선이 화면 아래
// 절반에 눌려 달 사이 차이가 안 보였다. 촘촘한 사다리로 10.6억 → 11억.
// 여백을 아예 없애면(꼭 맞추면) 최고점이 위 눈금선에 붙어 잘린 것처럼 보이므로
// 한 칸 위 눈금까지만 올린다.
const NICE_STEPS=[1,1.1,1.2,1.25,1.5,1.75,2,2.5,3,4,5,6,8,10];
function niceMax(v){
  if(v<=0)return 1;
  const exp=Math.pow(10,Math.floor(Math.log10(v)));
  for(const m of NICE_STEPS){if(v<=m*exp)return m*exp;}
  return 10*exp;
}

// 단조 3차 보간(Fritsch–Carlson) — 부드럽되 데이터에 없는 봉우리를 만들지 않는다.
// 카트멀-롬류는 급락 구간에서 0 아래로 출렁여 '마이너스 매출'처럼 보인다.
function smoothPath(pts){
  const n=pts.length;
  if(n===0)return'';
  if(n===1)return`M${pts[0].x},${pts[0].y}`;
  const dx=[],slope=[],m=[];
  for(let i=0;i<n-1;i++){dx[i]=pts[i+1].x-pts[i].x;slope[i]=(pts[i+1].y-pts[i].y)/dx[i];}
  m[0]=slope[0];m[n-1]=slope[n-2];
  for(let i=1;i<n-1;i++){
    if(slope[i-1]*slope[i]<=0){m[i]=0;continue;}
    const w1=2*dx[i]+dx[i-1],w2=dx[i]+2*dx[i-1];
    m[i]=(w1+w2)/(w1/slope[i-1]+w2/slope[i]);
  }
  let d=`M${pts[0].x},${pts[0].y.toFixed(1)}`;
  for(let i=0;i<n-1;i++){
    const c1x=pts[i].x+dx[i]/3,c1y=pts[i].y+m[i]*dx[i]/3;
    const c2x=pts[i+1].x-dx[i]/3,c2y=pts[i+1].y-m[i+1]*dx[i]/3;
    d+=`C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} `
      +`${pts[i+1].x},${pts[i+1].y.toFixed(1)}`;
  }
  return d;
}

// 범례는 **실적이 없는 기간에도** 그린다 — 통째로 지우면 '그래프가 고장났나'
// 로 보인다. 이제 스위치가 아니라 색 이름표다(2026-08-18 — 체크박스 제거).
function paintTrendLegend(hasPrev){
  $('trendLegend').innerHTML=
    '<span class="ser"><span class="key key-line" '
    +'style="background:linear-gradient(90deg,#2a78d6,#6a6ff0)"></span>매출'
    +(hasPrev?'<small>(올해·전년)</small>':'')+'</span>';
}

function renderMonthly(data){
  const el=$('monthlyChart');
  const months=monthsBetween(data.period.from,data.period.to);
  const by=list=>{const m={};(list||[]).forEach(x=>{m[x.month]=x;});return m;};
  const cur=by(data.monthly.current);
  const prevRaw=by(data.monthly.previous);
  const hasPrev=(data.monthly.previous||[]).some(m=>m.amount>0);
  const rows=months.map(ym=>{
    const[y,m]=ym.split('-');
    const prevYm=`${Number(y)-1}-${m}`;
    return{label:`${Number(m)}월`,ym,
      cur:(cur[ym]||{}).amount||0,count:(cur[ym]||{}).count||0,
      prev:(prevRaw[prevYm]||{}).amount||0};
  });
  if(!rows.some(r=>r.cur>0||r.prev>0)){
    el.innerHTML='<p class="empty">이 기간에 실적이 없습니다.</p>';
    paintTrendLegend(false);
    return;
  }
  // 곡선 그래프 (2026-08-09 사용자 요청 — 막대가 얇고 공백이 많았다).
  // 올해 = 그라디언트 면적 + 2.5px 선 + 점, 전년 = 회색 맥락선.
  const max=niceMax(Math.max(...rows.map(r=>Math.max(r.cur,r.prev)))) || 1;
  // 전년선 끝의 '전년' 꼬리표가 들어갈 자리를 우측에 벌린다.
  // 눈금 글자를 12px 로 키우며(노안 가독성) 좌측 여백도 64px 로 넓혔다.
  const PADL=64,PADR=hasPrev?46:16,
        H=208,BASE=H-20,TOP=14;
  const avail=(el.clientWidth||720)-PADL-PADR;
  const slot=Math.min(110,Math.max(48,avail/rows.length));
  const W=PADL+PADR+slot*rows.length;
  const yOf=v=>BASE-(v/max)*(BASE-TOP);

  const xOf=i=>PADL+i*slot+slot/2;
  const pts=key=>rows.map((r,i)=>({x:xOf(i),y:yOf(r[key])}));

  let svg=`<defs>
    <linearGradient id="gLine" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#2a78d6"/><stop offset="1" stop-color="#6a6ff0"/>
    </linearGradient>
    <linearGradient id="gArea" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4d79e6" stop-opacity=".22"/>
      <stop offset="1" stop-color="#4d79e6" stop-opacity="0"/>
    </linearGradient></defs>`
    +`<line class="axis" x1="${PADL-6}" y1="${BASE}" x2="${W-PADR}" y2="${BASE}"/>`;
  [.5,1].forEach(f=>{
    const y=yOf(max*f);
    svg+=`<line class="grid" x1="${PADL-6}" y1="${y}" x2="${W-PADR}" y2="${y}"/>`;
    svg+=`<text x="${PADL-9}" y="${y+3}" text-anchor="end">${eok(max*f)}</text>`;
  });
  rows.forEach((r,i)=>{
    svg+=`<text x="${xOf(i)}" y="${BASE+13}" text-anchor="middle">${r.label}</text>`;
  });
  // 십자선 — 포인터가 가리키는 달을 찾아준다 (선 그래프의 명중 규칙).
  svg+=`<line class="xhair" x1="0" y1="${TOP-6}" x2="0" y2="${BASE}" visibility="hidden"/>`;
  if(hasPrev){
    const pp=pts('prev');
    svg+=`<path class="ln-prev" d="${smoothPath(pp)}"/>`;
    // 전년선에도 점을 찍고 선 끝에 꼬리표를 단다 — 유리 배경에서 회색선만으로는
    // 묻힌다는 제보(2026-08-09). 점은 올해 점보다 작게(위계 유지).
    rows.forEach((r,i)=>{
      if(r.prev>0)svg+=`<circle class="dot-prev" cx="${xOf(i)}" cy="${yOf(r.prev).toFixed(1)}" r="3"/>`;
    });
    const last=pp[pp.length-1];
    svg+=`<text class="ln-tag" x="${last.x+9}" y="${(last.y+3).toFixed(1)}">전년</text>`;
  }
  const curPts=pts('cur');
  if(curPts.length>1){
    svg+=`<path fill="url(#gArea)" stroke="none" d="${smoothPath(curPts)}`
      +` L${curPts[curPts.length-1].x},${BASE} L${curPts[0].x},${BASE} Z"/>`;
  }
  svg+=`<path class="ln-cur" d="${smoothPath(curPts)}"/>`;
  // 점은 올해 선에만 — 흰 테두리로 선 위에서도 또렷하다. 값이 있는 달만 찍는다.
  const nonZero=rows.filter(r=>r.cur>0);
  const maxRow=nonZero.length?nonZero.reduce((a,b)=>a.cur>=b.cur?a:b):null;
  const lastRow=nonZero.length?nonZero[nonZero.length-1]:null;
  const labelAll=nonZero.length<=6;
  rows.forEach((r,i)=>{
    if(r.cur>0){
      svg+=`<circle class="dot-cur" cx="${xOf(i)}" cy="${yOf(r.cur).toFixed(1)}" r="4"/>`;
      if(labelAll||r===maxRow||r===lastRow){
        svg+=`<text class="val" x="${xOf(i)}" y="${yOf(r.cur)-9}" text-anchor="middle">${eok(r.cur)}</text>`;
      }
    }
    svg+=`<rect class="hit" data-i="${i}" tabindex="0" x="${PADL+i*slot}" y="${TOP-8}" `
      +`width="${slot}" height="${BASE-TOP+8}" aria-label="${r.label} 확정 ${money.format(r.cur)}원"/>`;
  });
  el.innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">${svg}</svg>`;

  const xhair=el.querySelector('.xhair');
  const tipRowsFor=i=>{
    const r=rows[i];
    const out=[{label:'매출 확정',value:`${money.format(r.cur)}원`,color:C_CUR}];
    if(hasPrev)out.push({label:'전년 동월',value:`${money.format(r.prev)}원`,color:C_PREV});
    if(hasPrev&&r.prev>0){
      const d=r.cur-r.prev;
      out.push({label:'매출 증감',value:`${d>=0?'+':'-'}${money.format(Math.abs(d))}원`});
    }
    return out;
  };
  el.querySelectorAll('.hit').forEach(hit=>{
    const i=Number(hit.dataset.i);
    const mark=()=>{xhair.setAttribute('x1',xOf(i));xhair.setAttribute('x2',xOf(i));
      xhair.setAttribute('visibility','visible');};
    const unmark=()=>{xhair.setAttribute('visibility','hidden');tipHide();};
    hit.addEventListener('pointermove',e=>{mark();tipShow(e.clientX,e.clientY,rows[i].label,tipRowsFor(i));});
    hit.addEventListener('pointerleave',unmark);
    hit.addEventListener('focus',()=>{
      mark();const b=hit.getBoundingClientRect();tipShow(b.left,b.bottom,rows[i].label,tipRowsFor(i));
    });
    hit.addEventListener('blur',unmark);
  });

  // 범례가 곧 스위치다 (2026-08-11 요청). 이름 옆에 체크를 두면 '무엇이 있고
  // 무엇을 보고 있나' 를 한 자리에서 읽는다. 다시 조회하지 않는다.
  paintTrendLegend(hasPrev);
}

function renderYearly(){
  const el=$('yearlyChart');
  if(yearly===null){el.innerHTML='<p class="empty">불러오는 중…</p>';return;}
  if(yearly===false){el.innerHTML='<p class="empty">불러오지 못했습니다.</p>';return;}
  // 공동은 더하지 않는다 (2026-08-10 요청) — 화면 어디서도 공동을 세지 않는다.
  const rows=yearly.map(y=>({year:y.year,amount:y.single||0,count:y.single_count||0}));
  if(!rows.some(r=>r.amount>0)){el.innerHTML='<p class="empty">최근 5년 실적이 없습니다.</p>';return;}
  const thisYear=latest?new Date(latest.period.to).getFullYear():new Date().getFullYear();
  const max=niceMax(Math.max(...rows.map(r=>r.amount)));
  // 패널 폭에 맞춰 5개 막대를 편다 — 고정폭이면 우측 절반이 비었다(실측 제보).
  const n=rows.length,PADL=8,PADR=8,H=208,BASE=H-20,TOP=14;
  const avail=(el.clientWidth||360)-PADL-PADR;
  const slot=Math.min(96,Math.max(44,avail/n));
  const W=PADL+PADR+slot*n;
  const bw=Math.min(24,Math.round(slot*.5));
  const yOf=v=>BASE-(v/max)*(BASE-TOP);
  let svg=`<defs><linearGradient id="gCurV" x1="0" y1="0" x2="0" y2="1">`
    +`<stop offset="0" stop-color="#6a6ff0"/><stop offset="1" stop-color="#2a78d6"/>`
    +`</linearGradient></defs>`
    +`<line class="axis" x1="${PADL}" y1="${BASE}" x2="${W-PADR}" y2="${BASE}"/>`;
  const maxRow=rows.reduce((a,b)=>a.amount>=b.amount?a:b);
  rows.forEach((r,i)=>{
    const cx=PADL+i*slot+slot/2;
    const isCur=r.year===thisYear;
    if(r.amount>0)svg+=roundTopRect(cx-bw/2,yOf(r.amount),bw,BASE-yOf(r.amount),
      isCur?'b-cur':'b-prev',4);
    svg+=`<text x="${cx}" y="${BASE+13}" text-anchor="middle"`
      +`${isCur?' font-weight="700" fill="#1f2937"':''}>${String(r.year).slice(2)}년</text>`;
    // 값 라벨은 전 막대에 — 5개뿐이라 소음이 아니고, 전년들과의 비교가 이 패널의
    // 일이다(잘 안 보인다는 제보 2026-08-09). 당해만 진한 잉크, 과거는 옅은 잉크.
    if(r.amount>0){
      svg+=`<text class="${isCur||r===maxRow?'val':'val-muted'}" x="${cx}" `
        +`y="${yOf(r.amount)-4}" text-anchor="middle">${eok(r.amount)}</text>`;
    }
    svg+=`<rect class="hit" data-i="${i}" tabindex="0" x="${PADL+i*slot}" y="${TOP-8}" `
      +`width="${slot}" height="${BASE-TOP+8}" aria-label="${r.year}년 ${money.format(r.amount)}원"/>`;
  });
  el.innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">${svg}</svg>`;
  el.querySelectorAll('.hit').forEach(hit=>{
    const i=Number(hit.dataset.i);
    const show=(x,y)=>tipShow(x,y,`${rows[i].year}년`,[
      {label:'연간 합계',value:`${money.format(rows[i].amount)}원`,color:rows[i].year===thisYear?C_CUR:C_PREV},
      {label:'건수',value:`${money.format(rows[i].count)}건`},
    ]);
    hit.addEventListener('pointermove',e=>show(e.clientX,e.clientY));
    hit.addEventListener('pointerleave',tipHide);
    hit.addEventListener('focus',()=>{const b=hit.getBoundingClientRect();show(b.left,b.bottom);});
    hit.addEventListener('blur',tipHide);
  });
  // 당해는 진행 중인 해 — 부분 연도임을 제목에 밝혀 정직하게 비교하게 한다.
  if(latest){
    const from=new Date(latest.period.from),to=new Date(latest.period.to);
    const part=from.getFullYear()===thisYear
      ?` · ${thisYear}년은 ${from.getMonth()+1}~${to.getMonth()+1}월`:'';
    $('yearlyTitle').innerHTML=`연도별 매출 <small>최근 5년${escapeHtml(part)}</small>`;
  }
}

// ── 발주처 — 일감이 오는 곳 + 식은 관계 ─────────────────────────────────
function renderClients(data){
  const el=$('clientsBody');
  const cs=data.customers||{top:[],others:{},gone:[]};
  const total=data.kpi.single.amount||0;
  if(!cs.top.length){
    el.innerHTML='<p class="empty">이 기간에 실적이 없습니다.</p>';
    return;
  }
  // 전년 실적이 아예 없으면 전부가 '신규'다 — 그때 배지는 소음이라 접는다.
  const badgeable=data.kpi.growth.prev_amount>0||data.kpi.growth.prev_count>0;
  const rows=cs.top.map(t=>({...t,other:false}));
  if(cs.others&&cs.others.kinds>0){
    rows.push({name:`기타 ${money.format(cs.others.kinds)}곳`,count:cs.others.count,
      amount:cs.others.amount,prev_amount:0,is_new:false,other:true,raw_kinds:0});
  }
  const scale=Math.max(...rows.map(r=>Math.max(r.amount,r.prev_amount||0)),1);
  let html;
  if(cs.top.length===1&&!(cs.others&&cs.others.kinds>0)){
    // 발주처가 한 곳이면 막대 하나짜리 차트는 그리지 않는다 — 숫자가 곧 차트다.
    const t=cs.top[0];
    html=`<p class="cl-single">이 기간 일감은 <b>${escapeHtml(t.name)}</b> 한 곳에서 왔습니다 — `
      +`${money.format(t.count)}건 · ${eok(t.amount)}${t.is_new&&badgeable?' <span class="badge badge-new">신규</span>':''}</p>`;
  }else{
    html='<div class="cl-rows">'+rows.map(r=>{
      const pct=total>0?(r.amount/total*100):0;
      const branch=r.raw_kinds>1?` · 지점·부서 ${r.raw_kinds}곳`:'';
      const tipText=r.other?'':`${r.raw_name||r.name}${branch}`;
      // 전년 금액은 띠만으로는 '얼마' 를 못 말한다(2026-08-09 제보) — 글자로 병기.
      const prevTxt=r.prev_amount>0
        ?` · <span class="cl-prev-tx">전년 ${escapeHtml(eok(r.prev_amount))}</span>`:'';
      return `<div class="cl-row"${tipText?` title="${escapeHtml(tipText)}"`:''}>
        <div class="cl-name">
          <span class="nm">${escapeHtml(r.name)}</span>
          ${r.is_new&&badgeable&&!r.other?'<span class="badge badge-new">신규</span>':''}
          <span class="cnt">${money.format(r.count)}건 · ${pct.toFixed(0)}%${prevTxt}</span>
          <span class="amt">${eok(r.amount)}</span>
        </div>
        ${clTrack(r.amount,r.prev_amount||0,scale,r.other?'other':'')}
      </div>`;
    }).join('')+'</div>';
  }
  // 식은 관계(작년엔 있었는데 올해 0건)는 카드에 상시로 두지 않고 AI 분석으로
  // 옮겼다(2026-08-10 사용자 확정) — 버튼을 눌렀을 때 서술과 함께 나온다.
  // 데이터(customers.gone)는 그대로 내려온다: AI 사실표가 그걸 먹는다.
  el.innerHTML=html;
}

// ── 매출 구성 — 업무종류·물건종류 100% 누적 막대(올해/전년) ──────────────
// ── 매출 구성 — 종류마다 '올해/전년' 라벨 붙은 막대 두 개 (2026-08-09 v2) ──
// v1(막대+전년 틱)은 틱이 '전년 위치'라는 걸 설명 없이는 못 읽었다(사용자 실측).
// 월별 차트와 같은 언어로 간다: 올해 = 파랑 그라디언트, 전년 = 회색, 각 막대에
// '올해/전년' 글자와 금액을 직접 붙인다 — 색 약속을 외울 필요가 없다.
function renderMixBlock(title,items,colors){
  const rows0=items.filter(x=>x.amount>0||(x.prev_amount||0)>0);
  if(!rows0.length)return'';
  const curTotal=rows0.reduce((s,x)=>s+x.amount,0);
  const prevTotal=rows0.reduce((s,x)=>s+(x.prev_amount||0),0);
  const head=rows0.slice(0,5);
  const tail=rows0.slice(5);
  const rows=head.map(x=>({...x,fold:false}));
  if(tail.length){
    rows.push({name:`기타 ${tail.length}종`,fold:true,
      amount:tail.reduce((s,x)=>s+x.amount,0),
      count:tail.reduce((s,x)=>s+x.count,0),
      prev_amount:tail.reduce((s,x)=>s+(x.prev_amount||0),0)});
  }
  const scale=Math.max(...rows.map(r=>Math.max(r.amount,r.prev_amount||0)),1);
  const top=rows0[0];
  const headline=top&&top.amount>0
    ?`<p class="mix-headline"><b>${escapeHtml(top.name)} ${(top.amount/Math.max(curTotal,1)*100).toFixed(0)}%</b>`
      +(prevTotal>0?` <span class="muted">(전년 ${((top.prev_amount||0)/prevTotal*100).toFixed(0)}%)</span>`:'')+'</p>'
    :'';
  const barLine=(year,cls,value)=>{
    const width=value>0?Math.max(value/scale*100,.8):0;
    return `<div class="mxp-line">
      <span class="mxp-year">${year}</span>
      <div class="mxp-track">${value>0?`<i class="mxp-bar ${cls}" style="width:${width}%"></i>`:''}</div>
      <span class="mxp-amt${value>0?'':' muted'}">${value>0?escapeHtml(eok(value)):'없음'}</span>
    </div>`;
  };
  const body=rows.map(r=>{
    const prev=r.prev_amount||0;
    const pct=curTotal>0?(r.amount/curTotal*100):0;
    let delta;
    if(r.amount>0&&prev<=0)delta='<span class="mx-delta up">신규</span>';
    else if(r.amount<=0)delta='<span class="mx-delta muted">올해 없음</span>';
    else{
      const d=r.amount-prev;
      delta=`<span class="mx-delta ${d>=0?'up':'down'}">${d>=0?'▲':'▼'} ${escapeHtml(eok(Math.abs(d)))}</span>`;
    }
    const dot=`<i class="dot" style="background:${r.fold?C_FOLD:colorOf(colors,r.name)}"></i>`;
    return `<div class="mxp-row">
      <div class="cl-name">
        <span class="nm">${dot}${escapeHtml(r.name)}</span>
        ${delta}
        <span class="cnt">${money.format(r.count)}건 · ${pct.toFixed(0)}%</span>
      </div>
      ${barLine('올해','cur',r.amount)}
      ${barLine('전년','prev',prev)}
    </div>`;
  }).join('');
  return `<div class="mix-block">
    <p class="mix-title">${escapeHtml(title)}</p>${headline}
    <div class="mxp-rows">${body}</div></div>`;
}

function renderMix(data){
  const el=$('mixBody');
  const html=renderMixBlock('물건종류',data.prop_types||[],PROP_COLORS)
    +renderMixBlock('업무종류',data.work_types||[],WORK_COLORS);
  el.innerHTML=html||'<p class="empty">이 기간에 실적이 없습니다.</p>';
}

// ── 당기 전건 표 — 위 모든 차트의 증빙 ─────────────────────────────────
// ── 구성 탭 (2026-08-10) ─────────────────────────────────────────────────
// 매출 구성과 발주처 두 카드를 하나로 합치고 탭으로 갈랐다.
// 매출·미수·거래처는 **좌측 표 + 우측 그래프**, 상여·가변비는 월별 표다.
// 상여·가변비는 여기서 처음 부른다(lazy) — 상여가 월당 3.7초라 대시보드에
// 얹으면 첫 그림이 그만큼 늦어진다. 한 번 받으면 조회를 새로 할 때까지 재사용한다.
let TAB='sales';
let AXIS='category';          // 매출 탭의 축: category(물건) | work(업무)
let CTAB='sales';             // 거래처별현황 하위 탭: sales(매출)|intake(접수)|recv(미수)
let LATE={bonus:null,variable:null};   // 탭에서 받아 두는 것
const TOPN=5;

function tabHint(text){$('tabHint').innerHTML=text||'';}

// 좌측 표 — **어느 탭이든 열 위치가 같아야 한다.** 자동 폭으로 두면 내용
// 길이에 따라 탭마다 칸이 밀려서 눈이 매번 열을 다시 찾는다(2026-08-10 제보).
// colgroup 으로 폭을 못 박고 table-layout:fixed 로 고정한다.
//
// 칸이 비어 보이던 것도 같은 제보다(2026-08-10). 이름 칸이 넓은데 '구분건물'
// 처럼 짧은 말이 들어가니 오른쪽 숫자까지 빈 벌판이었다. 남는 자리를 **뜻 있는
// 숫자**로 채운다 — 매출·거래처는 전년과 증감, 미수는 매출액과 미수율.
// 미수 금액만 보면 '많은 게 나쁜 건지' 알 수 없다. 매출이 크면 미수도 크다.
const TAB_COLS={
  sales:[['name','종류'],['count','건수'],['amount','금액'],
         ['prev','전년'],['delta','매출 증감'],['pct','비중']],
  // 미수액은 부가세 포함이라 매출액(공급가액)과 자가 다르다. 같은 자로 비교하게
  // **매출총액(부가세 포함)** 을 세운다 — 그래야 화면의 세 숫자가 서로 맞는다.
  // 미수금현황 화면과 같은 말·같은 값이다 — 거기서도 '매출총액'·'미수금' 이라고만
  // 쓰고 둘 다 부가세 포함이다. 굳이 VAT 를 적으면 오히려 특별해 보인다.
  receivable:[['name','종류'],['count','건수'],['amount','미수액'],
              ['gross','매출총액'],['rate','미수율'],['pct','비중']],
  clients:[['name','거래처'],['count','건수'],['amount','금액'],
           ['prev','전년'],['delta','매출 증감'],['pct','비중']],
};

// 전년 실적이 아예 없으면 전부가 '신규' 라 배지가 소음이다 — 그때는 안 붙인다.
// (renderClients 가 쓰던 것과 같은 잣대)
const hadPrev=data=>!!(data&&data.kpi&&data.kpi.growth
  &&(data.kpi.growth.prev_amount>0||data.kpi.growth.prev_count>0));

function tabTable(rows,total,kind,unit,newBadge,cut){
  if(!rows.length)return'<p class="empty">이 기간에 값이 없습니다.</p>';
  const cols=TAB_COLS[kind];
  const cell=(r,key)=>{
    if(key==='name')return`<td class="c-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td>`;
    if(key==='count')return`<td class="num">${r.count==null?'':money.format(r.count)}</td>`;
    if(key==='amount')return`<td class="num strong" title="${escapeHtml(won(r.amount))}">${escapeHtml(eok(r.amount))}</td>`;
    if(key==='sales')return`<td class="num" title="${escapeHtml(won(r.sales||0))}">${escapeHtml(eok(r.sales||0))}</td>`;
    // 매출총액은 미수율의 분모라 남기되 **한 발 물린다** — 이 화면에서 '매출' 은
    // 공급가액이고 여기만 부가세 포함이라, 강조하면 두 뜻이 부딪힌다.
    if(key==='gross')return`<td class="num soft" title="${escapeHtml(won(r.gross||0))}">`
      +`${escapeHtml(eok(r.gross||0))}</td>`;
    if(key==='prev')return`<td class="num"${r.prev_amount?` title="${escapeHtml(won(r.prev_amount))}"`:''}>${r.prev_amount?escapeHtml(eok(r.prev_amount)):'<span class="dim">-</span>'}</td>`;
    if(key==='rate'){
      // 분모는 매출총액이다 — 미수액이 부가세 포함이라 공급가액으로 나누면 부푼다.
      const base=r.gross||0;
      const rate=base>0?(r.amount/base*100):null;
      // 미수율이 이 탭의 주인공이다 — 금액만 보면 많은 게 나쁜 건지 알 수 없다.
      return`<td class="num strong">${rate===null?'<span class="dim">-</span>':rate.toFixed(0)+'%'}</td>`;
    }
    if(key==='delta'){
      const before=r.prev_amount||0;
      // 전년이 0인데 올해 값이 있으면 **신규**다 (2026-08-10 요청). '-' 로 두면
      // '증감을 못 구했다' 로 읽힌다. 다만 전년 실적이 통째로 없는 기간에는
      // 모두가 신규라 배지가 소음이 된다 — 그때는 '-' 로 남긴다.
      if(!before){
        return r.amount>0&&newBadge
          ?'<td class="num"><span class="badge badge-new">신규</span></td>'
          :'<td class="num"><span class="dim">-</span></td>';
      }
      const diff=r.amount-before,up=diff>=0;
      return`<td class="num ${up?'up':'down'}" title="${escapeHtml(won(diff))}">${up?'▲':'▼'} ${escapeHtml(eok(Math.abs(diff)))}</td>`;
    }
    const pct=total>0?(r.amount/total*100):0;
    return`<td class="num">${pct.toFixed(0)}%</td>`;
  };
  return'<table class="tab-table">'
    +'<colgroup>'+cols.map(([k])=>`<col class="c-${k}">`).join('')+'</colgroup>'
    +'<thead><tr>'
    +cols.map(([k,label],i)=>`<th${i?' class="num"':''}>`
       +escapeHtml(i===0&&unit?unit:label)
       // 잘라낸 경우에만 붙인다. 다섯 개 이하라 전부 보여 주는데 TOP 5 라고
       // 적으면 '나머지는 어디 갔나' 를 묻게 된다.
       +(i===0&&cut?` <span class="th-top">TOP ${TOPN}</span>`:'')
       +'</th>').join('')
    +'</tr></thead><tbody>'
    +rows.map(r=>'<tr>'+cols.map(([k])=>cell(r,k)).join('')+'</tr>').join('')
    +'</tbody></table>';
}

// 우측 그래프 — 가로 막대. 전년은 **아래 줄에 나란히 선 막대**다 (2026-08-10 확정).
// 틱 하나였을 때 깨지던 세 경우는 css 의 .cl-track 주석에 적어 두었다.
// 여기서 지켜야 할 것: 0 은 막대를 **아예 안 그린다**. 최소 폭(min-width)을
// 주면 '올해 0' 이 실제 52만원짜리 행(물건종류 '기계기구')보다 길어져
// 길이로 읽는 순위가 뒤집힌다.
function tabChart(rows,badgeable){
  if(!rows.length)return'';
  const scale=Math.max(...rows.map(r=>Math.max(r.amount,r.prev_amount||0)),1);
  return'<div class="cl-rows">'+rows.map(r=>{
    const prev=r.prev_amount||0;
    return`<div class="cl-row">
      <div class="cl-name"><span class="nm">${escapeHtml(r.name)}</span>
        ${prevNote(r,badgeable)}
        <span class="amt" title="${escapeHtml(won(r.amount))}">${escapeHtml(eok(r.amount))}</span></div>
      ${clTrack(r.amount,prev,scale)}</div>`;
  }).join('')+'</div>';
}

// 트랙 한 칸 — 위 줄 올해(파랑), 아래 줄 전년(회색). 같은 원점·같은 자.
function clTrack(cur,prev,scale,barClass){
  const w=v=>Math.min(v/scale*100,100).toFixed(2);
  return`<div class="cl-track">`
    +(prev>0?`<i class="cl-prev" style="width:${w(prev)}%" title="전년 동기 ${escapeHtml(won(prev))}"></i>`:'')
    +(cur>0?`<i class="cl-bar${barClass?' '+barClass:''}" style="width:${w(cur)}%" title="올해 ${escapeHtml(won(cur))}"></i>`:'')
    +'</div>';
}

// 이름 줄의 전년 꼬리표. 아래 줄이 '어디쯤' 을 말하니 글자는 '얼마' 를 맡는다.
// 전년이 없는 두 경우는 아래 줄이 없어 침묵하므로 배지가 대신 말한다 — 종전
// 틱이 '없음' 과 '신규' 를 똑같이 그리던 자리가 바로 여기다.
function prevNote(r,badgeable){
  const prev=r.prev_amount||0;
  if(prev>0)return`<span class="cl-prev-tx">전년 ${escapeHtml(eok(prev))}</span>`;
  if(r.amount>0)return badgeable?'<span class="badge badge-new">신규</span>':'';
  return'<span class="badge badge-gone">올해 없음</span>';
}

// 미수는 동그란 그래프로 (2026-08-10 요청).
// 이 화면은 원래 도넛을 뺐다 — 근접값끼리는 각도로 못 가린다는 이유였다.
// 미수는 사정이 다르다: 축이 두어 개뿐이고(실측 물건종류 3·업무종류 3), 묻는
// 것도 '어디에 얼마나 묶여 있나' 라는 **비중**이라 원이 맞는 그림이다.
// 값 비교는 왼쪽 표가 숫자로 확정하니 원은 크기만 말하면 된다.
function donutChart(rows,total,map){
  if(!rows.length||total<=0)return'';
  const R=58,C=2*Math.PI*R,GAP=3;        // 반지름·둘레·조각 사이 틈(px)
  let acc=0;
  const arcs=rows.map(r=>{
    const frac=Math.max(r.amount/total,0);
    // 조각 사이에 틈을 준다 — 붙어 있으면 비슷한 색끼리 한 덩어리로 보인다.
    // 틈보다 작은 조각은 틈을 빼면 사라지므로 그때는 최소 길이로 그린다.
    const len=Math.max(frac*C-(rows.length>1?GAP:0),0.5);
    const off=(-acc*C).toFixed(2);
    acc+=frac;
    return`<circle class="dn-seg" r="${R}" cx="76" cy="76"`
      +` stroke="${colorOf(map,r.name)}"`
      +` stroke-dasharray="${len.toFixed(2)} ${(C-len).toFixed(2)}"`
      +` stroke-dashoffset="${off}">`
      +`<title>${escapeHtml(r.name)} ${escapeHtml(won(r.amount))}</title></circle>`;
  }).join('');
  const legend=rows.map(r=>`<li title="${escapeHtml(won(r.amount))}">
    <i style="background:${colorOf(map,r.name)}"></i>
    <span class="dn-nm">${escapeHtml(r.name)}</span>
    <b>${escapeHtml(eok(r.amount))}</b>
    <span class="dn-pct">${(r.amount/total*100).toFixed(0)}%</span></li>`).join('');
  return`<div class="donut-wrap">
    <svg class="donut" viewBox="0 0 152 152" role="img" aria-label="미수 비중">
      <circle class="dn-bg" r="${R}" cx="76" cy="76"></circle>
      <g transform="rotate(-90 76 76)">${arcs}</g>
      <text class="dn-mid" x="76" y="70">미수 합계</text>
      <text class="dn-sum" x="76" y="90">${escapeHtml(eok(total))}</text>
    </svg>
    <ul class="donut-legend">${legend}</ul>
  </div>`;
}

function split(left,right){
  return`<div class="tab-split"><div class="tab-left">${left}</div>`
    +`<div class="tab-right">${right}</div></div>`;
}

// 축 고르개 — 매출·미수는 물건종류/업무종류 두 축이 있다.
function axisPicker(){
  return'<div class="axis-pick">'
    +[['category','물건종류'],['work','업무종류']].map(([k,label])=>
      `<button type="button" data-axis="${k}"${AXIS===k?' class="on"':''}>${label}</button>`
    ).join('')+'</div>';
}

// '왜 이리 적지' 를 막는 한 줄. 배지만으로는 몇 개 중 몇 개인지 모른다.
function topNote(list){
  const n=(list||[]).filter(x=>x.amount>0).length;
  return n>TOPN
    ? `<span class="hint-top">금액 상위 ${TOPN}개</span><span class="hint-of">전체 ${money.format(n)}개</span>`
    : '';
}

// 잘라냈나 — TOP 5 라는 말을 붙일지 가른다.
function cutOff(list){return (list||[]).filter(x=>x.amount>0).length>TOPN;}

function topRows(list){
  const rows=(list||[]).filter(x=>x.amount>0).slice(0,TOPN);
  return rows;
}

// 접수 TOP 은 금액이 아니라 **건수** 축이다 — 같은 규칙의 건수판.
function topRows2(list,key){return (list||[]).filter(x=>(x[key]||0)>0).slice(0,TOPN);}
function topNote2(list,key){
  const n=(list||[]).filter(x=>(x[key]||0)>0).length;
  return n>TOPN
    ? `<span class="hint-top">건수 상위 ${TOPN}개</span><span class="hint-of">전체 ${money.format(n)}개</span>`
    : '';
}

// 한 조각이 터져도 카드가 통째로 비지 않게 감싼다. 2026-08-10 에 donutChart 가
// 사라졌을 때, 본문을 한 번에 만드는 식 안에서 예외가 나 **대입 자체가 안 되고**
// 이전 화면이 그대로 남았다 — 사용자에게는 '탭이 안 먹는다' 로 보였다.
// 테스트 764건이 다 통과하는데도 화면이 죽어 있었다.
function renderTabBody(data){
  try{
    renderTabBodyInner(data);
  }catch(error){
    console.error('구성 탭 그리기 실패',error);
    $('tabBody').innerHTML='<p class="empty">이 탭을 그리지 못했습니다. '
      +'다른 탭을 눌러 보시고, 계속되면 새로고침해 주세요.</p>';
    tabHint('');
  }
}

// 거래처별현황 하위 탭 (2026-08-13 요청) — 매출 TOP·접수 TOP·미수 TOP,
// 셋 다 축은 거래처다. 종전의 미수 탭(물건·업무종류 축)은 여기 미수 TOP 으로
// 들어왔다.
function clientsPicker(){
  return'<div class="axis-pick">'
    +[['sales','매출 TOP'],['intake','접수 TOP'],['recv','미수 TOP']].map(([k,label])=>
      `<button type="button" data-ctab="${k}"${CTAB===k?' class="on"':''}>${label}</button>`
    ).join('')+'</div>';
}

// 접수·미수 TOP 우측의 간단한 가로 막대 — tabChart 는 금액(억) 포맷이 박혀
// 있어 건수 축에 못 쓴다. 이름·막대·값만 그리는 최소형.
function simpleBars(rows,valueOf,fmt){
  if(!rows.length)return'<p class="empty">이 기간에 값이 없습니다.</p>';
  const scale=Math.max(...rows.map(valueOf),1);
  return'<div class="cl-rows">'+rows.map(r=>`<div class="cl-row">
    <div class="cl-name"><span class="nm">${escapeHtml(r.name)}</span>
      <span class="amt">${escapeHtml(fmt(valueOf(r)))}</span></div>
    ${clTrack(valueOf(r),0,scale,'')}
  </div>`).join('')+'</div>';
}

function intakeTable(rows,total){
  if(!rows.length)return'<p class="empty">이 기간에 접수가 없습니다.</p>';
  return'<table class="tab-table">'
    +'<colgroup><col class="c-name"><col class="c-count"><col class="c-prev">'
    +'<col class="c-delta"><col class="c-pct"></colgroup>'
    +'<thead><tr><th>거래처</th><th class="num">접수</th><th class="num">전년</th>'
    +'<th class="num">증감</th><th class="num">비중</th></tr></thead><tbody>'
    +rows.map(r=>{
      const diff=(r.count||0)-(r.prev_count||0),up=diff>=0;
      const pct=total>0?((r.count||0)/total*100):0;
      return`<tr><td class="c-name" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</td>`
        +`<td class="num strong">${money.format(r.count||0)}건</td>`
        +`<td class="num">${r.prev_count?money.format(r.prev_count)+'건':'<span class="dim">-</span>'}</td>`
        +`<td class="num ${up?'up':'down'}">${up?'▲':'▼'} ${money.format(Math.abs(diff))}</td>`
        +`<td class="num">${pct.toFixed(0)}%</td></tr>`;
    }).join('')+'</tbody></table>';
}

function renderTabBodyInner(data){
  const body=$('tabBody');
  if(TAB==='sales'){
    const src=AXIS==='category'?(data.prop_types||[]):(data.work_types||[]);
    const rows=topRows(src);
    const total=data.kpi.single.amount||0;
    tabHint(topNote(src)+'<i class="prev-key"></i> 윗줄 올해 · 아랫줄 전년 동기');
    body.innerHTML=axisPicker()+split(
      tabTable(rows,total,'sales',AXIS==='category'?'물건종류':'업무종류',
               hadPrev(data),cutOff(src)),
      tabChart(rows,hadPrev(data)));
  }else if(TAB==='clients'){
    if(CTAB==='intake'){
      const it=data.intake||{top:[],total:0};
      const rows=topRows2(it.top,'count');
      tabHint(topNote2(it.top,'count')
        +`접수 합계 <b class="hint-total">${money.format(it.total||0)}건</b>`
        +(it.prev_total?` · 전년 동기 ${money.format(it.prev_total)}건`:''));
      body.innerHTML=clientsPicker()+split(
        intakeTable(rows,it.total||0),
        simpleBars(rows,r=>r.count||0,v=>money.format(v)+'건'));
    }else if(CTAB==='recv'){
      const rc=data.receivable||{customers:[],total:0};
      const rows=topRows(rc.customers);
      tabHint(topNote(rc.customers)
        +(rc.total>0?`미수 합계 <b class="hint-total">${escapeHtml(eok(rc.total))}</b>`:'')
        +' · 당기 발송 건 기준');
      body.innerHTML=clientsPicker()+split(
        tabTable(rows,rc.total,'receivable','거래처',false,cutOff(rc.customers)),
        simpleBars(rows,r=>r.amount||0,v=>eok(v)));
    }else{
      const cs=data.customers||{top:[]};
      const rows=topRows(cs.top);
      tabHint(topNote(cs.top)+'<i class="prev-key"></i> 윗줄 올해 · 아랫줄 전년 동기');
      body.innerHTML=clientsPicker()+split(
        tabTable(rows,data.kpi.single.amount||0,'clients',null,hadPrev(data),cutOff(cs.top)),
        tabChart(rows,hadPrev(data)));
    }
  }else if(TAB==='bonus'){
    renderMonths('bonus',body);
  }else{
    renderMonths('variable',body);
  }
}

// 상여·가변비 — 월별 표. 받아 둔 게 없으면 그때 부른다.
function renderMonths(kind,body){
  const got=LATE[kind];
  if(got===null){
    tabHint('');
    body.innerHTML=`<p class="empty">${kind==='bonus'?'상여는 달마다 계산해 시간이 걸립니다. 불러오는 중…':'불러오는 중…'}</p>`;
    loadLate(kind);
    return;
  }
  if(got===false){
    tabHint('');
    body.innerHTML='<p class="empty">불러오지 못했습니다.</p>';
    return;
  }
  const months=got.months||[];
  if(kind==='variable'){
    const total=got.total||0;
    tabHint(`합계 <b class="hint-total">${escapeHtml(eok(total))}</b>`);
    // 좌 월별 표 · 우 항목별 표. **그래프는 두지 않는다** (2026-08-10 요청) —
    // 월별 막대는 위 '전체 추이' 와 겹쳐 읽히고, 그 자리를 표에 주면 항목
    // 이름이 안 잘린다(그래프가 있을 땐 '탁상…'·'HU…' 로 잘렸다).
    // 건수 열은 다른 탭과 격자를 맞추려고 남기되 머리글은 비운다 — '건수' 라
    // 써 놓고 칸이 늘 비어 있으면 데이터가 빠진 것처럼 보인다.
    // 표 하나로 다 담는다 (요청) — 좌우로 가르지 않는다.
    body.innerHTML=vcTable(got);
    return;
  }
  const fields=got.fields||[];
  tabHint(`지급 합계 <b class="hint-total">${escapeHtml(eok(got.total||0))}</b>`);
  // 칸이 아홉이라 좁으면 가로로 민다 — 숫자를 줄여 쓰지 않는다.
  // note 가 달린 칸은 머리글에 풍선말을 붙이고 점선 밑줄로 표시한다 — '가변비'
  // 처럼 옆 탭과 이름이 같은데 기준이 다른 칸이 있다(서버 _BONUS_NOTES 참고).
  body.innerHTML='<div class="vc-scroll"><table class="tab-table wide"><thead><tr><th>월</th>'
    +fields.map(f=>f.note
      ?`<th class="num"><abbr class="col-note" title="${escapeHtml(f.note)}">`
        +`${escapeHtml(f.label)}</abbr></th>`
      :`<th class="num">${escapeHtml(f.label)}</th>`).join('')
    +'</tr></thead><tbody>'
    +months.map(m=>m.found
      ?`<tr><td>${escapeHtml(m.ym)}</td>`
        +fields.map(f=>`<td class="num">${escapeHtml(eok(m[f.key]||0))}</td>`).join('')+'</tr>'
      :`<tr class="dim"><td>${escapeHtml(m.ym)}</td>`
        +`<td class="num" colspan="${fields.length}">해당 없음</td></tr>`).join('')
    +'</tbody></table></div>';
}

// 가변비 — **표 하나**에 월(행) × 항목(열) 을 다 담는다 (2026-08-10 요청).
// 열은 이 기간에 값이 있는 항목만 선다. 22개를 다 세우면 대부분 빈 칸이라
// 표가 안 읽힌다. 갈래(인력 투입·기본 처리…)는 머리글 위 줄에 묶어 얹는다.
// 인력 투입은 수량이 시간(H:MM), 나머지는 건수다.
function vcQty(kind,qty){
  if(!qty)return'';
  if(kind!=='time')return`${money.format(qty)}건`;
  return`${Math.floor(qty/60)}:${String(qty%60).padStart(2,'0')}`;
}
function vcTable(data){
  const cols=data.columns||[],months=data.months||[];
  if(!cols.length)return'<p class="empty">이 기간에 가변비가 없습니다.</p>';
  // 갈래별로 몇 칸인지 세어 위 줄에 묶어 얹는다.
  const groups=[];
  cols.forEach(c=>{
    const last=groups[groups.length-1];
    if(last&&last.name===c.group)last.span++;
    else groups.push({name:c.group,span:1});
  });
  const sum=name=>months.reduce((s,m)=>s+(((m.cells||{})[name]||{}).amount||0),0);
  return'<div class="vc-scroll"><table class="tab-table vc-matrix">'
    +'<thead>'
    +'<tr class="vc-grouprow"><th></th>'
    +groups.map(g=>`<th colspan="${g.span}">${escapeHtml(g.name)}</th>`).join('')
    +'<th></th></tr>'
    +'<tr><th>월</th>'
    +cols.map(c=>`<th class="num">${escapeHtml(c.name)}</th>`).join('')
    +'<th class="num vc-total">합계</th></tr></thead><tbody>'
    +months.map(m=>{
      const cells=m.cells||{};
      // 상세가 0건인데 상여에는 잡히는 달 — 원장 표기('본인,공(아무개)') 때문에
      // 프로시저가 그 달을 통째로 버린 경우다. 값을 지어내지 않고 사실만 알린다.
      const only=Number(m.bonus_only||0);
      const tot=only>0
        ?`<td class="num vc-total" title="상세 조회에는 안 잡히지만 상여에는 ${escapeHtml(won(only))}이 반영된 달입니다 (원장 유치자 표기 문제)">`
          +`<span class="dim">${escapeHtml(eok(m.amount))}</span> <small>상여 ${escapeHtml(eok(only))}</small></td>`
        :`<td class="num vc-total">${escapeHtml(eok(m.amount))}</td>`;
      return`<tr><td class="c-name">${escapeHtml(m.ym)}</td>`
        +cols.map(c=>{
          const v=cells[c.name];
          if(!v||!v.amount)return'<td class="num dim">-</td>';
          const q=vcQty(c.kind,v.qty);
          return`<td class="num" title="${escapeHtml(c.name)} ${escapeHtml(q)} · ${escapeHtml(won(v.amount))}">`
            +`${escapeHtml(eok(v.amount))}${q?`<small>${escapeHtml(q)}</small>`:''}</td>`;
        }).join('')
        +tot+'</tr>';
    }).join('')
    +'</tbody><tfoot><tr><td class="c-name">합계</td>'
    +cols.map(c=>`<td class="num">${escapeHtml(eok(sum(c.name)))}</td>`).join('')
    +`<td class="num vc-total">${escapeHtml(eok(data.total||0))}</td></tr></tfoot>`
    +'</table></div>';
}

// 같은 요청이 두 번 나가는 길이 있었다: 프리페치가 아직 도는 중에 탭을 누르면
// LATE[kind] 가 여전히 null 이라 renderMonths 가 loadLate 를 또 부른다 —
// 12초짜리 계산이 두 벌 돈다. 대상별로 '가는 중' 을 기억해 막는다.
// 키에 대상을 넣는 이유: 사람을 바꾸면 새 요청은 막히면 안 된다.
const INFLIGHT={};
async function loadLate(kind){
  if(isAll())return;                 // 전체는 사람 단위 계산을 안 부른다
  const path=kind==='bonus'?'bonus':'variable-cost';
  const at=$('empName').value;       // 던질 때의 대상
  // 키에 **기간·지사까지** 넣는다. 이름만 넣으면 같은 사람의 다른 기간 요청이
  // '이미 가는 중' 으로 오해받아 아예 안 나간다(연도를 바꿨는데 옛 값이 남는다).
  const flight=`${kind}|${at}|${$('officeCode').value}|${$('dateFrom').value}|${$('dateTo').value}`;
  if(INFLIGHT[flight])return;
  INFLIGHT[flight]=true;
  try{
    const res=await fetch(`/api/my-sales/${path}?${scopeQuery()}`);
    const payload=await res.json();
    // **받은 시점에 대상이 그대로인지 다시 본다.** 개인 → 전체로 바꾸는 중에
    // 늦게 도착한 응답이 여기로 돌아오면, 전사 매출 곡선 밑에 한 사람의
    // 가변비가 그려진다. render() 가 LATE 를 비우는 것만으로는 못 막는다.
    if($('empName').value!==at)return;
    LATE[kind]=payload.success?payload.data:false;
  }catch(e){
    if($('empName').value!==at)return;
    LATE[kind]=false;
  }finally{
    delete INFLIGHT[flight];
  }
  // 추이 차트는 다시 안 그린다 — 가변비·상여 모두 차트에서 뺐다(2026-08-13).
  // 도착한 값이 실리는 곳은 제 탭의 월별 표뿐이다.
  if(TAB===kind)renderMonths(kind,$('tabBody'));
}

function bindTabs(){
  $('mixTabs').addEventListener('click',event=>{
    const button=event.target.closest('button[data-tab]');
    if(!button)return;
    TAB=button.dataset.tab;
    [...$('mixTabs').children].forEach(b=>b.classList.toggle('on',b===button));
    if(latest)renderTabBody(latest);
  });
  $('tabBody').addEventListener('click',event=>{
    const axisButton=event.target.closest('button[data-axis]');
    if(axisButton){
      AXIS=axisButton.dataset.axis;
      if(latest)renderTabBody(latest);
      return;
    }
    // 거래처별현황 하위 탭 (2026-08-13) — 매출/접수/미수 TOP.
    const ctabButton=event.target.closest('button[data-ctab]');
    if(!ctabButton)return;
    CTAB=ctabButton.dataset.ctab;
    if(latest)renderTabBody(latest);
  });
}

// 아래 표는 두 갈래다 — 매출 내역 / 미수 내역.
// 미수 내역은 **발송 기준**이다 (2026-08-13 사용자 확정: "감정서 발송되면
// 미수"). 종전에는 당기 매출 전표가 있는 건만 걸러서, 발송했는데 전표도
// 입금도 없는 건이 아예 안 보였다. 이제 서버가 발송일 기준으로 따로 준다
// (data.receivable_rows — 당기 발송분 중 지금 잔액이 남은 건).
let detailTab='sales';

function renderTable(data){
  const recv=detailTab==='receivable';
  const rows=recv?[...(data.receivable_rows||[])]:[...(data.recent||[])];
  const amountOf=r=>recv?(r.outstanding||0):r.amount;
  if(tableSort==='amount')rows.sort((a,b)=>amountOf(b)-amountOf(a));
  const sum=rows.reduce((s,r)=>s+amountOf(r),0);
  // 표는 위 차트의 증빙이라 **잘렸으면 잘렸다고 말해야** 한다. 전체 보기는
  // 본사 한 해만 수천 건이라 서버 상한(800)에 걸린다 — 안 알리면 '표 합계가
  // 히어로 금액과 다르다' 를 고장으로 신고하게 된다.
  const truncated=recv?data.receivable_rows_truncated:data.recent_truncated;
  const totalAll=recv?(data.receivable_rows_total||0):(data.recent_total||0);
  const cut=truncated
    ?` <span class="muted">(당기 ${money.format(totalAll)}건 중 `
      +`최근 ${money.format(Math.min(totalAll,800))}건만 봅니다`
      +`${recv?' — 위 미수 TOP 합계가 전건 기준입니다':''})</span>`:'';
  $('tableCount').innerHTML=`${recv?'당기 발송분 미수':'당기'} ${money.format(rows.length)}건`
    +` · <b class="hint-total">${escapeHtml(eok(sum))}</b>${cut}`;
  if(!rows.length){
    $('detailTable').innerHTML='<tr><td class="empty">'
      +(recv?'이 기간 발송 건 중 미수가 없습니다.':'이 기간에 내역이 없습니다.')
      +'</td></tr>';
    $('tableMore').classList.add('hidden');
    return;
  }
  const shown=rows.slice(0,tableShown);
  const dot=(map,name)=>`<i class="dot" style="background:${colorOf(map,(name||'').trim())}"></i>`;
  // 청구액은 미수금현황과 같은 기준액 max(전표 청구, 발송건 산정액)이다.
  const billedCell=r=>(r.billed||0)>0
    ?`<td class="number dim">${money.format(r.billed)}</td>`
    :'<td class="number dim">-</td>';
  $('detailTable').innerHTML=
    `<thead><tr><th>${recv?'발송일':'매출일'}</th><th>감정서번호</th><th>거래처</th><th>업무종류</th>`
    +'<th>물건종류</th><th>소재지</th>'
    // 미수 내역은 **미수금현황과 같은 값**을 쓴다. 부가세 표기는 하지 않는다:
    // 미수금현황도 안 쓰고, 굳이 적으면 이 화면만 특별해 보인다.
    +(recv?'<th class="number">청구액</th><th class="number">미수액</th>'
          :'<th class="number">금액</th>')
    +'</tr></thead><tbody>'
    +shown.map(r=>`<tr>
      <td>${escapeHtml((r.date||'').slice(2))}</td>
      <td>${escapeHtml(r.doc_id)}</td>
      <td class="cust" title="${escapeHtml(r.customer_name||'')}">${escapeHtml(r.customer_norm||r.customer_name||'-')}</td>
      <td>${dot(WORK_COLORS,r.work_type)}${escapeHtml(r.work_type||'-')}</td>
      <td>${dot(PROP_COLORS,r.category)}${escapeHtml(r.category||'-')}</td>
      <td class="addr" title="${escapeHtml(r.address||'')}">${escapeHtml(r.address||'-')}</td>
      ${recv?billedCell(r):''}
      <td class="number">${money.format(amountOf(r))}</td></tr>`).join('')+'</tbody>';
  const remain=rows.length-shown.length;
  $('tableMore').classList.toggle('hidden',remain<=0);
  if(remain>0)$('tableMore').textContent=`더 보기 (남은 ${money.format(remain)}건)`;
}

// ── 조립 ────────────────────────────────────────────────────────────────
function render(data){
  latest=data;
  resetAnalysis();
  const viewer=data.viewer||{};
  // 서버가 정한 모드를 믿는다 — 셀렉트 값이 아니라. 권한이 없으면 서버가
  // 조용히 본인으로 강등하는데, 화면만 '회사 전체' 라고 떠 있으면 개인 숫자를
  // 회사 숫자로 읽게 된다.
  const whole=!!data.is_all;
  const who=whole?`${officeLabel()} 전체`:`${data.emp_name} 평가사`;
  // 인쇄 머리글 — 종이에는 누가·언제 조회분인지가 박혀 있어야 한다.
  $('printHeader').innerHTML=`${escapeHtml(who)} 매출실적 `
    +`<small>· ${escapeHtml(data.period.from)} ~ ${escapeHtml(data.period.to)}`
    +` · 출력 ${new Date().toISOString().slice(0,10)}</small>`;
  $('empTitle').textContent=`${who}${(!whole&&viewer.is_self)?' (본인)':''}`;
  $('empSub').textContent=`${data.period.from} ~ ${data.period.to} · 전년 동기 ${data.prev_period.from} ~ ${data.prev_period.to}`;
  // 전체 모드에서는 셀렉트를 되돌리지 않는다 — 응답 emp_name 이 null 이라
  // 그대로 두면 대상이 개인으로 튄다.
  if(!whole&&$('empName').value!==data.emp_name
     &&[...$('empName').options].some(o=>o.value===data.emp_name)){
    $('empName').value=data.emp_name;
  }
  // 상여·가변비는 사람 단위 계산이라 전체를 줄 수 없다(서버가 400 으로 막는다).
  // 탭을 감추고, TAB 이 거기 있었으면 되돌린다.
  applyScopeChrome(whole);
  LATE={bonus:null,variable:null};   // 사람·기간이 바뀌었다 — 다시 받는다
  renderHero(data);renderMonthly(data);renderYearly();
  renderTabBody(data);renderTable(data);
  // 상여·가변비를 **미리 받아 둔다** (2026-08-16 요청 — "바로 조회").
  // 둘 다 사람·달마다 원장 프로시저를 도는 일이라 실측 10~11초다. 탭을 누른
  // 뒤에 부르면 그 10초를 사람이 통째로 기다린다 — 위 카드·차트를 보는 사이
  // 백그라운드로 받아 두면 탭은 즉시 뜬다. 조회 자체는 이미 끝나 화면이 다
  // 그려진 뒤라 첫 그림을 늦추지 않는다(fetch 는 비동기다).
  // 서버도 같은 (사람·기간)을 캐시하므로 되돌아올 때는 아예 안 돈다.
  // 전체 보기는 사람 단위 계산을 서버가 막는다 — loadLate 가 스스로 걸러낸다.
  loadLate('variable');loadLate('bonus');
}

// 지사 셀렉트에 적힌 이름 그대로 — '본사'·'경인'·'전 지사'.
function officeLabel(){
  const sel=$('officeCode');
  const opt=sel&&sel.selectedOptions&&sel.selectedOptions[0];
  const text=(opt&&opt.textContent||'').trim();
  return text&&text!=='전체'?text:'전 지사';
}

// 전체 모드에서 숨길 것들. 상여·가변비 탭과 AI 분석은 사람 단위 기능이다.
const PERSON_ONLY_TABS=['bonus','variable'];
function applyScopeChrome(whole){
  PERSON_ONLY_TABS.forEach(k=>{
    const button=document.querySelector(`#mixTabs button[data-tab="${k}"]`);
    if(button)button.classList.toggle('hidden',whole);
  });
  // 버튼만 감추면 #tab=bonus 해시로 곧장 들어오는 길이 남는다.
  if(whole&&PERSON_ONLY_TABS.includes(TAB)){
    TAB='sales';
    [...$('mixTabs').children].forEach(b=>b.classList.toggle('on',b.dataset.tab===TAB));
  }
  // AI 사실표·프롬프트가 '평가사 한 명' 을 전제로 쓰여 있다 (서버도 400 으로 막는다).
  $('aiPanel').classList.toggle('hidden',whole);
}

async function loadAppraisers(){
  const select=$('empName'),keep=select.value||HASH_EMP;
  select.innerHTML='<option value="">불러오는 중…</option>';
  const response=await fetch(`/api/my-sales/appraisers?${query()}`);
  const payload=await response.json();
  if(!payload.success){select.innerHTML='<option value="">불러오기 실패</option>';return;}
  const names=payload.data.names;
  const others=payload.data.can_view_others;
  // '회사 전체' 는 사람 목록(names) 안에 문자열로 끼워 넣지 않는다 — names 는
  // 이름 목록이고 서버의 이름 비교도 화면의 선택 복원도 전부 그 전제를 쓴다.
  // 지사 셀렉트의 '전체'(전 지사)와 글자가 겹치지 않게 '회사 전체' 로 적는다.
  const head=others&&payload.data.supports_all
    ?`<option value="${ALL_SCOPE}">회사 전체</option>`:'';
  select.innerHTML=head+(names.length
    ?names.map(n=>`<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('')
    :(head?'':'<option value="">실적자 없음</option>'));
  // 복원 조건에 전체를 넣어야 한다 — 안 넣으면 지사·연도를 바꿀 때마다
  // 목록을 다시 그리면서 **전체 선택이 조용히 풀려** 첫 사람으로 되돌아간다.
  if(keep&&(keep===ALL_SCOPE||names.includes(keep)))select.value=keep;
  select.disabled=!others;
  select.closest('label').classList.toggle('locked',!others);
}

// 요청 세대. 대상·기간을 바꾸면 올라가고, 늦게 온 옛 응답은 스스로 물러난다.
// 이게 없으면 A 를 고르고 곧바로 B 를 골랐을 때 A 의 늦은 응답이 B 화면을 덮는다.
let GEN=0;
async function loadDashboard(force){
  const gen=++GEN;
  $('searchButton').disabled=true;$('searchButton').textContent='조회 중…';
  // 재조회 동안 이전 화면을 흐리게 유지 — 스켈레톤 깜빡임·레이아웃 점프 금지.
  $('main-content').classList.add('loading');
  try{
    const response=await fetch(`/api/my-sales/dashboard?${query(target(force))}`);
    const payload=await response.json();
    if(gen!==GEN)return;                 // 그 사이 대상이 바뀌었다
    if(!payload.success){alert(payload.message||'조회에 실패했습니다.');return;}
    tableShown=50;
    render(payload.data);
  }finally{
    $('searchButton').disabled=false;$('searchButton').textContent='조회';
    $('main-content').classList.remove('loading');
  }
}

async function loadYearly(force){
  yearly=null;
  renderYearly();
  const params=query(target(force));
  params.set('end_year',String(new Date($('dateTo').value||Date.now()).getFullYear()));
  params.delete('date_from');params.delete('date_to');
  const gen=GEN;
  try{
    const payload=await(await fetch(`/api/my-sales/yearly?${params}`)).json();
    if(gen!==GEN)return;                 // 늦게 온 옛 응답은 물러난다
    yearly=payload.success?payload.data.years:false;
  }catch(err){
    if(gen!==GEN)return;
    yearly=false;
  }
  renderYearly();
}

// 첫 조회에는 목록과 대시보드가 **서로를 안 기다린다** (2026-08-11).
// 종전에는 목록(1.3초)이 끝나야 대시보드(2.1초)를 시작해 3.4초가 직렬로 쌓였다.
// 목록은 '누구를 고를 수 있나' 이고 첫 화면의 대상은 '회사 전체' 로 정해져 있으니
// 기다릴 이유가 없다. 권한이 없는 사람에게는 서버가 본인으로 강등하는데, 그 사람의
// 목록에는 어차피 본인 이름 하나뿐이라 둘이 같은 답으로 만난다.
let firstLoad=true;
async function loadAll(){
  const first=firstLoad; firstLoad=false;
  const force=(first&&!HASH_EMP)?'office':undefined;
  const before=$('empName').value;
  // 셋 다 나란히 던진다. 연도별(우측 5년 막대)이 마지막까지 대시보드 뒤에
  // 줄 서 있었는데, 그 둘은 서로의 결과를 안 쓴다 — 개인 기준 1.9초가 통째로
  // 대시보드 그늘에 들어간다.
  await Promise.all([loadAppraisers(), loadDashboard(force), loadYearly(force)]);
  // 목록을 다시 그리다가 대상이 바뀌는 경우가 있다 — 고른 사람이 새 지사·연도에
  // 실적이 없으면 첫 항목으로 떨어진다. 그때만 한 번 더 부른다(첫 조회는 제외:
  // 빈 값에서 '회사 전체'로 바뀌는 건 정상이고 이미 그걸로 받았다).
  if(!first && $('empName').value!==before){
    await Promise.all([loadDashboard(), loadYearly()]);
  }
}

// 기간은 **연도 하나**로 움직인다 (2026-08-10 요청). 달력으로 월·일까지 고르게
// 하니 실제로는 늘 한 해를 보는데 손이 두 번 갔다.
// 올해를 고르면 끝은 **오늘**이다 — 12-31 로 두면 아직 오지 않은 달이 0으로
// 그려져 추이가 뚝 떨어진 것처럼 보인다.
const YEARS_BACK=5;

function applyYear(year){
  const today=new Date();
  const last=(year===today.getFullYear())
    ?today
    :new Date(year,11,31);
  const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`
    +`-${String(d.getDate()).padStart(2,'0')}`;
  $('dateFrom').value=`${year}-01-01`;
  $('dateTo').value=iso(last);
}

function initDates(){
  const thisYear=new Date().getFullYear();
  const select=$('yearPick');
  select.innerHTML='';
  for(let y=thisYear;y>thisYear-YEARS_BACK;y--){
    const option=document.createElement('option');
    option.value=String(y);
    option.textContent=`${y}년`;
    select.appendChild(option);
  }
  select.value=String(thisYear);
  applyYear(thisYear);
}

function onPersonChange(){
  loadDashboard();
  loadYearly();
}

// ── AI 분석 — 누를 때만 돈다. 응답은 textContent 로만 붓는다(모델 출력도
// 신뢰하지 않는 데이터다). 사람·기간을 바꾸면 이전 분석은 접는다.
// 같은 조회를 접었다 다시 열 때는 저장해 둔 결과를 그대로 보여 준다 —
// 5초를 또 기다리게 하지 않고, Gemini 호출도 아낀다.
let aiCache=null; // {key, text}
const aiKey=()=>`${window.A10_OFFICE()}|${$('empName').value}|${$('dateFrom').value}|${$('dateTo').value}`;

async function loadAnalysis(){
  const button=$('aiButton'),panel=$('aiResult');
  if(aiCache&&aiCache.key===aiKey()&&panel.classList.contains('hidden')){
    paintAnalysis(panel,aiCache.text);
    panel.classList.remove('hidden');
    $('aiActions').classList.remove('hidden');
    button.textContent='✨ 다시 분석';
    return;
  }
  button.disabled=true;button.textContent='분석 중…';
  panel.classList.remove('hidden');
  $('aiActions').classList.add('hidden');
  panel.textContent='숫자를 읽고 있습니다…';
  try{
    const name=$('empName').value;
    const response=await fetch(`/api/my-sales/analyze?${query(target())}`);
    const payload=await response.json();
    if(payload.success){
      paintAnalysis(panel,payload.data.text);
      aiCache={key:aiKey(),text:payload.data.text};
      $('aiActions').classList.remove('hidden');
    }else{
      panel.textContent=payload.message||'AI 분석을 사용할 수 없습니다.';
    }
  }catch(err){
    panel.textContent='AI 분석이 잠시 응답하지 않습니다. 다시 시도해 주세요.';
  }finally{
    button.disabled=false;button.textContent='✨ 다시 분석';
  }
}
// 모델 글을 '제목|내용' 으로 받아 구획으로 그린다 (2026-08-11 요청 — 보기 편하게).
// **여전히 textContent 로만 붓는다.** 모델 출력은 신뢰하지 않는 데이터라
// 통째로 HTML 로 넣으면 그대로 XSS 통로가 된다 — 껍데기는 우리가 만들고
// 글자만 넣는다(createElement + textContent).
// 세로줄이 없는 줄(모델이 형식을 어겼을 때)은 제목 없이 그대로 한 줄로 둔다.
function paintAnalysis(panel,text){
  panel.textContent='';
  String(text||'').split(/\r?\n/).forEach(raw=>{
    const line=raw.replace(/^\s*[·*\-•]+\s*/,'').trim();
    if(!line)return;
    const cut=line.indexOf('|');
    let head=cut>0?line.slice(0,cut).trim():'';
    let body=cut>0?line.slice(cut+1).trim():line;
    // 제목이 너무 길면 제목으로 안 쓰되 **글자를 버리지는 않는다** — 종전에는
    // 그 줄의 앞부분이 통째로 사라졌다. 알약이 두 줄로 접히는 것보다 낫다.
    if(head.length>8){ body=`${head} ${body}`; head=''; }
    const row=document.createElement('div');
    row.className='ai-row';
    if(head){
      const h=document.createElement('span');
      h.className='ai-key'; h.textContent=head;
      row.appendChild(h);
    }
    const b=document.createElement('span');
    b.className='ai-txt'; b.textContent=body;
    row.appendChild(b);
    panel.appendChild(row);
  });
}

function resetAnalysis(){
  aiCache=null;
  $('aiResult').classList.add('hidden');
  $('aiResult').textContent='';
  $('aiActions').classList.add('hidden');
  $('aiButton').textContent='✨ AI 분석';
}
$('aiButton').addEventListener('click',loadAnalysis);
$('aiFold').addEventListener('click',()=>{
  $('aiResult').classList.add('hidden');
  $('aiActions').classList.add('hidden');
  $('aiButton').textContent='✨ 분석 다시 보기';
});
$('aiCopy').addEventListener('click',()=>{
  // 화면은 줄마다 div 라 textContent 로 긁으면 줄바꿈 없이 다 붙는다.
  // 모델이 준 원문을 따로 쥐고 그걸 복사한다.
  const text=(aiCache&&aiCache.text)||$('aiResult').textContent;
  const done=()=>{
    const b=$('aiCopy');b.textContent='✓ 복사됐습니다';
    setTimeout(()=>{b.textContent='📋 내용 복사';},1600);
  };
  // 운영은 http 라 navigator.clipboard 가 없다(보안 컨텍스트 아님) — 구식
  // 경로(textarea + execCommand)로 물러선다. 어느 쪽이든 눌렀으면 답을 준다.
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(()=>{legacyCopy(text);done();});
  }else{
    legacyCopy(text);done();
  }
});
function legacyCopy(text){
  const area=document.createElement('textarea');
  area.value=text;area.style.position='fixed';area.style.opacity='0';
  document.body.appendChild(area);area.select();
  try{document.execCommand('copy');}catch(_e){/* 최후엔 수동 복사뿐 */}
  document.body.removeChild(area);
}

// 인쇄할 때는 표를 전건으로 펼친다 — '더 보기' 뒤에 숨은 행이 종이에서
// 잘리면 반출 자료로 못 쓴다. 인쇄가 끝나면 원래대로 되돌린다.
let printRestore=null;
// 인쇄할 때만 전건을 펼친다. 다만 상한을 둔다 — 개인은 한 해 수백 건이라
// 그냥 펼쳐도 됐지만, 회사 전체는 본사만 수천 건이라 통째로 DOM 에 부으면
// 브라우저가 멈춘다. 서버 상한(800)과 같은 자리에서 끊는다.
const PRINT_MAX=800;
window.addEventListener('beforeprint',()=>{
  if(!latest)return;
  printRestore=tableShown;
  // 미수 내역은 이제 별도 배열(receivable_rows, 발송 기준)이라 recent 보다
  // 길 수 있다 — recent 길이만 보면 인쇄가 중간에서 소리 없이 끊긴다
  // (2026-08-14 검수: 실측 82명 중 4명이 미수 내역이 매출 내역보다 길었다).
  const rows=detailTab==='receivable'?(latest.receivable_rows||[]):(latest.recent||[]);
  tableShown=Math.min(rows.length,PRINT_MAX);
  renderTable(latest);
});
window.addEventListener('afterprint',()=>{
  if(printRestore===null||!latest)return;
  tableShown=printRestore;printRestore=null;
  renderTable(latest);
});

$('searchButton').addEventListener('click',loadAll);
$('officeCode').addEventListener('change',loadAll);
$('yearPick').addEventListener('change',event=>{
  applyYear(Number(event.target.value));
  loadAll();
});
$('empName').addEventListener('change',onPersonChange);
$('tableSort').addEventListener('click',event=>{
  const tab=event.target.closest('.tab');
  if(!tab)return;
  tableSort=tab.dataset.sort;
  $('tableSort').querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t===tab));
  if(latest)renderTable(latest);
});
$('detailTabs').addEventListener('click',event=>{
  const button=event.target.closest('button[data-dtab]');
  if(!button)return;
  detailTab=button.dataset.dtab;
  [...$('detailTabs').children].forEach(b=>b.classList.toggle('on',b===button));
  tableShown=50;                       // 갈래를 바꾸면 처음부터 본다
  if(latest)renderTable(latest);
});
$('tableMore').addEventListener('click',()=>{
  tableShown+=100;
  if(latest)renderTable(latest);
});
// 스크린샷·북마크용 — #tab=clients 처럼 열면 그 탭으로 시작한다.
// (미수 탭은 2026-08-13 에 거래처별현황 하위로 들어갔다 — receivable 해시는
// 거래처별현황의 미수 TOP 으로 보낸다. 옛 북마크가 죽지 않게.)
const hashTab=(location.hash.match(/tab=([a-z]+)/)||[])[1];
if(hashTab&&['sales','clients','bonus','variable'].includes(hashTab)){
  TAB=hashTab;
}else if(hashTab==='receivable'){
  TAB='clients';CTAB='recv';
}
const hashAxis=(location.hash.match(/axis=([a-z]+)/)||[])[1];
if(hashAxis&&['category','work'].includes(hashAxis))AXIS=hashAxis;
// #emp=안창덕 처럼 열면 그 사람으로 시작한다 (스크린샷·북마크용).
// 값을 고를 뿐이라 권한과 무관하다 — 서버가 여전히 _resolve_scope 로 가른다.
bindTabs();
[...document.getElementById('mixTabs').children].forEach(
  b=>b.classList.toggle('on',b.dataset.tab===TAB));
initDates();
window.A10_READY.then(()=>loadAll());
