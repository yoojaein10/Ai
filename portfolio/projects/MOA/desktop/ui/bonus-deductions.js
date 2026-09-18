// 상여 공제 대장 (2026-08-27) — 공제를 발생(대기) → 지급월 적용 → 마감 잠금으로 관리한다.
// 상여 화면 '공제 대장' 버튼으로 들어온다. 권한 키는 상여(bonus)를 같이 쓰고, 쓰기는 본사 재무팀·집행부만.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const num = v => (v == null || v === '') ? '' : money.format(Math.round(Number(v)));
const dateText = v => v ? String(v).slice(0, 10) : '';
// 종류를 빠지는 단계별로 묶는다 — 산출액(Q)·세전(Y)은 세금이 줄고, 세후(AB)는 실수령액만 준다. AB = 엑셀 미수금 탭 회수.
const KIND_GROUPS = [
  ['산출액(Q)에서 — 상여율 곱하기 전', [
    ['VARIABLE_ADJ', '가변비 추가(−)'], ['VARIABLE_CREDIT', '가변비 환입(+)'], ['UNPAID_CARRY', '미납비이월 수기(−)'],
    ['DOC_EXPENSE', '당월감정서경비(−)'], ['EXPENSE_CREDIT', '감정서경비 환입(+)'], ['MISC', '기타(N)(−)'],
  ]],
  ['세전(Y)에서 — 세금 계산 전에 뺌', [
    ['WREATH', '화환공제(−)'], ['PENALTY', '패널티(−)'], ['INSURANCE', '보험료·법인차량(−)'], ['OTHER_EXPENSE', '기타 비용공제(W)(−)'],
    ['HANDLING', '처리비·처리수당(+)'], ['ADVANCE_PAID', '선지급(−)'],
  ]],
  ['세후 — 세금 다 뗀 지급액에서 뺌', [['OTHER_DEDUCT', '미수금 회수(AB·세후)(−)']]],
];
const KINDS = KIND_GROUPS.flatMap(g => g[1]);
const STATUS_LABEL = { PENDING: '대기', APPLIED: '적용', VOID: '무효' };
const SOURCE_LABEL = { MANUAL: '수기', EXCEL: '엑셀', VOUCHER: '전표' };

let items = [];
let pendingSummary = {};
let closes = [];
const ctxOf = () => window.A10_CTX || {};
const requester = () => Number(ctxOf().usr_seq || 0);
const canWrite = () => !!ctxOf().is_operations;
const kindLabel = kind => (KINDS.find(k => k[0] === kind) || [kind, kind])[1];
const periodLabel = p => p ? `${p.slice(0, 4)}-${p.slice(4)}` : '';
const monthToPeriod = v => (v || '').replace('-', '');
const isClosed = period => closes.some(c => c.period === period && c.status === 'CLOSED');

// ── 공통 ──────────────────────────────────────────────────────────────

function toast(msg, err) {
  const t = $('toast');
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 6000);
}
const showError = err => toast(err.message || String(err), true);

async function api(method, url, body) {
  const res = await fetch(url, {
    method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify({ requester_usr_seq: requester(), ...body }) : undefined,
  });
  const p = await res.json();
  if (!p.success) throw new Error(p.message);
  return p.data;
}

function filterQuery() {
  const q = new URLSearchParams();
  const person = $('personFilter').value.trim();
  if (person) q.set('person', person);
  if ($('kindFilter').value) q.set('kind', $('kindFilter').value);
  return q;
}

// ── 조회 ──────────────────────────────────────────────────────────────

async function load() {
  $('resultSummary').textContent = '조회 중...';
  const status = $('statusFilter').value;
  const period = monthToPeriod($('periodFilter').value);
  const q = filterQuery();
  const calls = [];
  if (status === 'ALL' || status === 'PENDING') calls.push(api('GET', `/api/bonus/v2/deduction-items?status=PENDING&${q}`));
  if (status === 'ALL' || status === 'APPLIED') calls.push(api('GET', `/api/bonus/v2/deduction-items?status=APPLIED${period ? `&period=${period}` : ''}&${q}`));
  if (status === 'VOID') calls.push(api('GET', `/api/bonus/v2/deduction-items?status=VOID&${q}`));
  const results = await Promise.all(calls);
  const seen = new Set();
  items = results.flatMap(r => r.items).filter(i => !seen.has(i.item_id) && seen.add(i.item_id));
  pendingSummary = (results[0] && results[0].pending) || {};
  render();
}

function visibleItems() {
  const text = $('textFilter').value.trim().toLowerCase();
  const rows = text ? items.filter(i => `${i.doc_id || ''} ${i.memo || ''} ${i.person}`.toLowerCase().includes(text)) : items;
  const order = { PENDING: 0, APPLIED: 1, VOID: 2 };
  return [...rows].sort((a, b) => (order[a.status] - order[b.status]) || a.person.localeCompare(b.person, 'ko') || String(a.occurred_on || '').localeCompare(String(b.occurred_on || '')) || (a.item_id - b.item_id));
}

function actionCell(item) {
  if (!canWrite() || item.status === 'VOID') return '<td></td>';
  const locked = item.status === 'APPLIED' && isClosed(item.applied_period);
  const edit = item.status === 'PENDING' ? `<button class="small-button edit-button" data-id="${item.item_id}" type="button">수정</button>` : '';
  const split = item.status === 'PENDING' && item.amount > 1 ? `<button class="small-button split-button" data-id="${item.item_id}" type="button" title="이번 달엔 일부만 빼기 — 항목을 둘로 나눕니다">분할</button>` : '';
  const release = item.status === 'APPLIED' && !locked ? `<button class="small-button release-button" data-id="${item.item_id}" type="button" title="이 달 적용을 풀고 대기로">대기로</button>` : '';
  const voidButton = `<button class="small-button danger void-button" data-id="${item.item_id}" type="button"${locked ? ' disabled title="마감된 달에 들어 있어 재개 전엔 못 건드립니다"' : ''}>무효</button>`;
  return `<td>${edit}${split}${release}${voidButton}</td>`;
}

function render() {
  const rows = visibleItems();
  const totals = { PENDING: [0, 0], APPLIED: [0, 0], VOID: [0, 0] };
  rows.forEach(i => { totals[i.status][0] += 1; totals[i.status][1] += Number(i.amount || 0); });
  $('resultSummary').textContent = `대기 ${totals.PENDING[0]}건 ${num(totals.PENDING[1])}원 · 적용 ${totals.APPLIED[0]}건 ${num(totals.APPLIED[1])}원${totals.VOID[0] ? ` · 무효 ${totals.VOID[0]}건` : ''}`;
  const chips = Object.entries(pendingSummary).sort((a, b) => a[0].localeCompare(b[0], 'ko'))
    .map(([person, s]) => `<span class="chip" data-person="${esc(person)}" title="이 사람만 보기">${esc(person)} 대기 ${s.count}건 ${num(s.amount)}</span>`).join('');
  $('pendingChips').innerHTML = chips ? `미처리(대기) 사람: ${chips}` : '대기 중인 공제가 없습니다.';
  $('pendingChips').querySelectorAll('.chip').forEach(chip => chip.addEventListener('click', () => { $('personFilter').value = chip.dataset.person; load().catch(showError); }));
  $('emptyList').classList.toggle('hidden', rows.length !== 0);
  $('ledgerRows').innerHTML = rows.map(item => {
    const locked = item.status === 'APPLIED' && isClosed(item.applied_period);
    const applied = item.applied_period ? `${periodLabel(item.applied_period)}${locked ? '<span class="badge locked">마감</span>' : ''}` : '';
    return `<tr class="${item.status.toLowerCase()}" data-id="${item.item_id}"><td><span class="badge ${item.status.toLowerCase()}">${STATUS_LABEL[item.status] || item.status}</span></td>
      <td>${esc(item.person)}</td><td>${esc(kindLabel(item.kind))}</td><td class="number">${num(item.amount)}</td><td>${esc(item.doc_id || '')}</td><td>${dateText(item.occurred_on)}</td>
      <td class="memo">${esc(item.memo || '')}${item.void_reason ? `<span class="badge void">${esc(item.void_reason)}</span>` : ''}</td>
      <td><span class="badge muted">${esc(SOURCE_LABEL[item.source] || item.source)}</span></td><td>${applied}</td><td>${dateText(item.created_at)}</td>${actionCell(item)}</tr>`;
  }).join('');
  $('ledgerRows').querySelectorAll('.edit-button').forEach(b => b.addEventListener('click', () => openItem(items.find(i => i.item_id === Number(b.dataset.id)))));
  $('ledgerRows').querySelectorAll('.split-button').forEach(b => b.addEventListener('click', () => openSplit(items.find(i => i.item_id === Number(b.dataset.id)))));
  $('ledgerRows').querySelectorAll('.release-button').forEach(b => b.addEventListener('click', () => releaseItem(items.find(i => i.item_id === Number(b.dataset.id))).catch(showError)));
  $('ledgerRows').querySelectorAll('.void-button').forEach(b => b.addEventListener('click', () => openVoid(items.find(i => i.item_id === Number(b.dataset.id)))));
  fitTableHeight();
}

function fitTableHeight() {
  const wrap = document.querySelector('.list-panel > .table-wrap');
  if (!wrap) return;
  const top = wrap.getBoundingClientRect().top + window.scrollY;
  wrap.style.height = `${Math.max(360, window.innerHeight - top - 30)}px`;
}
window.addEventListener('resize', fitTableHeight);

// ── 등록 / 수정 ─────────────────────────────────────────────────────────

function openItem(item) {
  const dialog = $('itemDialog');
  dialog.dataset.id = item ? item.item_id : '';
  $('itemTitle').textContent = item ? `공제 항목 수정 · ${item.person}` : '새 공제 항목';
  $('fPerson').value = item ? item.person : ($('personFilter').value.trim() || '');
  $('fKind').value = item ? item.kind : 'WREATH';
  $('fAmount').value = item ? Math.round(item.amount) : '';
  $('fDoc').value = item ? (item.doc_id || '') : '';
  $('fDate').value = item ? dateText(item.occurred_on) : '';
  $('fMemo').value = item ? (item.memo || '') : '';
  $('fApply').value = '';
  // 수정 때는 지급월 칸을 숨긴다 — 적용은 상여 화면(사람별 공제)에서만 바꾼다
  document.querySelector('label[for="fApply"]').classList.toggle('hidden', !!item);
  $('fApply').classList.toggle('hidden', !!item);
  dialog.showModal();
}

async function saveItem() {
  const id = $('itemDialog').dataset.id;
  const body = {
    person: $('fPerson').value.trim(), kind: $('fKind').value, amount: Number($('fAmount').value || 0),
    doc_id: $('fDoc').value.trim() || null, occurred_on: $('fDate').value || null, memo: $('fMemo').value.trim() || null,
  };
  if (!body.person) throw new Error('이름을 적어 주세요.');
  if (!(body.amount > 0)) throw new Error('금액을 적어 주세요.');
  if (id) {
    await api('PUT', `/api/bonus/v2/deduction-items/${id}`, { ...body, memo: body.memo || '' });
    toast('공제 항목을 고쳤습니다.');
  } else {
    const apply = monthToPeriod($('fApply').value);
    const data = await api('POST', '/api/bonus/v2/deduction-items', { ...body, apply_period: apply || null });
    toast(data.item.status === 'APPLIED' ? `${body.person}의 공제를 ${periodLabel(data.item.applied_period)} 지급분에 바로 적용했습니다.` : `${body.person}의 공제를 대기로 올렸습니다.`);
  }
  $('itemDialog').close();
  await load();
}

async function releaseItem(item) {
  if (!confirm(`${item.person} · ${kindLabel(item.kind)} ${num(item.amount)}원의 ${periodLabel(item.applied_period)} 적용을 풀고 대기로 돌립니다. 계속할까요?`)) return;
  const current = await api('GET', `/api/bonus/v2/deduction-items?status=APPLIED&period=${item.applied_period}&person=${encodeURIComponent(item.person)}`);
  const keep = current.items.map(i => i.item_id).filter(id => id !== item.item_id);
  await api('PUT', `/api/bonus/v2/deductions/${item.applied_period}/${encodeURIComponent(item.person)}`, { applied_item_ids: keep, new_items: [] });
  toast('대기로 돌렸습니다.');
  await load();
}

function openSplit(item) {
  const dialog = $('splitDialog');
  dialog.dataset.id = item.item_id;
  $('splitHint').textContent = `${item.person} · ${kindLabel(item.kind)} ${num(item.amount)}원을 둘로 나눕니다. 떼어낸 금액이 새 대기 항목이 되고, 잔액은 이 항목에 남습니다 (엑셀 미수금 탭의 부분 회수 방식).`;
  $('splitAmount').value = '';
  $('splitAmount').max = Math.round(item.amount) - 1;
  dialog.showModal();
}

async function saveSplit() {
  const id = $('splitDialog').dataset.id;
  const amount = Number($('splitAmount').value || 0);
  if (!(amount > 0)) throw new Error('떼어낼 금액을 적어 주세요.');
  const data = await api('POST', `/api/bonus/v2/deduction-items/${id}/split`, { amount });
  $('splitDialog').close();
  toast(`${num(data.split.amount)}원을 떼어 새 대기 항목으로 만들었습니다 (잔액 ${num(data.remainder.amount)}원).`);
  await load();
}

function openVoid(item) {
  const dialog = $('voidDialog');
  dialog.dataset.id = item.item_id;
  $('voidHint').textContent = `${item.person} · ${kindLabel(item.kind)} ${num(item.amount)}원${item.applied_period ? ` (${periodLabel(item.applied_period)} 적용 중 — 무효 처리하면 그 달 계산에서 빠집니다)` : ''}`;
  $('voidReason').value = '';
  dialog.showModal();
}

async function saveVoid() {
  const id = $('voidDialog').dataset.id;
  const reason = $('voidReason').value.trim();
  if (!reason) throw new Error('무효 사유를 적어 주세요.');
  await api('POST', `/api/bonus/v2/deduction-items/${id}/void`, { reason });
  $('voidDialog').close();
  toast('무효 처리했습니다.');
  await load();
}

// ── 초기화 ─────────────────────────────────────────────────────────────

function kindOptions() {
  return KIND_GROUPS.map(([label, kinds]) =>
    `<optgroup label="${label}">${kinds.map(([k, text]) => `<option value="${k}">${text}</option>`).join('')}</optgroup>`).join('');
}

function fillKinds() {
  $('kindFilter').innerHTML = '<option value="">전체</option>' + kindOptions();
  $('fKind').innerHTML = kindOptions();
}

async function loadPeople() {
  try {
    const data = await api('GET', '/api/bonus/settings/persons');
    $('personList').innerHTML = (data.items || []).map(p => `<option value="${esc(p.person)}"></option>`).join('');
  } catch (err) { /* 사람 목록은 보조 — 없어도 화면은 돈다 */ }
}

async function loadStatus() {
  const data = await api('GET', '/api/bonus/v2/status');
  closes = data.periods || [];
  return data.next;
}

$('searchButton').addEventListener('click', () => load().catch(showError));
['statusFilter', 'kindFilter'].forEach(id => $(id).addEventListener('change', () => load().catch(showError)));
$('textFilter').addEventListener('input', () => render());
['personFilter', 'periodFilter'].forEach(id => $(id).addEventListener('keydown', event => { if (event.key === 'Enter') $('searchButton').click(); }));
$('backButton').addEventListener('click', () => { location.href = '/desktop/bonus'; });
$('newButton').addEventListener('click', () => openItem(null));
$('templateButton').addEventListener('click', () => { window.A10_DOWNLOAD('/api/bonus/v2/deduction-items/template.xlsx'); });
$('importButton').addEventListener('click', () => { $('importFile').value = ''; $('importFile').click(); });
$('importFile').addEventListener('change', () => importFile().catch(showError));

async function importFile() {
  const file = $('importFile').files[0];
  if (!file) return;
  const form = new FormData();
  form.append('requester_usr_seq', String(requester()));
  form.append('file', file);
  const res = await fetch('/api/bonus/v2/deduction-items/import', { method: 'POST', body: form });
  const p = await res.json();
  if (!p.success) throw new Error(p.message);
  const errors = p.data.errors || [];
  $('importErrors').classList.toggle('hidden', !errors.length);
  $('importErrors').textContent = errors.length ? `올리지 못한 행: ${errors.slice(0, 8).join(' / ')}${errors.length > 8 ? ` 외 ${errors.length - 8}건` : ''}` : '';
  toast(`${file.name}: ${p.message}`, errors.length > 0);
  await load();
}
$('exportButton').addEventListener('click', () => {
  const q = filterQuery();
  const status = $('statusFilter').value;
  if (status !== 'ALL') q.set('status', status);
  const period = monthToPeriod($('periodFilter').value);
  if (period && status !== 'PENDING') q.set('period', period);
  window.A10_DOWNLOAD(`/api/bonus/v2/deduction-items/export.xlsx?${q}`);
});
$('itemCancel').addEventListener('click', () => $('itemDialog').close());
$('itemSave').addEventListener('click', () => saveItem().catch(showError));
$('voidCancel').addEventListener('click', () => $('voidDialog').close());
$('voidSave').addEventListener('click', () => saveVoid().catch(showError));
$('splitCancel').addEventListener('click', () => $('splitDialog').close());
$('splitSave').addEventListener('click', () => saveSplit().catch(showError));

window.A10_READY.then(async ctx => {
  if (ctx.office_id !== '10' || !ctx.is_operations) {
    $('ledgerRows').innerHTML = ''; $('resultSummary').textContent = '';
    $('emptyList').classList.remove('hidden'); $('emptyList').textContent = '공제 대장은 본사 재무팀·집행부만 사용할 수 있습니다.';
    return;
  }
  fillKinds();
  $('newButton').classList.toggle('hidden', !canWrite());
  $('importButton').classList.toggle('hidden', !canWrite());
  try {
    const next = await loadStatus();
    $('periodFilter').value = periodLabel(next);
    await loadPeople();
    await load();
  } catch (err) { showError(err); }
});
