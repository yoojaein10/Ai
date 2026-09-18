// 계산서 일괄발급 (2026-08-27) — 입금된 건을 탭(일반·대주단·국민약식)별로 체크해 한 번에 팝빌 발행.
// 목록은 /api/taxinvoice/bulk/candidates, 발급은 /api/taxinvoice/bulk/issue (행마다 결과가 돌아온다).
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const num = v => money.format(Math.round(Number(v || 0)));
const fmtBiz = v => { const d = String(v || '').replace(/[^0-9]/g, '').slice(0, 10); return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d; };
const KIND_TITLE = { general: '일반', syndicate: '대주단', kb: '국민약식', external: '외부 발행 등록', pool: '계산서 적용' };
const KIND_NOTE = {
  general: '감정서 하나에 거래처 하나인 건입니다. 거래처가 둘 이상이면 대주단 탭에, 400으로 시작하는 국민 약식 의뢰번호는 국민약식 탭에 있습니다.',
  syndicate: '감정서 하나에 거래처가 여럿인 건 — 거래처마다 한 장씩, 금액은 그 거래처 매출 전표의 공급가입니다. 이미 발행된 거래처는 빠집니다(미발행만 해제하면 보입니다).',
  kb: '400으로 시작하는 국민 약식 의뢰번호 — 번호마다 해당 국민은행 지점 앞으로 한 장씩(품목 "약식평가수수료 400…"). 금액은 입금일 구간 안의 매출 전표 합계입니다: 27일만 고르면 그날 전표, 27~31일이면 그 사이 전표를 합쳐 한 장. 같은 구간에 이미 발행된 계산서는 뺍니다.',
};

let kind = 'general';
let items = [];
let isTest = false;
const ctxOf = () => window.A10_CTX || {};
const requester = () => Number(ctxOf().usr_seq || 0);

function toast(msg, err) {
  const t = $('toast');
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 7000);
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

function query() {
  const q = new URLSearchParams({
    kind, date_from: $('dateFrom').value, date_to: $('dateTo').value,
    pay_status: $('payStatus').value, only_unissued: $('onlyUnissued').checked ? 'true' : 'false',
    office_code: window.A10_OFFICE(),
  });
  return q;
}

async function load() {
  $('resultSummary').textContent = '조회 중...';
  $('rows').innerHTML = '<tr><td colspan="12" class="tb-hint">불러오는 중...</td></tr>';
  const data = await api('GET', `/api/taxinvoice/bulk/candidates?${query()}`);
  items = data.items || [];
  isTest = !!data.is_test;
  if (data.default_email) $('defaultEmail').textContent = data.default_email;
  render(data.truncated);
}

function render(truncated) {
  $('tabTitle').textContent = KIND_TITLE[kind];
  $('tabNote').textContent = KIND_NOTE[kind];
  const issuable = items.filter(i => i.issuable).length;
  $('resultSummary').textContent = `${items.length}건 · 발급 가능 ${issuable}건${truncated ? ' (너무 많아 일부만 — 기간을 좁히세요)' : ''}`;
  $('emptyList').classList.toggle('hidden', items.length !== 0);
  $('rows').innerHTML = items.map((it, i) => {
    // issued_note: 기발행 몫을 빼고 계산했다는 표시 (입금된 만큼만 발급, 2026-09-02)
    const deductNote = !it.issued && it.issued_note ? ` <span class="badge muted">${esc(it.issued_note)}</span>` : '';
    const state = it.issued ? `<span class="badge muted">${esc(it.reason)}</span>`
      : it.issuable ? `<span class="badge ok">발급 가능</span>${deductNote}` : `<span class="badge warn">${esc(it.reason)}</span>${deductNote}`;
    return `<tr data-i="${i}" class="${it.issuable ? '' : 'off'}">
      <td class="center"><input class="pick" type="checkbox"${it.issuable ? '' : ' disabled'}></td>
      <td>${esc(it.doc_id)}</td>
      <td title="${esc(it.customer_name || '')}">${esc(it.partner_name || it.customer_name || '-')}${it.kind === 'syndicate' ? ` <span class="badge muted">${esc(it.pay_status)}</span>` : ''}</td>
      <td class="center">${fmtBiz(it.corp_num) || '<span class="badge warn">없음</span>'}</td>
      <td>${esc(it.manager || '-')}</td>
      <td class="center">${esc(it.pay_status)}</td>
      <td><input class="dt" type="date" value="${esc(it.write_date || '')}"${it.issuable ? '' : ' disabled'}></td>
      <td class="number"><input class="amt supply" value="${num(it.supply_cost)}"${it.issuable ? '' : ' disabled'}></td>
      <td class="number"><input class="amt tax" value="${num(it.tax)}"${it.issuable ? '' : ' disabled'}></td>
      <td class="number total">${num(it.total)}</td>
      <td><input class="mail" placeholder="담당자 이메일 (비면 기본 주소)" value=""${it.issuable ? '' : ' disabled'}></td>
      <td class="result">${state}</td>
    </tr>`;
  }).join('');
  $('rows').querySelectorAll('.pick').forEach(box => box.addEventListener('change', updateSelection));
  // 공급가를 고치면 세액은 10%로 따라오고, 세액만 따로 고칠 수도 있다 (단건 팝업과 같은 습관)
  $('rows').querySelectorAll('tr').forEach(tr => {
    const supply = tr.querySelector('.supply'), tax = tr.querySelector('.tax');
    if (!supply) return;
    const digits = el => Number(String(el.value).replace(/[^0-9]/g, '') || 0);
    supply.addEventListener('input', () => { tax.value = num(Math.round(digits(supply) * 0.1)); tr.querySelector('.total').textContent = num(digits(supply) + digits(tax)); updateSelection(); });
    tax.addEventListener('input', () => { tr.querySelector('.total').textContent = num(digits(supply) + digits(tax)); updateSelection(); });
    supply.addEventListener('blur', () => { supply.value = num(digits(supply)); });
    tax.addEventListener('blur', () => { tax.value = num(digits(tax)); });
  });
  $('checkAll').checked = false;
  updateSelection();
  if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('rowsTable'), 'a10.taxBulk.columnWidths');
}

function selectedRows() {
  return Array.from($('rows').querySelectorAll('tr')).filter(tr => { const b = tr.querySelector('.pick'); return b && b.checked && !b.disabled; });
}

function rowPayload(tr) {
  const it = items[Number(tr.dataset.i)];
  const digits = el => Number(String(el.value).replace(/[^0-9]/g, '') || 0);
  return {
    kind: it.kind, doc_id: it.doc_id, tr_cd: it.tr_cd || '', corp_num: it.corp_num || '', partner_name: it.partner_name || '',
    supply_cost: digits(tr.querySelector('.supply')), tax: digits(tr.querySelector('.tax')),
    write_date: tr.querySelector('.dt').value, email: tr.querySelector('.mail').value.trim(),
  };
}

function updateSelection() {
  const rows = selectedRows();
  const total = rows.reduce((s, tr) => s + Number(String(tr.querySelector('.total').textContent).replace(/[^0-9]/g, '') || 0), 0);
  $('issueButton').disabled = rows.length === 0;
  $('issueButton').textContent = rows.length ? `선택 발급 (${rows.length}건 · ${num(total)}원)` : '선택 발급';
  $('summary').innerHTML = `<span>${isTest ? '<span class="test">팝빌 테스트 모드</span>' : '<span class="live">실발급 — 국세청·거래처로 전송됩니다</span>'}</span>`
    + `<span>선택 <b>${rows.length}</b>건</span><span>합계 <b>${num(total)}</b>원</span>`;
}

async function issueSelected() {
  const rows = selectedRows();
  if (!rows.length) return;
  const payload = rows.map(rowPayload);
  const bad = payload.find(p => !p.supply_cost || !p.write_date || String(p.write_date).replace(/-/g, '').length !== 8);
  if (bad) { toast(`${bad.doc_id}: 공급가와 작성일자를 확인하세요.`, true); return; }
  if (payload.length > 50) { toast('한 번에 50건까지 발급할 수 있습니다. 나눠서 발급하세요.', true); return; }
  const total = payload.reduce((s, p) => s + p.supply_cost + p.tax, 0);
  const warning = isTest ? '팝빌 테스트 서버로만 발행됩니다.' : '실제로 국세청과 거래처로 전송되며 되돌리기 어렵습니다.';
  if (!confirm(`세금계산서 ${payload.length}장(합계 ${num(total)}원)을 발급합니다.\n${warning}\n진행할까요?`)) return;
  const button = $('issueButton');
  button.disabled = true; button.textContent = `발급 중... (${payload.length}건)`;
  rows.forEach(tr => { tr.querySelector('.result').innerHTML = '<span class="badge">발급 중</span>'; });
  try {
    const data = await api('POST', '/api/taxinvoice/bulk/issue', { items: payload });
    const byKey = Object.fromEntries((data.results || []).map(r => [r.key, r]));
    rows.forEach(tr => {
      const it = items[Number(tr.dataset.i)];
      const r = byKey[it.key];
      const cell = tr.querySelector('.result');
      if (!r) { cell.innerHTML = '<span class="badge warn">결과 없음</span>'; return; }
      if (r.success) {
        cell.innerHTML = `<span class="badge ok">발급 완료</span> <small>${esc(r.nts_confirm || r.mgt_key || '')}${r.email ? ` · ${esc(r.email)}` : ''}</small>`;
        tr.classList.add('done'); tr.querySelector('.pick').checked = false; tr.querySelector('.pick').disabled = true;
        it.issued = true; it.issuable = false;
        tr.querySelectorAll('input.dt, input.amt, input.mail').forEach(el => { el.disabled = true; });
      } else {
        cell.innerHTML = `<span class="badge ${r.skipped ? 'muted' : 'bad'}">${esc(r.skipped ? '건너뜀' : '실패')}</span> <small>${esc(r.message || '')}</small>`;
        if (r.skipped) { tr.querySelector('.pick').checked = false; tr.querySelector('.pick').disabled = true; it.issuable = false; }
      }
    });
    toast(`${data.issued}건 발급${data.skipped ? ` · ${data.skipped}건 건너뜀` : ''}${data.failed ? ` · ${data.failed}건 실패 — 행의 사유를 보고 다시 시도하세요` : ''}`, data.failed > 0);
  } catch (err) {
    rows.forEach(tr => { tr.querySelector('.result').innerHTML = '<span class="badge bad">요청 실패</span>'; });
    showError(err);
  } finally {
    updateSelection();
  }
}

function setKind(next) {
  // 외부 발행 등록(2026-09-09)은 조회 목록이 아니라 별도 패널 — 두 패널의 탭 줄이 같은 버튼을 가진다
  document.querySelectorAll('.tb-tabs button').forEach(b => b.classList.toggle('active', b.dataset.kind === next));
  $('bulkPanel').hidden = next === 'external' || next === 'pool';
  $('extPanel').hidden = next !== 'external';
  $('poolPanel').hidden = next !== 'pool';
  if (next === 'pool' && window.A10_POOL_LOAD) window.A10_POOL_LOAD();
  if (next === 'external' || next === 'pool') return;
  kind = next;
  load().catch(showError);
}

async function loadCounts() {
  // 탭 머리의 건수 — 현재 조건으로 세 탭을 한 번씩 세어 둔다 (발급 가능 건수)
  for (const [k, id] of [['general', 'countGeneral'], ['syndicate', 'countSyndicate'], ['kb', 'countKb']]) {
    try {
      const q = query(); q.set('kind', k);
      const data = await api('GET', `/api/taxinvoice/bulk/candidates?${q}`);
      const n = (data.items || []).filter(i => i.issuable).length;
      $(id).textContent = n ? `(${n})` : '';
    } catch (err) { $(id).textContent = ''; }
  }
}

document.querySelectorAll('.tb-tabs button').forEach(b => b.addEventListener('click', () => setKind(b.dataset.kind)));
$('searchButton').addEventListener('click', () => { load().then(loadCounts).catch(showError); });
['dateFrom', 'dateTo'].forEach(id => $(id).addEventListener('keydown', e => { if (e.key === 'Enter') $('searchButton').click(); }));
['payStatus', 'onlyUnissued'].forEach(id => $(id).addEventListener('change', () => load().catch(showError)));
$('checkAll').addEventListener('change', () => {
  $('rows').querySelectorAll('.pick').forEach(box => { if (!box.disabled) box.checked = $('checkAll').checked; });
  updateSelection();
});
$('issueButton').addEventListener('click', () => issueSelected().catch(showError));
$('officeCode').addEventListener('change', () => { load().then(loadCounts).catch(showError); });

const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const today = new Date(); const weekAgo = new Date(today); weekAgo.setDate(today.getDate() - 6);
$('dateFrom').value = fmt(weekAgo); $('dateTo').value = fmt(today);

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10' || !ctx.is_operations) {
    $('rows').innerHTML = ''; $('resultSummary').textContent = '';
    $('emptyList').classList.remove('hidden'); $('emptyList').textContent = '계산서 일괄발급은 본사 재무팀·집행부만 사용할 수 있습니다.';
    document.querySelectorAll('.tb-tabs button[data-kind=external], .tb-tabs button[data-kind=pool]').forEach(b => { b.disabled = true; });
    return;
  }
  load().then(loadCounts).catch(showError);
});
