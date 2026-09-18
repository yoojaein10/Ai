// 입금발송내역 — 알림 큐(a10_payment_notify) 이벤트 목록과 알림톡 발송·전송 기록.
// 행 = 입금 증가 사건. 처리 컬럼에 발송/제외 사유가 남는다 (발송·전송처리는 본사 전용).
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const esc=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

// 서버가 500을 내면 본문이 JSON 이 아니라 'Internal Server Error' 라는 글자다.
// 그대로 json() 하면 "Unexpected token 'I' … is not valid JSON" 만 떠서 진짜 이유를
// 알 수 없다 (2026-08-21 제보: 수신자 2명 발송이 키 중복으로 터졌을 때).
// 본문을 글자로 먼저 읽고, JSON 이 아니면 상태 코드와 본문 앞머리를 보여 준다.
async function readJson(response){
  const text = await response.text();
  try { return JSON.parse(text); }
  catch (_) {
    const head = (text || '').trim().slice(0, 120);
    throw new Error(`서버 오류 (${response.status} ${response.statusText})${head ? ' — ' + head : ''}`);
  }
}

// 원장에 청구서(APW_Bill)가 없으면 0원이 아니라 자료가 없는 것이다.
const amountCell=value=>value==null
  ?'<span class="no-bill" title="APW_Bill 에 청구서가 아직 없습니다.">청구서 미작성</span>'
  :money.format(Math.round(value));

function buildQuery(){
  // 리스트는 지사 선택대로 조회, 알림톡 발송만 서버가 본사(office=10) 건으로 거른다
  const params=new URLSearchParams({
    date_from:$('dateFrom').value,
    date_to:$('dateTo').value,
    office_code:$('officeCode').value||'10',
    sent:$('sentFilter').value,
    pay_status:$('payStatusFilter').value,
  });
  const query=$('docQuery').value.trim();
  if(query)params.set('query',query);
  return params;
}

async function load(){
  $('summary').textContent='조회 중...';
  $('searchButton').disabled=true;
  try{
    const response=await fetch(`/api/payment-sms?${buildQuery()}`);
    const payload=await readJson(response);
    if(!payload.success)throw new Error(payload.message);
    const {items,totals,truncated}=payload.data;
    $('summary').innerHTML=`사건 <b>${money.format(totals.count)}</b>건
      · 감지 입금액 합계 <b>${money.format(Math.round(totals.delta_total))}</b>원
      · 처리 <b>${money.format(totals.done_count)}</b> / 미처리 <b>${money.format(totals.pending_count)}</b>
      ${truncated?` · <span style="color:#c62828">최신 ${money.format(items.length)}건만 표시(기간을 좁혀 주세요)</span>`:''}`;
    $('rows').innerHTML=items.map(item=>`<tr data-docid="${esc(item.doc_id)}">
      <td class="center"><input class="row-check" type="checkbox" aria-label="선택"></td>
      <td>${esc(item.doc_id)}</td>
      <td title="${esc(item.customer_name||'')}">${esc(item.customer_name||'-')}</td>
      <td title="${esc(item.manager||'')}">${esc(item.manager||'-')}</td>
      <td><b>${esc(item.recipients||'-')}</b></td>
      <td>${esc(item.detected_at||'-')}</td>
      <td>${esc(item.paid_date||'-')}</td>
      <td class="number">${amountCell(item.total_amount)}</td>
      <td class="number" title="착수금을 미리 받은 건은 잔금만 청구됩니다.">${amountCell(item.bill_amount)}</td>
      <td class="number">${money.format(Math.round(item.delta_amount))}</td>
      <td class="number">${money.format(Math.round(item.received_amount))}</td>
      <td class="center">${esc(item.status||'-')}</td>
      <td class="center">${item.queue_done
        ?`<span class="sms-badge sent">${esc(item.queue_result||'처리')}</span><span class="sms-time">${esc(item.queue_at||'')}</span>`
        :'<span class="sms-badge unsent">미처리</span>'}</td>
    </tr>`).join('');
    $('emptyList').classList.toggle('hidden',items.length!==0);
    $('checkAll').checked=false;
    window.A10_COLUMN_RESIZE($('psTable'),'a10.psTable.columnWidths');
  }catch(error){
    $('summary').textContent='조회하지 못했습니다';
    $('rows').innerHTML='';
    $('emptyList').classList.remove('hidden');
    $('emptyList').textContent=error.message;
  }finally{
    $('searchButton').disabled=false;
  }
}

function selectedDocIds(){
  // 분할입금은 같은 감정서가 여러 행일 수 있어 중복 제거
  return Array.from(new Set(
    Array.from(document.querySelectorAll('#rows .row-check:checked'))
      .map(check=>check.closest('tr').dataset.docid)
  ));
}

async function mark(sent){
  const docIds=selectedDocIds();
  if(!docIds.length){showToast('처리할 행을 선택하세요.',true);return}
  const button=sent?$('markSentButton'):$('markUnsentButton');
  button.disabled=true;
  try{
    const response=await fetch('/api/payment-sms/mark',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        requester_usr_seq:Number(window.A10_CTX.usr_seq),
        doc_ids:docIds,sent,
      }),
    });
    const payload=await readJson(response);
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    await load();
  }catch(error){
    showToast(error.message,true);
  }finally{
    button.disabled=false;
  }
}

// 알림톡 실발송 (미전송 건만 큐잉 — 서버가 수신번호 조회·테스트 모드 처리)
async function sendAlimtalk(){
  const docIds=selectedDocIds();
  if(!docIds.length){showToast('발송할 행을 선택하세요.',true);return}
  if(!confirm(`선택한 ${docIds.length}건의 입금 알림톡을 발송할까요?`))return;
  const button=$('sendButton');
  button.disabled=true;
  try{
    const response=await fetch('/api/payment-sms/send',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        requester_usr_seq:Number(window.A10_CTX.usr_seq),
        doc_ids:docIds,
      }),
    });
    const payload=await readJson(response);
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    await load();
  }catch(error){
    showToast(error.message,true);
  }finally{
    button.disabled=false;
  }
}

function showToast(message,isError=false){const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}

// 기본 기간 = 오늘 하루 (10분 배치가 감지한 당일 입금 사건이 올라온다)
const today=new Date();
const pad=value=>String(value).padStart(2,'0');
const todayStr=`${today.getFullYear()}-${pad(today.getMonth()+1)}-${pad(today.getDate())}`;
$('dateFrom').value=todayStr;
$('dateTo').value=todayStr;

$('searchButton').addEventListener('click',()=>load());
$('docQuery').addEventListener('keydown',event=>{if(event.key==='Enter')load()});
$('sentFilter').addEventListener('change',()=>load());
$('payStatusFilter').addEventListener('change',()=>load());
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/payment-sms/export.xlsx?${buildQuery()}`)});
$('sendButton').addEventListener('click',()=>sendAlimtalk());
$('markSentButton').addEventListener('click',()=>mark(true));
$('markUnsentButton').addEventListener('click',()=>mark(false));
$('checkAll').addEventListener('change',()=>{
  document.querySelectorAll('#rows .row-check').forEach(check=>{check.checked=$('checkAll').checked});
});

window.A10_READY.then(()=>load());
