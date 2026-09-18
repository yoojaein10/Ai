// 감정서 조회 — 통장 입금 대사 화면 (2026-08-05 개편).
// 기간(ACCT_TXDAY)으로 입금 목록을 띄우고, 검색칸에 거래처 이름을 넣으면
// 적요에 그 말이 든 것만 좁혀 본다. 줄을 누르면 그 줄의 감정서를 찾아
// 목록 표 아래에 따로 표로 편다.
// 조회 범위(본·지사)는 서버가 usr_seq 로 소속을 직접 풀어 강제한다 — 화면은 식별자만 보낸다.
// 렌더러는 자체 구현(내부망 CDN 불가 · 감정서 상세 카드에 쓴다).
const $=id=>document.getElementById(id);
const escapeHtml=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const USR=()=>window.A10_USR||'';
// 본·지사 칸은 뺐다 — 통장 한 계좌에 전 지사 수수료가 섞여 들어와 조회를
// 지사로 나눌 수 없고, 서버도 이 값으로 좁히지 않는다(문지기는 전체조회 권한).
// 서버가 usr_seq 로 소속을 다시 푸므로 빈 값을 보내도 판정은 그대로다.
const OFFICE=()=>'';
let busy=false;

// 굵게·코드만 인라인으로 살린다 (escape 뒤에 적용해 주입을 막는다).
function inline(text){
  return escapeHtml(text)
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/`([^`]+)`/g,'<code>$1</code>');
}

// 감정서번호는 눌러서 상세를 볼 수 있게 한다.
const DOC_RE=/\b(\d{2}-\d{4}-[0-9A-Z]-\d{4}(?:-\d+)?)\b/g;
function linkDocs(html){
  return html.replace(DOC_RE,'<span class="doc-link" data-doc="$1">$1</span>');
}

// 상태 값은 색 알약으로 — '완납·미수·선수금'이 결론이라 눈에 먼저 들어와야 한다.
function pillify(key,value){
  if(!/상태/.test(key))return inline(value);
  const parts=value.split(' · ');
  const first=parts.shift()||'';
  const cls=/완납/.test(first)?'green':/과입/.test(first)?'amber'
    :/선수금/.test(first)?'violet':/미수|부분|미입금/.test(first)?'red':'gray';
  return `<span class="pill ${cls}">${inline(first)}</span>`
    +(parts.length?' · '+inline(parts.join(' · ')):'');
}

const KV_RE=/^\*\*([^*]+)\*\*\s*[:：]\s*(.*)$/;

// ── 표 정렬 — 셀마다 따로 재지 않고 **열 단위**로 정한다 ────────────────────
// 셀 단위로 재면 같은 열에서 정렬이 갈린다: 평가액 열의 '1,000,000,000원'은
// 오른쪽인데 값이 없는 '-'는 가운데로 튀고, '약 399조 1,939억원'·'108,638 ▇▇▇'
// 처럼 한글 단위나 막대가 붙은 금액은 통째로 왼쪽에 붙어 자릿수가 어긋났다.
// 정렬 규칙은 기존 MOA 화면 관례를 그대로 따른다 (dashboard.css:126-127):
// 숫자 데이터 셀은 오른쪽+tabular-nums, 표 머리는 가운데, 날짜·텍스트는 왼쪽.
const BAR_CHARS=/[▇▆▅▄▃▂▁]/;
// 날짜는 숫자 판정보다 **먼저** 본다. 원문 표기가 제각각이라 넓게 받는다:
// 2025-07-28 · 2025-05 · 2024.05.10.(끝점) · 2024. 5. 10. · 2024/5/1
const DATE_CELL_RE=/^\d{4}\s*[-./]\s*\d{1,2}(\s*[-./]\s*\d{1,2})?\.?$/;
// 값이 없는 칸. 벤더가 '-개월'처럼 결측에 단위를 붙여 내보내는 자리가 있어 같이 받는다.
const EMPTY_CELL_RE=/^-\s*[가-힣%㎡]{0,3}$/;
// '수량으로 읽히는가' — 부호+숫자로 시작하고, 남는 건 단위·구분자뿐이면 숫자다.
// 감정서번호(01-2507-6-0389)·기간(2019-03-11~2025-07-28)은 중간의 '-'·'~' 때문에
// 걸리지 않는다 — 식별자·범위는 텍스트로 남아야 한다.
const NUM_BODY_RE=/^[-+]?\d[\d,.\s]*(?:(?:조|억|천만|백만|만|천|원|건|개월|개|명|배|%|㎡|평|일|회|위|점|초|분|시간|\/)[\d,.\s]*)*$/;
const WIDE_CHAR=/[ᄀ-ᇿ㄰-㆏가-힯一-鿿]/;
const cellWidth=s=>[...String(s)].reduce((n,c)=>n+(WIDE_CHAR.test(c)?2:1),0);

// 값과 꼬리를 가른다 — 막대 게이지('108,638 ▇▇▇')와 괄호 주석('(기재 72,854)').
// 꼬리 길이가 행마다 달라, 통째로 오른쪽 정렬하면 정작 숫자가 어긋난다.
function splitCell(raw){
  const v=String(raw??'').trim();
  let m=v.match(/^(.*?)\s*([▇▆▅▄▃▂▁]+)$/);
  if(m&&m[1].trim())return {value:m[1].trim(),tail:m[2],tailCls:'bar'};
  m=v.match(/^(.*?)\s*(\([^()]*\))$/);
  // 값이 '-'(결측)여도 뒤의 괄호는 주석이다 — 붙여 두면 결측이 텍스트로 읽힌다.
  if(m&&(/\d/.test(m[1])||EMPTY_CELL_RE.test(m[1].trim())))
    return {value:m[1].trim(),tail:m[2],tailCls:'hint'};
  return {value:v,tail:'',tailCls:''};
}

function cellKind(value){
  const v=String(value??'').replace(/\*\*/g,'').trim();
  if(v===''||EMPTY_CELL_RE.test(v))return 'empty';
  if(DATE_CELL_RE.test(v))return 'date';
  return NUM_BODY_RE.test(v.replace(/^약\s*/,'').trim())?'num':'text';
}

// 열별 계획: 타입(num/date/text) · 꼬리 분리 여부 · 숫자부 폭(ch).
// 빈 값은 표결에서 뺀다 — '-' 몇 개 때문에 금액 열이 텍스트로 판정되면 안 된다.
function columnPlan(head,body){
  return head.map((_,i)=>{
    let num=0,date=0,text=0,tail=0,width=0;
    body.forEach(row=>{
      const part=splitCell(row[i]??'');
      const kind=cellKind(part.value);
      if(part.tail)tail++;
      if(kind==='empty')return;
      if(kind==='num'){num++;width=Math.max(width,cellWidth(part.value.replace(/\*\*/g,'')));}
      else if(kind==='date')date++;
      else text++;
    });
    // 최다 득표. 동수면 숫자가 이긴다 — 표기가 섞인 열(예: '5,053,000' 과
    // '5,053,000원/㎡')에서 소수의 별난 칸 때문에 금액 전체가 왼쪽으로 눕는 게
    // 더 나쁘다. 날짜는 숫자보다 구체적이라 동수일 때 앞선다.
    let type='text';
    if(num&&num>=text&&num>=date)type='num';
    else if(date&&date>=text)type='date';
    // 첫 열은 집계 축 라벨이다 — group_by 에 따라 '2025'(연도)·'2025-07'(연월)·
    // '경기도 화성시'가 같은 자리에 오는데, 질문 종류에 따라 한 열의 정렬이
    // 뒤집히면 안 된다. 목록표의 감정서번호 열도 같은 이유로 왼쪽이 맞다.
    if(i===0)type='text';
    return {type,split:type==='num'&&tail>0,width:width||6};
  });
}

function renderCell(raw,plan){
  const part=splitCell(raw);
  const empty=cellKind(part.value)==='empty';
  const classes=[];
  if(plan.split)classes.push('numsplit');
  else if(plan.type==='num')classes.push('num');
  else if(plan.type==='date')classes.push('date');
  if(empty)classes.push('dim');
  const attr=classes.length?` class="${classes.join(' ')}"`:'';
  if(!plan.split)return `<td${attr}>${inline(String(raw??''))}</td>`;
  // 숫자부를 같은 폭 안에서 오른쪽으로 밀어 자릿수를 맞추고, 꼬리는 그 뒤에 붙인다.
  return `<td${attr}><span class="v" style="min-width:${plan.width}ch">${inline(part.value)}</span>`
    +(part.tail?`<span class="${part.tailCls}">${inline(part.tail)}</span>`:'')+'</td>';
}

function renderMarkdown(md){
  const out=[];
  const lines=String(md||'').split('\n');
  let i=0;
  while(i<lines.length){
    const line=lines[i];
    // 표: | a | b | 다음 줄이 |---|---|
    if(/^\s*\|/.test(line)&&i+1<lines.length&&/^\s*\|[\s:|-]+\|\s*$/.test(lines[i+1])){
      const cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
      const head=cells(line);
      i+=2;
      const body=[];
      while(i<lines.length&&/^\s*\|/.test(lines[i])){body.push(cells(lines[i]));i++;}
      // 2열 '구분|금액' 표는 키-값 행으로 (감정서 돈 이력 카드)
      if(head.length===2&&/구분/.test(head[0])){
        out.push(body.map(r=>`<div class="kv"><span>${inline(r[0]||'')}</span><b>${pillify(r[0]||'',r[1]||'')}</b></div>`).join(''));
        continue;
      }
      // 열 계획을 표에 실어 둔다 — '더보기'로 이어 붙는 행도 같은 정렬을 써야 한다.
      const plan=columnPlan(head,body);
      out.push('<div class="tbl"><button type="button" class="tbl-copy" title="표를 복사해 엑셀에 붙여넣기">복사</button>'
        +`<table data-plan='${JSON.stringify(plan)}'><thead><tr>`
        // 머리는 그 열의 내용과 같은 쪽으로 붙인다 — 가운데로 두면 숫자 열에서
        // 머리와 값이 서로 다른 자리에 놓여 눈이 따라가지 못한다 (2026-08-05 지적).
        +head.map((h,i)=>{
          const p=plan[i]||{type:'text'};
          const cls=(p.type==='num'&&!p.split)?' class="num"':(p.split?' class="numsplit"':'');
          return `<th${cls} title="눌러서 정렬">${inline(h)}</th>`;
        }).join('')
        +'</tr></thead><tbody>'
        +body.map(r=>'<tr>'+r.map((c,i)=>renderCell(c,plan[i]||{type:'text',width:6})).join('')+'</tr>').join('')
        +'</tbody></table></div>');
      continue;
    }
    if(/^\s*>/.test(line)){
      const buf=[];
      while(i<lines.length&&/^\s*>/.test(lines[i])){buf.push(lines[i].replace(/^\s*>\s?/,''));i++;}
      out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
      continue;
    }
    if(/^\s*[-*]\s+/.test(line)){
      const buf=[];
      while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i])){buf.push(lines[i].replace(/^\s*[-*]\s+/,''));i++;}
      // 전부 '**키**: 값' 꼴이면 키-값 행으로 (감정서 상세 카드)
      if(buf.length&&buf.every(b=>KV_RE.test(b))){
        out.push(buf.map(b=>{
          const m=b.match(KV_RE);
          return `<div class="kv"><span>${inline(m[1])}</span><b>${pillify(m[1],m[2])}</b></div>`;
        }).join(''));
        continue;
      }
      out.push('<ul>'+buf.map(b=>`<li>${inline(b)}</li>`).join('')+'</ul>');
      continue;
    }
    const h=line.match(/^(#{1,4})\s+(.*)$/);
    if(h){out.push(`<p><strong>${inline(h[2])}</strong></p>`);i++;continue;}
    // '🔎 강남구 · 물건 근린생활 · 담보 목적' 조건 줄은 칩으로
    if(/^\s*🔎/.test(line)){
      const chips=line.replace(/^\s*🔎\s*/,'').split(' · ').filter(Boolean)
        .map(c=>`<span class="chip">${inline(c)}</span>`).join('');
      out.push(`<div class="cond-chips">${chips}</div>`);i++;continue;
    }
    if(line.trim()){out.push(`<p>${inline(line)}</p>`);}
    i++;
  }
  return linkDocs(out.join(''));
}

// '## 제목'으로 시작하는 답(감정서 상세·돈 이력)은 통째로 카드에 담는다.
function renderAnswer(md){
  const m=String(md||'').match(/^##\s+(.+)\r?\n/);
  if(m){
    const rest=md.slice(m[0].length);
    return `<div class="doc-card"><div class="doc-card-head">`
      +`<b>${linkDocs(inline(m[1]))}</b></div><div class="doc-card-body">`
      +`${renderMarkdown(rest)}</div></div>`;
  }
  return renderMarkdown(md);
}

// ── 화면 상태 ────────────────────────────────────────────────────────────
function setBusy(value){
  busy=value;
  $('searchButton').disabled=value;
  $('searchButton').textContent=value?'조회 중…':'조회';
}
function setTitle(text,count){
  $('listTitle').textContent=text;
  $('listCount').textContent=count||'';
}
function showBody(html){$('resultBody').innerHTML=html;markTruncated($('resultBody'));}

// 칸이 좁아 잘린 글자는 마우스를 올리면 보이게 한다 (2026-08-06 요청).
// 셀마다 title 을 미리 박지 않고 **실제로 넘친 것만** 재서 붙인다 — 안 잘린
// 칸에까지 툴팁이 뜨면 오히려 성가시다.
function markTruncated(root){
  if(!root)return;
  root.querySelectorAll('td, th').forEach(cell=>{
    if(cell.scrollWidth>cell.clientWidth+1){
      const text=cell.textContent.trim();
      if(text&&!cell.title)cell.title=text;
    }else if(cell.title&&cell.title===cell.textContent.trim()){
      cell.removeAttribute('title');
    }
  });
}
function showLoading(text){showBody(`<p class="loading">${escapeHtml(text)}</p>`);}
function showError(text){showBody(`<p class="err">${escapeHtml(text)}</p>`);}

const won=v=>(v===null||v===undefined||v==='')?'-':Number(v).toLocaleString();

// ── ① 기간 입금 목록 ─────────────────────────────────────────────────────
// 사이버브랜치 '거래내역조회'와 같은 칸(거래일자·시간·금융기관·취급점·적요·입금액)에,
// 재무팀이 손으로 채우던 **감정서번호·거래처·미수금·근거**를 덧붙인 표다.
// 통장이 가진 값만 보여준다. 우리가 찾아낸 것(감정서 후보·거래처·미수금·근거)은
// 줄을 눌렀을 때 아래에 따로 표로 편다 (2026-08-05 요청).
const DEPOSIT_HEAD=['거래일자','시간','입출금여부','금융기관','계좌','취급점',
                    '적요','거래금액','감정서번호'];

// 이미 채워진 Memo 와 우리가 찾은 번호를 맞대 본다 — 재무팀이 손으로 넣은 것 중
// 어긋난 건을 잡는 게 이 화면의 두 번째 쓸모다. Memo 에는 '부산지사'·'잡이익'처럼
// 감정서번호가 아닌 처리 표시도 들어가므로, 번호가 적힌 것만 견준다.
const MEMO_DOC=/\d{2}-\d{4}-[0-9A-Z]-\d{4}/;

// 통장 값을 그리고, **감정서번호 칸이 비어 있으면 우리가 찾아 채운다**
// (2026-08-08). 재무팀은 이 번호 하나를 사이버브랜치 프로그램에 옮겨 적는다 —
// 그게 이 화면의 전부다. 예전에는 줄을 눌러야 그때 찾았는데, 하루 22건을
// 옮겨 적는 일에 22번의 클릭과 대기가 붙었다.
// 찾을 필요 없는 줄(약식평가·자사이체·카드·예금이자…)은 kind 로 걸러 안 두드린다.
// 실측(2026-07): 미처리 80건인 날에도 실제 대상은 0~24건이고, 24건을 동시 12로
// 돌리면 14초다. 그래서 미리 계산해 저장할 것 없이 목록을 열 때 그 자리에서 한다.
function depositRow(r,i){
  // 안 두드리는 줄은 **왜 안 찾는지**를 그 자리에 적는다. 그냥 '-' 로 두면
  // 재무팀이 있지도 않은 감정서를 계속 뒤진다 — 2023+ 미부착 4,689건 중
  // 601건(12.8%)이 여기서 걸린다.
  const memo=r.memo?escapeHtml(r.memo):(needsFind(r)
    ?`<span class="finding" data-find="${i}">찾는 중…</span>`
    :`<span class="dim">${escapeHtml(r.kind||'-')}</span>`);
  const inout=(r.inout==='출금')?'<span class="pill gray">출금</span>':'입금';
  return `<tr data-row="${i}" title="눌러서 감정서 찾기">`
    +`<td class="date">${escapeHtml(r.txday)}</td>`
    +`<td class="date">${escapeHtml(r.txtime)}</td>`
    +`<td>${inout}</td>`
    +`<td>${escapeHtml(r.bank)}</td>`
    +`<td class="dim">${escapeHtml(r.acct)}</td>`
    +`<td>${escapeHtml(r.branch)}</td>`
    +`<td class="jeokyo" title="${escapeHtml(r.jeokyo)}">${escapeHtml(r.jeokyo)}</td>`
    +`<td class="num">${won(r.amount)}</td>`
    +`<td class="memo" title="${escapeHtml(r.memo||'')}">${memo}</td>`
    +'</tr>';
}

// 눌린 줄 **바로 아래**에 후보 표를 편다. 한 줄 안에 우겨넣지 않는 이유는,
// 후보가 여럿일 때 고르는 건 사람의 몫이고 그러려면 접수일·의뢰처·금액을
// 나란히 놓고 봐야 하기 때문이다 (2026-08-05 사용자 요청).
// 회계팀이 실제로 쓰는 칸 구성 (2026-08-06 요청): 미수금·범위를 빼고
// 후보는 **표가 아니라 카드**로 쌓는다 (2026-08-06 판단).
// 실측(2개월·200건, 약식 제외): 후보 0건 20.5% · 1건 68.5% · 2건 이상 11.0%.
// 표가 표인 까닭은 줄끼리 견주기 위해서인데 견줄 일이 11%뿐이다. 89%는 칸만
// 11개 늘어선 한 줄짜리 표였고, 그 좁은 폭 때문에 정작 중요한 근거 상세
// (money_note 중앙값 34자·최대 57자)와 의뢰인·제출처가 늘 잘렸다.
// 감정서 LIST 상세도 같은 문제를 카드로 풀었다 (dashboard.html #detailContent).
const CAND_FIELDS=[
  ['의뢰인','cust_name'],['제출처','submit_to'],['채무자','debtor'],
  ['담당자','cust_charge'],['접수일','recv_date'],
];

// 회계 문장은 **줄이지 않고 그대로** 보여준다. 표 칸에 밀어 넣던 시절에는
// 줄여야 했지만(MONEY_SHORT), 카드는 세로로 자리가 있어 원문이 더 낫다.
function whyLines(c){
  const out=[];
  String(c.money_note||'').split(' · ').forEach(seg=>{
    seg=seg.trim();
    if(seg&&!out.includes(seg))out.push(seg);
  });
  if(c.voucher&&!out.some(t=>t.includes('전표')))out.push('전표 있음');
  return out;
}

// 근거 원장 — apw_masterex 면 '통합 데이터', 감정서 DB 면 원문 어디인지까지.
function whereText(c){
  return c.source==='원문'
    ? '감정서 원문'+(c.section?' · '+c.section:'')
    : '통합 데이터';
}

function evBadge(c){
  // '확신' 배지는 뺐다 (2026-08-06 요청) — 근거 조각(금액·이름·회계)이 바로
  // 옆에 나열되므로 같은 말을 두 번 하는 셈이었다. 경고만 남긴다:
  // 근거 하나짜리는 실측 정밀도가 낮다 (2개 이상 98% · 금액 단독 44% ·
  // 이름 단독 0%). 확인이 필요한 자리라 표시가 있어야 한다.
  const ev=c.evidence||[];
  return (ev.includes('번호')||ev.length>=2) ? ''
    : '<span class="pill amber" title="근거가 하나뿐입니다 — 확인 필요">단일 근거</span>';
}

function candCard(c,memo,open){
  const written=(memo||'').match(MEMO_DOC);
  const mark=(written&&written[0]===c.doc_id)
    ? ' <span class="pill green">메모와 같음</span>' : '';
  const office=c.doc_id.slice(0,2)==='01'
    ? '<span class="dim">본사</span>'
    : `<span class="office-copy" title="눌러서 지사명 복사">${escapeHtml(c.office||'지사')}</span>`;
  const ev=(c.evidence||[]).map(t=>`<span class="ev">${escapeHtml(t)}</span>`).join('');
  const fields=CAND_FIELDS.map(([label,key])=>{
    const v=escapeHtml(c[key]||'');
    return `<div><dt>${label}</dt><dd${v?` title="${v}"`:''}>${v||'<span class="dim">-</span>'}</dd></div>`;
  }).join('')
    +`<div><dt>매출총액</dt><dd class="amt">${won(c.billed)}원</dd></div>`;
  const lines=whyLines(c).map(t=>`<li>${escapeHtml(t)}</li>`).join('');
  // 겹쳐 걸린 축은 그 자체가 가장 강한 근거다 — 접힌 채로 묻히면 안 된다.
  const also=(c.also||[]).map(t=>`<li>${escapeHtml(t)}</li>`).join('');
  return `<details class="cand-card"${open?' open':''}>`
    +'<summary>'
    +`<span class="doc-link" data-doc="${escapeHtml(c.doc_id)}" title="눌러서 번호 복사">${escapeHtml(c.doc_id)}</span>`
    +mark+evBadge(c)
    +`<span class="sum-tail">${office}${ev?` · ${ev}`:''}</span>`
    +'</summary>'
    +`<dl class="cand-fields">${fields}</dl>`
    +'<div class="cand-why">'
    +`<p class="why-head"><b>${escapeHtml(c.word||'')}</b>`
    +`<span class="where">${escapeHtml(whereText(c))}`
    +`${c.field_label?' · '+escapeHtml(c.field_label):''}</span></p>`
    +((lines||also)?`<ul class="why-list">${lines}${also}</ul>`:'')
    +'</div></details>';
}

// 못 찾았을 때 '안 찾은 건지 없는 건지'를 가려 준다.
function stageLine(data){
  const tried=(data.stages||[]).map(s=>
    `${escapeHtml(s.source)} ${s.months}개월 ${s.hits}건`).join(' · ');
  const words=(data.tokens||[]).map(t=>`<span class="chip">${escapeHtml(t)}</span>`).join('');
  return (words?`<div class="cond-chips">${words}</div>`:'')
    +(tried?`<p class="stages">${tried}</p>`:'');
}

function candTable(r,data){
  if(data.kind){
    // '약식평가' → '약식' 처럼 짧게, 설명 없이 배지만 (2026-08-06 요청).
    const short=data.kind.replace('약식평가','약식').replace('지사 실적회비','실적회비');
    const head=`<p class="empty"><span class="kind-big">${escapeHtml(short)}</span></p>`;
    // 약식에는 감정서번호가 없다. 재무팀이 필요한 것도 번호가 아니라
    // **본/지사와 영업점명**뿐이라 그 둘만 보여준다 (2026-08-06 요청).
    // 적요의 가상계좌 하나로 둘 다 확정된다 — 실측 본/지사 100% · 영업점 99.0%.
    const y=data.yaksik||{};
    // 값이 나왔으면 '약식' 배지는 뺀다 (2026-08-06 요청) — 무슨 유형인지는
    // 본·지사·영업점이 이미 말해 주고, 배지만 덩그러니 있으면 군더더기다.
    // 값이 안 나온 나머지(1%)와 카드·자사이체·실적회비는 배지가 유일한
    // 표시라 그대로 둔다.
    if(!y.office&&!y.branch)return head;
    return '<dl class="yaksik">'
      +`<div><dt>본·지사</dt><dd>${y.office
          ?`<span class="office-copy" title="눌러서 복사">${escapeHtml(y.office)}</span>`
          :'<span class="dim">-</span>'}</dd></div>`
      +`<div><dt>영업점</dt><dd title="${escapeHtml(y.branch||'')}">${y.branch
          ?`<span class="office-copy" title="눌러서 복사">${escapeHtml(y.branch)}</span>`
          :'<span class="dim">-</span>'}</dd></div>`
      +'</dl>';
  }
  const items=data.items||[];
  if(!items.length){
    return stageLine(data)
      +'<p class="empty">적요의 단어로는 감정서를 찾지 못했습니다.</p>';
  }
  // 첫 장만 펼친다 — 5건 이상(실측 4.5%)일 때 전부 펼치면 세로로 늘어져
  // 오히려 견주기 어렵다. 나머지는 한 줄로 접고 눌러서 편다.
  return stageLine(data)
    +'<div class="cand-cards">'
    +items.map((c,i)=>candCard(c,r.memo,i===0)).join('')
    +'</div>';
}

// 찾은 결과는 **오른쪽 상세 패널**에 띄운다 — 감정서 LIST 와 같은 골격이라
// 목록이 밀리지 않고 좌우도 좁아진다 (2026-08-06 요청).
function openMatchPanel(r,html){
  const side=$('matchSide');
  side.innerHTML='<section id="matchPanel" class="match-panel">'
    +'<div class="match-head">'
    +'<h3>감정서 찾기</h3>'
    +'<button type="button" class="detail-close" title="닫기">×</button></div>'
    // 날짜·적요·금액을 한 줄에 이어 붙이면 적요가 길어 뭉개진다 — 라벨을 붙여
    // 위아래로 세운다 (2026-08-06 요청).
    +'<dl class="match-of">'
    +`<div><dt>거래일</dt><dd>${escapeHtml(r.txday)}</dd></div>`
    +`<div><dt>입금액</dt><dd class="amt">${won(r.amount)}원</dd></div>`
    +`<div class="wide"><dt>적요</dt><dd title="${escapeHtml(r.jeokyo)}">${escapeHtml(r.jeokyo)}</dd></div>`
    +'</dl>'
    +`<div class="match-body">${html}</div></section>`;
  side.querySelector('.detail-close').addEventListener('click',closeMatchPanel);
  markTruncated(side);
  return side.querySelector('#matchPanel');
}
function closeMatchPanel(){
  const side=$('matchSide');
  if(side){
    side.innerHTML='<div class="detail-placeholder" id="matchPlaceholder">'
      +'<div class="document-mark">文</div><h2>거래를 선택하세요</h2>'
      +'<p>왼쪽 목록에서 한 줄을 고르면 그 입금의 감정서를 찾아 보여드립니다.</p></div>';
  }
  document.querySelectorAll('#resultBody tr.picked')
    .forEach(tr=>tr.classList.remove('picked'));
}

async function matchRow(tr){
  const r=DEPOSITS[Number(tr.dataset.row)];
  if(!r||tr.dataset.busy)return;
  // 같은 줄을 다시 누르면 닫는다.
  if(tr.classList.contains('picked')){closeMatchPanel();return;}
  document.querySelectorAll('#resultBody tr.picked')
    .forEach(x=>x.classList.remove('picked'));
  tr.classList.add('picked');
  // 고른 줄의 적요를 검색칸에 넣어 둔다 — 같은 거래처의 다른 입금을 이어서
  // 훑는 흐름이라, 조회를 누르면 바로 그 적요로 좁혀진다 (2026-08-06 요청).
  $('question').value=r.jeokyo||'';
  if(r.match){
    openMatchPanel(r,candTable(r,r.match));
    return;
  }
  tr.dataset.busy='1';
  const panel=openMatchPanel(r,'<p class="loading">조회중…</p>');
  try{
    const response=await fetch('/api/gamjun-chat/deposit-match',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({jeokyo:r.jeokyo,amount:r.amount,day:r.txday,
        unique_field:r.unique_field,usr_seq:USR(),office_code:OFFICE()}),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message||'찾지 못했습니다.');
    r.match=payload.data||{};
    panel.querySelector('.match-body').innerHTML=candTable(r,r.match);
    markTruncated(panel);
  }catch(error){
    panel.querySelector('.match-body').innerHTML=
      `<p class="err">${escapeHtml(String(error&&error.message||error))}</p>`;
  }finally{
    delete tr.dataset.busy;
  }
}

// 찾아 줄 값이 있는 줄인가.
// 감정서가 있는 유형이면 **감정서번호**를, 약식평가면 **영업점명**을 찾아 준다.
// 약식은 감정서번호가 아예 없고 재무팀이 옮겨 적는 값도 영업점명이다.
// 값 조회가 가상계좌 하나로 끝나고 캐시가 물려 있어 건당 0.07초다(실측 12건).
// 나머지(자사이체·카드·실적회비·예금이자·환급금)는 옮겨 적을 값 자체가 없어 건너뛴다.
function needsFind(r){
  if(r.inout==='출금'||r.memo)return false;
  return !r.kind || r.kind==='약식평가';
}

// 목록이 뜨면 대상 줄을 병렬로 찾아 칸을 채운다.
// 한 달치(수백 건)를 열어도 목록 자체는 즉시 뜨고 번호만 순서대로 들어차므로
// 화면이 멈추지 않는다. 새 조회를 하면 FIND_GEN 이 올라가 앞 작업은 버려진다.
const FIND_CONC=6;          // 동시 6 — 12 는 서버가 다른 화면과 나눠 쓰기에 과하다
let FIND_GEN=0;

async function fillOne(index,gen){
  const r=DEPOSITS[index];
  const cell=document.querySelector(`[data-find="${index}"]`);
  try{
    const response=await fetch('/api/gamjun-chat/deposit-match',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({jeokyo:r.jeokyo,amount:r.amount,day:r.txday,
        unique_field:r.unique_field,usr_seq:USR(),office_code:OFFICE()}),
    });
    const payload=await response.json();
    if(gen!==FIND_GEN)return;                 // 그 사이 새 조회가 시작됐다
    r.match=payload.success?(payload.data||{}):{};
  }catch(error){
    if(gen!==FIND_GEN)return;
    r.match={};
  }
  if(!cell||gen!==FIND_GEN)return;
  // 약식은 감정서번호가 없다 — 옮겨 적을 값은 영업점명이다.
  const ya=(r.match&&r.match.yaksik)||{};
  if(r.kind==='약식평가'){
    const name=ya.branch||ya.office||'';
    if(name){
      cell.className='found office-copy';
      cell.textContent=name;
      cell.title='눌러서 복사 — 약식 영업점명';
    }else{
      cell.className='dim';
      cell.textContent='약식';
      cell.title='약식평가 — 영업점을 못 찾았습니다';
    }
    return;
  }
  const items=(r.match&&r.match.items)||[];
  // **한 건으로 좁혀졌을 때만 적는다.** 여럿이면 고르는 건 사람 몫이라
  // 목록에 박아 두면 오히려 잘못 옮겨 적게 만든다.
  if(items.length===1){
    const doc=items[0].doc_id||'';
    // 기존 감정서번호 복사 경로(.doc-link)를 그대로 탄다 — 내부망 http 라
    // clipboard API 가 없어 textarea 폴백이 필요한데, 그 처리가 거기 있다.
    cell.className='found doc-link';
    cell.textContent=doc;
    cell.title='눌러서 복사 — 사이버브랜치에 넣을 값';
    cell.dataset.doc=doc;
  }else if(items.length>1){
    cell.className='dim';
    cell.textContent=`후보 ${items.length}`;
    cell.title='줄을 눌러 고르세요';
  }else{
    cell.className='dim';
    cell.textContent='-';
    cell.title=(r.match&&r.match.note)||'';
  }
}

async function fillFound(){
  const gen=++FIND_GEN;
  // **보이는 페이지만** 채운다. 한 달을 열면 수백 건인데 다 두드리면 몇 분이고,
  // 정작 눈앞의 20줄은 늦게 찬다. 페이지를 넘기면 그때 그 페이지를 채운다.
  const from=PAGE*PAGE_SIZE, to=Math.min(from+PAGE_SIZE,DEPOSITS.length);
  const todo=[];
  for(let i=from;i<to;i++){
    if(needsFind(DEPOSITS[i])&&!DEPOSITS[i].match)todo.push(i);
  }
  if(!todo.length)return;
  let next=0;
  const worker=async()=>{
    while(next<todo.length&&gen===FIND_GEN){
      await fillOne(todo[next++],gen);
    }
  };
  await Promise.all(Array.from({length:Math.min(FIND_CONC,todo.length)},worker));
}

let DEPOSITS=[];
let PAGE=0;
// 번호로 찾으면 서버가 기간을 무시한다 — 화면도 그 사실을 말해야 조회 조건과
// 결과가 어긋나 보이지 않는다 (2026-08-06 요청).
let FOUND_BY='';
// 목록이 상한에서 잘렸는지 — 795건이 말없이 사라지던 일이 있었다 (2026-08-06).
let CUT=0;
const PAGE_SIZE=20;   // 기간을 길게 잡아도 표가 늘어지지 않게 (2026-08-06 요청)

function renderDeposits(data){
  const items=data.items||[];
  DEPOSITS=items;
  PAGE=0;
  FOUND_BY=data.number||'';
  CUT=data.truncated?(data.limit||0):0;
  if(!items.length){
    const word=$('question').value.trim();
    setTitle('거래 내역','');
    // 번호로 찾았으면 '그 기간에' 라고 하면 안 된다 — 기간을 안 봤으니까.
    showBody(FOUND_BY
      ? `<p class="empty">통장 전체에서 <b>${escapeHtml(FOUND_BY)}</b> 가 든 거래를 찾지 못했습니다.</p>`
      : `<p class="empty">그 기간에 ${word?`적요에 '${escapeHtml(word)}' 가 든 `:''}입금이 없습니다.</p>`);
    return;
  }
  renderPage();
  // 표를 먼저 띄우고 번호는 뒤따라 채운다 — 기다리게 하지 않는다.
  fillFound();
}

// 한 장은 20건. 합계 줄은 두지 않는다 (2026-08-06 요청) — 이 화면은 감정서를
// 찾는 곳이지 금액을 더하는 곳이 아니다. 건수는 표 머리에 이미 있다.
function renderPage(){
  const items=DEPOSITS;
  const word=$('question').value.trim();
  const pages=Math.max(1,Math.ceil(items.length/PAGE_SIZE));
  PAGE=Math.min(Math.max(PAGE,0),pages-1);
  const from=PAGE*PAGE_SIZE, to=Math.min(from+PAGE_SIZE,items.length);
  const count=pages>1?`${items.length}건 · ${from+1}~${to}`:`${items.length}건`;
  setTitle(FOUND_BY?`번호 찾기 · ${FOUND_BY}`:(word?`거래 내역 · ${word}`:'거래 내역'),
    FOUND_BY?`전체 기간 · ${count}`:count);
  // 칸 폭을 못 박는다 — 감정서 LIST 와 같은 방식(colgroup). 적요만 남는 폭을
  // 먹고 나머지는 내용만큼만 차지해 표가 좌우로 늘어지지 않는다.
  // 적요를 넓게 줬더니(2026-08-06) 감정서번호가 오른쪽으로 밀려 매번 가로
  // 스크롤을 해야 했다 (2026-08-13 요청으로 축소) — hover 로 전문을 볼 수
  // 있으니 칸은 좁혀도 된다. 폭은 드래그로 조절·저장된다.
  const COLS=['84px','48px','54px','58px','58px','92px','220px','92px','116px'];
  showBody('<div class="tbl wide"><button type="button" class="tbl-copy" title="표를 복사해 엑셀에 붙여넣기">복사</button>'
    +'<table id="depositTable"><colgroup>'
    +COLS.map(w=>w?`<col style="width:${w}">`:'<col>').join('')
    +'</colgroup><thead><tr>'
    +DEPOSIT_HEAD.map(h=>{
      const cls=(h==='거래금액')?' class="num"':'';
      return `<th${cls} title="눌러서 정렬">${escapeHtml(h)}</th>`;
    }).join('')
    +'</tr></thead><tbody>'
    // 줄 번호는 전체 기준 인덱스를 그대로 쓴다 — 장을 넘겨도 같은 줄을 가리킨다.
    +items.slice(from,to).map((r,i)=>depositRow(r,from+i)).join('')+'</tbody>'
    +'</table></div>'
    +pager(pages)
    +(CUT?`<p class="cut-note">이 기간에 입금이 너무 많아 최근 <b>${CUT.toLocaleString()}건</b>까지만 가져왔습니다. 기간을 좁히거나 위 칸에 이름·번호를 넣어 좁혀 보세요.</p>`:'')
    +(FOUND_BY
      ? '<p class="pick-hint">번호로 찾을 때는 기간을 보지 않고 통장 전체를 훑습니다.</p>'
      : '<p class="pick-hint">위 표에서 줄을 선택하면 감정서 번호를 찾아드립니다.</p>'));
  // 감정서 LIST 와 같은 칸 폭 드래그 조절 (머리 경계를 끌면 되고, 더블클릭이면
  // 기본값. 조절값은 브라우저에 남는다.)
  attachResize('depositTable','a10.depositTable.columnWidths.v1');
}

function attachResize(tableId,key){
  const table=document.getElementById(tableId);
  if(table&&window.A10_COLUMN_RESIZE)window.A10_COLUMN_RESIZE(table,key);
}

// 감정서 LIST 와 같은 모양 — 이전 / 현재 / 다음 (dashboard.html .pagination).
function pager(pages){
  if(pages<=1)return '';
  return '<div class="pagination">'
    +`<button type="button" data-page="${PAGE-1}"${PAGE===0?' disabled':''}>이전</button>`
    +`<span>${PAGE+1} / ${pages}</span>`
    +`<button type="button" data-page="${PAGE+1}"${PAGE>=pages-1?' disabled':''}>다음</button>`
    +'</div>';
}

async function loadDeposits(){
  if(busy)return;
  const from=$('dateFrom').value,to=$('dateTo').value;
  if(!from||!to){showError('시작일과 종료일을 정해 주세요.');return;}
  if(from>to){showError('시작일이 종료일보다 뒤입니다.');return;}
  setBusy(true);
  setTitle('거래 내역','');
  showBody('');   // 조회 중엔 아무것도 띄우지 않는다 (2026-08-06 요청)
  try{
    const response=await fetch('/api/gamjun-chat/deposits',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({date_from:from,date_to:to,
        // 체크를 풀어 두면 아직 감정서번호가 안 적힌 것만 본다 — 그게 일감이다.
        only_blank:!$('allRows').checked,
        // 검색칸은 적요 부분일치 필터다 — '세연스틸'·'부산은행'처럼 넣는다.
        keyword:$('question').value.trim(),
        // 약식 가상계좌 제외 (기본 켬 — Memo 빈 목록의 70%가 이 잡음이다)
        usr_seq:USR(),office_code:OFFICE()}),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message||'조회에 실패했습니다.');
    renderDeposits(payload.data||{});
  }catch(error){
    showError(String(error&&error.message||error));
  }finally{setBusy(false);}
}

// ── 감정서 상세 — 표에서 번호를 누르면 옆으로 열린다 (조회 결과는 그대로 둔다) ──
// 감정서번호 클릭 = 클립보드 복사 — 재무팀이 DB(Memo)에 바로 붙여넣는 게
// 목적이라 상세 패널 대신 번호만 복사한다 (2026-08-05 요청).
function copyDocId(el,docId){
  const done=()=>{
    const tip=document.createElement('span');
    tip.className='copied-tip';tip.textContent='복사됨';
    el.after(tip);setTimeout(()=>tip.remove(),1200);
  };
  // 내부망 http 에서는 clipboard API 가 없어 textarea 폴백을 쓴다.
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(docId).then(done).catch(()=>fallbackCopy(docId,done));
  }else{
    fallbackCopy(docId,done);
  }
}

// ── 검색칸 자동완성 — 거래처·평가사·지역·물건종별 ──────────────────────────
let suggestTimer=null,suggestIndex=-1;
function closeSuggest(){const b=$('suggestBox');if(b){b.remove();}suggestIndex=-1;}
function pickSuggest(value){
  const input=$('question');
  const words=input.value.split(/\s+/);
  words[words.length-1]=value;
  input.value=words.join(' ')+' ';
  closeSuggest();input.focus();
}
function renderSuggest(items){
  closeSuggest();
  if(!items.length)return;
  const box=document.createElement('div');
  box.id='suggestBox';box.className='suggest-box';
  items.forEach((it,i)=>{
    const b=document.createElement('button');
    b.type='button';b.dataset.index=i;b.dataset.value=it.value;
    b.innerHTML=`<span class="kind">${escapeHtml(it.kind)}</span>${escapeHtml(it.value)}`;
    b.addEventListener('mousedown',event=>{event.preventDefault();pickSuggest(it.value);});
    box.appendChild(b);
  });
  $('question').parentNode.appendChild(box);
}
$('question').addEventListener('input',()=>{
  clearTimeout(suggestTimer);
  const last=($('question').value.split(/\s+/).pop()||'').trim();
  if(last.length<1){closeSuggest();return;}
  suggestTimer=setTimeout(async()=>{
    try{
      const payload=await(await fetch(`/api/gamjun-chat/suggest?q=${encodeURIComponent(last)}&usr_seq=${encodeURIComponent(USR())}&office_code=${encodeURIComponent(OFFICE())}`)).json();
      const items=(payload.success&&payload.data&&payload.data.items)||[];
      // 입력이 그새 바뀌었으면 버린다
      const now=($('question').value.split(/\s+/).pop()||'').trim();
      if(now===last)renderSuggest(items);
    }catch(error){closeSuggest();}
  },220);
});
$('question').addEventListener('keydown',event=>{
  const box=$('suggestBox');
  if(!box)return;
  const buttons=[...box.querySelectorAll('button')];
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){
    event.preventDefault();
    suggestIndex+=(event.key==='ArrowDown'?1:-1);
    if(suggestIndex<0)suggestIndex=buttons.length-1;
    if(suggestIndex>=buttons.length)suggestIndex=0;
    buttons.forEach((b,i)=>b.classList.toggle('active',i===suggestIndex));
  }else if(event.key==='Enter'&&suggestIndex>=0){
    event.preventDefault();
    pickSuggest(buttons[suggestIndex].dataset.value);
  }else if(event.key==='Escape'){
    closeSuggest();
  }
});
$('question').addEventListener('blur',()=>setTimeout(closeSuggest,150));

// ── 표 정렬·복사 — 머리행 클릭으로 정렬, 복사 버튼으로 TSV(엑셀 붙여넣기) ──
// 한글 단위 금액('약 399조 1,939억원')을 실제 값으로 환산한다. 숫자만 추려 붙이면
// 3991939 가 되어 조 단위와 억 단위가 뒤섞인다.
const UNIT_MUL={'조':1e12,'억':1e8,'천만':1e7,'백만':1e6,'만':1e4,'천':1e3};
function num(cell){
  const t=String(cell??'').replace(/\*\*/g,'').replace(BAR_CHARS,'')
    .replace(/[▇▆▅▄▃▂▁]/g,'').replace(/\([^()]*\)/g,'').replace(/^\s*약\s*/,'').trim();
  if(!t)return null;
  if(/[조억만천]/.test(t)){
    let total=0,found=false,m;
    const re=/([\d,]+(?:\.\d+)?)\s*(조|억|천만|백만|만|천)?/g;
    while((m=re.exec(t))){
      const value=parseFloat(m[1].replace(/,/g,''));
      if(isNaN(value))continue;
      total+=value*(UNIT_MUL[m[2]]||1);found=true;
    }
    return found?total:null;
  }
  const v=t.replace(/[^0-9.\-]/g,'');
  return v&&!isNaN(+v)?+v:null;
}
function sortTable(th){
  const table=th.closest('table');
  const idx=[...th.parentNode.children].indexOf(th);
  const dir=(table.dataset.sortCol==idx&&table.dataset.sortDir==='asc')?'desc':'asc';
  table.dataset.sortCol=idx;table.dataset.sortDir=dir;
  const body=table.tBodies[0];
  const rows=[...body.rows];
  rows.sort((a,b)=>{
    const x=a.cells[idx]?a.cells[idx].textContent.trim():'';
    const y=b.cells[idx]?b.cells[idx].textContent.trim():'';
    // 값 없는 행('-')은 방향과 무관하게 항상 아래로 — 오름차순에서 맨 위를 차지하면
    // '작은 것부터'가 '빈 것부터'가 되어 읽는 사람을 속인다.
    const ex=(x===''||x==='-'),ey=(y===''||y==='-');
    if(ex!==ey)return ex?1:-1;
    if(ex&&ey)return 0;
    const nx=num(x),ny=num(y);
    const r=(nx!==null&&ny!==null)?nx-ny:x.localeCompare(y,'ko');
    return dir==='asc'?r:-r;
  });
  rows.forEach(r=>body.appendChild(r));
  table.querySelectorAll('thead th').forEach(h=>h.classList.remove('sort-asc','sort-desc'));
  th.classList.add(dir==='asc'?'sort-asc':'sort-desc');
}
function fallbackCopy(text,done){
  const ta=document.createElement('textarea');
  ta.value=text;document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');done();}catch(error){}
  ta.remove();
}
function copyTable(btn){
  const table=btn.closest('.tbl').querySelector('table');
  if(!table)return;
  const tsv=[...table.rows].map(r=>[...r.cells].map(c=>c.textContent.trim()).join('\t')).join('\n');
  const done=()=>{btn.textContent='복사됨';setTimeout(()=>{btn.textContent='복사';},1200);};
  // 내부망 http 에서는 clipboard API 가 없어 textarea 폴백을 쓴다.
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(tsv).then(done).catch(()=>fallbackCopy(tsv,done));
  }else{
    fallbackCopy(tsv,done);
  }
}

// ── 배선 ────────────────────────────────────────────────────────────────
$('queryForm').addEventListener('submit',event=>{
  event.preventDefault();closeSuggest();closeMatchPanel();
  loadDeposits();
});
$('resultBody').addEventListener('click',event=>{

  const page=event.target.closest('.pagination button');
  if(page){
    PAGE=Number(page.dataset.page);
    closeMatchPanel();
    renderPage();
    fillFound();          // 새 페이지의 빈 칸을 채운다
    return;
  }
  const copy=event.target.closest('.tbl-copy');
  if(copy){copyTable(copy);return;}
  const th=event.target.closest('.tbl thead th');
  if(th){sortTable(th);return;}
  const link=event.target.closest('.doc-link');
  if(link){copyDocId(link,link.dataset.doc);return;}
  // 약식 영업점명도 목록에서 바로 복사한다 (패널 핸들러는 #matchPanel 안만 본다).
  const office=event.target.closest('.office-copy');
  if(office){copyDocId(office,office.textContent.trim());return;}

  // 목록의 줄을 누르면 표 아래에 감정서 찾기 표가 선다 (첫 조회는 통장 값만).
  const row=event.target.closest('tbody tr[data-row]');
  if(row)matchRow(row);
});
// 오른쪽 감정서 찾기 카드 — 번호·지사명을 눌러 복사한다.
document.addEventListener('click',event=>{
  const panel=event.target.closest('#matchPanel');
  if(!panel)return;
  const link=event.target.closest('.doc-link');
  // summary 안에서 눌렀으므로 카드가 접히지 않게 막는다 — 번호를 복사하려던
  // 것이지 카드를 닫으려던 게 아니다.
  if(link){event.preventDefault();event.stopPropagation();
    copyDocId(link,link.dataset.doc);return;}
  // 지사명도 눌러서 복사 — 재무팀이 지사 건은 Memo 에 지사명을 적는다.
  const office=event.target.closest('.office-copy');
  if(office){event.preventDefault();event.stopPropagation();
    copyDocId(office,office.textContent.trim());}
});

async function checkHealth(){
  const badge=$('chatState');
  try{
    const payload=await(await fetch('/api/gamjun-chat/health')).json();
    const ok=payload.success&&payload.data&&payload.data.available;
    badge.textContent=ok?'연결됨':'연결 안 됨';
    badge.className='chat-state '+(ok?'ok':'bad');
  }catch(error){
    badge.textContent='연결 안 됨';badge.className='chat-state bad';
  }
}

// 기본 기간 — 오늘 하루. 대사는 '오늘 들어온 돈'부터 보는 일이다.
(function initDates(){
  const today=new Date();
  const iso=d=>d.toISOString().slice(0,10);
  const local=new Date(today.getTime()-today.getTimezoneOffset()*60000);
  $('dateFrom').value=iso(local);
  $('dateTo').value=iso(local);
})();

window.A10_READY.then(()=>{checkHealth();});
