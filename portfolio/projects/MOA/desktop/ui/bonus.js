// 상여 화면 v2 (2026-08-27) — 지급월 단위 리포트(/api/bonus/v2). 탭: 주주표 / 평·동표 / 총괄표 / 보류·경고.
// 수기 입력은 두 가지뿐: 사람 단위 공제(공제 대장에서 골라 적용)와 감정서 단위 오버라이드(⋯). 마감하면 스냅샷으로 고정된다.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const num = v => (v == null || v === '') ? '' : money.format(Math.round(Number(v)));
const pct = v => (v == null || v === '') ? '' : `${Number(v) % 1 === 0 ? Number(v) : Number(v).toFixed(1)}%`;
const RATES = [40, 45, 35, 30, 25, 20, 15, 10, 3];
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
const DEDUCTION_KINDS = KIND_GROUPS.flatMap(g => g[1]);
const KIND_STAGE = Object.fromEntries(KIND_GROUPS.flatMap(([, kinds], stage) => kinds.map(([k]) => [k, stage])));
const stageBadge = kind => KIND_STAGE[kind] === 2 ? '<span class="badge warn">세후</span>' : '<span class="badge muted">세전</span>';
const KIND_LABEL = { SHAREHOLDER: '주주', COMMON: '공통건', ASSOCIATE: '소속' };
const SOURCE_LABEL = { MANUAL: '수기', EXCEL: '엑셀', VOUCHER: '전표' };
const FLAG_LABEL = {
  PAID_BY_BUNDLE: '묶음입금', ADJUST: '기지급 차액', INCLUDED_BY_OVERRIDE: '수동 포함', NO_CANDIDATE: '수기 행', FALLBACK_LATEST: '요율 폴백',
  NO_SCHEDULE: '요율표 없음', FORMER_ASSOCIATE: '소속 시절', RETIRED: '퇴사', EXCEL: '엑셀 이력', FEE_OVERRIDE: '수수료 수기',
  RATE_OVERRIDE: '요율 수기', SHARE_OVERRIDE: '지분 수기', EXCLUDED: '제외', SIMPLE_APPRAISAL: '국민약식 합산',
};
const HELD_LABEL = {
  HELD_UNPAID: '미수 잔액', HELD_NO_FEE: '수수료 0 이하', HELD_PAID_LATER: '입금이 다음 달', HELD_INVOICE_ONLY: '청구 전표만',
  ALREADY_PAID: '이미 지급', RETIRED: '퇴사자',
};

let report = null;
let searchResult = null;
let currentTab = 'shareholders';
let closes = [];
const ctxOf = () => window.A10_CTX || {};
const requester = () => Number(ctxOf().usr_seq || 0);
const canWrite = () => !!ctxOf().is_operations && !!report && report.status !== 'CLOSED';

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

const periodValue = () => $('period').value.replace('-', '');
const periodLabel = p => `${p.slice(0, 4)}-${p.slice(4)}`;
const perfLabel = p => { const y = Number(p.slice(0, 4)), m = Number(p.slice(4)); return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`; };
const flagChips = flags => (flags || []).map(f => `<span class="badge ${/ADJUST|FALLBACK|NO_SCHEDULE|NO_CANDIDATE/.test(f) ? 'warn' : /EXCLUDED|RETIRED/.test(f) ? 'bad' : 'muted'}">${esc(FLAG_LABEL[f] || f)}</span>`).join('');
const dateText = v => v ? String(v).slice(0, 10) : '';
const totalPayment = () => report.summary.reduce((s, r) => s + Number(r.payment || 0), 0);
const kindLabel = kind => (DEDUCTION_KINDS.find(k => k[0] === kind) || [kind, kind])[1];

// ── 조회 ──────────────────────────────────────────────────────────────

async function loadReport() {
  $('resultSummary').textContent = '조회 중...';
  report = await api('GET', `/api/bonus/v2?period=${periodValue()}`);
  render();
}

function render() {
  if (!report) return;
  const closed = report.status === 'CLOSED';
  const close = closes.find(c => c.period === report.period);
  const pill = $('statusPill');
  pill.className = `status-pill ${closed ? 'closed' : 'open'}`;
  pill.textContent = closed ? `마감됨 · ${close && close.source === 'EXCEL' ? '엑셀 지급 이력' : 'MOA'}` : '열림 (계산 중인 달)';
  $('periodNote').textContent = `${periodLabel(report.period)} 지급분 · 입금월 ${perfLabel(report.period)}`;
  $('closeButton').classList.toggle('hidden', !(ctxOf().is_operations && !closed));
  $('reopenButton').classList.toggle('hidden', !(ctxOf().is_operations && closed && close && close.source === 'MOA'));
  $('screenNote').classList.toggle('closed', closed);
  if (closed) $('screenNote').innerHTML = '이 달은 <b>마감돼 스냅샷으로 고정</b>됐습니다. 고치려면 재개(MOA 마감만) 후 다시 계산합니다.';
  else $('screenNote').innerHTML = render.openNote;
  $('countShareholders').textContent = report.shareholders.length ? `(${report.shareholders.length})` : '';
  const assocCount = report.common.length + report.associates.length;
  $('countAssociates').textContent = assocCount ? `(${assocCount})` : '';
  $('countHeld').textContent = (report.held.length + report.warnings.length) ? `(${report.held.length}/${report.warnings.length})` : '';
  const pendingCount = Object.values(report.pending_deductions || {}).reduce((s, items) => s + items.length, 0);
  $('resultSummary').textContent = `주주 ${report.shareholders.length}명 · 공통건 ${report.common.length}명 · 소속 ${report.associates.length}명 · 지급액 합계 ${num(totalPayment())}원 · 보류 ${report.held.length}건 · 경고 ${report.warnings.length}건${pendingCount ? ` · 대기 공제 ${pendingCount}건` : ''}`;
  $('tabTitle').textContent = { shareholders: '주주표', associates: '평·동표', advances: '선지급', summary: '총괄표', held: '보류·경고', search: '검색' }[currentTab];
  ({ shareholders: renderShareholders, associates: renderAssociates, advances: renderAdvances, summary: renderSummary, held: renderHeld, search: renderSearch })[currentTab]();
  fitTableHeight();
}
render.openNote = $('screenNote').innerHTML;

function fitTableHeight() {
  const wrap = document.querySelector('.list-panel > .table-wrap');
  if (!wrap) return;
  const top = wrap.getBoundingClientRect().top + window.scrollY;
  wrap.style.height = `${Math.max(360, window.innerHeight - top - 30)}px`;
}
window.addEventListener('resize', fitTableHeight);

// 탭별 기본 컬럼 폭 — 드래그로 바꾼 폭은 A10_COLUMN_RESIZE 가 localStorage 에 저장한다 (표마다 열 수가 달라 키를 나눈다)
const LAYOUTS = {
  shareholders: [85, 140, 90, 190, 90, 60, 105, 110, 60, 110, 95, 100, 95, 80, 100, 95, 110, 105, 85, 85, 85, 110, 95, 100, 90, 95, 110, 100, 90, 140, 36],
  associates: [85, 140, 90, 190, 90, 60, 105, 95, 105, 95, 105, 60, 100, 90, 85, 60, 105, 95, 90, 95, 105, 90, 140, 36],
  summary: [90, 110, 120, 110, 110, 110, 120, 110, 260],
  held: [130, 90, 120, 120, 120, 110, 80],
  advances: [90, 150, 120, 100, 320, 70, 130],
  search: [80, 90, 95, 140, 110, 190, 90, 60, 70, 110, 110, 105, 220],
};
let currentLayout = 'shareholders';

function setHead(cells, kind) {
  currentLayout = kind || currentTab;
  $('bonusCols').innerHTML = (LAYOUTS[currentLayout] || []).map(w => `<col style="width:${w}px">`).join('');
  $('bonusHead').innerHTML = `<tr>${cells}</tr>`;
}

function setStickyOffsets() {
  const widths = Array.from($('bonusCols').children).map(col => parseInt(col.style.width, 10) || 0);
  let left = 0;
  const offsets = widths.map(w => { const l = left; left += w; return l; });
  document.querySelectorAll('#bonusTable [data-stick]').forEach(cell => { cell.style.left = `${offsets[Number(cell.dataset.stick)] || 0}px`; });
}
// 폭 드래그·더블클릭(기본 복원) 뒤 고정 컬럼 left 재계산
document.addEventListener('mouseup', () => setTimeout(setStickyOffsets, 0));
document.addEventListener('dblclick', () => setTimeout(setStickyOffsets, 0));

const deductionsOf = name => (report.deductions && report.deductions[name]) || [];
const pendingOf = name => (report.pending_deductions && report.pending_deductions[name]) || [];
const deductionChips = name => deductionsOf(name).map(d => `<span class="deduct-chip">${esc(kindLabel(d.kind).replace(/\((\+|−)\)$/, ''))} ${num(d.amount)}</span>`).join('');
const overrideOf = (doc, person) => (report.overrides || []).find(o => o.doc_id === doc && o.person === person);

function personHeadRow(entry, colCount) {
  const pending = pendingOf(entry.name).length;
  const buttons = canWrite()
    ? `<button class="small-button deduct-button" data-person="${esc(entry.name)}" type="button">공제${pending ? ` <span class="badge warn">대기 ${pending}</span>` : ''}</button>`
      + `<button class="small-button add-doc-button" data-person="${esc(entry.name)}" type="button" title="자동으로 안 잡힌 감정서를 이 사람 행으로 넣기">추가</button>`
    : (pending ? `<span class="badge warn">대기 공제 ${pending}건</span>` : '');
  const warnings = (entry.warnings || []).map(w => `<span class="badge warn">${esc(w)}</span>`).join(' ');
  return `<tr class="person-head"><td data-stick="0">${esc(entry.name)}${entry.retired ? '<span class="badge bad">퇴사</span>' : ''}</td>
    <td data-stick="1" colspan="3">${buttons}${deductionChips(entry.name)}</td><td colspan="${colCount - 4}">${warnings}</td></tr>`;
}

function rowMenuCell(row) {
  if (!canWrite()) return '<td></td>';
  return `<td><button class="row-menu override-button" data-doc="${esc(row.doc_id)}" data-person="${esc(row.person)}" type="button" title="포함·제외·수수료·요율·지분">⋯</button></td>`;
}

function finishTable(html) {
  $('bonusRows').innerHTML = html.join('');
  bindRowButtons();
  if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('bonusTable'), `bonus-v2-${currentLayout}`);
  setStickyOffsets();
}

// ── 주주표 ─────────────────────────────────────────────────────────────

const SH_COLS = 31;
function renderShareholders() {
  setHead(`<th data-stick="0">성명</th><th data-stick="1">감정서번호</th><th data-stick="2">업무구분</th><th data-stick="3">거래처</th>
    <th>접수일</th><th>요율</th><th class="number">순수수료<br>(F)</th><th class="number">토지조사비<br>−부족출장비(G)</th><th class="number">지분</th><th class="number">산정수수료<br>(H)</th>
    <th class="number">가변비<br>(J)</th><th class="number">손해배상<br>충당금(K)</th><th class="number">미납비<br>이월(M)</th><th class="number">기타<br>(N)</th><th class="number">당월감정서<br>경비(O)</th><th class="number">협회비,<br>공제료(P)</th>
    <th class="number">산출액<br>(Q)</th><th class="number">상여<br>(R)</th><th class="number">처리비<br>(S)</th><th class="number">화환<br>(W)</th><th class="number">물건<br>조사비(X)</th><th class="number">세전상여<br>(Y)</th>
    <th class="number">선지급</th><th class="number">소득세<br>(Z)</th><th class="number">주민세<br>(AA)</th><th class="number">기타공제<br>(AB)</th><th class="number">지급액<br>(AC)</th><th class="number">미납비용<br>(AE)</th><th class="number">B.C</th><th>표시</th><th></th>`);
  const groups = report.shareholders;
  $('emptyList').classList.toggle('hidden', groups.length !== 0);
  const html = [];
  const grand = { assessed: 0, indemnity: 0, association_fee: 0, payout_base: 0, bonus: 0, pretax: 0, income_tax: 0, resident_tax: 0, other_deduct: 0, payment: 0, unpaid_carry_out: 0, card_limit: 0 };
  for (const entry of groups) {
    html.push(personHeadRow(entry, SH_COLS));
    for (const row of entry.rows) {
      const excluded = (row.flags || []).includes('EXCLUDED');
      html.push(`<tr class="${excluded ? 'excluded' : ''}"><td data-stick="0"></td><td data-stick="1">${esc(row.doc_id)}</td><td data-stick="2">${esc(row.work_type)}</td><td data-stick="3">${esc(row.customer_name)}</td>
        <td>${dateText(row.receipt_date)}</td><td class="number">${pct(row.rate)}</td><td class="number">${num(row.fee)}</td><td class="number">${num((row.land_fee || 0) - (row.travel_fee || 0))}</td>
        <td class="number">${pct(row.share_pct)}</td><td class="number">${num(row.assessed)}</td><td></td><td class="number">${num(row.indemnity)}</td><td></td><td></td><td class="number">${row.expense_fee ? num(row.expense_fee) : ''}</td><td class="number">${num(row.association_fee)}</td>
        <td colspan="4"></td><td class="number">${row.survey_fee ? num(row.survey_fee) : ''}</td><td colspan="8"></td><td>${flagChips(row.flags)}</td>${rowMenuCell(row)}</tr>`);
    }
    const t = entry.totals;
    for (const b of entry.blocks || []) {
      const main = b.main;
      html.push(`<tr class="block-total"><td data-stick="0"></td><td data-stick="1" colspan="3">합계 ${b.rate != null ? `${b.rate}%` : '요율 없음'}${b.block_from ? ` (${dateText(b.block_from)}~)` : ''} · ${b.count}건</td>
        <td></td><td class="number">${pct(b.rate)}</td><td></td><td></td><td></td><td class="number">${num(b.assessed)}</td>
        <td class="number">${main ? num(t.variable_cost) : ''}</td><td class="number">${num(b.indemnity)}</td><td class="number">${main ? num(t.carry_in) : ''}</td><td class="number">${main ? num(t.misc) : ''}</td><td class="number">${main ? num(t.doc_expense) : ''}</td><td class="number">${num(b.association_fee)}</td>
        <td class="number">${num(b.payout_base)}</td><td class="number">${num(b.bonus)}</td><td class="number">${num(b.handling)}</td><td class="number">${num(b.wreath)}</td><td class="number">${num(b.survey_fee)}</td><td class="number">${num(b.pretax)}</td>
        <td class="number">${num(b.advance_paid)}</td><td class="number">${num(b.income_tax)}</td><td class="number">${num(b.resident_tax)}</td><td class="number">${num(b.other_deduct)}</td><td class="number">${num(b.payment)}</td><td class="number">${num(b.unpaid_carry_out)}</td><td class="number">${num(b.card_limit)}</td><td></td><td></td></tr>`);
    }
    if ((entry.blocks || []).length !== 1) {
      html.push(`<tr class="person-total"><td data-stick="0">${esc(entry.name)}</td><td data-stick="1" colspan="3">사람 합계</td><td colspan="5"></td><td class="number">${num(t.assessed)}</td>
        <td class="number">${num(t.variable_cost)}</td><td class="number">${num(t.indemnity)}</td><td class="number">${num(t.carry_in)}</td><td class="number">${num(t.misc)}</td><td class="number">${num(t.doc_expense)}</td><td class="number">${num(t.association_fee)}</td>
        <td class="number">${num(t.payout_base)}</td><td class="number">${num(t.bonus)}</td><td class="number">${num(t.handling)}</td><td class="number">${num(t.wreath)}</td><td class="number">${num(t.survey_fee)}</td><td class="number">${num(t.pretax)}</td>
        <td class="number">${num(t.advance_paid)}</td><td class="number">${num(t.income_tax)}</td><td class="number">${num(t.resident_tax)}</td><td class="number">${num(t.other_deduct)}</td><td class="number">${num(t.payment)}</td><td class="number">${num(t.unpaid_carry_out)}</td><td class="number">${num(t.card_limit)}</td><td></td><td></td></tr>`);
    }
    for (const k of Object.keys(grand)) grand[k] += Number(t[k] || 0);
  }
  if (groups.length) {
    html.push(`<tr class="grand-total"><td data-stick="0">총계</td><td data-stick="1" colspan="3">주주 ${groups.length}명</td><td colspan="5"></td><td class="number">${num(grand.assessed)}</td><td></td><td class="number">${num(grand.indemnity)}</td><td colspan="3"></td><td class="number">${num(grand.association_fee)}</td>
      <td class="number">${num(grand.payout_base)}</td><td class="number">${num(grand.bonus)}</td><td colspan="3"></td><td class="number">${num(grand.pretax)}</td><td></td><td class="number">${num(grand.income_tax)}</td><td class="number">${num(grand.resident_tax)}</td><td class="number">${num(grand.other_deduct)}</td><td class="number">${num(grand.payment)}</td><td class="number">${num(grand.unpaid_carry_out)}</td><td class="number">${num(grand.card_limit)}</td><td></td><td></td></tr>`);
  }
  finishTable(html);
}

// ── 평·동표 ────────────────────────────────────────────────────────────

const AS_COLS = 24;
function renderAssociates() {
  setHead(`<th data-stick="0">성명</th><th data-stick="1">감정서번호</th><th data-stick="2">업무구분</th><th data-stick="3">거래처</th>
    <th>접수일</th><th>구분</th><th class="number">순수수료<br>(F)</th><th class="number">토지조사비<br>(G)</th><th class="number">산정수수료<br>(I)</th><th class="number">손해배상<br>충당금(J)</th><th class="number">산정액<br>(L)</th>
    <th class="number">요율</th><th class="number">상여</th><th class="number">처리수당<br>(AB)</th><th class="number">화환<br>(AC)</th><th class="number">지급률</th><th class="number">세전상여<br>(AD)</th>
    <th class="number">소득세<br>(AE)</th><th class="number">지방세<br>(AF)</th><th class="number">기타공제<br>(AG)</th><th class="number">지급액<br>(AH)</th><th class="number">B.C</th><th>표시</th><th></th>`);
  const groups = [...report.common, ...report.associates];
  $('emptyList').classList.toggle('hidden', groups.length !== 0);
  const html = [];
  const grand = { gross: 0, indemnity: 0, assessed: 0, bonus: 0, pretax: 0, income_tax: 0, resident_tax: 0, other_deduct: 0, payment: 0, card_limit: 0 };
  for (const entry of groups) {
    html.push(personHeadRow(entry, AS_COLS));
    for (const row of entry.rows) {
      const excluded = (row.flags || []).includes('EXCLUDED');
      const rateText = row.kind === 'COMMON' ? pct(row.applied_rate) : '누진';
      html.push(`<tr class="${excluded ? 'excluded' : ''}"><td data-stick="0"></td><td data-stick="1">${esc(row.doc_id)}</td><td data-stick="2">${esc(row.work_type)}</td><td data-stick="3">${esc(row.customer_name)}</td>
        <td>${dateText(row.receipt_date)}</td><td>${esc(KIND_LABEL[row.kind] || row.kind)}</td><td class="number">${num(row.fee)}</td><td class="number">${num(row.land_fee)}</td><td class="number">${num(row.gross)}</td><td class="number">${num(row.indemnity)}</td><td class="number">${num(row.assessed)}</td>
        <td class="number">${rateText}</td><td class="number">${num(row.bonus)}</td><td colspan="9"></td><td>${flagChips(row.flags)}</td>${rowMenuCell(row)}</tr>`);
    }
    const t = entry.totals;
    html.push(`<tr class="person-total"><td data-stick="0">${esc(entry.name)}</td><td data-stick="1" colspan="3">${esc(KIND_LABEL[entry.kind] || entry.kind)} 합계 · ${t.count != null ? t.count : entry.rows.length}건</td><td colspan="4"></td>
      <td class="number">${num(t.gross)}</td><td class="number">${num(t.indemnity)}</td><td class="number">${num(t.assessed)}</td><td></td><td class="number">${num(t.bonus)}</td><td class="number">${num(t.handling)}</td><td class="number">${num(t.wreath)}</td><td class="number">${t.pay_ratio != null ? Number(t.pay_ratio).toFixed(2) : ''}</td><td class="number">${num(t.pretax)}</td>
      <td class="number">${num(t.income_tax)}</td><td class="number">${num(t.resident_tax)}</td><td class="number">${num(t.other_deduct)}</td><td class="number">${num(t.payment)}</td><td class="number">${num(t.card_limit)}</td><td></td><td></td></tr>`);
    for (const k of Object.keys(grand)) grand[k] += Number(t[k] || 0);
  }
  if (groups.length) {
    html.push(`<tr class="grand-total"><td data-stick="0">총계</td><td data-stick="1" colspan="3">${groups.length}명</td><td colspan="4"></td><td class="number">${num(grand.gross)}</td><td class="number">${num(grand.indemnity)}</td><td class="number">${num(grand.assessed)}</td><td></td><td class="number">${num(grand.bonus)}</td><td colspan="3"></td><td class="number">${num(grand.pretax)}</td>
      <td class="number">${num(grand.income_tax)}</td><td class="number">${num(grand.resident_tax)}</td><td class="number">${num(grand.other_deduct)}</td><td class="number">${num(grand.payment)}</td><td class="number">${num(grand.card_limit)}</td><td></td><td></td></tr>`);
  }
  finishTable(html);
}

// ── 선지급 (공제 대장 ADVANCE_PAID — 대기·적용 전부) ────────────────────────

function renderAdvances() {
  setHead('<th data-stick="0">성명</th><th>감정서</th><th class="number">선지급 금액</th><th>발생일</th><th>메모</th><th>출처</th><th>상태</th>');
  $('bonusRows').innerHTML = '<tr><td colspan="7">불러오는 중...</td></tr>';
  loadAdvances().catch(showError);
}

async function loadAdvances() {
  const data = await api('GET', '/api/bonus/v2/deduction-items?kind=ADVANCE_PAID');
  const rows = (data.items || []).filter(i => i.status !== 'VOID').sort((a, b) => a.person.localeCompare(b.person, 'ko') || (b.item_id - a.item_id));
  $('countAdvances').textContent = rows.length ? `(${rows.length})` : '';
  $('emptyList').classList.toggle('hidden', rows.length !== 0);
  const html = rows.map(i => `<tr><td data-stick="0">${esc(i.person)}</td><td>${esc(i.doc_id || '')}</td><td class="number">${num(i.amount)}</td><td>${dateText(i.occurred_on)}</td><td>${esc(i.memo || '')}</td>
    <td><span class="badge muted">${esc(SOURCE_LABEL[i.source] || i.source)}</span></td><td>${i.status === 'APPLIED' ? `<span class="badge ok">${esc(periodLabel(i.applied_period))} 적용</span>` : '<span class="badge warn">대기</span>'}</td></tr>`);
  const total = rows.reduce((s, i) => s + Number(i.amount || 0), 0);
  const pending = rows.filter(i => i.status === 'PENDING').reduce((s, i) => s + Number(i.amount || 0), 0);
  html.push(`<tr class="grand-total"><td data-stick="0">합계</td><td>${rows.length}건</td><td class="number">${num(total)}</td><td colspan="4">대기 ${num(pending)}원 · 등록·수정·무효는 공제 대장에서</td></tr>`);
  finishTable(html);
}

// ── 총괄표 (+ 전표) ─────────────────────────────────────────────────────

function renderSummary() {
  setHead('<th data-stick="0">성명</th><th>구분</th><th class="number">세전상여</th><th class="number">소득세</th><th class="number">주민세</th><th class="number">기타공제</th><th class="number">지급액</th><th class="number">B.C</th><th>비고</th>');
  const rows = report.summary;
  $('emptyList').classList.toggle('hidden', rows.length !== 0);
  const total = { pretax: 0, income_tax: 0, resident_tax: 0, other_deduct: 0, payment: 0, card_limit: 0 };
  const html = rows.map(r => {
    for (const k of Object.keys(total)) total[k] += Number(r[k] || 0);
    return `<tr><td data-stick="0">${esc(r.name)}</td><td>${(r.kinds || []).map(k => KIND_LABEL[k] || k).join('·')}</td><td class="number">${num(r.pretax)}</td><td class="number">${num(r.income_tax)}</td><td class="number">${num(r.resident_tax)}</td><td class="number">${num(r.other_deduct)}</td><td class="number">${num(r.payment)}</td><td class="number">${num(r.card_limit)}</td><td>${r.retired ? '<span class="badge bad">퇴사</span>' : ''}</td></tr>`;
  });
  html.push(`<tr class="grand-total"><td data-stick="0">합계</td><td>${rows.length}명</td><td class="number">${num(total.pretax)}</td><td class="number">${num(total.income_tax)}</td><td class="number">${num(total.resident_tax)}</td><td class="number">${num(total.other_deduct)}</td><td class="number">${num(total.payment)}</td><td class="number">${num(total.card_limit)}</td><td></td></tr>`);
  const withholding = total.income_tax + total.resident_tax;
  html.push('<tr class="journal-head"><td data-stick="0">전표</td><td>계정</td><td class="number">차변</td><td class="number">대변</td><td colspan="5">적요</td></tr>');
  [['임원상여', total.pretax, null, '성과상여 산정금액'], ['예수금', null, withholding, '소득세·주민세'], ['미수금', null, total.other_deduct, '기타공제'], ['보통예금', null, total.payment, '지급액']]
    .forEach(([acct, dr, cr, remark]) => html.push(`<tr><td data-stick="0"></td><td>${acct}</td><td class="number">${num(dr)}</td><td class="number">${num(cr)}</td><td colspan="5">${remark}</td></tr>`));
  finishTable(html);
}

// ── 보류·경고 ───────────────────────────────────────────────────────────

function renderHeld() {
  setHead('<th data-stick="0">감정서번호</th><th>사람</th><th>사유</th><th class="number">수수료 전표합</th><th class="number">미수 잔액</th><th>마지막 입금</th><th></th>');
  const html = report.held.map(h => {
    const person = h.person || '';
    const button = canWrite() ? `<button class="small-button include-button" data-doc="${esc(h.doc_id)}" data-person="${esc(person || '*')}" type="button">포함</button>` : '';
    return `<tr><td data-stick="0">${esc(h.doc_id)}</td><td>${esc(person)}</td><td><span class="badge ${h.reason === 'RETIRED' ? 'bad' : 'warn'}">${esc(HELD_LABEL[h.reason] || h.reason)}</span></td>
      <td class="number">${num(h.fee_total != null ? h.fee_total : h.fee)}</td><td class="number">${num(h.outstanding)}</td><td>${dateText(h.last_received_date)}</td><td>${button}</td></tr>`;
  });
  if (report.warnings.length) {
    html.push(`<tr class="journal-head"><td data-stick="0">경고</td><td colspan="6">${report.warnings.length}건</td></tr>`);
    html.push(`<tr><td data-stick="0"></td><td colspan="6"><ul class="warn-list">${report.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></td></tr>`);
  }
  const notes = report.expense_notes || [];
  if (notes.length) {
    html.push(`<tr class="journal-head"><td data-stick="0">참고</td><td colspan="6">감정서번호가 없어 후보로 올리지 않은 경비 전표 ${notes.length}건 — 사람 몫이면 공제 대장에 직접 올리세요</td></tr>`);
    notes.slice(0, 60).forEach(n => html.push(`<tr><td data-stick="0">${dateText(n.voucher_date)}</td><td>${esc(n.account_name || '')}</td><td colspan="2">${esc(n.remark || '')}</td><td class="number">${num(n.amount)}</td><td colspan="2"></td></tr>`));
  }
  $('emptyList').classList.toggle('hidden', html.length !== 0);
  finishTable(html);
}

// ── 검색 (여러 달 × 감정서번호·유치자) ───────────────────────────────────

const filtersActive = () => !!($('periodTo').value || $('docFilter').value.trim() || $('personFilter').value.trim());

async function runSearch() {
  const a = periodValue();
  const b = ($('periodTo').value || $('period').value).replace('-', '');
  setTab('search');
  $('resultSummary').textContent = '검색 중...';
  const query = new URLSearchParams({ period_from: a <= b ? a : b, period_to: a <= b ? b : a });
  if ($('docFilter').value.trim()) query.set('doc_id', $('docFilter').value.trim());
  if ($('personFilter').value.trim()) query.set('person', $('personFilter').value.trim());
  searchResult = await api('GET', `/api/bonus/v2/search?${query}`);
  render();
}

function renderSearch() {
  setHead(`<th>지급월</th><th>성명</th><th>구분</th><th>감정서번호</th><th>업무구분</th><th>거래처</th>
    <th>접수일</th><th class="number">요율</th><th class="number">지분</th><th class="number">순수수료(F)</th><th class="number">산정수수료</th><th class="number">상여</th><th>표시</th>`);
  const res = searchResult;
  if (!res) {
    $('emptyList').classList.add('hidden');
    $('bonusRows').innerHTML = '<tr><td colspan="13">위에서 지급월 구간(~)과 감정서번호·유치자를 넣고 조회를 누르세요. 마감 달은 스냅샷, 열린 달은 지금 계산한 값입니다.</td></tr>';
    return;
  }
  const rows = res.rows || [];
  $('countSearch').textContent = rows.length ? `(${res.total})` : '';
  $('emptyList').classList.toggle('hidden', rows.length !== 0);
  $('resultSummary').textContent = `검색: ${periodLabel(res.period_from)}~${periodLabel(res.period_to)} 지급분 · ${res.total}행${res.truncated ? ` (표시는 ${rows.length}행까지)` : ''}`;
  const html = rows.map(r => {
    const rateText = r.kind === 'ASSOCIATE' ? '누진' : pct(r.rate);
    const kindText = r.held_reason
      ? `<span class="badge ${r.held_reason === 'RETIRED' ? 'bad' : 'warn'}">보류 · ${esc(HELD_LABEL[r.held_reason] || r.held_reason)}</span>`
      : esc(KIND_LABEL[r.kind] || r.kind || '');
    return `<tr><td>${esc(periodLabel(r.period))}</td><td>${esc(r.person)}</td><td>${kindText}</td>
      <td>${esc(r.doc_id)}</td><td>${esc(r.work_type || '')}</td><td>${esc(r.customer_name || '')}</td><td>${dateText(r.receipt_date)}</td>
      <td class="number">${r.held_reason ? '' : rateText}</td><td class="number">${pct(r.share_pct)}</td><td class="number">${num(r.fee)}</td><td class="number">${num(r.assessed)}</td><td class="number">${num(r.bonus)}</td><td>${flagChips(r.flags)}</td></tr>`;
  });
  if (rows.length) {
    const total = { fee: 0, assessed: 0, bonus: 0 };
    for (const r of rows) { if (!r.held_reason) { total.fee += Number(r.fee || 0); total.assessed += Number(r.assessed || 0); total.bonus += Number(r.bonus || 0); } }
    html.push(`<tr class="grand-total"><td>합계</td><td colspan="8">${(res.months || []).length}달 · ${res.total}행 (보류 제외 합)</td>
      <td class="number">${num(total.fee)}</td><td class="number">${num(total.assessed)}</td><td class="number">${num(total.bonus)}</td><td></td></tr>`);
  }
  finishTable(html);
}

// ── 공제 (대장에서 골라 적용) ───────────────────────────────────────────

function itemRow(item, checked) {
  // 대장에 있는 항목: 값은 못 고치고 이번 달 적용 여부만 고른다
  const tr = document.createElement('tr');
  tr.dataset.itemId = item.item_id;
  tr.dataset.kind = item.kind;
  tr.dataset.amount = item.amount;
  tr.innerHTML = `<td class="center"><input class="d-apply" type="checkbox"${checked ? ' checked' : ''}></td>
    <td>${esc(kindLabel(item.kind))}${stageBadge(item.kind)}</td><td class="number">${num(item.amount)}</td><td>${esc(item.doc_id || '')}</td><td>${dateText(item.occurred_on)}</td>
    <td>${esc(item.memo || '')}</td><td><span class="badge muted">${esc(SOURCE_LABEL[item.source] || item.source)}</span>${item.applied_period && item.applied_period !== report.period ? `<span class="badge warn">${esc(periodLabel(item.applied_period))} 적용</span>` : ''}</td><td></td>`;
  tr.querySelector('.d-apply').addEventListener('change', updatePreview);
  return tr;
}

function newItemRow() {
  const tr = document.createElement('tr');
  tr.classList.add('new-item');
  tr.innerHTML = `<td class="center"><input class="d-apply" type="checkbox" checked title="끄면 대기로만 둔다"></td>
    <td><select class="d-kind">${KIND_GROUPS.map(([label, kinds]) => `<optgroup label="${label}">${kinds.map(([k, text]) => `<option value="${k}">${text}</option>`).join('')}</optgroup>`).join('')}</select></td>
    <td><input class="d-amount num" type="number" min="0" step="1" placeholder="금액"></td>
    <td><input class="d-doc" maxlength="50" placeholder="감정서번호(선택)"></td>
    <td><input class="d-date" type="date"></td>
    <td><input class="d-memo" maxlength="200" placeholder="메모"></td>
    <td><span class="badge muted">새 항목</span></td>
    <td><button type="button" class="row-menu del" title="빼기">×</button></td>`;
  tr.querySelector('.del').addEventListener('click', () => { tr.remove(); updatePreview(); });
  tr.querySelectorAll('.d-apply, .d-kind, .d-amount').forEach(f => f.addEventListener('input', updatePreview));
  tr.querySelector('.d-apply').addEventListener('change', updatePreview);
  return tr;
}

// 체크 상태의 공제 목록 (대장 항목 + 새 항목 중 체크된 것) → 지급액 미리보기. 음수면 빨간 글씨.
function selectedDeductions() {
  return Array.from($('deductRows').querySelectorAll('tr')).filter(tr => tr.querySelector('.d-apply').checked).map(tr => {
    if (tr.dataset.itemId) return { kind: tr.dataset.kind, amount: Number(tr.dataset.amount) };
    return { kind: tr.querySelector('.d-kind').value, amount: Number(tr.querySelector('.d-amount').value || 0) };
  }).filter(d => d.amount > 0);
}

function updatePreview() {
  const person = $('deductDialog').dataset.person;
  if (!person || !window.BonusCalc) return;
  const now = window.BonusCalc.preview(report, person, selectedDeductions());
  const applied = window.BonusCalc.preview(report, person, deductionsOf(person));
  const drift = Math.abs(applied.payment - now.server) >= 1;
  const delta = now.payment - now.server;
  $('deductPreview').innerHTML = `<span>현재 지급액 <b>${num(now.server)}</b>원</span>`
    + `<span>선택 반영 <b class="${now.payment < 0 ? 'neg' : ''}">${num(now.payment)}</b>원${now.payment < 0 ? ' <span class="neg">(지급액이 음수입니다 — 산출액 부족분은 다음 달 미납비로 넘어가고, 선지급 초과분은 확인이 필요합니다)</span>' : ''}</span>`
    + `<span class="delta">${delta === 0 ? '변동 없음' : `${delta > 0 ? '+' : ''}${num(delta)}원`}</span>`
    + (drift ? '<span class="warn">미리보기 계산이 서버 값과 달라 저장 후 값을 확인하세요</span>' : '');
}

function openDeductions(person) {
  const dialog = $('deductDialog');
  dialog.dataset.person = person;
  $('deductTitle').textContent = `${person} · ${periodLabel(report.period)} 지급분 공제`;
  const body = $('deductRows');
  body.innerHTML = '';
  const applied = deductionsOf(person).map(d => ({ ...d, source: (d.source || 'MANUAL'), applied_period: report.period }));
  const pending = pendingOf(person);
  applied.forEach(item => body.appendChild(itemRow(item, true)));
  pending.forEach(item => body.appendChild(itemRow(item, false)));
  $('deductHint').textContent = applied.length || pending.length
    ? `적용 ${applied.length}건 · 대기 ${pending.length}건 — 체크한 항목이 이번 달에 빠집니다. 체크를 풀면 대기로 돌아가고, 새 항목은 저장과 함께 대장에 오릅니다.`
    : '대장에 이 사람의 항목이 없습니다. 아래 줄 추가로 새로 올리세요 (체크를 끄면 대기로만 둡니다).';
  if (!applied.length && !pending.length) body.appendChild(newItemRow());
  updatePreview();
  dialog.showModal();
}

function readNewRow(tr) {
  return {
    kind: tr.querySelector('.d-kind').value, amount: Number(tr.querySelector('.d-amount').value || 0),
    doc_id: tr.querySelector('.d-doc').value.trim() || null, occurred_on: tr.querySelector('.d-date').value || null,
    memo: tr.querySelector('.d-memo').value.trim() || null,
  };
}

async function saveDeductions() {
  const person = $('deductDialog').dataset.person;
  const rows = Array.from($('deductRows').querySelectorAll('tr'));
  const appliedIds = rows.filter(tr => tr.dataset.itemId && tr.querySelector('.d-apply').checked).map(tr => Number(tr.dataset.itemId));
  const newRows = rows.filter(tr => tr.classList.contains('new-item')).map(tr => ({ apply: tr.querySelector('.d-apply').checked, item: readNewRow(tr) })).filter(r => r.item.amount > 0);
  for (const r of newRows.filter(r => !r.apply)) {
    await api('POST', '/api/bonus/v2/deduction-items', { ...r.item, person });          // 대기로만
  }
  const data = await api('PUT', `/api/bonus/v2/deductions/${report.period}/${encodeURIComponent(person)}`, {
    applied_item_ids: appliedIds, new_items: newRows.filter(r => r.apply).map(r => r.item),
  });
  $('deductDialog').close();
  toast(`${person}의 공제 ${data.applied.length}건을 이번 달에 적용했습니다.${newRows.some(r => !r.apply) ? ' (대기 항목도 올렸습니다)' : ''}`);
  await loadReport();
}

// ── 오버라이드 ───────────────────────────────────────────────────────────

function openOverride(doc, person) {
  const dialog = $('overrideDialog');
  dialog.dataset.doc = doc; dialog.dataset.person = person;
  $('overrideTitle').textContent = `${doc} · ${person === '*' ? '감정서 전체' : person}`;
  const current = (overrideOf(doc, person) || {}).actions || {};
  $('ovInclude').checked = 'INCLUDE' in current;
  $('ovExclude').checked = 'EXCLUDE' in current;
  $('ovFee').value = current.FEE != null ? Math.round(current.FEE) : '';
  $('ovRate').innerHTML = '<option value="">자동</option>' + RATES.map(r => `<option value="${r}"${Number(current.RATE) === r ? ' selected' : ''}>${r}%</option>`).join('');
  $('ovShare').value = current.SHARE != null ? current.SHARE : '';
  $('ovWork').value = current.WORK || '';
  dialog.showModal();
}

async function saveOverride() {
  const dialog = $('overrideDialog');
  const actions = {};
  if ($('ovInclude').checked) actions.INCLUDE = null;
  if ($('ovExclude').checked) actions.EXCLUDE = null;
  if ($('ovFee').value !== '') actions.FEE = Number($('ovFee').value);
  if ($('ovRate').value !== '') actions.RATE = Number($('ovRate').value);
  if ($('ovShare').value !== '') actions.SHARE = Number($('ovShare').value);
  if ($('ovWork').value.trim()) actions.WORK = $('ovWork').value.trim();
  await api('PUT', `/api/bonus/v2/overrides/${report.period}`, { doc_id: dialog.dataset.doc, person: dialog.dataset.person, actions });
  dialog.close();
  toast(Object.keys(actions).length ? '오버라이드를 저장했습니다.' : '오버라이드를 지웠습니다.');
  await loadReport();
}

async function includeHeld(doc, person) {
  await api('PUT', `/api/bonus/v2/overrides/${report.period}`, { doc_id: doc, person, actions: { INCLUDE: null } });
  toast(`${doc} 을 포함했습니다.`);
  await loadReport();
}

// ── 감정서 추가 (자동으로 안 잡힌 건을 이 사람 행으로) ─────────────────────

function personDocs(person) {
  const ids = new Set();
  for (const group of ['shareholders', 'common', 'associates']) {
    (report[group] || []).forEach(p => { if (p.name === person) p.rows.forEach(r => ids.add(r.doc_id)); });
  }
  return ids;
}

function openDocDialog(person) {
  const dialog = $('docDialog');
  dialog.dataset.person = person;
  $('docTitle').textContent = `${person} · 감정서 추가 (${periodLabel(report.period)} 지급분)`;
  const to = new Date(); const from = new Date(to.getFullYear() - 1, to.getMonth(), 1);
  const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  if (!$('docFrom').value) $('docFrom').value = fmt(from);
  if (!$('docTo').value) $('docTo').value = fmt(to);
  $('docRows').innerHTML = ''; $('docCount').textContent = '';
  dialog.showModal();
  searchDocs().catch(showError);
}

async function searchDocs() {
  const person = $('docDialog').dataset.person;
  $('docCount').textContent = '검색 중...';
  const data = await api('GET', `/api/bonus/v2/docs?person=${encodeURIComponent(person)}&date_from=${$('docFrom').value}&date_to=${$('docTo').value}`);
  const have = personDocs(person);
  const held = new Set((report.held || []).map(h => h.doc_id));
  const items = data.items || [];
  $('docRows').innerHTML = items.map(d => {
    const included = have.has(d.doc_id);
    const state = included ? '<span class="badge ok">이미 포함</span>' : held.has(d.doc_id) ? '<span class="badge warn">보류 중</span>' : '';
    return `<tr class="${included ? 'included' : ''}" data-doc="${esc(d.doc_id)}"><td><input class="doc-pick" type="checkbox"${included ? ' disabled' : ''}></td>
      <td>${esc(d.doc_id)}</td><td>${dateText(d.receipt_date)}</td><td>${esc(d.work_type)}</td><td>${esc(d.customer_name)}</td><td>${esc(d.manager)}${d.common ? ' <span class="badge muted">공통건</span>' : ''}</td><td class="number">${num(d.fee)}</td><td>${state}</td></tr>`;
  }).join('');
  $('docCount').textContent = `${items.length}건${items.length >= 300 ? ' (300건까지만 — 기간을 좁히세요)' : ''}`;
  $('docRows').querySelectorAll('tr').forEach(tr => tr.addEventListener('dblclick', () => { const box = tr.querySelector('.doc-pick'); if (!box.disabled) box.checked = !box.checked; }));
}

async function addSelectedDocs() {
  const person = $('docDialog').dataset.person;
  const docs = Array.from($('docRows').querySelectorAll('tr')).filter(tr => tr.querySelector('.doc-pick').checked).map(tr => tr.dataset.doc);
  if (!docs.length) { toast('추가할 감정서를 체크하세요.', true); return; }
  for (const doc of docs) {
    const current = (overrideOf(doc, person) || {}).actions || {};
    await api('PUT', `/api/bonus/v2/overrides/${report.period}`, { doc_id: doc, person, actions: { ...current, INCLUDE: null } });
  }
  $('docDialog').close();
  toast(`${person}에게 감정서 ${docs.length}건을 추가했습니다.`);
  await loadReport();
}

function bindRowButtons() {
  document.querySelectorAll('.deduct-button').forEach(b => b.addEventListener('click', () => openDeductions(b.dataset.person)));
  document.querySelectorAll('.add-doc-button').forEach(b => b.addEventListener('click', () => openDocDialog(b.dataset.person)));
  document.querySelectorAll('.override-button').forEach(b => b.addEventListener('click', () => openOverride(b.dataset.doc, b.dataset.person)));
  document.querySelectorAll('.include-button').forEach(b => b.addEventListener('click', () => includeHeld(b.dataset.doc, b.dataset.person).catch(showError)));
}

// ── 마감 / 재개 ─────────────────────────────────────────────────────────

async function closePeriod() {
  const label = `${periodLabel(report.period)} 지급분`;
  if (!confirm(`${label}을 마감합니다. 지급액 합계 ${num(totalPayment())}원 — 마감하면 스냅샷으로 고정되고 입력이 잠깁니다. 계속할까요?`)) return;
  const result = await api('POST', `/api/bonus/v2/close/${report.period}`, {});
  toast(`${label}을 마감했습니다 (${result.rows}행).${result.warnings.length ? ' ' + result.warnings.join(' ') : ''}`, result.warnings.length > 0);
  await loadStatus(); await loadReport();
}

async function reopenPeriod() {
  const label = `${periodLabel(report.period)} 지급분`;
  if (!confirm(`${label} 마감을 재개합니다. 스냅샷을 지우고 다시 계산합니다. 계속할까요?`)) return;
  await api('POST', `/api/bonus/v2/reopen/${report.period}`, {});
  toast(`${label} 마감을 재개했습니다.`);
  await loadStatus(); await loadReport();
}

async function loadStatus() {
  const data = await api('GET', '/api/bonus/v2/status');
  closes = data.periods || [];
  return data.next;
}

// ── 초기화 ─────────────────────────────────────────────────────────────

function setTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.bonus-tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  render();
}
document.querySelectorAll('.bonus-tabs button').forEach(button => button.addEventListener('click', () => {
  setTab(button.dataset.tab);
  if (button.dataset.tab === 'search' && !searchResult) runSearch().catch(showError);
}));
// 구간(~)·감정서번호·유치자 중 하나라도 채웠으면 검색 탭으로, 아니면 지급월 하나 조회
$('searchButton').addEventListener('click', () => {
  if (filtersActive()) { runSearch().catch(showError); return; }
  if (currentTab === 'search') setTab('shareholders');
  loadReport().catch(showError);
});
['period', 'periodTo', 'docFilter', 'personFilter'].forEach(id =>
  $(id).addEventListener('keydown', event => { if (event.key === 'Enter') $('searchButton').click(); }));
$('exportButton').addEventListener('click', () => { window.A10_DOWNLOAD(`/api/bonus/v2/export.xlsx?period=${periodValue()}`); });
$('settingsButton').addEventListener('click', () => { location.href = '/desktop/bonus-settings'; });
$('ledgerButton').addEventListener('click', () => { location.href = '/desktop/bonus-deductions'; });
$('closeButton').addEventListener('click', () => closePeriod().catch(showError));
$('reopenButton').addEventListener('click', () => reopenPeriod().catch(showError));
$('deductAdd').addEventListener('click', () => { $('deductRows').appendChild(newItemRow()); updatePreview(); });
$('deductCancel').addEventListener('click', () => $('deductDialog').close());
$('deductSave').addEventListener('click', () => saveDeductions().catch(showError));
$('overrideCancel').addEventListener('click', () => $('overrideDialog').close());
$('docCancel').addEventListener('click', () => $('docDialog').close());
$('docSearch').addEventListener('click', () => searchDocs().catch(showError));
$('docAdd').addEventListener('click', () => addSelectedDocs().catch(showError));
$('overrideSave').addEventListener('click', () => saveOverride().catch(showError));
$('ovInclude').addEventListener('change', () => { if ($('ovInclude').checked) $('ovExclude').checked = false; });
$('ovExclude').addEventListener('change', () => { if ($('ovExclude').checked) $('ovInclude').checked = false; });

window.A10_READY.then(async ctx => {
  if (ctx.office_id !== '10') {
    $('bonusRows').innerHTML = ''; $('resultSummary').textContent = '';
    $('emptyList').classList.remove('hidden'); $('emptyList').textContent = '상여 화면은 본사만 사용할 수 있습니다.';
    return;
  }
  try {
    const next = await loadStatus();
    $('period').value = periodLabel(next);
    await loadReport();
  } catch (err) { showError(err); }
});
