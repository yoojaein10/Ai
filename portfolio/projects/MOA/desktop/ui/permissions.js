// 권한부여 화면 (본사 전용). 지사 사용자에게 전체지사 조회 권한을 부여/회수한다.
// 기본 규칙(본사=전체, 지사=자기 지사)은 그대로고, 이 화면은 예외 목록만 관리한다.
const $=id=>document.getElementById(id);
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function showToast(message,isError=false){const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}

// 검색 선택값은 "이름 #USR_ID" 형태 — 동명이인 구분 겸 부여 대상 키 전달
let employeeCache={};

function searchEmployees(keyword){
  clearTimeout(searchEmployees.timer);
  const trimmed=keyword.replace(/#\S+\s*$/,'').trim();
  if(!trimmed)return;
  searchEmployees.timer=setTimeout(async()=>{
    try{
      const response=await fetch(`/api/permissions/employees?q=${encodeURIComponent(trimmed)}`);
      const payload=await response.json();
      if(!payload.success)return;
      employeeCache={};
      $('empList').innerHTML=payload.data.items.map(emp=>{
        const value=`${emp.emp_name} #${emp.usr_id}`;
        employeeCache[value]=emp;
        return `<option value="${escapeHtml(value)}">${escapeHtml(emp.office_name)}</option>`;
      }).join('');
    }catch(error){/* 자동완성 실패는 무시 */}
  },300);
}

async function loadList(){
  $('resultSummary').textContent='조회 중...';
  const response=await fetch('/api/permissions');
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  const items=payload.data.items;
  const activeCount=items.filter(item=>item.active).length;
  $('resultSummary').textContent=`활성 ${activeCount}건 / 전체 ${items.length}건`;
  $('emptyList').classList.toggle('hidden',items.length!==0);
  $('permRows').innerHTML=items.map(item=>`<tr data-id="${item.id}">
    <td>${escapeHtml(item.emp_name||'-')}${item.retired?'<span class="badge-retired">퇴사</span>':''}</td>
    <td>${escapeHtml(item.usr_id)}</td>
    <td>${escapeHtml(item.office_name||'-')}</td>
    <td class="center">${item.active&&item.view_all_offices?'<span class="badge-on">전체지사 조회</span>':'<span class="badge-off">회수됨</span>'}</td>
    <td title="${escapeHtml(item.memo||'')}">${escapeHtml(item.memo||'-')}</td>
    <td>${escapeHtml(item.updated_at||'-')}</td>
    <td class="center">${item.active?'<button class="revoke-button" type="button">회수</button>':''}</td>
  </tr>`).join('');
  document.querySelectorAll('#permRows .revoke-button').forEach(button=>button.addEventListener('click',()=>revoke(button)));
  if(window.A10_COLUMN_RESIZE)window.A10_COLUMN_RESIZE($('permTable'),'permissions-cols');
}

async function grant(){
  const raw=$('empSearch').value.trim();
  const selected=employeeCache[raw];
  const match=raw.match(/#(\S+)\s*$/);
  const usrId=selected?selected.usr_id:(match?match[1]:'');
  if(!usrId){showToast('직원을 검색해서 목록에서 선택하세요.',true);return}
  $('grantButton').disabled=true;
  try{
    const response=await fetch('/api/permissions/grant',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        requester_usr_seq:Number(window.A10_CTX.usr_seq),
        usr_id:usrId,
        memo:$('memoInput').value.trim()||null,
      }),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    $('empSearch').value='';$('memoInput').value='';
    await loadList();
  }catch(error){
    showToast(error.message,true);
  }finally{
    $('grantButton').disabled=false;
  }
}

async function revoke(button){
  const row=button.closest('tr');
  const name=row.querySelector('td').textContent;
  if(!confirm(`${name}의 전체지사 조회 권한을 회수할까요?`))return;
  button.disabled=true;
  try{
    const response=await fetch(`/api/permissions/${row.dataset.id}/revoke`,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({requester_usr_seq:Number(window.A10_CTX.usr_seq)}),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    await loadList();
  }catch(error){
    showToast(error.message,true);button.disabled=false;
  }
}

function showError(error){$('resultSummary').textContent='조회하지 못했습니다';$('permRows').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').textContent=error.message}

// ── 전표 캐시 수동 동기화 ──────────────────────────────────────────────
// 최근 일수 또는 직접 지정한 기간의 전표를 다시 받아온다. 31일을 초과하는
// 기간은 서버가 월별로 나눠 처리하며, 상태를 3초마다 폴링해 진행률을 보여준다.
function renderSyncStatus(state){
  const status=$('syncStatus');
  status.classList.toggle('error',!!state.error);
  if(state.running){
    status.textContent=`실행 중 (${state.date_from}~${state.date_to}, ${state.days}일) — ${state.progress||'준비 중'}`;
    $('syncButton').disabled=true;
    clearTimeout(renderSyncStatus.timer);
    renderSyncStatus.timer=setTimeout(pollSyncStatus,3000);
    return;
  }
  $('syncButton').disabled=false;
  if(state.error){status.textContent=`실패 (${state.finished_at}) — ${state.error}`;return}
  if(state.result){
    const chunks=state.result.chunks_total>1?`, 기간 ${state.result.chunks_completed}/${state.result.chunks_total}`:'';
    status.textContent=`완료 (${state.finished_at}) — 전표 ${Number(state.result.fetched).toLocaleString()}건, 요약 ${Number(state.result.summary_rows).toLocaleString()}건 재집계${chunks}`;
    return;
  }
  status.textContent='';
}

async function pollSyncStatus(){
  try{
    const response=await fetch('/api/cache-sync/status');
    const payload=await response.json();
    if(payload.success)renderSyncStatus(payload.data);
  }catch(error){/* 폴링 실패는 다음 주기에 재시도 */renderSyncStatus.timer=setTimeout(pollSyncStatus,3000)}
}

function localDateValue(value){
  const offset=value.getTimezoneOffset()*60000;
  return new Date(value.getTime()-offset).toISOString().slice(0,10);
}

function toggleSyncMode(){
  const range=$('syncMode').value==='range';
  $('syncDaysLabel').classList.toggle('hidden',range);
  $('syncFromLabel').classList.toggle('hidden',!range);
  $('syncToLabel').classList.toggle('hidden',!range);
  if(range&&!$('syncDateFrom').value){
    const today=new Date();
    $('syncDateTo').value=localDateValue(today);
    $('syncDateFrom').value=localDateValue(new Date(today.getFullYear(),today.getMonth(),1));
  }
}

async function startSync(){
  const mode=$('syncMode').value;
  let body;
  let description;
  if(mode==='days'){
    const days=Number($('syncDays').value);
    if(!Number.isInteger(days)||days<1||days>365){showToast('일수는 1~365 사이 숫자로 입력하세요.',true);return}
    body={days};
    description=`최근 ${days}일`;
  }else{
    const dateFrom=$('syncDateFrom').value;
    const dateTo=$('syncDateTo').value;
    if(!dateFrom||!dateTo){showToast('시작일과 종료일을 입력하세요.',true);return}
    if(dateFrom>dateTo){showToast('시작일은 종료일보다 늦을 수 없습니다.',true);return}
    const days=Math.floor((new Date(`${dateTo}T00:00:00`)-new Date(`${dateFrom}T00:00:00`))/86400000)+1;
    if(days>365){showToast('한 번에 가져올 수 있는 기간은 최대 365일입니다.',true);return}
    body={date_from:dateFrom,date_to:dateTo};
    description=`${dateFrom}~${dateTo}`;
  }
  if(!confirm(`${description} 전표를 다시 가져올까요?\n(기간이 길면 월별로 나눠 처리하며, 다른 전표 동기화는 잠시 건너뜁니다)`))return;
  $('syncButton').disabled=true;
  try{
    const response=await fetch('/api/cache-sync/run',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message||payload.detail?.[0]?.msg||'동기화를 시작하지 못했습니다.');
    showToast(payload.message);
    renderSyncStatus(payload.data);
  }catch(error){
    showToast(error.message,true);
    $('syncButton').disabled=false;
  }
}

$('empSearch').addEventListener('input',event=>searchEmployees(event.target.value));
$('grantButton').addEventListener('click',grant);
$('memoInput').addEventListener('keydown',event=>{if(event.key==='Enter')grant()});
$('syncMode').addEventListener('change',toggleSyncMode);
$('syncButton').addEventListener('click',startSync);
toggleSyncMode();

window.A10_READY.then(ctx=>{
  if(ctx.office_id!=='10'){
    $('permRows').innerHTML='';$('resultSummary').textContent='';
    document.querySelector('.grant-form').classList.add('hidden');
    document.querySelector('.sync-form').classList.add('hidden');
    $('emptyList').classList.remove('hidden');$('emptyList').textContent='권한부여는 본사만 사용할 수 있습니다.';
    return;
  }
  loadList().catch(showError);
  pollSyncStatus();
});
