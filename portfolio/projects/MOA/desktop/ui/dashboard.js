// app/static/dashboard.js 이식본 (데스크톱).
// 웹 버전과의 차이는 두 곳뿐이므로 원본과 diff 하면 재이식이 쉽다:
//  1) loadOffices() 없음 — 지사 셀렉트는 context.js가 사용자 권한에 맞춰 채우고 잠근다.
//  2) 최초 조회를 window.A10_READY(사용자 확인) 이후로 미룬다.
const state={page:1,pageSize:30,total:0,selected:null,sortBy:null,sortOrder:'asc'};
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const dateText=value=>value?String(value).slice(0,10):'-';
const accountLabels={'1080000':'외상매출금','4010001':'감정수수료','8120000':'여비교통비','2550000':'부가세예수금','1030000':'보통예금','2570000':'가수금','2590000':'선수금'};
const accountName=line=>line.account_name||line.acctNm||accountLabels[String(line.account_code||line.acctCd||'')]||line.account_code||line.acctCd||'계정 미지정';
const inputDate=value=>{
  const year=value.getFullYear();const month=String(value.getMonth()+1).padStart(2,'0');const day=String(value.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
};
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const sortLabels={doc_id:'감정서번호',cust_doc_id:'의뢰번호',receipt_date:'접수일',address:'소재지',customer_name:'거래처',title:'건명',debtor:'채무자',owner_name:'소유자',manager:'담당자',author:'조사자',purpose:'업무구분',eval_purpose:'평가목적',progress_status:'진행상태',send_date:'발송일',appraisal_amount:'감정가액',base_fee:'순수수료',appraisal_cost:'여비및기타',sales_amount:'수수료합계',vat_amount:'부가세',gross_total:'매출총액',travel_expense:'여비',survey_fee:'물건조사비',document_fee:'공부발급비',land_survey_fee:'토지조사비',other_expense:'기타실비',special_service_fee:'특별용역비'};
// 세금계산서/현금영수증 발행여부 (2026-08-27) — 입금현황(receivables.js)과 같은 칸·같은 값('발행' 하나, 내역은 툴팁).
const proofIssuedCell=row=>{
  const tips=[];
  if(row.tax_issued)tips.push('계산서 '+Number(row.tax_issued_slips||0)+'장 · '+money.format(Number(row.tax_issued_amount||0))+'원');
  if(row.cash_issued)tips.push('현금영수증 '+Number(row.cash_issued_slips||0)+'건 · '+money.format(Number(row.cash_issued_amount||0))+'원');
  if(!tips.length)return row.card_sales?'<span class="tax-issued card" title="카드매출 — 세금계산서 불필요">카드</span>':'<span class="dim">-</span>';
  return '<span class="tax-issued" title="'+escapeHtml(tips.join(' / '))+'">발행</span>';
};
// 발행금액 (2026-09-03) — 세금계산서+현금영수증 발행 순액 합계. 취소분은 빠진 값이라
// 이미 얼마 나갔는지 목록에서 바로 보인다(중복 발급 방지에도 쓰인다).
const proofAmountCell=row=>{const amount=Number(row.proof_issued_amount||0);return amount>0?money.format(amount):'<span class="dim">-</span>';};
function renderLoading(){ const columns=document.querySelectorAll('#appraisalTable thead th').length;$('emptyList').classList.add('hidden');$('emptyList').classList.remove('error');$('appraisalRows').innerHTML=Array.from({length:7},()=>`<tr class="skeleton-row">${Array.from({length:columns},()=>'<td><span></span></td>').join('')}</tr>`).join(''); }

// 현재 검색 조건·정렬을 쿼리로 만든다 (목록 조회와 엑셀 내보내기가 공유).
function buildListQuery(){
  const query=new URLSearchParams({office_code:window.A10_OFFICE()});
  const filters={keyword:'keyword',docId:'doc_id',custDocId:'cust_doc_id',address:'address',customerName:'customer_name',manager:'manager',charge:'charge',purpose:'purpose'};
  Object.entries(filters).forEach(([inputId,param])=>{const value=$(inputId).value.trim();if(value)query.set(param,value);});
  if($('dateFrom').value)query.set('date_from',$('dateFrom').value);
  if($('dateTo').value)query.set('date_to',$('dateTo').value);
  if($('billFrom').value.trim())query.set('bill_from',$('billFrom').value.trim());
  if($('billTo').value.trim())query.set('bill_to',$('billTo').value.trim());
  if($('priceFrom').value.trim())query.set('price_from',$('priceFrom').value.trim());
  if($('priceTo').value.trim())query.set('price_to',$('priceTo').value.trim());
  if(state.sortBy){query.set('sort_by',state.sortBy);query.set('sort_order',state.sortOrder);}
  return query;
}

async function loadList(){
  const query=buildListQuery();
  query.set('page',state.page);query.set('page_size',state.pageSize);
  $('resultSummary').textContent='조회 중...';$('searchButton').disabled=true;$('searchButton').textContent='조회 중';renderLoading();
  const response=await fetch(`/api/appraisals?${query}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const data=payload.data;state.total=data.total;
  const sortText=state.sortBy?` / ${sortLabels[state.sortBy]} ${state.sortOrder==='asc'?'오름차순':'내림차순'}`:'';$('resultSummary').textContent=`총 ${money.format(data.total)}건 · ${data.page}페이지${sortText}`;
  $('emptyList').textContent='조건에 맞는 감정서가 없습니다.';$('emptyList').classList.remove('error');
  $('emptyList').classList.toggle('hidden',data.items.length!==0);
  // 열 구성 2026-09-01 사용자 확정 (dashboard.html 주석 참조).
  // 입금액·입금일·미수금은 입금현황과 같은 판정식(attach_payment_amounts)이다.
  $('appraisalRows').innerHTML=data.items.map(row=>`<tr data-docid="${escapeHtml(row.doc_id)}" class="${state.selected===row.doc_id?'selected':''}">
    <td>${escapeHtml(row.doc_id)}</td>
    <td><span class="payment-status payment-${escapeHtml(row.payment_status||'미확인')}">${escapeHtml(row.payment_status||'미확인')}</span></td>
    <td>${dateText(row.receipt_date)}</td><td>${dateText(row.send_date)}</td>
    <td title="${escapeHtml(row.purpose||'')}">${escapeHtml(row.purpose||'-')}</td>
    <td title="${escapeHtml(row.eval_purpose||'')}">${escapeHtml(row.eval_purpose||'-')}</td>
    <td title="${escapeHtml(row.customer_name||'')}">${escapeHtml(row.customer_name||'-')}</td>
    <td title="${escapeHtml(row.title||'')}">${escapeHtml(row.title||'-')}</td>
    <td title="${escapeHtml(row.cust_doc_id||'')}">${escapeHtml(row.cust_doc_id||'-')}</td>
    <td title="${escapeHtml(row.debtor||'')}">${escapeHtml(row.debtor||'-')}</td>
    <td title="${escapeHtml(row.owner_name||'')}">${escapeHtml(row.owner_name||'-')}</td>
    <td title="${escapeHtml(row.address)}">${escapeHtml(row.address||'-')}</td>
    <td>${escapeHtml(row.manager||'-')}</td><td>${escapeHtml(row.author||'-')}</td>
    <td class="number">${money.format(row.appraisal_amount||0)}</td>
    <td class="number">${money.format(row.base_fee||0)}</td>
    <td class="number">${money.format(row.travel_expense||0)}</td>
    <td class="number">${money.format(row.survey_fee||0)}</td>
    <td class="number">${money.format(row.document_fee||0)}</td>
    <td class="number">${money.format(row.land_survey_fee||0)}</td>
    <td class="number">${money.format(row.other_expense||0)}</td>
    <td class="number">${money.format(row.special_service_fee||0)}</td>
    <td class="number">${money.format(row.sales_amount||0)}</td>
    <td class="number">${money.format(row.vat_amount||0)}</td>
    <td class="number">${money.format(row.gross_total||0)}</td>
    <td class="number received">${money.format(row.received_total||0)}</td>
    <td>${dateText(row.last_received_date)}</td>
    <td class="number outstanding">${money.format(row.outstanding_amount||0)}</td>
    <td class="proof-cell">${proofIssuedCell(row)}</td>
    <td class="number">${proofAmountCell(row)}</td>
  </tr>`).join('');
  document.querySelectorAll('#appraisalRows tr').forEach(row=>{
    row.addEventListener('click',()=>selectDoc(row.dataset.docid,row));
    row.addEventListener('contextmenu',event=>openContextMenu(event,row));
  });
  const pages=Math.max(1,Math.ceil(state.total/state.pageSize));$('pageLabel').textContent=`${state.page} / ${pages}`;
  $('prevPage').disabled=state.page<=1;$('nextPage').disabled=state.page>=pages;$('searchButton').disabled=false;$('searchButton').textContent='조회';
}

// 청구서상 수수료 내역. 항목합 - 절사금액 = 수수료합계, 수수료합계 + 부가세 = 청구금액.
// 금액이 0인 부가 항목(토지조사비/절사금액)은 있을 때만 표시한다.
// 특별용역비는 0이어도 늘 보인다 (2026-08-20 사용자 요청) — 실비 아래에서
// '없음'을 눈으로 확인하는 자리다. 실제로 값이 붙는 건은 73만 건 중 8,289건뿐이라
// 숨겨 두면 있는지조차 모른다.
function renderFeeSummary(fee){
  const panel=$('feeSummary');
  if(!fee){panel.classList.add('hidden');return;}
  const rows=[
    ['평가액', fee.appraisal_amount],
    ['순수수료', fee.base_fee],
    ['여비', fee.travel_expense],
    ['물건조사비', fee.survey_fee],
    ['토지조사비', fee.land_survey_fee, true],
    ['공부발급비', fee.document_fee],
    ['기타실비', fee.other_expense],
    ['특별용역비', fee.special_service_fee],
    ['절사금액', fee.rounding_off, true],
    ['수수료합계', fee.fee_total, false, 'sum'],
    ['부가세', fee.vat],
    ['청구금액', fee.billed_amount, false, 'total'],
  ];
  $('feeSummaryRows').innerHTML=rows
    .filter(([,value,onlyWhenSet])=>!onlyWhenSet||Number(value||0)!==0)
    .map(([label,value,,emphasis])=>`<div class="${emphasis||''}"><dt>${label}</dt><dd>${money.format(Number(value||0))}</dd></div>`)
    .join('');
  panel.classList.remove('hidden');
}

// 세금계산서 내역 (TAMS 캐시). 전표 아래 한 표로 표시한다.
function renderTaxInvoices(taxes){
  $('taxEmpty').classList.toggle('hidden',taxes.length!==0);
  $('taxList').innerHTML=taxes.length?`<section class="voucher"><div class="voucher-grid-wrap"><table class="voucher-grid"><colgroup><col style="width:82px"><col style="width:150px"><col style="width:62px"><col style="width:76px"><col style="width:100px"><col style="width:76px"><col style="width:76px"><col style="width:76px"></colgroup><thead><tr><th>발행일자</th><th>상호</th><th>상태</th><th>발행유형</th><th>승인번호</th><th class="number">공급가액</th><th class="number">세액</th><th class="number">합계금액</th></tr></thead>
    <tbody>${taxes.map(tax=>`<tr><td>${dateText(tax.tax_date)}</td><td class="ellipsis" title="${escapeHtml(tax.company_name||'')}">${escapeHtml(tax.company_name||'-')}</td><td>${escapeHtml(tax.status||'-')}</td><td>${escapeHtml(tax.issue_type||'-')}</td><td class="ellipsis" title="${escapeHtml(tax.approval_no||'')}">${escapeHtml(tax.approval_no||'-')}</td><td class="number">${money.format(tax.supply_amount||0)}</td><td class="number">${money.format(tax.vat_amount||0)}</td><td class="number">${money.format(tax.total_amount||0)}</td></tr>`).join('')}</tbody></table></div></section>`:'';
  window.A10_COLUMN_RESIZE(document.querySelector('#taxList table'),'a10.taxGrid.columnWidths');
}

async function selectDoc(docId,row){
  state.selected=docId;document.querySelectorAll('#appraisalRows tr').forEach(item=>item.classList.remove('selected'));row.classList.add('selected');
  $('detailPlaceholder').classList.add('hidden');$('detailContent').classList.remove('hidden');$('selectedDocId').textContent=docId;$('matchBadge').textContent='조회 중';
  const response=await fetch(`/api/appraisals/${encodeURIComponent(docId)}/vouchers`);const payload=await response.json();
  if(!payload.success){$('matchBadge').textContent='조회 실패';return;}
  renderFeeSummary(payload.data.fee_summary);
  renderTaxInvoices(payload.data.tax_invoices||[]);
  const items=payload.data.items;$('matchBadge').textContent=items.length?`${items.length}건 연결`:'미연결';$('voucherEmpty').classList.toggle('hidden',items.length!==0);
  const debitTotal=items.reduce((sum,voucher)=>sum+Number(voucher.debit_total||0),0);
  const creditTotal=items.reduce((sum,voucher)=>sum+Number(voucher.credit_total||0),0);
  $('voucherList').innerHTML=items.length?`<section class="voucher"><div class="voucher-grid-wrap"><table class="voucher-grid"><colgroup><col style="width:82px"><col style="width:92px"><col style="width:110px"><col style="width:110px"><col style="width:76px"><col style="width:76px"><col style="width:140px"></colgroup><thead><tr><th>전표일자</th><th>전표번호</th><th>계정과목</th><th>거래처</th><th class="number">차변금액</th><th class="number">대변금액</th><th>적요</th></tr></thead>
    <tbody>${items.flatMap(voucher=>(voucher.lines||[]).map(line=>{const amount=Number(line.amount||line.acctAm||0);const isDebit=String(line.debit_credit||line.drcrFg)==='3';const bundle=line.allocated&&voucher.batch_settlement?`<small class="bundle-note" title="${escapeHtml(voucher.batch_note||'')}"><span class="bundle-badge">여러 건 묶음</span>${escapeHtml(voucher.batch_doc_count||'')}건 · 원전표 ${money.format(voucher.original_cash_amount||0)}</small>`:'';const off=line.offset?`<span class="offset-badge" title="${escapeHtml(line.offset_note||'')}">반제</span>`:'';return `<tr${line.offset?' class="offset"':''}><td>${dateText(voucher.voucher_date)}</td><td title="${escapeHtml(voucher.status||'')}">${escapeHtml(voucher.source_voucher_no)}</td><td><strong>${off}${escapeHtml(accountName(line))}</strong>${bundle}</td><td class="ellipsis" title="${escapeHtml(line.partner_name||'')}">${escapeHtml(line.partner_name||'-')}</td><td class="number debit">${isDebit?money.format(amount):'-'}</td><td class="number credit">${isDebit?'-':money.format(amount)}</td><td class="ellipsis" title="${escapeHtml(line.remark||line.rmkDc||'')}">${escapeHtml(line.remark||line.rmkDc||'-')}</td></tr>`;})).join('')}</tbody>
    <tfoot><tr><th colspan="4"><span>합계</span> ${debitTotal===creditTotal?'<span class="balanced">일치</span>':'<span class="unbalanced">불일치</span>'}</th><th class="number">${money.format(debitTotal)}</th><th class="number">${money.format(creditTotal)}</th><th></th></tr></tfoot></table></div></section>`:'';
  window.A10_COLUMN_RESIZE(document.querySelector('#voucherList table'),'a10.voucherGrid.columnWidths');
  // 적요로만 붙은 경비 줄(expense_items)은 전표내용엔 안 넣고 비용 지급내역에만 합친다 (2026-09-10)
  renderPaid(items.concat(payload.data.expense_items||[]),docId);
}

// 감정서별 비용 지급내역 — 이미 받아 온 전표에서 이 감정서의 비용 줄만 골라 낸다.
// 새로 조회하지 않는다. 8 계열이 비용이다: 8310000 지급수수료(카드·이체 수수료가
// 입금에서 떼인 것), 8600000 협회비(감정평가사협회 심사비), 8170000 세금과공과금,
// 8210000 보험료, 8120000 여비교통비(2026-08-21부터 재무팀이 관리번호를 붙인다).
//
// **본사 기준(2026-09-10 사용자 확정): 적요가 이 감정서번호로 시작하는 줄만** 본다.
// 경비 줄은 재무팀이 관리항목에 감정서번호를 넣지 않고 적요 맨 앞에 적는다. 관리번호로는
// 고르지 않는다 — 지사가 관리번호에 넣고 적요엔 다른 번호를 적은 줄(02 지사 협회비)이
// 엉뚱한 감정서에 붙었다. 적요 줄은 서버가 expense_items 로 따로 내려 전표내용에는 안 섞인다.
// 전표 목록은 감정서가 걸린 전표의 라인을
// 전부 내려주는데, 회계가 여러 건의 지출을 한 전표에 몰아 넣기 때문이다 — 계정만
// 보고 고르면 남의 지출이 딸려 온다 (실측 01-2605-3-1707: 그 감정서 줄은 가수금
// 27,500 하나뿐인데 같은 전표에 여비교통비·광고선전비·소모품비 28만원이 섞여 있다).
// 8 계열 차변 12.7만 줄 중 관리번호가 붙은 것은 354줄뿐이다.
const PAID_ACCOUNT_PREFIX='8';
function renderPaid(items,docId){
  const mine=String(docId||'').trim();
  const rows=(items||[]).flatMap(voucher=>(voucher.lines||[])
    .filter(line=>String(line.account_code||line.acctCd||'').startsWith(PAID_ACCOUNT_PREFIX)
      && String(line.debit_credit||line.drcrFg)==='3'
      && String(line.remark||line.rmkDc||'').trim().startsWith(mine))
    .map(line=>({voucher,line})));
  $('paidEmpty').classList.toggle('hidden',rows.length!==0);
  if(!rows.length){$('paidList').innerHTML='';return}
  const total=rows.reduce((sum,{line})=>sum+Number(line.amount||line.acctAm||0),0);
  $('paidList').innerHTML=`<section class="voucher"><div class="voucher-grid-wrap"><table class="voucher-grid">
    <colgroup><col style="width:82px"><col style="width:110px"><col style="width:130px"><col style="width:90px"><col></colgroup>
    <thead><tr><th>전표일자</th><th>계정과목</th><th>거래처</th><th class="number">지급액</th><th>적요</th></tr></thead>
    <tbody>${rows.map(({voucher,line})=>`<tr>
      <td>${dateText(voucher.voucher_date)}</td>
      <td><strong>${escapeHtml(accountName(line))}</strong></td>
      <td class="ellipsis" title="${escapeHtml(line.partner_name||'')}">${escapeHtml(line.partner_name||'-')}</td>
      <td class="number debit">${money.format(Number(line.amount||line.acctAm||0))}</td>
      <td class="ellipsis" title="${escapeHtml(line.remark||line.rmkDc||'')}">${escapeHtml(line.remark||line.rmkDc||'-')}</td>
    </tr>`).join('')}</tbody>
    <tfoot><tr><th colspan="3">합계</th><th class="number">${money.format(total)}</th><th></th></tr></tfoot>
  </table></div></section>`;
  window.A10_COLUMN_RESIZE(document.querySelector('#paidList table'),'a10.paidGrid.columnWidths');
}

// 관리번호 복사 — 클릭하면 번호 전체가 선택되고, [복사] 버튼은 클립보드에 넣는다.
// http로 접속하는 사내망이라 navigator.clipboard를 못 쓴다(보안 컨텍스트 아님) →
// 임시 textarea + execCommand로 복사한다 (receivables.js와 같은 방식).
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
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/appraisals/export.xlsx?${buildListQuery()}`);});
$('searchButton').addEventListener('click',()=>{state.page=1;loadList().catch(showError)});['keyword','docId','custDocId','address','customerName','manager','charge','purpose','billFrom','billTo','priceFrom','priceTo'].forEach(id=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter'){$('searchButton').click();}}));
$('officeCode').addEventListener('change',()=>{state.page=1;state.selected=null;$('detailContent').classList.add('hidden');$('detailPlaceholder').classList.remove('hidden');loadList().catch(showError)});
$('prevPage').addEventListener('click',()=>{if(state.page>1){state.page--;loadList().catch(showError);}});$('nextPage').addEventListener('click',()=>{state.page++;loadList().catch(showError);});
function showError(error){$('resultSummary').textContent='조회하지 못했습니다';$('appraisalRows').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').classList.add('error');$('emptyList').innerHTML=`<strong>감정서 목록을 불러오지 못했습니다</strong><span>${escapeHtml(error.message)}</span><br><button class="retry-button" type="button">다시 조회</button>`;$('emptyList').querySelector('button').addEventListener('click',()=>loadList().catch(showError));$('searchButton').disabled=false;$('searchButton').textContent='다시 조회';}
function sortByColumn(column){state.sortOrder=state.sortBy===column&&state.sortOrder==='asc'?'desc':'asc';state.sortBy=column;state.page=1;document.querySelectorAll('th[data-sort]').forEach(th=>{if(th.dataset.sort===column){th.setAttribute('aria-sort',state.sortOrder==='asc'?'ascending':'descending')}else{th.removeAttribute('aria-sort')}});loadList().catch(showError)}
document.querySelectorAll('th[data-sort]').forEach(th=>{th.tabIndex=0;th.setAttribute('role','button');th.addEventListener('click',()=>sortByColumn(th.dataset.sort));th.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();sortByColumn(th.dataset.sort)}})});
function openContextMenu(event,row){
  event.preventDefault();state.selected=row.dataset.docid;
  document.querySelectorAll('#appraisalRows tr').forEach(item=>item.classList.remove('selected'));row.classList.add('selected');
  const menu=$('rowContextMenu');menu.dataset.docid=row.dataset.docid;menu.classList.remove('hidden');
  const width=menu.offsetWidth,height=menu.offsetHeight;
  menu.style.left=`${Math.min(event.clientX,window.innerWidth-width-8)}px`;menu.style.top=`${Math.min(event.clientY,window.innerHeight-height-8)}px`;
  $('createVoucherMenu').focus();
}
function closeContextMenu(){$('rowContextMenu').classList.add('hidden')}
function showToast(message,isError=false){const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}
let voucherContext=null,selectedPartner=null;
function setDialogError(message=''){const element=$('partnerDialogError');element.textContent=message;element.classList.toggle('hidden',!message)}
function partnerText(value){return value||'-'}
function renderPartnerResults(items){
  selectedPartner=null;$('confirmVoucherButton').disabled=true;
  $('partnerResults').innerHTML=items.length?items.map((partner,index)=>`<label class="partner-option"><input type="radio" name="amaranthPartner" value="${escapeHtml(partner.partner_code)}" data-index="${index}"><span><strong>${escapeHtml(partner.name||'-')}</strong><small>${escapeHtml(partner.business_no||'사업자번호 없음')} · ${escapeHtml(partner.representative||'대표자 미등록')}</small></span><code>${escapeHtml(partner.partner_code||'-')}</code></label>`).join(''):'<div class="partner-no-results">일치하는 Amaranth 거래처가 없습니다.<br>검색어를 바꾸거나 신규 거래처를 추가해 주세요.</div>';
  document.querySelectorAll('input[name="amaranthPartner"]').forEach(input=>input.addEventListener('change',()=>{selectedPartner=items[Number(input.dataset.index)];$('confirmVoucherButton').disabled=false;setDialogError()}));
}
async function searchPartners(search){
  if(!voucherContext)return;setDialogError();$('partnerResults').innerHTML='<div class="partner-no-results">검색 중...</div>';
  try{const query=new URLSearchParams({company_code:voucherContext.company_code,search,page:'1',page_size:'50'});const response=await fetch(`/api/partners?${query}`);const payload=await response.json();if(!payload.success)throw new Error(payload.message);renderPartnerResults(payload.data.items||[])}catch(error){renderPartnerResults([]);setDialogError(error.message)}
}
async function openPartnerDialog(){
  const docId=$('rowContextMenu').dataset.docid;closeContextMenu();if(!docId)return;
  await openPartnerDialogFor(docId);
}
// 우클릭 메뉴 외에 발급 팝업(taxinvoice-dialog)의 '전표 생성' 버튼도 이 흐름을 쓴다.
async function openPartnerDialogFor(docId){
  voucherContext=null;selectedPartner=null;$('partnerDialogLoading').classList.remove('hidden');$('partnerDialogContent').classList.add('hidden');$('confirmVoucherButton').disabled=true;setDialogError();$('partnerDialog').showModal();
  try{
    const response=await fetch(`/api/appraisals/${encodeURIComponent(docId)}/partner-context`);const payload=await response.json();if(!payload.success)throw new Error(payload.message);voucherContext=payload.data;
    const apw=payload.data.apworks_partner;$('apwPartnerName').textContent=partnerText(apw.name);$('apwProduction').textContent=partnerText(apw.production);$('apwBusinessNo').textContent=partnerText(apw.business_no);$('apwRepresentative').textContent=partnerText(apw.representative);$('apwAddress').textContent=partnerText([apw.address1,apw.address2].filter(Boolean).join(' '));$('partnerSearch').value=payload.data.partner_search_name||'';$('voucherDate').value=payload.data.voucher_date||'';
    $('newPartnerName').value=apw.name||'';$('newBusinessNo').value=apw.business_no||'';$('newRepresentative').value=apw.representative||'';$('newTelephone').value=apw.telephone||'';$('newBusinessType').value=apw.business_type||'';$('newBusinessItem').value=apw.business_item||'';$('newAddress1').value=[apw.address1,apw.address2].filter(Boolean).join(' ');
    renderPartnerResults(payload.data.matches||[]);$('partnerDialogLoading').classList.add('hidden');$('partnerDialogContent').classList.remove('hidden');
  }catch(error){$('partnerDialogLoading').textContent=error.message;}
}
async function registerPartner(){
  if(!voucherContext)return;setDialogError();const button=$('registerPartnerButton');button.disabled=true;button.textContent='등록 중...';
  const body={company_code:voucherContext.company_code,name:$('newPartnerName').value.trim(),short_name:$('newPartnerName').value.trim(),business_no:$('newBusinessNo').value,representative:$('newRepresentative').value.trim()||null,telephone:$('newTelephone').value.trim()||null,business_type:$('newBusinessType').value.trim()||null,business_item:$('newBusinessItem').value.trim()||null,email:$('newPartnerEmail').value.trim()||null,address1:$('newAddress1').value.trim()||null,partner_type:'1'};
  try{const response=await fetch('/api/partners',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const payload=await response.json();if(!payload.success&&payload.code!=='PARTNER_DUPLICATE')throw new Error(payload.message||'거래처 등록에 실패했습니다.');const partner=payload.code==='PARTNER_DUPLICATE'?payload.data:payload.data;await searchPartners(partner.name||body.name);showToast(payload.code==='PARTNER_DUPLICATE'?'이미 등록된 거래처를 표시했습니다.':'거래처가 등록되었습니다.');$('partnerCreatePanel').classList.add('hidden')}catch(error){setDialogError(error.message)}finally{button.disabled=false;button.textContent='Amaranth에 거래처 등록'}
}
async function createDefaultVoucher(){
  if(!voucherContext||!selectedPartner)return;const button=$('confirmVoucherButton');button.disabled=true;button.textContent='전표 생성 중...';setDialogError();
  const voucherDate=$('voucherDate').value;if(!voucherDate){setDialogError('전표일자를 선택해 주세요.');button.disabled=false;button.textContent='선택한 거래처로 전표 생성';return}
  try{const response=await fetch(`/api/appraisals/${encodeURIComponent(voucherContext.doc_id)}/vouchers/default`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({partner_code:selectedPartner.partner_code,partner_name:selectedPartner.name||'',voucher_date:voucherDate,requester_usr_seq:Number((window.A10_CTX||{}).usr_seq||0)||null})});const payload=await response.json();if(!payload.success)throw new Error(payload.message||'전표 생성에 실패했습니다.');$('partnerDialog').close();showToast(`전표가 생성되었습니다. (전표번호 ${payload.data.voucher_no})`);await loadList();const row=document.querySelector(`#appraisalRows tr[data-docid="${CSS.escape(voucherContext.doc_id)}"]`);if(row)await selectDoc(voucherContext.doc_id,row)}catch(error){setDialogError(error.message);button.disabled=false}finally{button.textContent='선택한 거래처로 전표 생성'}
}
// 현금영수증 발급분은 거래처가 늘 이 하나뿐이라 고르는 창을 띄우지 않는다
// (2026-08-20 사용자 요청). 코드는 아마란스 거래처 '현금영수증(국세청)' 이다.
const CASH_RECEIPT_PARTNER={code:'0000028605',name:'현금영수증(국세청)'};

// 거래처가 이미 정해진 건은 창 없이 바로 만든다. 전표일자는 창을 열 때와 같은
// 값을 쓰려고 partner-context 에서 받아 온다.
async function createVoucherWithPartner(docId,partner,opts){
  // recreate: 증빙을 취소하고 세금계산서를 다시 발행한 건 — 기존 전표를 상쇄하는
  // 마이너스 전표 1장 + 새 매출 전표 1장 (2026-09-02 사용자 요청, 01-2608-3-2700)
  const recreate=!!(opts&&opts.recreate);
  if(recreate&&!confirm(`증빙을 취소하고 다시 발행한 건입니다.\n기존 전표를 상쇄하는 마이너스 전표 1장과 새 매출 전표 1장을 만듭니다.\n(${docId} · 거래처 ${partner.name||partner.code})\n진행할까요?`))return;
  try{
    const context=await (await fetch(`/api/appraisals/${encodeURIComponent(docId)}/partner-context`)).json();
    if(!context.success)throw new Error(context.message||'전표일자를 가져오지 못했습니다.');
    const voucherDate=context.data.voucher_date;
    if(!voucherDate)throw new Error('전표일자를 정할 수 없습니다. 우클릭 메뉴로 만들어 주세요.');
    const post=useEvidence=>fetch(`/api/appraisals/${encodeURIComponent(docId)}/vouchers/default${recreate?'/recreate':''}`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({partner_code:partner.code,partner_name:partner.name,
        voucher_date:voucherDate,requester_usr_seq:Number((window.A10_CTX||{}).usr_seq||0)||null,
        use_evidence_amount:!!useEvidence}),
    }).then(r=>r.json());
    let payload=await post(!!(opts&&opts.evidence));   // 발급 팝업 경로는 증빙 금액 (2026-09-08)
    // 청구액보다 적게 받고 끝난 건 — 원장 금액으로는 못 만든다. 실제 증빙 금액으로
    // 세울지 물어본다 (2026-09-07 01-2609-6-0487: 청구 55,000 · 입금 5,500).
    if(!payload.success&&/증빙 일부금액만 발행된 상태/.test(payload.message||'')){
      if(!confirm(`${payload.message}

실제 입금이 그것으로 끝난 건이면 발행된 증빙 금액으로 전표를 세울 수 있습니다.
증빙 금액으로 만들까요?`))throw new Error('전표 생성을 취소했습니다.');
      payload=await post(true);
    }
    if(!payload.success)throw new Error(payload.message||'전표 생성에 실패했습니다.');
    showToast(recreate
      ?`취소 전표(${payload.data.cancel_voucher_no||'-'})와 새 전표(${payload.data.voucher_no})가 생성되었습니다.`
      :`${payload.message||'전표가 생성되었습니다.'} (전표번호 ${payload.data.voucher_no})`);
    await loadList();
    const row=document.querySelector(`#appraisalRows tr[data-docid="${CSS.escape(docId)}"]`);
    if(row)await selectDoc(docId,row);
  }catch(error){showToast(error.message,true);}
}

$('createVoucherMenu').addEventListener('click',openPartnerDialog);
window.A10_CREATE_VOUCHER=openPartnerDialogFor;
window.A10_CREATE_VOUCHER_CASH=(docId,opts)=>createVoucherWithPartner(docId,CASH_RECEIPT_PARTNER,opts);
// 세금계산서도 발급 팝업의 공급받는자(거래처코드)로 창 없이 바로 만든다 (2026-08-27 재무팀 요청)
window.A10_CREATE_VOUCHER_TAX=(docId,partner,opts)=>createVoucherWithPartner(docId,partner,opts);
$('issueTaxMenu').addEventListener('click',()=>{const docId=$('rowContextMenu').dataset.docid;closeContextMenu();if(docId&&window.A10_TAX_ISSUE)window.A10_TAX_ISSUE(docId);});
$('partnerSearchButton').addEventListener('click',()=>searchPartners($('partnerSearch').value.trim()));$('partnerSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchPartners($('partnerSearch').value.trim())}});
$('showPartnerCreate').addEventListener('click',()=>$('partnerCreatePanel').classList.toggle('hidden'));
// method="dialog" 폼은 입력칸 Enter가 암시적 제출 = 다이얼로그 닫힘이라, 신규 거래처
// 입력칸에서는 Enter를 다음 칸 이동으로 바꾸고(마지막 칸은 등록 버튼으로), 나머지
// 입력칸에서도 Enter로 닫히지 않게 막는다.
const partnerCreateFields=['newPartnerName','newBusinessNo','newRepresentative','newTelephone','newBusinessType','newBusinessItem','newPartnerEmail','newAddress1'];
partnerCreateFields.forEach((id,index)=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();const next=partnerCreateFields[index+1];if(next)$(next).focus();else $('registerPartnerButton').focus();}}));
document.querySelector('.partner-dialog-card').addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.tagName==='INPUT')event.preventDefault();});
$('registerPartnerButton').addEventListener('click',registerPartner);$('confirmVoucherButton').addEventListener('click',createDefaultVoucher);

// 감정서번호 없는 탁상·가격자문 수기 매출. 내부 참조번호는 팝빌 중복과 MOA
// 재시도를 구분하는 키일 뿐 Amaranth 관리번호(maNb/ctNb)에는 보내지 않는다.
function newManualReference(){
  const bytes=new Uint8Array(4);crypto.getRandomValues(bytes);
  const suffix=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('').toUpperCase();
  return `MS-${inputDate(new Date()).replace(/-/g,'')}-${suffix}`;
}
const manualNumber=id=>Number(String($(id).value||'').replace(/[^0-9-]/g,''))||0;
function setManualMessage(message='',kind=''){
  const el=$('manualSaleMessage');el.textContent=message;el.className=`manual-sale-message ${kind}`.trim();
}
function updateManualTotal(){
  $('manualTotal').textContent=money.format(manualNumber('manualSupply')+manualNumber('manualTax'));
}
function manualReceiver(){
  return {
    tr_cd:$('manualPartnerCode').value.trim(),
    corp_num:$('manualBusinessNo').value.replace(/[^0-9]/g,''),
    corp_name:$('manualPartnerName').value.trim(),ceo_name:$('manualCeo').value.trim(),
    biz_type:$('manualBizType').value.trim(),biz_class:$('manualBizClass').value.trim(),
    addr:$('manualAddress').value.trim(),email:$('manualEmail').value.trim(),
  };
}
function validateManual(forTax=false){
  if(!$('manualOffice').value)return '회계단위를 선택해 주세요.';
  if(!$('manualPartnerCode').value.trim())return 'Amaranth 거래처를 검색해 선택해 주세요.';
  if(!$('manualPartnerName').value.trim())return '거래처명을 입력해 주세요.';
  if(manualNumber('manualSupply')<=0)return '공급가액을 확인해 주세요.';
  if(manualNumber('manualTax')<0)return '부가세를 확인해 주세요.';
  if(!$('manualMemo').value.trim())return '적요를 입력해 주세요.';
  if(forTax&&manualReceiver().corp_num.length!==10)return '세금계산서 발급에는 사업자번호 10자리가 필요합니다.';
  return '';
}
async function fillManualContactEmail(trCd){
  try{
    const payload=await (await fetch(`/api/taxinvoice/contact-email?tr_cd=${encodeURIComponent(trCd)}`)).json();
    if($('manualPartnerCode').value===trCd&&!$('manualEmail').value.trim())$('manualEmail').value=(payload.data&&payload.data.email)||'';
  }catch(_error){ /* 이메일은 직접 입력 가능 */ }
}
function pickManualPartner(item){
  $('manualPartnerCode').value=item.partner_code||'';$('manualPartnerName').value=item.name||'';
  $('manualBusinessNo').value=item.business_no||'';$('manualCeo').value=item.representative||'';
  $('manualBizType').value=item.business_type||'';$('manualBizClass').value=item.business_item||'';
  $('manualAddress').value=[item.address1,item.address2].filter(Boolean).join(' ');
  $('manualEmail').value='';if(item.partner_code)fillManualContactEmail(item.partner_code);
  $('manualPartnerResults').classList.add('hidden');setManualMessage();
}
async function searchManualPartners(){
  const q=$('manualPartnerSearch').value.trim();if(!q){setManualMessage('거래처 검색어를 입력해 주세요.','err');return}
  const box=$('manualPartnerResults');box.classList.remove('hidden');box.innerHTML='<button type="button" disabled>검색 중...</button>';
  try{
    let payload=await (await fetch(`/api/taxinvoice/customer-search?q=${encodeURIComponent(q)}`)).json();
    if(!payload.success)throw new Error(payload.message||'거래처를 조회하지 못했습니다.');
    let items=(payload.data&&payload.data.items)||[];
    const compact=q.replace(/\s+/g,'');
    if(!items.length&&compact!==q){
      payload=await (await fetch(`/api/taxinvoice/customer-search?q=${encodeURIComponent(compact)}`)).json();
      if(!payload.success)throw new Error(payload.message||'거래처를 조회하지 못했습니다.');
      items=(payload.data&&payload.data.items)||[];
    }
    box.innerHTML=items.length?items.map((item,index)=>`<button type="button" data-index="${index}"><span><strong>${escapeHtml(item.name||'-')}</strong><small>${escapeHtml(item.business_no||'사업자번호 없음')} · ${escapeHtml(item.representative||'대표 미등록')}</small></span><code>${escapeHtml(item.partner_code||'-')}</code></button>`).join(''):'<button type="button" disabled>검색 결과가 없습니다.</button>';
    box.querySelectorAll('button[data-index]').forEach(button=>button.addEventListener('click',()=>pickManualPartner(items[Number(button.dataset.index)])));
  }catch(error){box.innerHTML=`<button type="button" disabled>${escapeHtml(error.message)}</button>`;}
}
function openManualSale(){
  $('manualReference').value=newManualReference();$('manualDate').value=inputDate(new Date());
  $('manualOffice').innerHTML=Array.from($('officeCode').options)
    .filter(option=>option.value&&option.value!=='all')
    .map(option=>`<option value="${escapeHtml(option.value)}">${escapeHtml(option.textContent)}</option>`).join('');
  const wanted=String((window.A10_CTX||{}).office_id||window.A10_OFFICE()||'');
  if(Array.from($('manualOffice').options).some(option=>option.value===wanted))$('manualOffice').value=wanted;
  ['manualPartnerSearch','manualPartnerCode','manualPartnerName','manualBusinessNo','manualCeo','manualBizType','manualBizClass','manualAddress','manualEmail'].forEach(id=>$(id).value='');
  $('manualSupply').value='30000';$('manualTax').value='3000';$('manualAccount').value='4010002';$('manualSalesDivision').value='09';$('manualItemName').value='탁상수수료';$('manualMemo').value='탁상수수료';$('manualPurpose').value='영수';
  $('manualPartnerResults').classList.add('hidden');$('manualTaxButton').disabled=false;$('manualVoucherButton').disabled=false;
  updateManualTotal();setManualMessage();$('manualSaleDialog').showModal();setTimeout(()=>$('manualPartnerSearch').focus(),0);
}
async function issueManualTax(){
  const error=validateManual(true);if(error){setManualMessage(error,'err');return}
  const total=manualNumber('manualSupply')+manualNumber('manualTax');
  if(!confirm(`${$('manualPartnerName').value.trim()}에 ${money.format(total)}원 세금계산서를 발급합니다.\n국세청에 전송되며 되돌리기 어렵습니다. 진행할까요?`))return;
  const button=$('manualTaxButton');button.disabled=true;button.textContent='발급 중...';setManualMessage();
  const body={reference:$('manualReference').value,office_code:$('manualOffice').value,write_date:$('manualDate').value.replace(/-/g,''),supply_cost:manualNumber('manualSupply'),tax:manualNumber('manualTax'),receiver:manualReceiver(),email:$('manualEmail').value.trim(),purpose:$('manualPurpose').value,item_name:$('manualItemName').value.trim()||'탁상수수료',item_remark:'',remark1:$('manualMemo').value.trim(),account_code:$('manualAccount').value};
  try{
    const payload=await (await fetch('/api/manual-sales/taxinvoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(!payload.success)throw new Error(payload.message||'세금계산서 발급에 실패했습니다.');
    const confirmNum=payload.data&&payload.data.info&&payload.data.info.nts_confirm;
    setManualMessage(`세금계산서 발급 완료${confirmNum?` · 승인번호 ${confirmNum}`:''}. 이제 전표를 생성하세요.`,'ok');
    button.textContent='세금계산서 발급 완료';
  }catch(err){button.disabled=false;button.textContent='세금계산서 발급';setManualMessage(err.message,'err');}
}
async function createManualVoucher(){
  const error=validateManual(false);if(error){setManualMessage(error,'err');return}
  const total=manualNumber('manualSupply')+manualNumber('manualTax');
  if(!confirm(`${$('manualPartnerName').value.trim()} 수기 매출전표 ${money.format(total)}원을 생성할까요?`))return;
  const button=$('manualVoucherButton');button.disabled=true;button.textContent='전표 생성 중...';setManualMessage();
  const body={reference:$('manualReference').value,office_code:$('manualOffice').value,partner_code:$('manualPartnerCode').value.trim(),partner_name:$('manualPartnerName').value.trim(),voucher_date:$('manualDate').value,supply_cost:manualNumber('manualSupply'),tax:manualNumber('manualTax'),revenue_account:$('manualAccount').value,sales_division:$('manualSalesDivision').value,memo:$('manualMemo').value.trim()};
  try{
    const payload=await (await fetch('/api/manual-sales/voucher',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(!payload.success)throw new Error(payload.message||'전표 생성에 실패했습니다.');
    setManualMessage(`전표 생성 완료 · 전표번호 ${payload.data.voucher_no}`,'ok');button.textContent='전표 생성됨';
    showToast(`수기 매출전표가 생성되었습니다. (전표번호 ${payload.data.voucher_no})`);
  }catch(err){button.disabled=false;button.textContent='전표 생성';setManualMessage(err.message,'err');}
}
$('manualSaleButton').addEventListener('click',openManualSale);
$('manualPartnerSearchButton').addEventListener('click',searchManualPartners);
$('manualPartnerSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchManualPartners()}});
['manualSupply','manualTax'].forEach(id=>$(id).addEventListener('input',updateManualTotal));
$('manualTaxButton').addEventListener('click',issueManualTax);$('manualVoucherButton').addEventListener('click',createManualVoucher);
document.querySelector('.manual-sale-card').addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.tagName==='INPUT')event.preventDefault();});
document.addEventListener('click',event=>{if(!$('rowContextMenu').contains(event.target))closeContextMenu()});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeContextMenu()});
window.addEventListener('blur',closeContextMenu);window.addEventListener('resize',closeContextMenu);window.addEventListener('scroll',closeContextMenu,true);
const today=new Date();const weekStart=new Date(today);weekStart.setDate(today.getDate()-6);
$('dateFrom').value=inputDate(weekStart);$('dateTo').value=inputDate(today);
// 컬럼 폭 드래그 조절 (column-resize.js 공통 유틸). 전표·계산서 표는 렌더링 시마다 부착한다.
// 저장 키에 v2: 의뢰문서번호 컬럼이 중간에 추가되어 예전 저장 폭은 한 칸씩 밀린다.
window.A10_COLUMN_RESIZE($('appraisalTable'),'a10.appraisalTable.columnWidths.v2');
window.A10_READY.then(()=>loadList().catch(showError));
