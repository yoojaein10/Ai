// 상여 설정 (본사 재무팀·집행부) — 사람 파라미터 · 요율 스케줄 · 감정서 지분.
// 상여 화면 오른쪽 위 '설정' 버튼으로 들어온다 (2026-08-25 상여 재작성 1단계).
// 저장은 표마다 replace-all — 화면에 남긴 목록이 곧 현재 상태다.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 3 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const RATES = [40, 45, 35, 30];

let people = [];            // 사람 표
let rates = {};             // 사람 → 요율 구간 목록
let shares = {};            // 감정서 → 지분 목록
const dirty = { persons: false, rates: new Set(), shares: new Set() };
const requester = () => Number((window.A10_CTX || {}).usr_seq || 0);

// ── 공통 ──────────────────────────────────────────────────────────────

function showToast(msg, err) {
  const t = $('toast');
  if (!t) { alert(msg); return; }
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 5000);
}

function pendingCount() { return (dirty.persons ? 1 : 0) + dirty.rates.size + dirty.shares.size; }

function updateSummary() {
  const shareholders = people.filter(p => p.kind === 'SHAREHOLDER').length;
  const pending = pendingCount() ? ` · 저장 안 한 변경 <b>${pendingCount()}</b>건` : '';
  $('summary').innerHTML = `주주 <b>${shareholders}</b>명 · 소속 <b>${people.length - shareholders}</b>명 · 요율 <b>${Object.keys(rates).length}</b>명 · 지분 감정서 <b>${Object.keys(shares).length}</b>건${pending}`;
}

async function putJson(url, body) {
  const res = await fetch(url, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requester_usr_seq: requester(), ...body }),
  });
  const p = await res.json();
  if (!p.success) throw new Error(p.message);
  return p.data;
}

function switchTab(tab) {
  document.querySelectorAll('.bs-tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.bs-panel').forEach(p => p.classList.toggle('hidden', p.id !== 'panel-' + tab));
}

// ── 사람 ──────────────────────────────────────────────────────────────

function personRow(person) {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="p-name" maxlength="30" value="${esc(person.person || '')}" placeholder="이름"></td>
    <td><select class="p-kind">
      <option value="SHAREHOLDER"${person.kind === 'ASSOCIATE' ? '' : ' selected'}>주주</option>
      <option value="ASSOCIATE"${person.kind === 'ASSOCIATE' ? ' selected' : ''}>소속</option>
    </select></td>
    <td><input class="p-pay num" type="number" step="0.01" min="0.01" max="1" value="${person.pay_ratio ?? 1}"></td>
    <td><input class="p-tax num" type="number" step="0.01" min="0" max="0.99" value="${person.tax_rate ?? 0.3}"></td>
    <td><input class="p-common num" type="number" step="0.5" min="0.5" max="100" value="${person.common_rate ?? ''}" placeholder="규칙"></td>
    <td><input class="p-memo" maxlength="200" value="${esc(person.memo || '')}" placeholder="메모"></td>
    <td><button type="button" class="del" title="빼기">×</button></td>`;
  row.querySelectorAll('input, select').forEach(f => f.addEventListener('input', () => markPersons()));
  row.querySelector('.del').addEventListener('click', () => { row.remove(); markPersons(); });
  return row;
}

function markPersons() {
  dirty.persons = true;
  $('panel-persons').querySelector('.bs-card').classList.add('dirty');
  updateSummary();
}

function renderPersons() {
  const panel = $('panel-persons');
  panel.innerHTML = `
    <section class="bs-card">
      <div class="bs-head"><h3>사람</h3><span class="state">지급률은 소속 합계에 곱한다(기본 1) · 소득세율은 주주 0.30, 소속 0.15 · 공통건 %는 비우면 규칙(산업은행 4 / 국공유재산·법원 15·하한 30만 / 보상 15 / 그 외 3)</span>
        <button type="button" class="add">사람 추가</button></div>
      <table class="bs-rows">
        <thead><tr><th style="width:16%">이름</th><th style="width:12%">구분</th><th style="width:10%">지급률</th><th style="width:10%">소득세율</th><th style="width:10%" title="공(X) 공통건 요율 %. 비우면 규칙(산업은행 4, 국공유재산·법원 15 하한 30만, 보상 15) 아니면 3">공통건 %</th><th>메모</th><th style="width:44px"></th></tr></thead>
        <tbody></tbody>
      </table></section>`;
  const body = panel.querySelector('tbody');
  people.forEach(p => body.appendChild(personRow(p)));
  panel.querySelector('.add').addEventListener('click', () => { body.appendChild(personRow({ kind: 'SHAREHOLDER' })); markPersons(); });
}

function readPersons() {
  return Array.from($('panel-persons').querySelectorAll('tbody tr')).map(row => ({
    person: row.querySelector('.p-name').value.trim(),
    kind: row.querySelector('.p-kind').value,
    pay_ratio: Number(row.querySelector('.p-pay').value),
    tax_rate: Number(row.querySelector('.p-tax').value),
    common_rate: row.querySelector('.p-common').value === '' ? null : Number(row.querySelector('.p-common').value),
    memo: row.querySelector('.p-memo').value.trim(),
  })).filter(p => p.person);
}

// ── 요율 ──────────────────────────────────────────────────────────────

function rateRow(person, item) {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="r-from" type="date" value="${esc(item.from_date || '')}"></td>
    <td><input class="r-to" type="date" value="${esc(item.to_date || '')}"></td>
    <td><select class="r-rate">${RATES.map(r => `<option value="${r}"${Number(item.rate) === r ? ' selected' : ''}>${r}%</option>`).join('')}</select></td>
    <td><input class="r-label" maxlength="100" value="${esc(item.label || '')}" placeholder="근거 (엑셀 라벨 등)"></td>
    <td class="src">${esc(item.source || '')}</td>
    <td><button type="button" class="del" title="빼기">×</button></td>`;
  row.querySelectorAll('input, select').forEach(f => f.addEventListener('input', () => markRates(person)));
  row.querySelector('.del').addEventListener('click', () => { row.remove(); markRates(person); });
  return row;
}

function markRates(person) {
  dirty.rates.add(person);
  const card = document.querySelector(`.bs-card[data-person="${CSS.escape(person)}"]`);
  if (card) card.classList.add('dirty');
  updateSummary();
}

function rateCard(person) {
  const card = document.createElement('section');
  card.className = 'bs-card'; card.dataset.person = person;
  const rows = rates[person] || [];
  card.innerHTML = `
    <div class="bs-head"><h3>${esc(person)}</h3>
      <span class="state${rows.length ? '' : ' warn'}">${rows.length ? `${rows.length}구간` : '요율 없음 — 이 사람의 건은 요율 경고로 나온다'}</span>
      <button type="button" class="add">구간 추가</button></div>
    <table class="bs-rows">
      <thead><tr><th style="width:16%">접수일부터</th><th style="width:16%">접수일까지 (비우면 계속)</th><th style="width:10%">요율</th><th>근거</th><th style="width:8%"></th><th style="width:44px"></th></tr></thead>
      <tbody></tbody>
    </table>`;
  const body = card.querySelector('tbody');
  rows.forEach(item => body.appendChild(rateRow(person, item)));
  card.querySelector('.add').addEventListener('click', () => { body.appendChild(rateRow(person, { rate: 40 })); markRates(person); });
  return card;
}

function renderRates() {
  const panel = $('panel-rates');
  panel.innerHTML = '';
  const names = new Set(people.filter(p => p.kind === 'SHAREHOLDER').map(p => p.person));
  Object.keys(rates).forEach(n => names.add(n));
  Array.from(names).sort().forEach(person => panel.appendChild(rateCard(person)));
  if (!names.size) panel.innerHTML = '<p class="bs-empty">주주가 없습니다. 사람 탭에서 먼저 넣으세요.</p>';
}

function readRates(person) {
  const card = document.querySelector(`.bs-card[data-person="${CSS.escape(person)}"]`);
  return Array.from(card.querySelectorAll('tbody tr')).map(row => ({
    from_date: row.querySelector('.r-from').value || null,
    to_date: row.querySelector('.r-to').value || null,
    rate: Number(row.querySelector('.r-rate').value),
    label: row.querySelector('.r-label').value.trim(),
  }));
}

// ── 지분 ──────────────────────────────────────────────────────────────

function shareRow(doc, item) {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="s-person" maxlength="30" value="${esc(item.person || '')}" placeholder="이름"></td>
    <td><input class="s-pct num" type="number" step="0.001" min="0.001" max="100" value="${item.share_pct ?? ''}"></td>
    <td><input class="s-bc num" type="number" step="0.001" min="0.001" max="100" value="${item.bc_pct ?? ''}" placeholder="지분과 같으면 비움"></td>
    <td><input class="s-note" maxlength="200" value="${esc(item.note || '')}" placeholder="근거"></td>
    <td class="src">${esc(item.source || '')}</td>
    <td><button type="button" class="del" title="빼기">×</button></td>`;
  row.querySelectorAll('input').forEach(f => f.addEventListener('input', () => markShares(doc)));
  row.querySelector('.del').addEventListener('click', () => { row.remove(); markShares(doc); });
  return row;
}

function shareTotalText(doc) {
  const total = readShares(doc).reduce((sum, r) => sum + (r.share_pct || 0), 0);
  return { total, text: `합 ${money.format(total)}%`, warn: Math.abs(total - 100) > 0.01 };
}

function markShares(doc) {
  dirty.shares.add(doc);
  const card = document.querySelector(`.bs-card[data-doc="${CSS.escape(doc)}"]`);
  if (card) {
    card.classList.add('dirty');
    const t = shareTotalText(doc);
    const state = card.querySelector('.state');
    state.textContent = t.text + (t.warn ? ' — 100이 아닙니다(공동유치 50% 인정 등이면 그대로 저장)' : '');
    state.classList.toggle('warn', t.warn);
  }
  updateSummary();
}

function shareCard(doc) {
  const card = document.createElement('section');
  card.className = 'bs-card'; card.dataset.doc = doc;
  const rows = shares[doc] || [];
  const total = rows.reduce((sum, r) => sum + (r.share_pct || 0), 0);
  const warn = Math.abs(total - 100) > 0.01;
  card.innerHTML = `
    <div class="bs-head"><h3>${esc(doc)}</h3><span class="state${warn ? ' warn' : ''}">합 ${money.format(total)}%${warn ? ' — 100이 아닙니다' : ''}</span>
      <button type="button" class="add">사람 추가</button></div>
    <table class="bs-rows">
      <thead><tr><th style="width:16%">이름</th><th style="width:12%">지분 %</th><th style="width:14%">법인카드 %</th><th>근거</th><th style="width:8%"></th><th style="width:44px"></th></tr></thead>
      <tbody></tbody>
    </table>`;
  const body = card.querySelector('tbody');
  rows.forEach(item => body.appendChild(shareRow(doc, item)));
  if (!rows.length) body.appendChild(shareRow(doc, {}));
  card.querySelector('.add').addEventListener('click', () => { body.appendChild(shareRow(doc, {})); markShares(doc); });
  return card;
}

function renderShares() {
  const filter = $('shareFilter').value.trim();
  const docs = Object.keys(shares).filter(d => !filter || d.includes(filter)).sort().reverse();
  const list = $('shareList');
  list.innerHTML = '';
  // 다 그리면 수백 장이라 앞의 60건만 — 번호로 좁혀서 본다.
  docs.slice(0, 60).forEach(doc => list.appendChild(shareCard(doc)));
  $('shareCount').textContent = docs.length > 60 ? `${docs.length}건 중 60건 표시 — 번호로 좁히세요` : `${docs.length}건`;
}

function readShares(doc) {
  const card = document.querySelector(`.bs-card[data-doc="${CSS.escape(doc)}"]`);
  if (!card) return shares[doc] || [];
  return Array.from(card.querySelectorAll('tbody tr')).map(row => ({
    person: row.querySelector('.s-person').value.trim(),
    share_pct: Number(row.querySelector('.s-pct').value),
    bc_pct: row.querySelector('.s-bc').value === '' ? null : Number(row.querySelector('.s-bc').value),
    note: row.querySelector('.s-note').value.trim(),
  })).filter(r => r.person);
}

async function addShareDoc() {
  const doc = $('shareFilter').value.trim();
  if (!/^[0-9A-Za-z-]{5,50}$/.test(doc)) { showToast('감정서번호를 정확히 적으세요 (예: 01-2603-1-0155).', true); return; }
  // 감정서의 지분 근거(APW 담당자·거래처, APW_Booking 지분, 매출입력 배분)를 보여 주고, 지분표가 비어 있으면 Booking 값으로 채워 준다
  let info = null;
  try {
    const res = await fetch(`/api/bonus/settings/shares/lookup?doc_id=${encodeURIComponent(doc)}`);
    const p = await res.json();
    if (p.success) info = p.data;
  } catch (e) { /* 조회 실패해도 수기 추가는 된다 */ }
  const booking = (info && info.booking) || {};
  if (!shares[doc]) {
    shares[doc] = Object.keys(booking).length
      ? Object.entries(booking).map(([person, pct]) => ({ person: person.replace(/^공\((.*)\)$/, '$1'), share_pct: Number(pct), bc_pct: null, note: 'APW_Booking' }))
      : [];
  }
  const box = $('shareLookup');
  if (info && info.meta) {
    const ga = Object.entries(info.gaprice || {}).map(([n, v]) => `${n} ${money.format(v)}`).join(', ');
    const bk = Object.entries(booking).map(([n, v]) => `${n} ${v}%`).join(', ');
    box.textContent = `${doc} · 담당 ${info.meta.manager || '-'} · ${info.meta.customer_name || ''} · ${info.meta.work_type || ''} · 접수 ${info.meta.receipt_date || '-'} · 순수수료 ${money.format(info.meta.fee || 0)} | APW_Booking 지분: ${bk || '없음'} | 매출입력 배분: ${ga || '없음'}`;
    box.classList.remove('hidden');
  } else if (info) {
    box.textContent = `${doc}: APW 마스터에 없는 번호입니다 — 수기로 적습니다.`;
    box.classList.remove('hidden');
  }
  renderShares();
  markShares(doc);
}

// ── 저장 ──────────────────────────────────────────────────────────────

async function saveAll() {
  if (!pendingCount()) { showToast('바뀐 것이 없습니다.'); return; }
  const button = $('saveAll');
  button.disabled = true; button.textContent = '저장 중...';
  const failed = [];
  try {
    if (dirty.persons) {
      try {
        people = (await putJson('/api/bonus/settings/persons', { people: readPersons() })).items;
        dirty.persons = false;
      } catch (e) { failed.push('사람: ' + e.message); }
    }
    for (const person of Array.from(dirty.rates)) {
      try {
        rates[person] = (await putJson(`/api/bonus/settings/rates/${encodeURIComponent(person)}`, { rows: readRates(person) })).items;
        dirty.rates.delete(person);
      } catch (e) { failed.push(`${person} 요율: ${e.message}`); }
    }
    for (const doc of Array.from(dirty.shares)) {
      try {
        const data = await putJson(`/api/bonus/settings/shares/${encodeURIComponent(doc)}`, { rows: readShares(doc) });
        shares[doc] = data.items.map(i => ({ ...i, source: 'MANUAL' }));
        if (!shares[doc].length) delete shares[doc];
        dirty.shares.delete(doc);
      } catch (e) { failed.push(`${doc} 지분: ${e.message}`); }
    }
    renderPersons(); renderRates(); renderShares(); updateSummary();
    showToast(failed.length ? `저장 실패 ${failed.length}건 — ${failed[0]}` : '저장했습니다.', failed.length > 0);
  } finally {
    button.disabled = false; button.textContent = '변경 저장';
  }
}

async function load() {
  try {
    const [p, r, s] = await Promise.all([
      fetch('/api/bonus/settings/persons').then(x => x.json()),
      fetch('/api/bonus/settings/rates').then(x => x.json()),
      fetch('/api/bonus/settings/shares').then(x => x.json()),
    ]);
    for (const payload of [p, r, s]) if (!payload.success) throw new Error(payload.message);
    people = p.data.items || [];
    rates = {};
    (r.data.items || []).forEach(item => (rates[item.person] = rates[item.person] || []).push(item));
    shares = {};
    (s.data.items || []).forEach(item => (shares[item.doc_id] = shares[item.doc_id] || []).push(item));
    renderPersons(); renderRates(); renderShares(); updateSummary();
  } catch (e) {
    $('summary').textContent = '불러오지 못했습니다: ' + e.message;
  }
}

// 저장하지 않고 나가면 적은 것이 사라진다 — 한 번 잡아 준다.
window.addEventListener('beforeunload', event => {
  if (!pendingCount()) return;
  event.preventDefault();
  event.returnValue = '';
});

$('saveAll').addEventListener('click', saveAll);
$('shareFilter').addEventListener('input', renderShares);
$('shareAdd').addEventListener('click', addShareDoc);
document.querySelectorAll('.bs-tabs button').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('summary').textContent = '상여 설정은 본사만 고칠 수 있습니다.';
    $('saveAll').classList.add('hidden');
    return;
  }
  load();
});
