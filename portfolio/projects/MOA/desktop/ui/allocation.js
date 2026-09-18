// 수수료 배분 승인 화면 (데스크톱 전용, 본사만).
// 야간 배치가 만든 초안(a10_gaprice_outbox)을 표에서 확인·수정 후 승인하면
// APWorks의 Apw_Mae_GaPrice에 새 행으로 반영된다. 여러 명 배분이면 감정서 칸을 묶어(rowspan) 표시한다.
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const ratioNumber=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2});
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function showToast(message,isError=false){const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}

const isApprovedMode=()=>$('approvedOnly').checked;
const currentStatus=()=>isApprovedMode()?'APPROVED':'PENDING';
const dateTimeText=value=>value?String(value).replace('T',' ').slice(0,19):'-';

function buildListQuery(){
  const query=new URLSearchParams({status:currentStatus()});
  if($('dateFrom').value)query.set('date_from',$('dateFrom').value);
  if($('dateTo').value)query.set('date_to',$('dateTo').value);
  if($('docQuery').value.trim())query.set('doc_id',$('docQuery').value.trim());
  if($('managerQuery').value.trim())query.set('manager',$('managerQuery').value.trim());
  return query;
}

let listTruncated=false; // 서버가 100건까지만 주므로 잘렸으면 합계에 '표시분 기준'을 밝힌다

async function loadList(){
  const approved=isApprovedMode();
  syncViewMode();
  $('resultSummary').textContent='조회 중...';
  const response=await fetch(`/api/gaprice/outbox?${buildListQuery()}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const items=payload.data.items;
  const total=payload.data.count;
  listTruncated=total>items.length;
  const label=approved?'승인 완료':'승인 대기';
  $('resultSummary').textContent=total>items.length
    ?`${label} 총 ${money.format(total)}건 · 입금일 최신순 ${money.format(items.length)}건 표시${approved?'':' (승인하면 다음 건이 이어서 나옵니다)'}`
    :`${label} ${money.format(total)}건`;
  $('emptyList').classList.toggle('hidden',items.length!==0);
  $('checkAll').checked=false;
  $('allocationRows').innerHTML=items.map(doc=>{
    const count=doc.rows.length;
    const approval=`<div class="approval-meta"><strong>${escapeHtml(doc.approved_by_name||`사용자 #${doc.approved_by||'-'}`)}</strong>${dateTimeText(doc.approved_at)}</div>`;
    return doc.rows.map((row,index)=>`<tr data-docid="${escapeHtml(doc.doc_id)}" data-rowid="${row.id}" data-basefee="${doc.base_fee}" data-inprice="${row.in_price}" data-basicsusu="${row.basic_susu}">
      ${index===0?`${approved?'':`<td rowspan="${count}" class="check-cell"><input type="checkbox" class="doc-check" aria-label="${escapeHtml(doc.doc_id)} 선택"></td>`}
      <td rowspan="${count}"><strong>${escapeHtml(doc.doc_id)}</strong></td>`:''}
      <td>${escapeHtml(row.manager)}</td>
      ${index===0?`<td rowspan="${count}" title="${escapeHtml(doc.customer_name||'')}">${escapeHtml(doc.customer_name||'-')}</td>
      <td rowspan="${count}">${escapeHtml(doc.in_date||'-')}</td>
      <td rowspan="${count}" class="number">${money.format(doc.base_fee)}</td>
      <td rowspan="${count}" class="number${doc.paid_amount!=null&&doc.paid_amount<doc.base_fee?' paid-short':''}"
        ${doc.paid_amount!=null&&doc.paid_amount<doc.base_fee?'title="실입금액이 순수수료보다 적습니다 (분할입금)"':''}>${doc.paid_amount!=null?money.format(doc.paid_amount):'-'}</td>`:''}
      <td class="number">${approved?`<span class="approved-value">${ratioNumber.format(row.ratio)}</span>`:`<input class="amount-input ratio-input" type="text" inputmode="decimal" value="${row.ratio}">`}</td>
      <td class="number">${approved?`<span class="approved-value">${money.format(Math.round(row.in_price))}</span>`:`<input class="amount-input in-price" type="text" inputmode="numeric" value="${money.format(Math.round(row.in_price))}">`}</td>
      <td class="number">${approved?`<span class="approved-value">${money.format(Math.round(row.basic_susu))}</span>`:`<input class="amount-input basic-susu" type="text" inputmode="numeric" value="${money.format(Math.round(row.basic_susu))}">`}</td>
      ${index===0?`<td rowspan="${count}" class="action-cell">
        ${approved?`${approval}<button class="cancel-button" type="button">승인 취소</button>`:`<button class="approve-button" type="button">승인</button>
        <button class="reject-button" type="button">보류</button>
        <button class="add-person-button" type="button" title="이 감정서에 담당자 추가">+ 담당자</button>`}
      </td>`:''}
    </tr>`).join('');
  }).join('');
  if(approved){
    // 승인 취소는 원장(Apw_Mae_GaPrice)에서 실제로 지운다 — 되돌릴 수 없으니 확인받는다.
    document.querySelectorAll('#allocationRows .cancel-button').forEach(button=>button.addEventListener('click',()=>{
      const docId=button.closest('tr').dataset.docid;
      if(!confirm(`${docId} 의 승인을 취소합니다.
매출입력(GaPrice)에서 지워지고 승인 대기로 돌아갑니다.
되돌릴 수 없습니다. 진행할까요?`))return;
      submit(docId,'cancel');
    }));
  }
  if(!approved){
    document.querySelectorAll('#allocationRows .approve-button').forEach(button=>button.addEventListener('click',()=>submit(button.closest('tr').dataset.docid,'approve')));
    document.querySelectorAll('#allocationRows .reject-button').forEach(button=>button.addEventListener('click',()=>submit(button.closest('tr').dataset.docid,'reject')));
    document.querySelectorAll('#allocationRows .add-person-button').forEach(button=>button.addEventListener('click',()=>addPersonRow(button.closest('tr').dataset.docid)));
    document.querySelectorAll('.doc-check').forEach(check=>check.addEventListener('change',updateBulkButton));
    document.querySelectorAll('#allocationRows tr').forEach(wireRowInputs);
    new Set(items.map(doc=>doc.doc_id)).forEach(updateRatioWarning);
  }
  recalcTotals();
  updateBulkButton();
  if(window.A10_COLUMN_RESIZE)window.A10_COLUMN_RESIZE($('allocationTable'),'allocation-cols');
}

function syncViewMode(){
  const approved=isApprovedMode();
  $('listTitle').textContent=approved?'유치실적 승인 내역':'유치실적 대기';
  $('actionHeader').textContent=approved?'승인정보':'처리';
  $('selectionControls').classList.toggle('hidden',approved);
  $('bulkApprove').classList.toggle('hidden',approved);
  $('printButton').classList.toggle('hidden',!approved);
  $('selectionHeader').classList.toggle('hidden',approved);
  $('selectionColumn').style.display=approved?'none':'';
  $('emptyList').textContent=approved?'조건에 맞는 승인 내역이 없습니다.':'입력 대기 중인 매출이 없습니다.';
}

// 입력칸 공통 배선: 금액칸은 콤마, 비율칸은 소수 허용 + 금액 자동 재계산
function wireRowInputs(tr){
  tr.querySelectorAll('.amount-input:not(.ratio-input)').forEach(input=>input.addEventListener('input',()=>{
    input.value=money.format(parseAmount(input.value));
    recalcTotals();
  }));
  const ratio=tr.querySelector('.ratio-input');
  if(ratio)ratio.addEventListener('input',()=>{
    ratio.value=String(ratio.value).replace(/[^0-9.]/g,'').replace(/(\..*)\./g,'$1');
    recalcFromRatio(tr);
    updateRatioWarning(tr.dataset.docid);
    recalcTotals();
  });
}

function parseRatio(value){
  return Number(String(value).replace(/[^0-9.]/g,''))||0;
}

// 비율을 바꾸면 실적인정금액·입금액 = 순수수료 × 비율 로 즉시 재계산 (금액 직접 수정도 여전히 가능)
function recalcFromRatio(tr){
  const share=Math.round(Number(tr.dataset.basefee||0)*parseRatio(tr.querySelector('.ratio-input').value)/100);
  tr.querySelector('.in-price').value=money.format(share);
  tr.querySelector('.basic-susu').value=money.format(share);
}

// 목록 하단 합계 — 순수수료는 감정서당 1번, 실적인정금액은 전 행 입력값을 더한다 (수정 시 즉시 갱신)
function recalcTotals(){
  const trs=Array.from(document.querySelectorAll('#allocationRows tr'));
  const tfoot=$('allocationTotals');
  if(!trs.length){tfoot.innerHTML='';return}
  const seen=new Set();
  let baseTotal=0;
  trs.forEach(tr=>{
    if(seen.has(tr.dataset.docid))return;
    seen.add(tr.dataset.docid);
    baseTotal+=Number(tr.dataset.basefee||0);
  });
  const susuTotal=trs.reduce((sum,tr)=>{
    const input=tr.querySelector('.basic-susu');
    return sum+(input?parseAmount(input.value):Number(tr.dataset.basicsusu||0));
  },0);
  tfoot.innerHTML=`<tr>
    <td colspan="${isApprovedMode()?4:5}">합계 (${money.format(seen.size)}건${listTruncated?' · 표시분 기준':''})</td>
    <td class="number">${money.format(baseTotal)}</td>
    <td></td><td></td><td></td>
    <td class="number">${money.format(susuTotal)}</td>
    <td></td>
  </tr>`;
}

// 비율 합계 ≠ 100%면 노란 경고만 표시한다 (일부 배분 등 예외가 있어 승인은 막지 않음, 2026-07-22)
function updateRatioWarning(docId){
  const inputs=docRows(docId).map(tr=>tr.querySelector('.ratio-input')).filter(Boolean);
  const total=inputs.reduce((sum,input)=>sum+parseRatio(input.value),0);
  const off=Math.abs(total-100)>0.01;
  inputs.forEach(input=>{
    input.classList.toggle('ratio-off',off);
    input.title=off?`비율 합계 ${Math.round(total*100)/100}% (100%가 아닙니다)`:'';
  });
}

function addPersonRow(docId){
  const rows=docRows(docId);
  const first=rows[0];
  first.querySelectorAll('td[rowspan]').forEach(td=>{td.rowSpan=td.rowSpan+1});
  const tr=document.createElement('tr');
  tr.dataset.docid=docId;tr.dataset.new='1';tr.dataset.basefee=first.dataset.basefee;
  tr.innerHTML=`<td class="new-person-cell">
      <input class="person-name" list="empList" placeholder="이름 검색" autocomplete="off">
      <button class="remove-person" type="button" title="추가한 담당자 삭제">✕</button></td>
    <td class="number"><input class="amount-input ratio-input" type="text" inputmode="decimal" value="0"></td>
    <td class="number"><input class="amount-input in-price" type="text" inputmode="numeric" value="0"></td>
    <td class="number"><input class="amount-input basic-susu" type="text" inputmode="numeric" value="0"></td>`;
  rows[rows.length-1].after(tr);
  wireRowInputs(tr);
  tr.querySelector('.person-name').addEventListener('input',event=>searchEmployees(event.target.value));
  tr.querySelector('.remove-person').addEventListener('click',()=>{
    first.querySelectorAll('td[rowspan]').forEach(td=>{td.rowSpan=td.rowSpan-1});
    tr.remove();
    updateRatioWarning(docId);
    recalcTotals();
  });
  updateRatioWarning(docId);
  tr.querySelector('.person-name').focus();
}

// 재직자 이름 자동완성 — 선택값은 "이름 #USR_SEQ" 형태로 넣어 동명이인을 구분한다
function searchEmployees(keyword){
  clearTimeout(searchEmployees.timer);
  const trimmed=keyword.replace(/#\d+\s*$/,'').trim();
  if(!trimmed)return;
  searchEmployees.timer=setTimeout(async()=>{
    try{
      const response=await fetch(`/api/gaprice/employees?q=${encodeURIComponent(trimmed)}`);
      const payload=await response.json();
      if(!payload.success)return;
      $('empList').innerHTML=payload.data.items.map(emp=>
        `<option value="${escapeHtml(emp.emp_name)} #${emp.usr_seq}">${escapeHtml(emp.office_id==='10'?'본사':emp.office_id)}</option>`
      ).join('');
    }catch(error){/* 자동완성 실패는 조용히 무시 — 이름 직접 입력 가능 */}
  },300);
}

function parseAmount(value){
  return Number(String(value).replace(/[^0-9]/g,''))||0;
}

function docRows(docId){
  return Array.from(document.querySelectorAll(`#allocationRows tr[data-docid="${CSS.escape(docId)}"]`));
}

function docPayload(docId){
  const trs=docRows(docId);
  return {
    doc_id:docId,
    rows:trs.filter(tr=>!tr.dataset.new).map(tr=>({
      id:Number(tr.dataset.rowid),
      in_price:parseAmount(tr.querySelector('.in-price').value),
      basic_susu:parseAmount(tr.querySelector('.basic-susu').value),
      ratio:parseRatio(tr.querySelector('.ratio-input').value),
    })),
    new_rows:trs.filter(tr=>tr.dataset.new).map(tr=>{
      const raw=tr.querySelector('.person-name').value.trim();
      const seqMatch=raw.match(/#(\d+)\s*$/);
      return {
        manager:raw.replace(/#\d+\s*$/,'').trim(),
        usr_seq:seqMatch?Number(seqMatch[1]):null,
        ratio:parseRatio(tr.querySelector('.ratio-input').value),
        in_price:parseAmount(tr.querySelector('.in-price').value),
        basic_susu:parseAmount(tr.querySelector('.basic-susu').value),
      };
    }).filter(row=>row.manager||row.ratio>0||row.in_price>0||row.basic_susu>0),
  };
}

// 추가 행에 금액·비율만 있고 이름이 없으면 승인 전에 걸러낸다
function validateNewRows(payloads){
  for(const doc of payloads){
    if((doc.new_rows||[]).some(row=>!row.manager)){
      showToast(`${doc.doc_id}: 추가한 담당자의 이름을 입력하세요.`,true);
      return false;
    }
  }
  return true;
}

function updateBulkButton(){
  if(isApprovedMode()){
    $('bulkApprove').disabled=true;
    $('bulkApprove').textContent='선택 일괄 승인';
    return;
  }
  const checked=document.querySelectorAll('.doc-check:checked').length;
  $('bulkApprove').disabled=checked===0;
  $('bulkApprove').textContent=checked?`선택 ${checked}건 일괄 승인`:'선택 일괄 승인';
}

async function submit(docId,action){
  const buttons=docRows(docId).flatMap(tr=>Array.from(tr.querySelectorAll('button')));
  buttons.forEach(button=>button.disabled=true);
  const body={approver_usr_seq:Number(window.A10_CTX.usr_seq)};
  if(action==='approve'){
    const payload=docPayload(docId);
    if(!validateNewRows([payload])){buttons.forEach(button=>button.disabled=false);return}
    body.rows=payload.rows;
    body.new_rows=payload.new_rows;
  }
  try{
    const response=await fetch(`/api/gaprice/outbox/${encodeURIComponent(docId)}/${action}`,
      {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    await loadList();
  }catch(error){
    showToast(error.message,true);buttons.forEach(button=>button.disabled=false);
  }
}

async function bulkApprove(){
  const docIds=Array.from(document.querySelectorAll('.doc-check:checked')).map(check=>check.closest('tr').dataset.docid);
  if(!docIds.length)return;
  const docs=docIds.map(docPayload);
  if(!validateNewRows(docs))return;
  if(!confirm(`선택한 ${docIds.length}건을 GaPrice에 반영합니다. 진행할까요?`))return;
  $('bulkApprove').disabled=true;$('bulkApprove').textContent='반영 중...';
  try{
    const response=await fetch('/api/gaprice/outbox/approve-bulk',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({approver_usr_seq:Number(window.A10_CTX.usr_seq),docs}),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    const failed=(payload.data&&payload.data.failed)||[];
    showToast(payload.message,failed.length>0);
    await loadList();
  }catch(error){
    showToast(error.message,true);
  }finally{
    updateBulkButton();
  }
}

const PRINT_MAX_DOCS=1000;

function printConditions(){
  const parts=[`구분: ${isApprovedMode()?'승인 완료':'승인 대기'}`];
  if($('dateFrom').value||$('dateTo').value)parts.push(`입금일: ${$('dateFrom').value||''} ~ ${$('dateTo').value||''}`);
  if($('docQuery').value.trim())parts.push(`감정서번호: ${$('docQuery').value.trim()}`);
  if($('managerQuery').value.trim())parts.push(`유치자: ${$('managerQuery').value.trim()}`);
  return parts.join('  |  ');
}

function buildPrintHtml(items,total){
  const approved=isApprovedMode();
  const rowCount=items.reduce((sum,doc)=>sum+doc.rows.length,0);
  const baseTotal=items.reduce((sum,doc)=>sum+Number(doc.base_fee||0),0);
  const paidTotal=items.reduce((sum,doc)=>sum+Number(doc.paid_amount||0),0);
  const inPriceTotal=items.flatMap(doc=>doc.rows).reduce((sum,row)=>sum+Number(row.in_price||0),0);
  const salesTotal=items.flatMap(doc=>doc.rows).reduce((sum,row)=>sum+Number(row.basic_susu||0),0);
  // 감정서 단위 값(rowspan)과 담당자 단위 값이 번갈아 나온다 — 담당자가 2명 이상인
  // 감정서는 둘째 행부터 rowspan 칸을 비우고, 남은 칸이 순서대로 밀려 들어간다.
  const rows=items.map(doc=>doc.rows.map((row,index)=>`<tr>
    ${index===0?`<td rowspan="${doc.rows.length}">${escapeHtml(doc.doc_id)}</td><td rowspan="${doc.rows.length}" class="print-customer">${escapeHtml(doc.customer_name||'-')}</td>`:''}
    <td>${escapeHtml(row.manager||'-')}</td>
    ${index===0?`<td rowspan="${doc.rows.length}" class="number">${money.format(doc.base_fee||0)}</td>`:''}
    <td class="number">${ratioNumber.format(row.ratio||0)}</td><td class="number">${money.format(row.in_price||0)}</td><td class="number">${money.format(row.basic_susu||0)}</td>
    ${index===0?`<td rowspan="${doc.rows.length}" class="number">${doc.paid_amount==null?'-':money.format(doc.paid_amount)}</td><td rowspan="${doc.rows.length}">${escapeHtml(doc.in_date||'-')}</td>`:''}
  </tr>`).join('')).join('');
  const printed=items.length<total
    ?`총 ${money.format(total)}건 중 ${money.format(items.length)}건 인쇄 (상한 ${money.format(PRINT_MAX_DOCS)}건)`
    :`총 ${money.format(total)}건 · 담당자 ${money.format(rowCount)}행`;
  const now=new Date();
  const stamp=`${inputDate(now)} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}`;
  return `<h1>${approved?'개인별 매출 실적 내역':'매출 입력 대기 내역'}</h1>
    <p class="print-meta">${escapeHtml(printConditions())}<br>${printed} · 출력 ${stamp}</p>
    <table class="allocation-print-table"><colgroup><col style="width:9%"><col style="width:24%"><col style="width:7%"><col style="width:11%"><col style="width:6%"><col style="width:11%"><col style="width:13%"><col style="width:11%"><col style="width:8%"></colgroup><thead><tr><th>감정서번호</th><th class="print-customer">거래처명</th><th>유치자</th><th class="number">순수수료</th><th class="number">비율(%)</th><th class="number">배분액</th><th class="number">실적인정금액</th><th class="number">실입금액</th><th>입금일</th></tr></thead>
    <tbody>${rows}</tbody><tfoot><tr class="print-total"><td colspan="3">합계 (${money.format(items.length)}건)</td><td class="number">${money.format(baseTotal)}</td><td></td><td class="number">${money.format(inPriceTotal)}</td><td class="number">${money.format(salesTotal)}</td><td class="number">${money.format(paidTotal)}</td><td></td></tr></tfoot></table>`;
}

async function printList(){
  const button=$('printButton');
  const label=button.textContent;
  button.disabled=true;button.textContent='준비 중...';
  try{
    const query=buildListQuery();query.set('limit',PRINT_MAX_DOCS);
    const response=await fetch(`/api/gaprice/outbox?${query}`);const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    const items=payload.data.items||[];
    if(!items.length){showToast('인쇄할 내역이 없습니다.',true);return}
    $('printArea').innerHTML=buildPrintHtml(items,payload.data.count||items.length);
    const pageTitle=document.title;document.title=' ';
    try{window.print()}finally{document.title=pageTitle}
  }catch(error){
    showToast(`인쇄 준비 실패: ${error.message}`,true);
  }finally{
    button.disabled=false;button.textContent=label;
  }
}

function showError(error){$('resultSummary').textContent='조회하지 못했습니다';$('allocationRows').innerHTML='';$('allocationTotals').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').textContent=error.message}

// 재무팀 일과: 전날 입금분을 다음날 확인하므로 기본 기간은 어제 하루다.
const inputDate=value=>{
  const year=value.getFullYear();const month=String(value.getMonth()+1).padStart(2,'0');const day=String(value.getDate()).padStart(2,'0');
  return `${year}-${month}-${day}`;
};
const yesterday=new Date();yesterday.setDate(yesterday.getDate()-1);
$('dateFrom').value=inputDate(yesterday);$('dateTo').value=inputDate(yesterday);

$('searchButton').addEventListener('click',()=>loadList().catch(showError));
$('approvedOnly').addEventListener('change',()=>loadList().catch(showError));
['dateFrom','dateTo','docQuery','managerQuery'].forEach(id=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter')$('searchButton').click()}));
$('checkAll').addEventListener('change',()=>{
  document.querySelectorAll('.doc-check').forEach(check=>{check.checked=$('checkAll').checked});
  updateBulkButton();
});
$('bulkApprove').addEventListener('click',bulkApprove);
$('printButton').addEventListener('click',printList);
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/gaprice/outbox/export.xlsx?${buildListQuery()}`);});

window.A10_READY.then(ctx=>{
  if(ctx.office_id!=='10'){
    $('allocationRows').innerHTML='';$('resultSummary').textContent='';
    $('emptyList').classList.remove('hidden');$('emptyList').textContent='유치실적은 본사(재무팀)만 사용할 수 있습니다.';
    return;
  }
  loadList().catch(showError);
});
