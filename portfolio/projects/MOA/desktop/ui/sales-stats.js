// 기간별 매출실적. 매출일(전표일자) 기준 공급가액.
// 왼쪽: 당기 매출 전표의 감정서별 상세(근거 자료), 오른쪽: 목적별 당기·전기 증감표.
// 전기는 직접 지정할 수 있고, 당기를 바꾸면 전년 동기로 자동 채워진다.
// 본·지사: 본사 사용자는 지사 선택(+전체) 가능, 지사 사용자는 자기 지사 고정
// (context.js가 officeCode 셀렉트를 권한대로 구성한다 — 입금현황과 같은 패턴).
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
// 증감표에서 분류를 클릭하면 왼쪽 상세를 그 분류만 보여준다 (다시 클릭·합계 클릭 시 해제)
let detailItems=[];
let purposeFilter=null;

function statsQuery(){
  const query=new URLSearchParams({date_from:$('dateFrom').value,date_to:$('dateTo').value,office_code:window.A10_OFFICE()});
  // 전기가 비어 있으면 서버가 전년 동기로 계산한다 (2/29 등 자동 제안 실패 대비)
  if($('prevFrom').value&&$('prevTo').value){
    query.set('prev_from',$('prevFrom').value);
    query.set('prev_to',$('prevTo').value);
  }
  return query;
}

function detailQuery(){
  return new URLSearchParams({date_from:$('dateFrom').value,date_to:$('dateTo').value,office_code:window.A10_OFFICE()});
}

async function loadStats(){
  $('resultSummary').textContent='조회 중...';
  const response=await fetch(`/api/sales-stats?${statsQuery()}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const {rows,period,prev_period}=payload.data;
  // 기간은 둘째 줄 작은 글씨로 — 머리말이 길어져 금액 칸이 밀리지 않게 한다
  $('curHead').innerHTML=`당기<small>${escapeHtml(period.from)} ~ ${escapeHtml(period.to)}</small>`;
  $('prevHead').innerHTML=`전기<small>${escapeHtml(prev_period.from)} ~ ${escapeHtml(prev_period.to)}</small>`;
  const officeSelect=$('officeCode');
  const officeName=officeSelect&&officeSelect.selectedIndex>=0?officeSelect.options[officeSelect.selectedIndex].textContent:'본사';
  $('resultSummary').textContent=`매출일(전표일자) 기준 공급가액 · ${officeName}`;
  $('statsRows').innerHTML=rows.map(row=>{
    const isTotal=row.purpose==='합계';
    const rate=row.rate==null?'-':`${row.rate>0?'+':''}${row.rate.toFixed(1)}`;
    // 달성률 = 당기 ÷ 전기. 100% 미만이면 증감률과 같은 기준으로 빨간색.
    const achievement=row.achievement==null?'-':row.achievement.toFixed(1);
    return `<tr${isTotal?' class="total-row"':''} data-purpose="${escapeHtml(row.purpose)}">
      <td class="purpose-cell">${escapeHtml(row.purpose)}</td>
      <td class="number">${row.docs?money.format(row.docs):'-'}</td>
      <td class="number">${money.format(Math.round(row.amount))}</td>
      <td class="number">${row.prev_docs?money.format(row.prev_docs):'-'}</td>
      <td class="number">${money.format(Math.round(row.prev_amount))}</td>
      <td class="number${row.diff<0?' rate-down':''}">${money.format(Math.round(row.diff))}</td>
      <td class="number${row.rate!=null&&row.rate<0?' rate-down':''}">${rate}</td>
      <td class="number${row.achievement!=null&&row.achievement<100?' rate-down':''}">${achievement}</td>
    </tr>`;
  }).join('');
  document.querySelectorAll('#statsRows tr').forEach(row=>row.addEventListener('click',()=>togglePurposeFilter(row.dataset.purpose)));
  stickySecondHeaderRow($('statsTable'));
  if(window.A10_COLUMN_RESIZE)window.A10_COLUMN_RESIZE($('statsTable'),'sales-stats-cols');
}

function togglePurposeFilter(purpose){
  purposeFilter=(purpose==='합계'||purposeFilter===purpose)?null:purpose;
  document.querySelectorAll('#statsRows tr').forEach(tr=>tr.classList.toggle('filter-on',purposeFilter!==null&&tr.dataset.purpose===purposeFilter));
  renderDetailRows();
}

// 2단 머리말: 둘째 줄이 첫 줄과 겹치지 않도록 첫 줄 높이만큼 내려 고정한다
function stickySecondHeaderRow(table){
  const firstRow=table&&table.querySelector('thead tr');
  if(!firstRow)return;
  const height=firstRow.getBoundingClientRect().height;
  table.querySelectorAll('thead tr:nth-child(2) th').forEach(th=>{th.style.top=`${height}px`});
}

async function loadDetail(){
  $('detailSummary').textContent='조회 중...';
  const response=await fetch(`/api/sales-stats/detail?${detailQuery()}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  detailItems=payload.data.items;
  renderDetailRows();
}

function renderDetailRows(){
  const items=purposeFilter?detailItems.filter(item=>(item.work_type||'기타')===purposeFilter):detailItems;
  const filterText=purposeFilter?` · ${purposeFilter}만 표시 (해제하려면 오른쪽 표에서 다시 클릭)`:'';
  $('detailSummary').textContent=`${money.format(items.length)}건 · 전표일자 최신순${filterText}`;
  $('detailEmpty').classList.toggle('hidden',items.length!==0);
  // 열 순서: 감정서번호·발송일자·감정목적·업무구분·전표매출액·전표일자·거래처 (2026-08-27 사용자 요청), 나머지는 뒤에
  $('detailRows').innerHTML=items.map(item=>`<tr>
    <td class="${item.doc_id==='국민 약식수수료'?'kb-yak-label':''}">${escapeHtml(item.doc_id)}</td>
    <td>${escapeHtml(item.send_date||'-')}</td>
    <td>${escapeHtml(item.purpose_detail||'-')}</td>
    <td>${escapeHtml(item.work_type||'-')}</td>
    <td class="number">${money.format(Math.round(item.voucher_amount))}</td>
    <td>${escapeHtml(item.voucher_date||'-')}</td>
    <td title="${escapeHtml(item.customer_name||'')}">${escapeHtml(item.customer_name||'-')}</td>
    <td>${escapeHtml(item.manager||'-')}</td>
    <td>${escapeHtml(item.investigator||'-')}</td>
    <td class="number">${money.format(Math.round(item.base_fee))}</td>
    <td class="number">${money.format(Math.round(item.billed_amount))}</td>
  </tr>`).join('');
  window.A10_COLUMN_RESIZE&&window.A10_COLUMN_RESIZE($('detailTable'),'sales-stats-detail-cols');
}

// pdfFactory에서 표 오른쪽이 잘리던 문제(receivables.js와 같은 방식) — 표
// 자연폭이 인쇄폭을 넘으면 zoom으로 줄여 한 장 폭에 맞춘다.
const PRINT_USABLE_WIDTH=990; // A4 가로 297mm − 좌우 패딩 30mm ≈ 267mm @96dpi
function fitPrintZoom(){
  const area=$('printArea');
  const prev={display:area.style.display,position:area.style.position,left:area.style.left};
  Object.assign(area.style,{display:'block',position:'absolute',left:'-10000px'});
  area.querySelectorAll('table').forEach(table=>{
    table.style.zoom='1';
    const natural=table.scrollWidth;
    if(natural>PRINT_USABLE_WIDTH){
      table.style.zoom=(PRINT_USABLE_WIDTH/natural).toFixed(4);
      table.style.width='auto';
    }else{
      table.style.zoom='1';
      table.style.width='100%';
    }
  });
  Object.assign(area.style,prev);
}

function buildDetailPrintTable(){
  const items=purposeFilter?detailItems.filter(item=>(item.work_type||'기타')===purposeFilter):detailItems;
  const sum=key=>items.reduce((acc,item)=>acc+Number(item[key]||0),0);
  // 인쇄도 화면과 같은 열 순서. 거래처만 왼쪽 정렬(class="left"), 나머지는 CSS 로 가운데.
  const rows=items.map(item=>`<tr>
    <td>${escapeHtml(item.doc_id)}</td>
    <td>${escapeHtml(item.send_date||'-')}</td>
    <td>${escapeHtml(item.purpose_detail||'-')}</td>
    <td>${escapeHtml(item.work_type||'-')}</td>
    <td class="number">${money.format(Math.round(item.voucher_amount))}</td>
    <td>${escapeHtml(item.voucher_date||'-')}</td>
    <td class="left">${escapeHtml(item.customer_name||'-')}</td>
    <td>${escapeHtml(item.manager||'-')}</td>
    <td>${escapeHtml(item.investigator||'-')}</td>
    <td class="number">${money.format(Math.round(item.base_fee))}</td>
    <td class="number">${money.format(Math.round(item.billed_amount))}</td>
  </tr>`).join('');
  const filterNote=purposeFilter?` · ${escapeHtml(purposeFilter)}만`:'';
  return `<p class="print-meta">${money.format(items.length)}건${filterNote}</p>
    <table><thead><tr>
      <th>감정서번호</th><th>발송일자</th><th>감정목적</th><th>업무구분</th>
      <th class="number">전표매출액</th><th>전표일자</th><th class="left">거래처</th>
      <th>담당자</th><th>조사자</th><th class="number">순수수료</th><th class="number">청구액</th>
    </tr></thead><tbody>${rows}</tbody>
    <tfoot><tr class="print-total">
      <td colspan="4">합계</td>
      <td class="number">${money.format(sum('voucher_amount'))}</td>
      <td></td><td class="left"></td><td></td><td></td>
      <td class="number">${money.format(sum('base_fee'))}</td>
      <td class="number">${money.format(sum('billed_amount'))}</td>
    </tr></tfoot></table>`;
}

function printReport(){
  const button=$('printButton');
  const label=button.textContent;
  button.disabled=true;button.textContent='준비 중...';
  try{
    if(!detailItems.length){window.A10_TOAST('인쇄할 내역이 없습니다.',true);return;}
    const officeSelect=$('officeCode');
    const officeName=officeSelect&&officeSelect.selectedIndex>=0?officeSelect.options[officeSelect.selectedIndex].textContent:'본사';
    const period=`${$('dateFrom').value} ~ ${$('dateTo').value}`;
    $('printArea').innerHTML=`<h1>기간별 매출실적 — 매출 상세</h1><p class="print-meta">${escapeHtml(officeName)} · 당기 ${escapeHtml(period)}</p>
      ${buildDetailPrintTable()}`;
    fitPrintZoom();
    const pageTitle=document.title;
    document.title=' ';
    try{ window.print(); } finally { document.title=pageTitle; }
  }catch(error){
    window.A10_TOAST(`인쇄 준비 실패: ${error.message}`,true);
  }finally{
    button.disabled=false;button.textContent=label;
  }
}
$('printButton').addEventListener('click',printReport);

function loadAll(){
  purposeFilter=null;  // 새 조회 시 분류 필터 해제
  loadStats().catch(showStatsError);
  loadDetail().catch(showDetailError);
}

function showStatsError(error){$('resultSummary').textContent='조회하지 못했습니다';$('statsRows').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').textContent=error.message}
function showDetailError(error){$('detailSummary').textContent='조회하지 못했습니다';$('detailRows').innerHTML='';$('detailEmpty').classList.remove('hidden');$('detailEmpty').textContent=error.message}

const inputDate=value=>{
  const year=value.getFullYear();const month=String(value.getMonth()+1).padStart(2,'0');const day=String(value.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
};

// 당기를 바꾸면 전기를 전년 동기로 자동 제안한다 (그 후 직접 수정 가능)
function suggestPrevPeriod(){
  ['dateFrom','dateTo'].forEach((id,index)=>{
    const value=$(id).value;
    if(!value)return;
    const target=index===0?'prevFrom':'prevTo';
    const [year,month,day]=value.split('-');
    $(target).value=`${Number(year)-1}-${month}-${day}`;
  });
}

// 기본 기간: 당기 = 오늘 하루, 전기 = 전년 같은 날 (2026-08-03 사용자 요청).
// 시작일을 종료일과 같은 날로 둔다 — 연초부터 잡아두면 매번 시작일을 고쳐야 했다.
const today=new Date();
$('dateFrom').value=inputDate(today);
$('dateTo').value=inputDate(today);
suggestPrevPeriod();

['dateFrom','dateTo'].forEach(id=>$(id).addEventListener('change',suggestPrevPeriod));
$('searchButton').addEventListener('click',loadAll);
['dateFrom','dateTo','prevFrom','prevTo'].forEach(id=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter')$('searchButton').click()}));
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/sales-stats/export.xlsx?${statsQuery()}`);});
$('detailExportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/sales-stats/detail-export.xlsx?${detailQuery()}`);});

$('officeCode').addEventListener('change',loadAll);
window.A10_READY.then(()=>loadAll());
