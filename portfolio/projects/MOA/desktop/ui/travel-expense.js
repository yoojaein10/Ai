// 출장비 (2026-09-10) — APWorks 델파이 출장비프로그램(출장비입력·남직원출장리스트·출장분기리스트) 이식.
// 이 파일: 탭·공통 도우미·리스트/결재·월별 현황. 입력 폼은 travel-expense-entry.js.
// 데이터는 델파이와 같은 APWorks 테이블이라 두 프로그램을 같이 써도 어긋나지 않는다.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const num = v => money.format(Math.round(Number(v || 0)));
const digits = v => Number(String(v ?? '').replace(/[^0-9]/g, '') || 0);
const requester = () => Number((window.A10_CTX || {}).usr_seq || 0);

const TE = window.A10_TE = { me: null, listRows: [] };

function toast(msg, err) {
  const t = $('toast');
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 7000);
}
TE.toast = toast;

async function api(method, url, body) {
  const res = await fetch(url, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify({ requester_usr_seq: requester(), ...body }) : undefined,
  });
  const p = await res.json();
  if (!p.success) throw new Error(p.message || (p.detail && p.detail.message) || '요청 실패');
  return p;
}
TE.api = api; TE.esc = esc; TE.num = num; TE.digits = digits;

const stateBadge = row => `<span class="badge s${row.appro_state}">${esc(row.state_label)}</span>`;
TE.stateBadge = stateBadge;

// ── 탭 ──────────────────────────────────────────────────────────────────────
const ENTRY_HIDDEN = () => !!document.querySelector('.te-tabs button[data-tab=entry][hidden]');
function showTab(name) {
  if (name === 'entry' && ENTRY_HIDDEN()) return;   // 입력 탭은 당분간 숨김 (2026-09-10 사용자)
  document.querySelectorAll('.te-tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  $('tabEntry').hidden = name !== 'entry';
  $('tabList').hidden = name !== 'list';
  $('tabMonths').hidden = name !== 'months';
  if (name === 'months') loadMonths().catch(e => toast(e.message, true));
}
TE.showTab = showTab;
document.querySelectorAll('.te-tabs button').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

// ── 리스트·결재 ─────────────────────────────────────────────────────────────
function listQuery() {
  const kind = document.querySelector('input[name=dateKind]:checked').value;
  const q = new URLSearchParams({ bungi: kind ? '' : $('lsMonth').value, emp: $('lsEmp').value, doc_id: $('lsDoc').value.trim(), date_kind: kind });
  if ($('lsState').value !== '') q.set('state', $('lsState').value);
  if (kind) { q.set('date_from', $('lsFrom').value); q.set('date_to', $('lsTo').value); }
  return q;
}

async function loadList() {
  $('lsSummary').textContent = '조회 중...';
  $('lsRows').innerHTML = '<tr><td colspan="30" class="te-hint">불러오는 중...</td></tr>';
  const p = await api('GET', `/api/travel-expense/list?${listQuery()}`);
  TE.listRows = p.data.items || [];
  TE.listSummary = p.data.summary;
  if (p.data.writers && p.data.writers.length) {
    const cur = $('lsEmp').value;
    $('lsEmp').innerHTML = '<option value="">전체</option>' + p.data.writers.map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join('');
    $('lsEmp').value = cur;
  }
  renderList();
}

// 표 열 순서: 체크 · 앞 8칸(상태~발송일) · 금액 8칸 · 물건내역 · 금액 10칸 · 비고 = 29칸
const AMT = ['cul_in', 'cul_out', 'cul_total', 'regis_copy', 'toji_use', 'toji_dae', 'build_dae', 'jijuck'];
const AMT2 = ['mul_amt', 'gong_total', 'amount_total', 'yebi', 'muljosabi', 'tojosabi', 'gongbu', 'silbi', 'yongyeuk', 'bill_total'];
const amountCells = (s, keys) => keys.map(k => `<td class="number">${num(s[k])}</td>`).join('');

function sumRow(label, s, cls) {
  return `<tr class="${cls}"><td></td><td colspan="9">${esc(label)} · ${s.count}건</td>${amountCells(s, AMT)}<td></td>${amountCells(s, AMT2)}<td></td></tr>`;
}

function renderList() {
  const rows = TE.listRows, me = TE.me || {};
  $('lsSummary').textContent = rows.length ? `${rows.length}건 · 합계 ${num(TE.listSummary.grand.amount_total)}원` : '조건에 맞는 건이 없습니다.';
  if (!rows.length) { $('lsRows').innerHTML = '<tr><td colspan="30" class="te-hint">조건에 맞는 건이 없습니다.</td></tr>'; updateListSelection(); return; }
  // 출장일 순 한 줄 목록 (2026-09-11 사용자 요청) — 서버가 출장일·작성자·감정서번호 순으로 준다.
  // 작성자별 소계는 총괄표에 있다.
  let html = '';
  rows.forEach((r, i) => {
      html += `<tr data-i="${i}" class="pick${r.editable ? ' editable' : ''}${r.check_note ? ' wrong' : ''}" title="${r.editable ? '더블클릭하면 입력 폼에서 고칠 수 있습니다' : ''}">
        <td class="center"><input class="pick" type="checkbox"></td>
        <td class="center">${stateBadge(r)}</td><td>${esc(r.write_name)}</td><td>${esc(r.receipt_date || '')}</td><td>${esc(r.cul_date || '')}</td><td>${esc(r.doc_id)}</td>
        <td>${esc(r.status || '')}</td><td>${esc(r.manager || '')}</td><td title="${esc(r.address)}">${esc(r.address)}</td><td>${esc(r.send_date || '')}</td>
        ${['cul_in', 'cul_out', 'cul_total', 'regis_copy', 'toji_use', 'toji_dae', 'build_dae', 'jijuck'].map(k => `<td class="number">${num(r[k])}</td>`).join('')}
        <td>${esc(r.mul_remark)}</td>${['mul_amt', 'gong_total', 'amount_total', 'yebi', 'muljosabi', 'tojosabi', 'gongbu', 'silbi', 'yongyeuk', 'bill_total'].map(k => `<td class="number">${num(r[k])}</td>`).join('')}
        <td title="${esc(r.bigo)}">${esc(r.bigo)}${r.check_note ? `<div class="check-note">${esc(r.check_note)}</div>` : ''}</td></tr>`;
  });
  html += sumRow('총 계', TE.listSummary.grand, 'grand');
  $('lsRows').innerHTML = html;
  $('lsRows').querySelectorAll('input.pick').forEach(b => b.addEventListener('change', updateListSelection));
  $('lsRows').querySelectorAll('tr.editable').forEach(tr => tr.addEventListener('dblclick', () => {
    const r = rows[Number(tr.dataset.i)];
    if (window.A10_TE_ENTRY && !ENTRY_HIDDEN()) { showTab('entry'); window.A10_TE_ENTRY.open(r.doc_id, r.seq); }
  }));
  $('lsAll').checked = false;
  updateListSelection();
  if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('lsTable'), 'a10.travelExpense.columnWidths');
}

function selectedList() {
  return Array.from($('lsRows').querySelectorAll('tr[data-i]')).filter(tr => tr.querySelector('input.pick').checked).map(tr => TE.listRows[Number(tr.dataset.i)]);
}

function updateListSelection() {
  const sel = selectedList(), me = TE.me || {};
  const mine0 = sel.filter(r => r.appro_state === 0 && r.write_name === me.name);
  $('lsSubmit').disabled = mine0.length === 0;
  $('lsSubmit').textContent = mine0.length ? `선택 제출 (${mine0.length}건)` : '선택 제출';
  const g = me.grade;
  const approvable = g ? sel.filter(r => r.appro_state === g) : [];
  const rejectable = g ? sel.filter(r => r.appro_state === g || (g === 3 && r.appro_state === 4)) : [];
  $('lsApprove').hidden = !me.is_approver; $('lsReject').hidden = !me.is_approver;
  $('lsApprove').disabled = approvable.length === 0; $('lsApprove').textContent = approvable.length ? `선택 결재 (${approvable.length}건)` : '선택 결재';
  $('lsReject').disabled = rejectable.length === 0; $('lsReject').textContent = rejectable.length ? `선택 반려 (${rejectable.length}건)` : '선택 반려';
}

async function act(action) {
  const sel = selectedList(), me = TE.me || {}, g = me.grade;
  const targets = sel.filter(r => action === 'submit' ? (r.appro_state === 0 && r.write_name === me.name)
    : action === 'approve' ? r.appro_state === g : (r.appro_state === g || (g === 3 && r.appro_state === 4)));
  if (!targets.length) return;
  let bigo = '';
  if (action === 'reject') { bigo = prompt(`${targets.length}건을 반려합니다. 사유를 적으세요.`) || ''; if (!bigo.trim()) return; }
  else if (!confirm(`${targets.length}건을 ${action === 'submit' ? '제출' : '결재'}합니다. 진행할까요?`)) return;
  try {
    const p = await api('POST', '/api/travel-expense/approve', { action, targets: targets.map(r => ({ seq: r.seq, doc_id: r.doc_id })), bigo });
    toast(p.message, (p.data.skipped || []).length > 0);
    await loadList();
    if (window.A10_TE_ENTRY) window.A10_TE_ENTRY.reloadMine();
  } catch (e) { toast(e.message, true); }
}
TE.act = act;

function setMonthRange() {
  const m = $('lsMonth').value; if (!m) return;
  const y = Number(m.slice(0, 4)), mo = Number(m.slice(4, 6));
  const last = new Date(y, mo, 0).getDate();
  $('lsFrom').value = `${m.slice(0, 4)}-${m.slice(4, 6)}-01`; $('lsTo').value = `${m.slice(0, 4)}-${m.slice(4, 6)}-${String(last).padStart(2, '0')}`;
}

$('lsSearch').addEventListener('click', () => loadList().catch(e => toast(e.message, true)));
$('lsDoc').addEventListener('keydown', e => { if (e.key === 'Enter') $('lsSearch').click(); });
// 기준이 '월'인 채 날짜만 고치면 조회·총괄표 제목이 월 그대로였다(2026-09-10) — 날짜를 만지면 출장일 기준으로,
// 월을 고르면 월 기준으로 자동 전환해 제목과 조회가 늘 보이는 조건을 따른다.
$('lsMonth').addEventListener('change', () => { document.querySelector('input[name=dateKind][value=""]').checked = true; setMonthRange(); });
['lsFrom', 'lsTo'].forEach(id => $(id).addEventListener('change', () => { if (!document.querySelector('input[name=dateKind]:checked').value) document.querySelector('input[name=dateKind][value="cul"]').checked = true; }));
$('lsAll').addEventListener('change', () => { $('lsRows').querySelectorAll('input.pick').forEach(b => { b.checked = $('lsAll').checked; }); updateListSelection(); });
$('lsSubmit').addEventListener('click', () => act('submit'));
$('lsApprove').addEventListener('click', () => act('approve'));
$('lsReject').addEventListener('click', () => act('reject'));
// 엑셀은 EXE 에서도 받히게 공용 내려받기(A10_DOWNLOAD)로 — 새 창(window.open)은 pywebview 에서 안 열린다
$('lsExcel').addEventListener('click', () => { window.A10_DOWNLOAD(`/api/travel-expense/export.xlsx?${listQuery()}`); });
// 인쇄는 델파이 양식(작성자별 청구서, 결재란) — travel-expense-print.js (2026-09-10)
$('lsPrint').addEventListener('click', () => { if (window.A10_TE_PRINT) window.A10_TE_PRINT(listQuery()).catch(e => toast(e.message, true)); });
$('lsPrintSummary').addEventListener('click', () => { if (window.A10_TE_PRINT_SUMMARY) window.A10_TE_PRINT_SUMMARY(listQuery()).catch(e => toast(e.message, true)); });

// ── 월별 현황 ───────────────────────────────────────────────────────────────
async function loadMonths() {
  $('moRows').innerHTML = '<tr><td colspan="5" class="te-hint">불러오는 중...</td></tr>';
  const p = await api('GET', '/api/travel-expense/months');
  const items = (p.data.items || []).slice().reverse();
  $('moRows').innerHTML = items.map(m => `<tr class="pick" data-bungi="${esc(m.bungi)}">
    <td class="center"><b>${esc(m.label)}</b></td><td class="number">${num(m.count)}</td>
    <td>${Object.entries(m.by_state).map(([k, v]) => `${esc(k)} ${v}`).join(' · ') || '-'}</td>
    <td class="center">${m.locked ? '<span class="badge lock">잠김</span>' : '<span class="badge s0">열림</span>'}</td><td class="center">${esc(m.locked_date || '-')}</td></tr>`).join('');
  $('moRows').querySelectorAll('tr.pick').forEach(tr => tr.addEventListener('click', () => {
    $('lsMonth').value = tr.dataset.bungi; document.querySelector('input[name=dateKind][value=""]').checked = true; setMonthRange();
    showTab('list'); loadList().catch(e => toast(e.message, true));
  }));
}
$('moRefresh').addEventListener('click', () => loadMonths().catch(e => toast(e.message, true)));

// ── 시작 ────────────────────────────────────────────────────────────────────
window.A10_READY.then(async ctx => {
  if (ctx.office_id !== '10') {
    $('enSummary').textContent = '출장비는 본사 직원만 쓸 수 있습니다.'; $('enDocs').innerHTML = '';
    document.querySelectorAll('.te-tabs button').forEach(b => { b.disabled = true; });
    return;
  }
  try {
    const p = await api('GET', '/api/travel-expense/me');
    TE.me = p.data;
    $('lsMonth').innerHTML = p.data.months.map(m => `<option value="${m}">${m.slice(0, 4)}-${m.slice(4, 6)}</option>`).join('');
    $('lsMonth').value = p.data.current_month; setMonthRange();
    $('lsEmpGrp').hidden = !p.data.is_approver;
    $('enMe').textContent = `${p.data.name} · ${p.data.is_approver ? `결재자 ${p.data.grade}급` : '작성자'}`;
    $('lsHint').textContent = p.data.is_approver ? `결재자(${p.data.grade}급)라 전체가 보입니다. 내 등급과 같은 상태의 건만 결재·반려할 수 있습니다.` : '작성자는 본인 건만 보입니다. 미상신 건은 더블클릭해서 고치거나 체크해서 제출하세요.';
    if (window.A10_TE_ENTRY && !ENTRY_HIDDEN()) window.A10_TE_ENTRY.init();
    showTab('months');
  } catch (e) { toast(e.message, true); }
});
