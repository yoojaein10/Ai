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
const sortLabels={doc_id:'감정서번호',receipt_date:'접수일',address:'소재지',customer_name:'거래처명',manager:'유치자',author:'조사자',progress_status:'진행상태',send_date:'발송일',appraisal_amount:'평가액',base_fee:'기초수수료',travel_expense:'여비'};
function renderLoading(){ $('emptyList').classList.add('hidden');$('emptyList').classList.remove('error');$('appraisalRows').innerHTML=Array.from({length:7},()=>`<tr class="skeleton-row">${Array.from({length:12},()=>'<td><span></span></td>').join('')}</tr>`).join(''); }

async function loadList(){
  const query=new URLSearchParams({page:state.page,page_size:state.pageSize,office_code:$('officeCode').value});
  const filters={docId:'doc_id',address:'address',customerName:'customer_name',manager:'manager',charge:'charge'};
  Object.entries(filters).forEach(([inputId,param])=>{const value=$(inputId).value.trim();if(value)query.set(param,value);});
  if($('dateFrom').value)query.set('date_from',$('dateFrom').value);
  if($('dateTo').value)query.set('date_to',$('dateTo').value);
  if(state.sortBy){query.set('sort_by',state.sortBy);query.set('sort_order',state.sortOrder);}
  $('resultSummary').textContent='조회 중...';$('searchButton').disabled=true;$('searchButton').textContent='조회 중';renderLoading();
  const response=await fetch(`/api/appraisals?${query}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const data=payload.data;state.total=data.total;
  const sortText=state.sortBy?` / ${sortLabels[state.sortBy]} ${state.sortOrder==='asc'?'오름차순':'내림차순'}`:'';$('resultSummary').textContent=`총 ${money.format(data.total)}건 · ${data.page}페이지${sortText}`;
  $('emptyList').textContent='조건에 맞는 감정서가 없습니다.';$('emptyList').classList.remove('error');
  $('emptyList').classList.toggle('hidden',data.items.length!==0);
  $('appraisalRows').innerHTML=data.items.map(row=>`<tr data-docid="${escapeHtml(row.doc_id)}" class="${state.selected===row.doc_id?'selected':''}">
    <td>${escapeHtml(row.doc_id)}</td><td>${dateText(row.receipt_date)}</td><td><span class="payment-status payment-${escapeHtml(row.payment_status||'미확인')}">${escapeHtml(row.payment_status||'미확인')}</span></td><td title="${escapeHtml(row.address)}">${escapeHtml(row.address||'-')}</td>
    <td>${escapeHtml(row.customer_name||'-')}</td><td>${escapeHtml(row.manager||'-')}</td><td>${escapeHtml(row.author||'-')}</td>
    <td><span class="status">${escapeHtml(row.progress_status||'-')}</span></td><td>${dateText(row.send_date)}</td>
    <td class="number">${money.format(row.appraisal_amount||0)}</td><td class="number">${money.format(row.base_fee||0)}</td><td class="number">${money.format(row.travel_expense||0)}</td>
  </tr>`).join('');
  document.querySelectorAll('#appraisalRows tr').forEach(row=>{
    row.addEventListener('click',()=>selectDoc(row.dataset.docid,row));
    row.addEventListener('contextmenu',event=>openContextMenu(event,row));
  });
  const pages=Math.max(1,Math.ceil(state.total/state.pageSize));$('pageLabel').textContent=`${state.page} / ${pages}`;
  $('prevPage').disabled=state.page<=1;$('nextPage').disabled=state.page>=pages;$('searchButton').disabled=false;$('searchButton').textContent='조회';
}

async function loadOffices(){
  try{
    const response=await fetch('/api/appraisals/offices');const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    $('officeCode').innerHTML='<option value="all">전체</option>'+payload.data.items.map(office=>`<option value="${escapeHtml(office.office_code)}">${escapeHtml(office.office_name)}</option>`).join('');
    $('officeCode').value='10';
  }catch(error){$('officeCode').title=`지사 목록 조회 실패: ${error.message}`;}
}

async function selectDoc(docId,row){
  state.selected=docId;document.querySelectorAll('#appraisalRows tr').forEach(item=>item.classList.remove('selected'));row.classList.add('selected');
  $('detailPlaceholder').classList.add('hidden');$('detailContent').classList.remove('hidden');$('selectedDocId').textContent=docId;$('matchBadge').textContent='조회 중';
  const response=await fetch(`/api/appraisals/${encodeURIComponent(docId)}/vouchers`);const payload=await response.json();
  if(!payload.success){$('matchBadge').textContent='조회 실패';return;}
  const items=payload.data.items;$('matchBadge').textContent=items.length?`${items.length}건 연결`:'미연결';$('voucherEmpty').classList.toggle('hidden',items.length!==0);
  $('voucherList').innerHTML=items.map(voucher=>`<section class="voucher"><div class="voucher-head"><div><strong>${escapeHtml(voucher.source_voucher_no)}</strong><small>${escapeHtml(voucher.status)}</small>${voucher.batch_settlement?`<em class="bundle-badge" title="${escapeHtml(voucher.batch_note||'')}">여러 건 묶음 · ${escapeHtml(voucher.batch_doc_count||'')}건</em>`:''}</div><span>관리번호 ${escapeHtml(voucher.management_no)}</span></div>
    <div class="voucher-grid-wrap"><table class="voucher-grid"><colgroup><col><col class="date-col"><col class="amount-col"><col class="amount-col"></colgroup><thead><tr><th>계정과목</th><th>전표일자</th><th class="number">차변</th><th class="number">대변</th></tr></thead>
    <tbody>${(voucher.lines||[]).map(line=>{const amount=Number(line.amount||line.acctAm||0);const isDebit=String(line.debit_credit||line.drcrFg)==='3';return `<tr><td><strong>${escapeHtml(accountName(line))}</strong><small>${escapeHtml(line.remark||line.rmkDc||'')}</small></td><td>${dateText(voucher.voucher_date)}</td><td class="number debit">${isDebit?money.format(amount):'-'}</td><td class="number credit">${isDebit?'-':money.format(amount)}</td></tr>`;}).join('')}</tbody>
    <tfoot><tr><th><span>합계</span> ${Number(voucher.debit_total)===Number(voucher.credit_total)?'<span class="balanced">일치</span>':'<span class="unbalanced">불일치</span>'}</th><th></th><th class="number">${money.format(voucher.debit_total)}</th><th class="number">${money.format(voucher.credit_total)}</th></tr></tfoot></table></div></section>`).join('');
}

$('searchButton').addEventListener('click',()=>{state.page=1;loadList().catch(showError)});['docId','address','customerName','manager','charge'].forEach(id=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter'){$('searchButton').click();}}));
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
  const body={company_code:voucherContext.company_code,name:$('newPartnerName').value.trim(),short_name:$('newPartnerName').value.trim(),business_no:$('newBusinessNo').value,representative:$('newRepresentative').value.trim()||null,telephone:$('newTelephone').value.trim()||null,business_type:$('newBusinessType').value.trim()||null,business_item:$('newBusinessItem').value.trim()||null,address1:$('newAddress1').value.trim()||null,partner_type:'1'};
  try{const response=await fetch('/api/partners',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const payload=await response.json();if(!payload.success&&payload.code!=='PARTNER_DUPLICATE')throw new Error(payload.message||'거래처 등록에 실패했습니다.');const partner=payload.code==='PARTNER_DUPLICATE'?payload.data:payload.data;await searchPartners(partner.name||body.name);showToast(payload.code==='PARTNER_DUPLICATE'?'이미 등록된 거래처를 표시했습니다.':'거래처가 등록되었습니다.');$('partnerCreatePanel').classList.add('hidden')}catch(error){setDialogError(error.message)}finally{button.disabled=false;button.textContent='Amaranth에 거래처 등록'}
}
async function createDefaultVoucher(){
  if(!voucherContext||!selectedPartner)return;const button=$('confirmVoucherButton');button.disabled=true;button.textContent='전표 생성 중...';setDialogError();
  const voucherDate=$('voucherDate').value;if(!voucherDate){setDialogError('전표일자를 선택해 주세요.');button.disabled=false;button.textContent='선택한 거래처로 전표 생성';return}
  try{const response=await fetch(`/api/appraisals/${encodeURIComponent(voucherContext.doc_id)}/vouchers/default`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({partner_code:selectedPartner.partner_code,partner_name:selectedPartner.name||'',voucher_date:voucherDate})});const payload=await response.json();if(!payload.success)throw new Error(payload.message||'전표 생성에 실패했습니다.');$('partnerDialog').close();showToast(`전표가 생성되었습니다. (전표번호 ${payload.data.voucher_no})`);await loadList();const row=document.querySelector(`#appraisalRows tr[data-docid="${CSS.escape(voucherContext.doc_id)}"]`);if(row)await selectDoc(voucherContext.doc_id,row)}catch(error){setDialogError(error.message);button.disabled=false}finally{button.textContent='선택한 거래처로 전표 생성'}
}
$('createVoucherMenu').addEventListener('click',openPartnerDialog);
$('partnerSearchButton').addEventListener('click',()=>searchPartners($('partnerSearch').value.trim()));$('partnerSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchPartners($('partnerSearch').value.trim())}});
$('showPartnerCreate').addEventListener('click',()=>$('partnerCreatePanel').classList.toggle('hidden'));
// method="dialog" 폼은 입력칸 Enter가 암시적 제출 = 다이얼로그 닫힘이라, 신규 거래처
// 입력칸에서는 Enter를 다음 칸 이동으로 바꾸고(마지막 칸은 등록 버튼으로), 나머지
// 입력칸에서도 Enter로 닫히지 않게 막는다.
const partnerCreateFields=['newPartnerName','newBusinessNo','newRepresentative','newTelephone','newBusinessType','newBusinessItem','newAddress1'];
partnerCreateFields.forEach((id,index)=>$(id).addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();const next=partnerCreateFields[index+1];if(next)$(next).focus();else $('registerPartnerButton').focus();}}));
document.querySelector('.partner-dialog-card').addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.tagName==='INPUT')event.preventDefault();});
$('registerPartnerButton').addEventListener('click',registerPartner);$('confirmVoucherButton').addEventListener('click',createDefaultVoucher);
document.addEventListener('click',event=>{if(!$('rowContextMenu').contains(event.target))closeContextMenu()});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeContextMenu()});
window.addEventListener('blur',closeContextMenu);window.addEventListener('resize',closeContextMenu);window.addEventListener('scroll',closeContextMenu,true);
const today=new Date();const weekStart=new Date(today);weekStart.setDate(today.getDate()-6);
$('dateFrom').value=inputDate(weekStart);$('dateTo').value=inputDate(today);
loadOffices().then(()=>loadList().catch(showError));
