// app/static/receivables.js 이식본 (데스크톱).
// 웹 버전과의 차이(원본과 diff 하면 재이식이 쉽다):
//  1) 조회에 office_code 전달 — 지사 사용자는 자기 지사만 보이게 한다.
//  2) 지사 셀렉트 변경 시 재조회.
//  3) 최초 조회를 window.A10_READY(사용자 확인) 이후로 미룬다.
//  4) 검색 조건 확장(유치자·상태·기간·청구액·미수금 범위) — 데스크톱 전용.
//     기간은 입금 현황=최근 입금일, 미수금 현황=발송일 기준이며 기본 최근 1개월.
//  5) 목록 하단 합계 바 — 현재 검색 조건 전체(페이지 무관)의 청구·입금·미수·과입금 합계.
// 미수금 현황과 한 화면(mode 전환)이었다가 2026-09-01 두 화면으로 분리했다.
// 이 파일은 **입금 현황 전용**이다 — 미수금 현황은 outstanding.js.
// 옛 주소(?mode=outstanding)는 서버(/desktop/receivables)가 리다이렉트한다.
const state={mode:'received',page:1,pageSize:30,total:0,selected:null,sortBy:null,sortOrder:'asc',itemsByDoc:{}};
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
// 선수금 두 칸의 뜻:
//   선수금(기) = 받은 금액 (전표 2590000 대변 합계)
//   선수금     = 남은 잔액. 매출에 전액 상계됐으면 0이다.
// 예전에는 두 칸 다 순액(대변-차변)을 기간별로 찍어서 상계한 날 음수가 떴고,
// 재무팀이 이를 '선수금을 두 번 인식한다'고 읽었다. 받은 금액과 남은 잔액으로
// 나누면 둘 다 음수가 될 수 없어 그 혼선이 없고, 전액 상계된 건도
// 선수금(기)에 금액이 남아 '선수금이 아예 없던 건'과 구분된다.
// 받고 쓴 흐름은 행을 선택하면 우측 전표 목록에서 날짜별로 보인다.
const advanceReceivedCell=row=>{
  const received=Number(row.advance_received||0);
  if(!received) return money.format(0);
  return `<span title="입금액에 이미 포함된 금액입니다 (따로 더하지 마세요)">${money.format(received)}</span>`;
};
const advanceCell=row=>{
  const balance=Number(row.advance_amount||0);
  const received=Number(row.advance_received||0);
  if(!received) return money.format(balance);
  const tip=`선수금 ${money.format(received)} 받음`
    +(Number(row.advance_offset||0)?` · ${money.format(Number(row.advance_offset))} 매출에 상계`:'');
  return `<span title="${escapeHtml(tip)}">${money.format(balance)}</span>`;
};

const dateText=value=>value?String(value).slice(0,10):'-';
const inputDate=value=>{
  const year=value.getFullYear();const month=String(value.getMonth()+1).padStart(2,'0');const day=String(value.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
};
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const sortLabels={doc_id:'감정서번호',purpose:'업무구분',eval_purpose:'평가목적',customer_name:'거래처명',address:'소재지',manager:'유치자',charge:'조사자',receipt_date:'접수일',send_date:'발송일',last_received_date:'최근 입금일',appraisal_amount:'감정가액',base_fee:'순수수료',travel_expense:'여비',survey_fee:'물건조사비',document_fee:'공부발급비',land_survey_fee:'토지조사비',other_expense:'기타실비',special_service_fee:'특별용역비',other_expense:'기타실비',billed_amount:'청구액',received_amount:'입금액',outstanding_amount:'미수금',overpaid_amount:'과입금',progress_status:'진행상태'};
const receivedHeaders='<th data-sort="doc_id">감정서번호</th><th>입금상태</th><th data-sort="purpose">업무구분</th><th data-sort="eval_purpose">평가목적</th><th data-sort="customer_name">거래처명</th><th data-sort="address">소재지</th><th data-sort="manager">유치자</th><th data-sort="charge">조사자</th><th data-sort="receipt_date">접수일</th><th data-sort="send_date">발송일</th><th data-sort="last_received_date">최근 입금일</th><th class="number" data-sort="appraisal_amount">감정가액</th><th class="number" data-sort="base_fee">순수수료</th><th class="number" data-sort="travel_expense">여비</th><th class="number" data-sort="survey_fee">물건조사비</th><th class="number" data-sort="document_fee">공부발급비</th><th class="number" data-sort="land_survey_fee">토지조사비</th><th class="number" data-sort="other_expense">기타실비</th><th class="number" data-sort="special_service_fee">특별용역비</th><th class="number">매출액</th><th class="number">부가세</th><th class="number">매출총액</th><th class="number">선수금(기)</th><th class="number">입금액(기)</th><th class="number">입금액</th><th class="number">선수금</th><th class="number" data-sort="outstanding_amount">미수금</th><th data-sort="progress_status">진행상태</th><th class="proof-cell">세금계산서/현금영수증</th>';
const receivedColumns='<col style="width:130px"><col style="width:92px"><col style="width:100px"><col style="width:130px"><col style="width:150px"><col style="width:200px"><col style="width:80px"><col style="width:80px"><col style="width:95px"><col style="width:95px"><col style="width:95px"><col style="width:110px"><col style="width:100px"><col style="width:100px"><col style="width:100px"><col style="width:100px"><col style="width:100px"><col style="width:100px"><col style="width:100px"><col style="width:105px"><col style="width:90px"><col style="width:110px"><col style="width:105px"><col style="width:105px"><col style="width:110px"><col style="width:100px"><col style="width:110px"><col style="width:110px"><col style="width:150px">';
// 열 수는 헤더 상수에서 센다 — 숫자를 박아두면 열을 늘릴 때마다 어긋난다.
function renderLoading(){const columns=receivedHeaders.split('<th').length-1;$('emptyList').classList.add('hidden');$('emptyList').classList.remove('error');$('rows').innerHTML=Array.from({length:7},()=>`<tr class="skeleton-row">${Array.from({length:columns},()=>'<td><span></span></td>').join('')}</tr>`).join('');}

// 상태 다중선택 — 체크된 상태들을 pay_status 파라미터로 반복해서 보낸다.
const payStatusChecks=()=>Array.from(document.querySelectorAll('#payStatusMenu input[type=checkbox]'));
const selectedStatuses=()=>payStatusChecks().filter(box=>box.checked).map(box=>box.value);
function syncStatusButton(){
  const picked=selectedStatuses();
  $('payStatusButton').textContent=picked.length===0?'전체'
    :picked.length<=2?picked.join(', ')
    :`${picked[0]} 외 ${picked.length-1}건`;
  $('payStatusButton').title=picked.length?picked.join(', '):'전체';
}

// 현재 검색 조건·정렬을 쿼리로 만든다 (목록 조회와 엑셀 내보내기가 공유).
function buildListQuery(){
  const query=new URLSearchParams({mode:state.mode,office_code:window.A10_OFFICE(),date_basis:$('dateBasis').value});
  const filters={docId:'doc_id',customerName:'customer_name',manager:'manager',dateFrom:'date_from',dateTo:'date_to',billFrom:'bill_from',billTo:'bill_to',outstandingFrom:'outstanding_from',outstandingTo:'outstanding_to'};
  Object.entries(filters).forEach(([inputId,param])=>{const value=$(inputId).value.trim();if(value)query.set(param,value);});
  selectedStatuses().forEach(status=>query.append('pay_status',status));
  if(state.sortBy){query.set('sort_by',state.sortBy);query.set('sort_order',state.sortOrder);}
  return query;
}

async function loadList(){
  const query=buildListQuery();
  query.set('page',state.page);query.set('page_size',state.pageSize);
  $('resultSummary').textContent='조회 중...';$('searchButton').disabled=true;$('searchButton').textContent='조회 중';renderLoading();
  const response=await fetch(`/api/receivables?${query}`);const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const data=payload.data;state.total=data.total;
  // 우클릭 메뉴(실비 처리)가 행 데이터를 봐야 한다 — 확인창 금액·활성 조건.
  state.itemsByDoc=Object.fromEntries(data.items.map(r=>[String(r.doc_id),r]));
  const sortText=state.sortBy?` / ${sortLabels[state.sortBy]} ${state.sortOrder==='asc'?'오름차순':'내림차순'}`:'';$('resultSummary').textContent=`총 ${money.format(data.total)}건 · ${data.page}페이지${sortText}`;
  $('emptyList').textContent='조건에 맞는 내역이 없습니다.';$('emptyList').classList.remove('error');
  $('emptyList').classList.toggle('hidden',data.items.length!==0);
  $('rows').innerHTML=data.items.map(row=>`<tr data-docid="${escapeHtml(row.doc_id)}" class="${state.selected===row.doc_id?'selected':''}${row.kb_simple?' kb-simple':''}"><td>${escapeHtml(row.doc_id)}${expenseBadge(row)}</td><td>${paymentBadge(row)}</td><td title="${escapeHtml(row.purpose||'')}">${escapeHtml(row.purpose||'-')}</td><td title="${escapeHtml(row.eval_purpose||'')}">${escapeHtml(row.eval_purpose||'-')}</td><td>${escapeHtml(row.customer_name||'-')}</td><td title="${escapeHtml(row.address||'')}">${escapeHtml(row.address||'-')}</td><td>${escapeHtml(row.manager||'-')}</td><td>${escapeHtml(row.charge||'-')}</td><td>${dateText(row.receipt_date)}</td><td>${dateText(row.send_date)}</td><td>${dateText(row.last_received_date)}</td><td class="number">${money.format(row.appraisal_amount||0)}</td><td class="number">${money.format(row.base_fee||0)}</td><td class="number">${money.format(row.travel_expense||0)}</td><td class="number">${money.format(row.survey_fee||0)}</td><td class="number">${money.format(row.document_fee||0)}</td><td class="number">${money.format(row.land_survey_fee||0)}</td><td class="number">${money.format(row.other_expense||0)}</td><td class="number">${money.format(row.special_service_fee||0)}</td><td class="number">${money.format(row.sales_amount||0)}</td><td class="number">${money.format(row.vat_amount||0)}</td><td class="number">${money.format(row.invoice_total||0)}</td><td class="number">${advanceReceivedCell(row)}</td><td class="number">${money.format(row.existing_received_amount||0)}</td><td class="number received">${money.format(row.daily_received_amount||0)}</td><td class="number">${advanceCell(row)}</td><td class="number outstanding">${money.format(row.outstanding_amount||0)}</td><td title="${escapeHtml(row.progress_status||'')}">${escapeHtml(row.progress_status||'-')}</td><td class="proof-cell">${proofIssuedCell(row)}</td></tr>`).join('');
  // 국민 약식수수료 묶음 행은 감정서가 아니다 — 상세(전표)도 세금계산서 발급 메뉴도 없다
  document.querySelectorAll('#rows tr').forEach(row=>{if(row.classList.contains('kb-simple'))return;row.addEventListener('click',()=>selectDoc(row.dataset.docid,row));row.addEventListener('contextmenu',event=>openTaxMenu(event,row));});
  const pages=Math.max(1,Math.ceil(state.total/state.pageSize));$('pageLabel').textContent=`${state.page} / ${pages}`;$('prevPage').disabled=state.page<=1;$('nextPage').disabled=state.page>=pages;$('searchButton').disabled=false;$('searchButton').textContent='조회';
  $('sumBar').innerHTML=receivedSumBar(data,data.sums||{});
}

// 입금현황 합계 바 — 윗줄은 조회 조건 전체, 아랫줄은 입금 종료일 '당일' 입금분.
function receivedSumBar(data,sums){
  const daily=data.daily_sums;
  const top=`<div class="sum-line"><span class="sum-label">조회 합계 (${money.format(data.total)}건)</span>`
    +`<span>매출총액 <b>${money.format(sums.invoice_total||0)}</b></span>`
    +`<span>입금액 <b class="received">${money.format(sums.received_amount||0)}</b></span>`
    +`<span>선수금 <b>${money.format(sums.advance_amount||0)}</b></span>`
    +`<span>미수금 <b class="outstanding">${money.format(sums.outstanding_amount||0)}</b></span></div>`;
  if(!daily)return top;
  return top+`<div class="sum-line"><span class="sum-label">종료일(${escapeHtml(daily.date)}) 입금 (${money.format(daily.count)}건)</span>`
    +`<span>매출총액 <b>${money.format(daily.invoice_total||0)}</b></span>`
    +`<span>입금액 <b class="received">${money.format(daily.received_amount||0)}</b></span>`
    +`<span>선수금 <b>${money.format(daily.advance_amount||0)}</b></span>`
    +`<span>미수금 <b class="outstanding">${money.format(daily.outstanding_amount||0)}</b></span></div>`;
}

// 세금계산서 내역 (TAMS 캐시). 전표 아래 한 표로 표시한다 (dashboard.js와 같은 코드).
// 세금계산서 발행여부 (2026-08-07 요청). 서버가 '발행' 아니면 빈 값을 준다.
// 선언을 const 화살표로 두는 것은 취향이 아니라 약속이다 —
// tests/check_receivable_columns.js 가 `const 이름=` 을 찾아 행 템플릿이 부르는
// 헬퍼를 자동으로 끌어온다. function 으로 쓰면 그 검사가 ReferenceError 로 깨진다.
// 세금계산서/현금영수증 한 칸 (2026-08-13) — 둘은 받는 주체(사업자/개인)만 다른
// 같은 층위의 증빙이라 칸을 나누지 않고, 값도 예전 세금계산서 칸처럼 '발행'
// 하나다. 어떤 증빙이 몇 건·얼마인지는 툴팁이 말한다. 문자열 연결로 쓰는 이유:
// check_receivable_columns.js 의 블록 파서가 중첩 백틱을 못 읽는다.
// 실비 종결 배지 (2026-09-01) — 우클릭 '실비 처리'로 수금액이 최종 매출로 확정된 건.
// 문자열 연결로 쓰는 이유는 proofIssuedCell 과 같다(중첩 백틱 금지).
const expenseBadge=row=>row.expense_closed
  ?'<span class="expense-closed" title="실비종결 · '+escapeHtml(row.expense_closed_by||'')
    +' · '+escapeHtml(String(row.expense_closed_at||'').slice(0,10))+'">토지조사비</span>'
  :'';

const proofIssuedCell=row=>{
  const tips=[];
  if(row.tax_issued)tips.push('계산서 '+Number(row.tax_issued_slips||0)+'장 · '
    +money.format(Number(row.tax_issued_amount||0))+'원');
  if(row.cash_issued)tips.push('현금영수증 '+Number(row.cash_issued_slips||0)+'건 · '
    +money.format(Number(row.cash_issued_amount||0))+'원');
  if(!tips.length)return row.card_sales?'<span class="tax-issued card" title="카드매출 — 세금계산서 불필요">카드</span>':'<span class="dim">-</span>';
  return '<span class="tax-issued" title="'+escapeHtml(tips.join(' / '))+'">발행</span>';
};

function renderTaxInvoices(taxes){
  $('taxEmpty').classList.toggle('hidden',taxes.length!==0);
  $('taxList').innerHTML=taxes.length?`<section class="voucher"><div class="voucher-grid-wrap"><table class="voucher-grid"><colgroup><col style="width:82px"><col style="width:150px"><col style="width:62px"><col style="width:76px"><col style="width:100px"><col style="width:76px"><col style="width:76px"><col style="width:76px"></colgroup><thead><tr><th>발행일자</th><th>상호</th><th>상태</th><th>발행유형</th><th>승인번호</th><th class="number">공급가액</th><th class="number">세액</th><th class="number">합계금액</th></tr></thead>
    <tbody>${taxes.map(tax=>`<tr><td>${dateText(tax.tax_date)}</td><td class="ellipsis" title="${escapeHtml(tax.company_name||'')}">${escapeHtml(tax.company_name||'-')}</td><td>${escapeHtml(tax.status||'-')}</td><td>${escapeHtml(tax.issue_type||'-')}</td><td class="ellipsis" title="${escapeHtml(tax.approval_no||'')}">${escapeHtml(tax.approval_no||'-')}</td><td class="number">${money.format(tax.supply_amount||0)}</td><td class="number">${money.format(tax.vat_amount||0)}</td><td class="number">${money.format(tax.total_amount||0)}</td></tr>`).join('')}</tbody></table></div></section>`:'';
  window.A10_COLUMN_RESIZE(document.querySelector('#taxList table'),'a10.taxGrid.columnWidths');
}

async function selectDoc(docId,row){
  state.selected=docId;document.querySelectorAll('#rows tr').forEach(x=>x.classList.remove('selected'));row.classList.add('selected');$('detailPlaceholder').classList.add('hidden');$('detailContent').classList.remove('hidden');$('selectedDocId').textContent=docId;$('matchBadge').textContent='조회 중';
  const response=await fetch(`/api/appraisals/${encodeURIComponent(docId)}/vouchers`);const payload=await response.json();if(!payload.success)throw new Error(payload.message);const items=payload.data.items;$('matchBadge').textContent=`${items.length}건 연결`;
  renderTaxInvoices(payload.data.tax_invoices||[]);
  const debitTotal=items.reduce((sum,v)=>sum+Number(v.debit_total||0),0);
  const creditTotal=items.reduce((sum,v)=>sum+Number(v.credit_total||0),0);
  $('voucherList').innerHTML=items.length?`<section class="voucher"><div class="voucher-grid-wrap"><table class="voucher-grid"><colgroup><col style="width:82px"><col style="width:92px"><col style="width:110px"><col style="width:110px"><col style="width:76px"><col style="width:76px"><col style="width:140px"></colgroup><thead><tr><th>전표일자</th><th>전표번호</th><th>계정과목</th><th>거래처</th><th class="number">차변금액</th><th class="number">대변금액</th><th>적요</th></tr></thead><tbody>${items.flatMap(v=>(v.lines||[]).map(line=>{const amount=Number(line.amount||0),debit=String(line.debit_credit)==='3';const bundle=line.allocated&&v.batch_settlement?`<small class="bundle-note" title="${escapeHtml(v.batch_note||'')}"><span class="bundle-badge">여러 건 묶음</span>${escapeHtml(v.batch_doc_count||'')}건 · 원전표 ${money.format(v.original_cash_amount||0)}</small>`:'';const off=line.offset?`<span class="offset-badge" title="${escapeHtml(line.offset_note||'')}">반제</span>`:'';return `<tr${line.offset?' class="offset"':''}><td>${dateText(v.voucher_date)}</td><td>${escapeHtml(v.source_voucher_no)}</td><td><strong>${off}${escapeHtml(line.account_name||line.account_code||'-')}</strong>${bundle}</td><td class="ellipsis" title="${escapeHtml(line.partner_name||'')}">${escapeHtml(line.partner_name||'-')}</td><td class="number debit">${debit?money.format(amount):'-'}</td><td class="number credit">${debit?'-':money.format(amount)}</td><td class="ellipsis" title="${escapeHtml(line.remark||'')}">${escapeHtml(line.remark||'-')}</td></tr>`})).join('')}</tbody><tfoot><tr><th colspan="4">합계</th><th class="number">${money.format(debitTotal)}</th><th class="number">${money.format(creditTotal)}</th><th></th></tr></tfoot></table></div></section>`:'';
  window.A10_COLUMN_RESIZE(document.querySelector('#voucherList table'),'a10.voucherGrid.columnWidths');
}

// 사이드 메뉴는 이제 context.js 가 그린다(2026-08-07). 예전에는 이 화면 HTML 이
// 메뉴에 id 를 박아 두고 여기서 집었는데, 그 id 가 사라졌다. 주소로 찾으면
// 메뉴를 누가 그리든 깨지지 않고, 없으면 조용히 넘어간다.
// 사이드 메뉴 활성 표시는 context.js(a10MenuActive)가 주소로 처리한다.
function syncModeUi(){
  $('pageTitle').textContent='입금 현황';$('listTitle').textContent='입금 현황';
  $('tableHeaders').innerHTML=receivedHeaders;$('tableColumns').innerHTML=receivedColumns;
  $('receivableTable').classList.add('received-columns');
  document.title='입금 현황 | 감정서 LIST';
  syncDateBasisLabels();
}
// 기간 기준(입금일/발송일)에 따라 날짜 라벨을 맞춘다 (2026-09-02)
function dateBasisName(){return $('dateBasis').value==='send'?'발송':'입금';}
function syncDateBasisLabels(){
  const name=dateBasisName();
  $('dateFromLabel').textContent=`${name} 시작일`;$('dateToLabel').textContent=`${name} 종료일`;
}
// 우클릭 → 세금계산서 발급 / 실비 처리 (감정서 LIST와 같은 컨텍스트 메뉴 패턴)
function openTaxMenu(event,row){
  event.preventDefault();
  const menu=$('rowContextMenu');menu.dataset.docid=row.dataset.docid;
  const item=state.itemsByDoc[row.dataset.docid]||{};
  // 이미 실비 처리된 건은 해제 메뉴로 (2026-09-01)
  $('expenseCloseMenu').classList.toggle('hidden',!!item.expense_closed);
  $('expenseReleaseMenu').classList.toggle('hidden',!item.expense_closed);
  // 입금이 아예 없는 건은 실비 처리 비활성 (사용자 요구 — 서버도 거부한다)
  $('expenseCloseMenu').disabled=paidOf(item)<=0;
  menu.classList.remove('hidden');
  const w=menu.offsetWidth,h=menu.offsetHeight;
  menu.style.left=`${Math.min(event.clientX,window.innerWidth-w-8)}px`;menu.style.top=`${Math.min(event.clientY,window.innerHeight-h-8)}px`;
}
function closeTaxMenu(){$('rowContextMenu').classList.add('hidden')}
const paidOf=item=>Number(item.received_amount||0)+Number(item.settled_advance||0);
function showToast(message,isError=false){const toast=$('toast');if(!toast){alert(message);return}toast.textContent=message;toast.classList.toggle('error',!!isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}
// 실비 처리 — 지금 수금액이 이 감정서의 최종 매출이 된다. APWorks 실비 필드와 무관.
async function markExpenseClose(){
  const docId=$('rowContextMenu').dataset.docid;closeTaxMenu();if(!docId)return;
  const item=state.itemsByDoc[docId]||{};
  const paid=paidOf(item),gross=Number(item.invoice_total||0);
  const give=Math.max(gross-paid,0);
  if(!confirm(`${docId}\n현재 수금액 ${money.format(paid)}원을 이 감정서의 최종 매출로 확정하고 완납 종결합니다.\n(표시 매출총액 ${money.format(gross)}원 — 차액 ${money.format(give)}원은 받지 않는 것으로 확정)\n진행할까요?`))return;
  try{
    const payload=await(await fetch('/api/receivables/expense-close',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({doc_id:docId})})).json();
    if(!payload.success)throw new Error(payload.message||'실비 처리에 실패했습니다.');
    showToast(`실비 처리 완료 — ${docId} 매출 ${money.format(payload.data.closed_amount)}원으로 종결`);
    loadList().catch(showError);
  }catch(error){showToast(error.message,true)}
}
async function releaseExpenseClose(){
  const docId=$('rowContextMenu').dataset.docid;closeTaxMenu();if(!docId)return;
  if(!confirm(`${docId}\n실비 처리를 해제하고 원래 판정으로 되돌립니다. 진행할까요?`))return;
  try{
    const payload=await(await fetch('/api/receivables/expense-close/release',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({doc_id:docId})})).json();
    if(!payload.success)throw new Error(payload.message||'실비 처리 해제에 실패했습니다.');
    showToast(`실비 처리를 해제했습니다 — ${docId}`);
    loadList().catch(showError);
  }catch(error){showToast(error.message,true)}
}
$('issueTaxMenu').addEventListener('click',()=>{const docId=$('rowContextMenu').dataset.docid;closeTaxMenu();if(docId&&window.A10_TAX_ISSUE)window.A10_TAX_ISSUE(docId);});
$('expenseCloseMenu').addEventListener('click',markExpenseClose);
$('expenseReleaseMenu').addEventListener('click',releaseExpenseClose);
document.addEventListener('click',event=>{if(!$('rowContextMenu').contains(event.target))closeTaxMenu()});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeTaxMenu()});
window.addEventListener('blur',closeTaxMenu);window.addEventListener('resize',closeTaxMenu);window.addEventListener('scroll',closeTaxMenu,true);

function showError(error){$('resultSummary').textContent='조회하지 못했습니다';$('rows').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').classList.add('error');$('emptyList').innerHTML=`<strong>입금·미수금 목록을 불러오지 못했습니다</strong><span>${escapeHtml(error.message)}</span><br><button class="retry-button" type="button">다시 조회</button>`;$('emptyList').querySelector('button').addEventListener('click',()=>loadList().catch(showError));$('searchButton').disabled=false;$('searchButton').textContent='다시 조회'}
function sortByColumn(column){state.sortOrder=state.sortBy===column&&state.sortOrder==='asc'?'desc':'asc';state.sortBy=column;state.page=1;document.querySelectorAll('th[data-sort]').forEach(th=>{if(th.dataset.sort===column){th.setAttribute('aria-sort',state.sortOrder==='asc'?'ascending':'descending')}else{th.removeAttribute('aria-sort')}});loadList().catch(showError)}
function bindSortHeaders(){document.querySelectorAll('th[data-sort]').forEach(th=>{th.tabIndex=0;th.setAttribute('role','button');th.addEventListener('click',()=>sortByColumn(th.dataset.sort));th.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();sortByColumn(th.dataset.sort)}})})}
$('officeCode').addEventListener('change',()=>{state.page=1;state.selected=null;$('detailContent').classList.add('hidden');$('detailPlaceholder').classList.remove('hidden');loadList().catch(showError)});
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/receivables/export.xlsx?${buildListQuery()}`);});
$('printButton').addEventListener('click',()=>printList());

// ── 인쇄 ─────────────────────────────────────────────────────────
// 화면 한 페이지(30건)가 아니라 현재 검색 조건의 전체 목록을 뽑는다.
// 목록 API는 한 번에 100건까지라 나눠 받고, 너무 길어지지 않게 상한을 둔다.
const PRINT_MAX_ROWS=2000;
const PRINT_PAGE_SIZE=100;

// 입금상태 배지 (2026-09-03) — 감정서 LIST 처럼 매출총액 대비 입금으로 판정.
// 화면 숫자 기준인 statusOf 를 그대로 써 인쇄표·목록이 같은 값이 되게 한다.
function paymentBadge(row){const s=statusOf(row);return '<span class="payment-status payment-'+s+'">'+s+'</span>';}
function statusOf(row){
  const outstanding=Number(row.outstanding_amount||0),overpaid=Number(row.overpaid_amount||0);
  const received=Number(row.received_amount||0),billed=Number(row.billed_amount||0),advance=Number(row.advance_amount||0);
  // 산정액(masterex 청구금액) 대비 입금이 부족하면 전표상 완납이라도 부분입금으로 본다.
  // 공동감정 배분처럼 입금분만 계상돼 전표상으론 완납으로 잡히는 건을 잡아낸다.
  // 매출총액 기준으로 미수를 내므로 별도 산정액 대조가 필요 없다.
  const assessed=Number(row.invoice_total||row.assessed_billed||0);
  if(advance>0&&billed===0)return '선수금';
  if(overpaid>0)return '과입금';
  if(outstanding<=0&&billed>0)return assessed-received>1000?'부분입금':'완납';
  return received>0?'부분입금':'미입금';
}

async function fetchAllRows(){
  const items=[];
  let total=0;
  for(let page=1;page===1||(items.length<total&&items.length<PRINT_MAX_ROWS);page++){
    const query=buildListQuery();
    query.set('page',page);query.set('page_size',PRINT_PAGE_SIZE);
    const response=await fetch(`/api/receivables?${query}`);
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    total=payload.data.total;
    items.push(...payload.data.items);
    if(!payload.data.items.length)break;
  }
  return {items:items.slice(0,PRINT_MAX_ROWS),total};
}

// 인쇄물 머리말 조건 요약 — 기간(고른 기준의 이름으로)만 남긴다.
// 구분·본지사·상태·검색어는 숨긴다 (2026-08-04 재무팀 요청: 필터 표시 최소화).
function printConditions(){
  if($('dateFrom').value||$('dateTo').value)
    return `${dateBasisName()}일: ${$('dateFrom').value||''} ~ ${$('dateTo').value||''}`;
  return '';
}

function buildPrintHtml(items,total){
  const sum=key=>items.reduce((acc,row)=>acc+Number(row[key]||0),0);
  // 건수·출력시각 줄은 뺀다 (2026-08-05 요청). 단 상한에 걸려 일부만 찍힐 때는
  // 경고를 남긴다 — 잘린 인쇄물이 전체처럼 보이면 안 된다.
  const parts=[escapeHtml(printConditions())];
  if(items.length<total)parts.push(`⚠ 총 ${money.format(total)}건 중 ${money.format(items.length)}건만 인쇄 (상한 ${money.format(PRINT_MAX_ROWS)}건)`);
  const metaHtml=parts.filter(Boolean).length
    ?`<p class="print-meta">${parts.filter(Boolean).join('<br>')}</p>`:'';
  {
    // 열 재배치(2026-08-04 요청): 발송일·진행상태 추가, 최근 입금일은 맨 오른쪽.
    const rows=items.map(row=>`<tr>
      <td>${escapeHtml(row.doc_id)}</td><td>${escapeHtml(row.purpose||'-')}</td><td>${escapeHtml(row.eval_purpose||'-')}</td>
      <td>${escapeHtml(row.customer_name||'-')}</td><td class="left">${escapeHtml(row.address||'-')}</td><td>${escapeHtml(row.manager||'-')}</td><td>${escapeHtml(row.charge||'-')}</td><td>${dateText(row.send_date)}</td>
      <td class="number">${money.format(row.appraisal_amount||0)}</td><td class="number">${money.format(row.base_fee||0)}</td><td class="number">${money.format(row.travel_expense||0)}</td><td class="number">${money.format(row.survey_fee||0)}</td><td class="number">${money.format(row.document_fee||0)}</td><td class="number">${money.format(row.land_survey_fee||0)}</td><td class="number">${money.format(row.other_expense||0)}</td><td class="number">${money.format(row.special_service_fee||0)}</td>
      <td class="number">${money.format(row.sales_amount||0)}</td><td class="number">${money.format(row.vat_amount||0)}</td>
      <td class="number">${money.format(row.invoice_total||0)}</td>
      <td class="number">${money.format(row.existing_received_amount||0)}</td><td class="number">${money.format(row.daily_received_amount||0)}</td>
      <td class="number">${money.format(row.advance_amount||0)}</td><td class="number">${money.format(row.outstanding_amount||0)}</td>
      <td>${statusOf(row)}</td><td>${dateText(row.last_received_date)}</td>
    </tr>`).join('');
    return `<h1>입금 현황</h1>${metaHtml}
      <table><thead><tr><th>감정서번호</th><th>업무구분</th><th>평가목적</th><th>거래처명</th><th class="left">소재지</th><th>유치자</th><th>조사자</th><th>발송일</th>
      <th class="number">감정가액</th><th class="number">순수수료</th><th class="number" data-sort="travel_expense">여비</th><th class="number" data-sort="survey_fee">물건조사비</th><th class="number" data-sort="document_fee">공부발급비</th><th class="number" data-sort="land_survey_fee">토지조사비</th><th class="number" data-sort="other_expense">기타실비</th><th class="number" data-sort="special_service_fee">특별용역비</th><th class="number">매출액</th><th class="number">부가세</th>
      <th class="number">매출총액</th><th class="number">입금액(기)</th>
      <th class="number">입금액</th><th class="number">선수금</th><th class="number">미수금</th><th>진행상태</th><th>최근 입금일</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr class="print-total">
        <td colspan="8">합계 (${money.format(items.length)}건)</td><td></td>
        ${['base_fee','travel_expense','survey_fee','document_fee','land_survey_fee','other_expense','special_service_fee','sales_amount','vat_amount','invoice_total',
           'existing_received_amount','daily_received_amount','advance_amount']
          .map(key=>`<td class="number">${money.format(sum(key))}</td>`).join('')}
        <td class="number">${money.format(sum('outstanding_amount'))}</td><td></td><td></td>
      </tr></tfoot></table>`;
  }
}

// pdfFactory에서 표 오른쪽이 잘리던 문제(2026-08-06): 표 자연폭이 용지
// 인쇄폭을 넘으면 zoom으로 줄여 한 장 폭에 정확히 맞춘다. 화면 CSS에
// 인쇄와 같은 글꼴·패딩을 둬서 숨겨진 상태에서 잰 자연폭이 인쇄 때
// 폭과 같도록 했다(receivables.html 참고).
// Chromium 인쇄에서는 zoom 대상의 CSS px가 PDF에서 약 1.45배로 배치된다.
// 860px를 목표로 잡으면 A4 가로에서 좌우 약 15mm 여백이 실제로 균등해진다.
const PRINT_USABLE_WIDTH=860;
function fitPrintZoom(){
  const area=$('printArea');
  const table=area.querySelector('table');
  if(!table)return;
  const prev={display:area.style.display,position:area.style.position,left:area.style.left};
  Object.assign(area.style,{display:'block',position:'absolute',left:'-10000px'});
  table.style.zoom='1';
  table.style.width='max-content';
  const natural=table.scrollWidth;
  if(natural>PRINT_USABLE_WIDTH){
    table.style.zoom=(PRINT_USABLE_WIDTH/natural).toFixed(4);
    // auto 폭이면 인쇄 엔진이 축소 뒤 남은 공간만큼 표를 다시 늘려 오른쪽 여백을
    // 없앤다. 측정한 자연폭을 고정해야 zoom 결과와 margin:auto가 함께 유지된다.
    table.style.width=`${natural}px`;
  }else{
    table.style.zoom='1';
    table.style.width='100%';   // 좁은 표(미수금 현황 등)는 기존처럼 용지 폭을 채운다
  }
  Object.assign(area.style,prev);
}

async function printList(){
  const button=$('printButton');
  const label=button.textContent;
  button.disabled=true;button.textContent='준비 중...';
  try{
    const {items,total}=await fetchAllRows();
    if(!items.length){window.A10_TOAST('인쇄할 내역이 없습니다.',true);return;}
    $('printArea').innerHTML=buildPrintHtml(items,total);
    fitPrintZoom();
    // 인쇄 머리말 오른쪽의 '입금 현황 | 감정서 LIST'는 브라우저가 document.title을
    // 찍는 것이라 CSS로 못 지운다. 인쇄하는 순간만 제목을 비웠다가 되돌린다.
    const pageTitle=document.title;
    document.title=' ';
    try{ window.print(); } finally { document.title=pageTitle; }
  }catch(error){
    window.A10_TOAST(`인쇄 준비 실패: ${error.message}`,true);
  }finally{
    button.disabled=false;button.textContent=label;
  }
}
// 관리번호 복사 — 클릭하면 번호 전체가 선택되고, [복사] 버튼은 클립보드에 넣는다.
// http로 접속하는 사내망이라 navigator.clipboard를 못 쓴다(보안 컨텍스트 아님) →
// 임시 textarea + execCommand로 복사한다.
function copyText(text){
  const area=document.createElement('textarea');
  area.value=text;area.style.position='fixed';area.style.opacity='0';
  document.body.appendChild(area);area.select();
  let done=false;
  try{ done=document.execCommand('copy'); }catch(error){ done=false; }
  document.body.removeChild(area);
  return done;
}
$('selectedDocId').addEventListener('click',()=>{
  const range=document.createRange();range.selectNodeContents($('selectedDocId'));
  const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
});
$('copyDocId').addEventListener('click',()=>{
  const docId=$('selectedDocId').textContent.trim();
  if(!docId)return;
  const ok=copyText(docId);
  window.A10_TOAST(ok?`복사했습니다: ${docId}`:'복사하지 못했습니다. 번호를 긁어서 Ctrl+C 해주세요.',!ok);
});

// 상태 드롭다운: 버튼으로 열고, 바깥을 누르거나 Esc면 닫는다. 체크할 때마다 바로 조회.
function toggleStatusMenu(open){
  const menu=$('payStatusMenu');
  const show=open===undefined?menu.classList.contains('hidden'):open;
  menu.classList.toggle('hidden',!show);
  $('payStatusButton').setAttribute('aria-expanded',String(show));
}
$('payStatusButton').addEventListener('click',event=>{event.stopPropagation();toggleStatusMenu()});
$('payStatusMenu').addEventListener('click',event=>event.stopPropagation());
$('payStatusMenu').addEventListener('change',()=>{
  syncStatusButton();state.page=1;loadList().catch(showError);
});
$('payStatusClear').addEventListener('click',()=>{
  payStatusChecks().forEach(box=>{box.checked=false});
  syncStatusButton();state.page=1;loadList().catch(showError);
});
document.addEventListener('click',()=>toggleStatusMenu(false));
document.addEventListener('keydown',event=>{if(event.key==='Escape')toggleStatusMenu(false)});
syncStatusButton();

$('dateBasis').addEventListener('change',()=>{syncDateBasisLabels();state.page=1;loadList().catch(showError)});
$('searchButton').addEventListener('click',()=>{state.page=1;loadList().catch(showError)});['docId','customerName','manager','billFrom','billTo','outstandingFrom','outstandingTo'].forEach(id=>$(id).addEventListener('keydown',e=>{if(e.key==='Enter')$('searchButton').click()}));$('prevPage').addEventListener('click',()=>{if(state.page>1){state.page--;loadList().catch(showError)}});$('nextPage').addEventListener('click',()=>{state.page++;loadList().catch(showError)});syncModeUi();bindSortHeaders();
// 기본 기간: 어제 하루 (2026-08-05 요청. 그전에는 오늘 하루였다).
// setDate 는 월·해를 알아서 넘긴다 (1일이면 지난달 말일, 1월 1일이면 작년 12월 31일).
const today=new Date();
const yesterday=new Date(today);yesterday.setDate(today.getDate()-1);
$('dateFrom').value=inputDate(yesterday);$('dateTo').value=inputDate(yesterday);
// 컬럼 폭 드래그 조절 (column-resize.js 공통 유틸). 전표·계산서 표는 렌더링 시마다 부착한다.
// 저장키를 모드별로 나눈다 — 입금현황 18열 / 미수금현황 16열이라 키를 공유하면 폭이 밀린다.
window.A10_COLUMN_RESIZE($('receivableTable'),`a10.receivableTable.${state.mode}.columnWidths`);
window.A10_READY.then(()=>loadList().catch(showError));
