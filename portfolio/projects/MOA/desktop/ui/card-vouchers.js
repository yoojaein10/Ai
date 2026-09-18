// 카드전표: 엑셀 업로드 → 검증 목록(수정 가능) → 분개 확정 → 아마란스 전송.
// 승인금액·카드·승인번호는 원천 데이터라 수정할 수 없다(카드 청구액과 어긋나면 안 되므로).
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));

const PURPOSES = ['복리후생비', '차량유지비', '여비교통비', '통신비', '운반비', '지급수수료', '체력단련비', '미수금'];
let items = [];          // 업로드·검증 결과 (화면에서 수정됨)
let visibleItems = [];   // 그 중 화면에 실제로 그려진 것 (엑셀 내보내기·인쇄가 쓴다)
let sortBy = '';         // 머리글을 눌러 고른 정렬 기준 (빈 값이면 원천 순서)
let sortOrder = 'asc';
let selectedDraft = null;

const usrSeq = () => Number((window.A10_CTX || {}).usr_seq || 0);

// ── 임시저장 ────────────────────────────────────────────────────
// 분류·체크를 다 해 놓고 실수(새로고침·재조회·화면 이동)로 날리는 일을 막는다
// (2026-08-31 사용자 요청). 수정할 때마다 이 PC 브라우저 저장소에 자동 저장하고,
// 화면을 열면 마지막 작업을 그대로 복원한다.
const SAVE_KEY = 'a10.cardVouchers.worksheet';
let saveTimer = null;

const clock = d => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

function saveWork(manual) {
  if (!items.length) {
    if (manual) window.A10_TOAST('저장할 목록이 없습니다.', true);
    return;
  }
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify({
      saved_at: new Date().toISOString(),
      filename: $('cvFileName').textContent || '',
      summary: lastSummary,
      items,
    }));
    $('cvSaveNote').textContent = `${manual ? '임시저장됨' : '자동저장'} ${clock(new Date())}`;
    if (manual) setMsg($('cvMsg'), `${items.length}건을 임시저장했습니다. 화면을 닫아도 다시 열면 복원됩니다.`, 'ok');
  } catch (error) {
    if (manual) setMsg($('cvMsg'), '임시저장 실패 — 브라우저 저장 공간을 확인하세요.', 'err');
  }
}

// 연타(일괄변경 등)에 저장이 몰리지 않게 잠깐 모아서 저장한다.
function queueSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveWork(false), 800);
}

function restoreWork() {
  try {
    const saved = JSON.parse(localStorage.getItem(SAVE_KEY) || 'null');
    if (!saved || !Array.isArray(saved.items) || !saved.items.length) return;
    items = saved.items;
    lastSummary = saved.summary || null;
    $('cvFileName').textContent = saved.filename || '';
    renderRows();
    const at = saved.saved_at ? new Date(saved.saved_at) : null;
    const stamp = at && !Number.isNaN(at.getTime())
      ? `${at.getMonth() + 1}/${at.getDate()} ${clock(at)}에 ` : '';
    setMsg($('cvMsg'), `${stamp}작업하던 ${items.length}건을 복원했습니다.`, 'ok');
  } catch (error) { /* 복원에 실패하면 빈 화면으로 시작한다 */ }
}

// 새로 불러온 목록에 하던 작업(분류·공제·금액·적요·체크)을 같은 건 기준으로 다시
// 입힌다 — 작업 중에 '카드내역 불러오기'를 한 번 더 눌러도 날아가지 않게.
// 이미 확정·전송된 건은 서버 상태가 진실이라 덮지 않는다.
function mergeSavedEdits(fresh) {
  const prev = new Map(items.map(it => [it.dedup_key, it]));
  let kept = 0;
  fresh.forEach(it => {
    const old = prev.get(it.dedup_key);
    if (!old || it.processed_status || old.processed_status) return;
    if (old.edited) {
      it.purpose = old.purpose;
      it.account_code = old.account_code;
      it.deductible = old.deductible;
      it.supply = old.supply;
      it.vat = old.vat;
      it.remark = old.remark;
      it.auto_purpose = false;
      it.edited = true;
      kept += 1;
    }
    if (old.picked !== undefined) it.picked = old.picked;
  });
  return kept;
}

function setMsg(el, text, kind) {
  el.textContent = text || '';
  el.className = 'cv-msg' + (kind ? ' ' + kind : '');
}

// ── 업로드 ──────────────────────────────────────────────────────
async function upload() {
  const file = $('cvFile').files[0];
  if (!file) { setMsg($('cvMsg'), '엑셀 파일을 선택하세요.', 'err'); return; }
  const button = $('cvUpload');
  button.disabled = true; button.textContent = '검증 중...';
  setMsg($('cvMsg'), '');
  try {
    const form = new FormData();
    form.append('file', file);
    form.append('requester_usr_seq', usrSeq());
    form.append('auto_register', $('cvAutoRegister').checked ? 'true' : 'false');
    const response = await fetch('/api/card-vouchers/analyze', { method: 'POST', body: form });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    const fresh = payload.data.items || [];
    const kept = mergeSavedEdits(fresh);
    items = fresh;
    $('cvFileName').textContent = payload.data.filename || '';
    renderSummary(payload.data.summary);
    renderRows();
    if (kept) setMsg($('cvMsg'), `하던 작업 ${kept}건의 분류·수정을 새 목록에 다시 적용했습니다.`, 'ok');
  } catch (error) {
    setMsg($('cvMsg'), error.message, 'err');
  } finally {
    button.disabled = false; button.textContent = '업로드·검증';
  }
}

// ── 카드내역 DB 불러오기 (엑셀과 같은 목록으로 합류, 중복은 서버가 보류 처리) ──
async function fetchDb() {
  const from = $('cvDbFrom').value, to = $('cvDbTo').value;
  if (!from || !to) { setMsg($('cvMsg'), '조회 기간을 선택하세요.', 'err'); return; }
  const button = $('cvFetchDb');
  button.disabled = true; button.textContent = '불러오는 중...';
  setMsg($('cvMsg'), '');
  try {
    const query = new URLSearchParams({
      requester_usr_seq: usrSeq(), date_from: from, date_to: to,
      auto_register: $('cvAutoRegister').checked ? 'true' : 'false',
    });
    const response = await fetch(`/api/card-vouchers/fetch?${query}`);
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    const fresh = payload.data.items || [];
    const kept = mergeSavedEdits(fresh);
    items = fresh;
    $('cvFileName').textContent = payload.data.filename || '';
    renderSummary(payload.data.summary);
    renderRows();
    if (!items.length) setMsg($('cvMsg'), '해당 기간에 카드내역이 없습니다.', '');
    else if (kept) setMsg($('cvMsg'), `하던 작업 ${kept}건의 분류·수정을 새 목록에 다시 적용했습니다.`, 'ok');
  } catch (error) {
    setMsg($('cvMsg'), error.message, 'err');
  } finally {
    button.disabled = false; button.textContent = '카드내역 불러오기';
  }
}

let lastSummary = null;

const autoCount = () => items.filter(it => it.auto_purpose).length;

function renderSummary(summary) {
  lastSummary = summary || lastSummary;
  if (!lastSummary) { $('cvSummary').classList.add('hidden'); return; }
  const s = lastSummary;
  const hidden = items.filter(isDone).length;
  $('cvSummary').classList.remove('hidden');
  $('cvSummary').innerHTML =
    `<span>사용일자 <b>${esc((s.dates || []).join(', '))}</b></span>` +
    `<span>전체 <b>${s.total_count}건</b></span>` +
    `<span>생성대상 <b>${s.ready_count}건</b></span>` +
    `<span>보류 <b>${s.hold_count}건</b></span>` +
    `<span>공제대상 <b>${s.deductible_count}건</b></span>` +
    `<span>합계 <b>${money.format(s.ready_amount || 0)}원</b></span>` +
    (autoCount() ? `<span>계정 자동 <b>${autoCount()}건</b> — 확인하세요</span>` : '') +
    (hidden && doneFilter() === 'open' ? `<span class="cv-hidden-note">전송완료 <b>${hidden}건</b> 숨김</span>` : '') +
    (doneFilter() === 'done' ? `<span class="cv-hidden-note">미처리 <b>${items.length - hidden}건</b> 숨김</span>` : '');
}

// 아마란스 전송까지 끝난 건만 숨긴다. 확정만 하고 안 보낸 건(D)과 실패한 건(F)은
// 담당자가 알아야 하므로 계속 보여준다.
const isDone = it => it.processed_status === 'S';
// 처리 구분 콤보박스: all(전체) | done(처리 = 전송완료) | open(미처리) — 2026-08-26 사용자 요청
const doneFilter = () => $('cvDoneFilter').value;

// 수정하면 다시 계산되는 사유들. 서버가 준 다른 사유(취소 건, 이미 생성됨 등)는 그대로 둔다.
const RECHECKED = ['계정 미매핑', '금액 불일치', '가맹점 거래처', '가맹점 사업자번호'];

// 확정을 막지 않는 '안내' 보류 — 노란 줄로 보이지만 골라서 확정할 수 있다
// (2026-08-20 사용자 결정). 서버 목록(card_vouchers.ADVISORY_HOLDS)과 같아야 한다.
const ADVISORY_HOLDS = ['가맹점 거래처 없음', '승인번호 분할'];
const isAdvisory = hold => ADVISORY_HOLDS.some(prefix => String(hold).startsWith(prefix));

function recompute(item) {
  const holds = (item.holds || []).filter(h => !RECHECKED.some(p => h.startsWith(p)));
  if (!item.account_code) holds.push('계정 미매핑');
  if (item.deductible && Number(item.supply) + Number(item.vat) !== Number(item.total)) {
    holds.push(`금액 불일치(${money.format(item.supply)} + ${money.format(item.vat)} ≠ ${money.format(item.total)})`);
  }
  // 가맹점 미등록 안내는 2026-08-31 뺐다 — 전표에 안 쓰이는 정보인데 매달
  // 130건쯤 노란 줄만 만들었다. RECHECKED 의 '가맹점 거래처' 항목은 임시저장으로
  // 복원된 옛 줄에서 그 안내를 걷어내는 용도로 남겨 둔다.
  item.holds = holds;
  item.status = holds.length ? 'hold' : 'ready';   // 색·배지용
  item.blocked = holds.some(h => !isAdvisory(h));  // 확정 가능 여부
  // 정상구분이 '정상'이면 보류라도 체크해 둔다 (2026-08-20 사용자 요청) — 보류를
  // 일괄변경으로 푸는 게 흔한 일이라, 그때마다 다시 고르지 않아도 되게 한다.
  // 확정 대상은 picked()가 ready만 고르므로 보류가 체크돼 있어도 확정되지 않는다.
  // 취소·처리된 건은 기본으로 체크하지 않는다. 처리된 건도 체크 자체는 된다
  // (2026-08-31 사용자 제보: 체크가 막혀 있으면 확정·전송한 건을 엑셀로 못 담는다).
  if (item.picked === undefined) item.picked = !item.canceled && !item.processed_status;
}

const fmtUseDate = d => (d && String(d).length === 8)
  ? `${String(d).slice(0, 4)}.${String(d).slice(4, 6)}.${String(d).slice(6, 8)}` : String(d || '');

function renderRows() {
  if (!items.length) {
    $('cvRows').innerHTML = '<tr><td colspan="17">엑셀을 업로드하세요.</td></tr>';
    $('cvCreateDraft').disabled = true;
    $('cvExport').disabled = true;
    $('cvPrint').disabled = true;
    visibleItems = [];
    return;
  }
  items.forEach(recompute);
  // 숨겨도 data-i는 원본 배열의 위치를 유지해야 수정 이벤트가 엉키지 않는다.
  const mode = doneFilter();
  const visible = items.map((it, i) => [it, i]).filter(([it]) => mode === 'all' || (mode === 'done') === isDone(it));
  if (sortBy) {
    const direction = sortOrder === 'asc' ? 1 : -1;
    visible.sort(([a], [b]) => compareRows(a, b) * direction);
  }
  // 내보내기는 화면에 보이는 것과 같아야 한다 — 숨긴 건은 엑셀에도 안 담는다.
  visibleItems = visible.map(([it]) => it);
  if (!visible.length) {
    $('cvRows').innerHTML = `<tr><td colspan="17">표시할 건이 없습니다. (${mode === 'done' ? '전송완료 건이 없습니다' : '전송완료 건은 숨김 상태입니다'})</td></tr>`;
    renderSummary(null);
    updateCreateButton();
    return;
  }
  $('cvRows').innerHTML = visible.map(([it, i]) => {
    const hold = it.status === 'hold';
    // 처리된 건(확정·전송·실패)은 '보류'가 아니라 전표 상태를 배지로 보인다 — '보류 / 이미 아마란스로
    // 전송된 건'이 못 보낸 것처럼 읽혔다 (2026-08-26 사용자 요청). "이미 …" 사유는 배지와 겹치니 뺀다.
    const done = it.processed_status;
    const reasons = done ? (it.holds || []).filter(h => !String(h).startsWith('이미 ')) : (it.holds || []);
    const why = reasons.length && (hold || done) ? `<div class="cv-hold-why">${esc(reasons.join(' / '))}</div>` : '';
    // 안내뿐이면 확정되므로 배지를 '확인' 으로 구분한다 (막히는 건과 헷갈리지 않게)
    const badge = done ? [`done-${done}`, STATUS_TEXT[done] || done]
      : (!hold ? ['ready', '정상'] : (it.blocked ? ['hold', '보류'] : ['note', '확인']));
    return `<tr class="${done ? 'done' : (hold ? 'hold' : '')}" data-i="${i}">
      <td><input type="checkbox" class="cv-pick" data-i="${i}" ${it.picked ? 'checked' : ''}></td>
      <td><span class="cv-badge ${badge[0]}">${badge[1]}</span>${why}</td>
      <td class="locked">${it.canceled ? '<span class="cv-badge hold">취소</span>' : '정상'}</td>
      <td class="locked">${esc(it.user_name)}</td>
      <td class="locked" title="${esc(it.card_partner_name)}">${esc(it.card_alias || it.card_partner_name || '')}</td>
      <td class="locked cv-cardno">${esc(it.card_no || '')}</td>
      <td class="locked">${esc(fmtUseDate(it.use_date))}</td>
      <td class="locked">${esc(it.appr_time || '')}</td>
      <td title="${esc(it.merchant_partner_name || '거래처 미등록')}">${esc(it.merchant)}</td>
      <td class="locked">${esc(it.industry || '')}</td>
      <td class="number locked">${money.format(it.total)}</td>
      <td><select class="cv-purpose" data-i="${i}">
        <option value="" ${it.purpose ? '' : 'selected'}></option>
        ${PURPOSES.map(p => `<option ${p === it.purpose ? 'selected' : ''}>${p}</option>`).join('')}
        ${!it.purpose || PURPOSES.includes(it.purpose) ? '' : `<option selected>${esc(it.purpose)}</option>`}
      </select>${it.auto_purpose ? '<span class="cv-auto" title="지난 전표에서 같은 가맹점·업종이 쓴 계정입니다. 맞는지 확인하세요">자동</span>' : ''}</td>
      <td><select class="cv-deduct" data-i="${i}">
        <option value="1" ${it.deductible ? 'selected' : ''}>공제</option>
        <option value="0" ${it.deductible ? '' : 'selected'}>미공제</option>
      </select></td>
      <td class="locked">${esc(it.tax_info || '')}</td>
      <td class="number"><input class="num cv-supply" data-i="${i}" value="${money.format(it.supply)}"></td>
      <td class="number"><input class="num cv-vat" data-i="${i}" value="${money.format(it.vat)}"></td>
      <td><input class="cv-remark" data-i="${i}" value="${esc(it.remark)}" style="max-width:180px"></td>
    </tr>${''}`;
  }).join('');
  bindRowEvents();
  applyColumnResize();
  renderSummary(null);
  updateCreateButton();
  // 계정·공제·금액·일괄변경·확정은 전부 여기를 거친다 — 자동 임시저장도 여기서 건다.
  if (items.length) queueSave();
}

// 표를 다시 그리면 헤더도 새로 만들어지므로 폭 조절 핸들을 매번 다시 붙인다
// (column-resize.js가 중복 부착은 스스로 막는다).
function applyColumnResize() {
  const resize = window.A10_COLUMN_RESIZE;
  if (!resize) return;
  resize($('cvTable'), 'a10.cardVouchers.rows.columnWidths');
  resize(document.querySelector('.cv-drafts'), 'a10.cardVouchers.drafts.columnWidths');
  resize(document.querySelector('.cv-lines'), 'a10.cardVouchers.lines.columnWidths');
}

const digits = v => Number(String(v || '').replace(/[^0-9-]/g, '') || 0);

// ── 머리글 정렬 ──────────────────────────────────────────────────
// 정렬은 화면에 그리는 순서만 바꾼다 — 행의 data-i 는 items 안 제자리를
// 가리키므로, 정렬해도 수정 이벤트가 엉키지 않는다.
const SORT_NUMBERS = new Set(['total', 'supply', 'vat']);

// 상태 칸은 배지(정상·확인·보류) 순으로 세운다 — hold/ready 두 값으로 세우면
// 확인·보류가 섞여 정렬이 안 되는 것처럼 보였다 (2026-08-26 제보).
function statusRank(item) {
  if (item.processed_status) return 3;      // 처리된 건은 맨 뒤(또는 내림차순이면 맨 앞)
  if (item.status !== 'hold') return 0;
  return item.blocked ? 2 : 1;
}

function sortValue(item, key) {
  if (key === 'status') return statusRank(item);
  if (key === 'deductible') return item.deductible ? 1 : 0;
  if (key === 'canceled') return item.canceled ? 1 : 0;
  if (key === 'card_alias') return cardCompanyOf(item);
  return item[key];
}

function compareRows(a, b) {
  const left = sortValue(a, sortBy), right = sortValue(b, sortBy);
  if (SORT_NUMBERS.has(sortBy) || typeof left === 'number') {
    return Number(left || 0) - Number(right || 0);
  }
  return String(left ?? '').localeCompare(String(right ?? ''), 'ko', { numeric: true });
}

function sortByColumn(column) {
  sortOrder = sortBy === column && sortOrder === 'asc' ? 'desc' : 'asc';
  sortBy = column;
  document.querySelectorAll('#cvTable th[data-sort]').forEach(th => {
    if (th.dataset.sort === column) {
      th.setAttribute('aria-sort', sortOrder === 'asc' ? 'ascending' : 'descending');
    } else {
      th.removeAttribute('aria-sort');
    }
  });
  renderRows();
}

function bindSortHeaders() {
  document.querySelectorAll('#cvTable th[data-sort]').forEach(th => {
    th.tabIndex = 0;
    th.setAttribute('role', 'button');
    th.addEventListener('click', () => sortByColumn(th.dataset.sort));
    th.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        sortByColumn(th.dataset.sort);
      }
    });
  });
}
bindSortHeaders();

function bindRowEvents() {
  document.querySelectorAll('.cv-purpose').forEach(el => el.addEventListener('change', () => {
    const it = items[Number(el.dataset.i)];
    it.purpose = el.value;
    it.account_code = ACCOUNT_MAP[el.value] || '';
    reapplyRemarkSuffix(it);
    it.auto_purpose = false;   // 사람이 고른 값이면 '자동' 표시를 뗀다
    it.edited = true;
    renderRows();
  }));
  document.querySelectorAll('.cv-deduct').forEach(el => el.addEventListener('change', () => {
    const it = items[Number(el.dataset.i)];
    it.deductible = el.value === '1';
    it.edited = true;
    renderRows();
  }));
  document.querySelectorAll('.cv-supply').forEach(el => el.addEventListener('change', () => {
    const it = items[Number(el.dataset.i)];
    it.supply = digits(el.value); it.edited = true; renderRows();
  }));
  document.querySelectorAll('.cv-vat').forEach(el => el.addEventListener('change', () => {
    const it = items[Number(el.dataset.i)];
    it.vat = digits(el.value); it.edited = true; renderRows();
  }));
  document.querySelectorAll('.cv-remark').forEach(el => el.addEventListener('change', () => {
    items[Number(el.dataset.i)].remark = el.value; items[Number(el.dataset.i)].edited = true;
    queueSave();  // 적요 수정은 renderRows 를 거치지 않는다
  }));
  document.querySelectorAll('.cv-pick').forEach(el => el.addEventListener('change', () => {
    items[Number(el.dataset.i)].picked = el.checked;  // 다른 행을 고쳐도 선택이 유지되도록 보관
    updateCreateButton();
    queueSave();  // 체크도 renderRows 를 거치지 않는다
  }));
}

// 계정코드 표는 서버와 같은 값을 쓴다 (app/services/card_vouchers.py ACCOUNT_MAP).
const ACCOUNT_MAP = {
  '복리후생비': '8110000', '차량유지비': '8220000', '여비교통비': '8120000',
  '통신비': '8140000', '운반비': '8240000', '지급수수료': '8310000',
  '체력단련비': '8590000', '미수금': '1200000',
};

// 계정별 적요 꼬리말 (app/services/card_vouchers.py REMARK_SUFFIX 와 같은 값).
const REMARK_SUFFIX = { '복리후생비': '-사원식대 및 회식대' };

// 사용용도를 바꾸면 적요 꼬리말도 따라 바뀌어야 한다. 옛 꼬리말을 떼고 새 것을
// 붙이는 방식이라 담당자가 손으로 고친 앞부분은 그대로 남는다.
function reapplyRemarkSuffix(it) {
  let base = it.remark || '';
  for (const suffix of Object.values(REMARK_SUFFIX)) {
    if (base.endsWith(suffix)) { base = base.slice(0, -suffix.length); break; }
  }
  it.remark = base + (REMARK_SUFFIX[it.purpose] || '');
}

function picked() {
  // 안내뿐인 건(가맹점 거래처 없음·승인번호 분할)은 노란 줄이어도 확정 대상이다.
  // 처리된 건은 체크돼 있어도(엑셀·인쇄 범위용) 전표로 다시 나가면 안 된다.
  return items.filter(it => it.picked && !it.blocked && !it.processed_status);
}

function updateCreateButton() {
  const chosen = picked();
  const n = chosen.length;
  // 체크한 수와 확정되는 수가 다른 이유를 밝힌다 — 보류 건은 체크돼 있어도
  // 확정에서 빠진다 (2026-08-20 제보: 60건 체크했는데 버튼은 38건이라 헷갈렸다).
  const checked = items.filter(it => it.picked && !it.processed_status).length;
  const held = checked - n;
  const heldNote = held > 0 ? `체크 ${checked}건 중 보류 ${held}건은 빠집니다` : '';

  $('cvCreateDraft').disabled = n === 0;
  $('cvCreateDraft').textContent = n ? `선택 ${n}건 확정 + 아마란스 전송` : '선택 건 확정 + 아마란스 전송';
  // 인쇄·엑셀은 체크한 건을 담으므로 확정과 달리 보류도 포함해 센다
  const anyPicked = visibleItems.some(it => it.picked);
  $('cvPrint').disabled = !anyPicked;
  $('cvExport').disabled = !anyPicked;

  // 선택한 건의 사용일 범위를 보여주고, 전표일자와 다른 달이 섞이면 알린다.
  // (부가세 신고분이 갈리는 자리라 막지는 않고 확인만 하게 한다.)
  const info = $('cvPickInfo');
  if (!n) {
    info.textContent = heldNote ? `${heldNote} — 보류를 풀어야 확정됩니다` : '';
    info.classList.toggle('warn', Boolean(heldNote));
    return;
  }
  const used = chosen.map(it => String(it.use_date || '')).filter(d => d.length === 8).sort();
  const fmt = d => `${d.slice(4, 6)}-${d.slice(6, 8)}`;
  const span = used.length ? (used[0] === used[used.length - 1]
    ? fmt(used[0]) : `${fmt(used[0])} ~ ${fmt(used[used.length - 1])}`) : '';
  const vMonth = ($('cvVoucherDate').value || '').replace(/-/g, '').slice(0, 6);
  const crossMonth = used.some(d => d.slice(0, 6) !== vMonth);
  info.textContent = (heldNote ? `${heldNote} · ` : '') + `사용일 ${span}`
    + (crossMonth ? ' — 전표일자와 다른 달의 사용분이 섞여 있습니다(부가세 신고분 확인)' : '');
  info.classList.toggle('warn', crossMonth);
}

// ── 분개 확정 ───────────────────────────────────────────────────
async function createDraft() {
  const chosen = picked();
  if (!chosen.length) return;
  const voucherDate = $('cvVoucherDate').value;
  if (!voucherDate) { setMsg($('cvMsg'), '전표일자를 지정하세요.', 'err'); return; }
  const button = $('cvCreateDraft');
  button.disabled = true; button.textContent = '확정 중...';
  try {
    const response = await fetch('/api/card-vouchers/drafts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requester_usr_seq: usrSeq(), items: chosen,
        voucher_date: voucherDate,
        source_file: $('cvFileName').textContent,
      }),
    });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    const draftId = payload.data.id;
    // 확정과 전송을 한 번에 (2026-09-08 사용자 요청 — 두 번 누르는 흐름 제거).
    // 아마란스가 거부하면 방금 만든 확정을 지워 확정 전 상태로 되돌린다 — 확정만
    // 남겨 두면 항목이 잠긴 채 '미전송'으로 쌓여 수정할 길이 막힌다.
    button.textContent = '아마란스 전송 중...';
    let sent;
    try {
      sent = await sendById(draftId);
    } catch (sendError) {
      let rolledBack = false;
      try {
        const undo = await fetch(`/api/card-vouchers/drafts/${draftId}?requester_usr_seq=${usrSeq()}`, { method: 'DELETE' });
        rolledBack = !!(await undo.json()).success;
      } catch (_) { /* 되돌리기 실패는 아래 문구로 알린다 */ }
      throw new Error(rolledBack
        ? `아마란스 전송 실패: ${sendError.message} — 확정을 되돌렸습니다. 내용을 고친 뒤 다시 확정하세요.`
        : `아마란스 전송 실패: ${sendError.message} — 확정은 남아 있습니다(미전송). 전표 목록에서 취소하거나 다시 전송하세요.`);
    }
    setMsg($('cvMsg'), sentMessage(sent, `${chosen.length}건을 확정하고 아마란스로 전송했습니다`), 'ok');
    // 전송까지 끝났으니 처리(S)로 표시한다 — '처리 구분: 미처리'에서는 숨겨진다.
    const keys = new Set(chosen.map(it => it.dedup_key));
    items.forEach(it => {
      if (!keys.has(it.dedup_key)) return;
      it.processed_status = 'S';
      it.picked = false;
      it.holds = [...(it.holds || []), '이미 전표로 전송된 건'];
      it.status = 'hold';
    });
    renderRows();
    // 목록은 전표일자로 자른다 — 소급 확정(7월분을 8월에)이면 기간을 그 전표일자까지 넓혀 방금 만든 것이 보이게
    if ($('cvDraftFrom').value && voucherDate < $('cvDraftFrom').value) $('cvDraftFrom').value = voucherDate;
    if ($('cvDraftTo').value && voucherDate > $('cvDraftTo').value) $('cvDraftTo').value = voucherDate;
    await loadDrafts();
    selectDraft(draftId);
  } catch (error) {
    setMsg($('cvMsg'), error.message, 'err');
  } finally {
    updateCreateButton();
  }
}

// ── 확정 전표 목록 / 전송 ───────────────────────────────────────
const STATUS_TEXT = { D: '확정(미전송)', S: '전송완료', F: '전송실패', X: '아마란스 삭제' };

// 아마란스에서 삭제된 전송완료 전표를 X로 정리한다 — 회차당 몇 개 전표일자만
// 검사하므로 목록 로드를 막지 않게 백그라운드로 돌리고, 바뀐 게 있으면 다시 그린다.
async function syncAmaranth() {
  try {
    const response = await fetch('/api/card-vouchers/sync-amaranth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ requester_usr_seq: usrSeq() }),
    });
    const payload = await response.json();
    const removed = (payload.success && payload.data && payload.data.deleted) || [];
    if (removed.length) {
      setMsg($('cvSendMsg'),
        `아마란스에서 삭제된 전표 ${removed.length}건을 정리했습니다 `
        + `(${removed.map(v => `#${v.id}`).join(', ')}) — 담긴 건들은 다시 확정할 수 있습니다.`, 'ok');
      await loadDrafts();
    }
  } catch (error) { /* 동기화 실패는 조용히 — 다음 로드에서 다시 시도 */ }
}

async function loadDrafts() {
  // 전표일자 기준. 기본은 당일치 — 기간을 비워 보내면 서버가 오늘로 잡는다.
  const query = new URLSearchParams({ requester_usr_seq: usrSeq() });
  if ($('cvDraftFrom').value) query.set('date_from', $('cvDraftFrom').value);
  if ($('cvDraftTo').value) query.set('date_to', $('cvDraftTo').value);
  const response = await fetch(`/api/card-vouchers/drafts?${query}`);
  const payload = await response.json();
  if (!payload.success) return;
  const rows = payload.data.items || [];
  renderDraftNote(payload.data);
  $('cvDrafts').innerHTML = rows.length ? rows.map(v => `
    <tr data-id="${v.id}" class="${selectedDraft === v.id ? 'sel' : ''}">
      <td>${v.id}</td><td>${esc(v.voucher_date)}</td>
      <td class="number">${v.item_count}</td>
      <td class="number">${money.format(v.total_amount)}</td>
      <td class="st-${esc(v.status)}" title="${esc(v.error_msg || '')}">${STATUS_TEXT[v.status] || v.status}</td>
      <td>${esc(v.a10_voucher_no || '-')}</td>
    </tr>`).join('') : '<tr><td colspan="6">확정된 전표가 없습니다.</td></tr>';
  document.querySelectorAll('#cvDrafts tr[data-id]').forEach(tr =>
    tr.addEventListener('click', () => selectDraft(Number(tr.dataset.id))));
  applyColumnResize();
}

// 기간 밖에 아직 손이 필요한 전표가 남아 있으면 알려준다 — 당일치만 보다가
// 실패한 전표를 잊는 일이 없게 (2026-08-14 고아 전표 재발 방지).
function renderDraftNote(data) {
  const outside = data.outside || {};
  const parts = [];
  if (outside.failed) parts.push(`실패 ${outside.failed}건`);
  if (outside.draft) parts.push(`미전송 ${outside.draft}건`);
  const note = $('cvDraftNote');
  if (parts.length) {
    note.textContent = `이 기간 밖에 ${parts.join(', ')}이 남아 있습니다 — 기간을 넓혀 확인하세요`;
    note.classList.add('warn');
  } else {
    note.textContent = '행을 누르면 아래에 분개 미리보기가 열립니다';
    note.classList.remove('warn');
  }
}

async function selectDraft(id) {
  selectedDraft = id;
  document.querySelectorAll('#cvDrafts tr[data-id]').forEach(tr =>
    tr.classList.toggle('sel', Number(tr.dataset.id) === id));
  const response = await fetch(`/api/card-vouchers/drafts/${id}?requester_usr_seq=${usrSeq()}`);
  const payload = await response.json();
  if (!payload.success) { setMsg($('cvSendMsg'), payload.message, 'err'); return; }
  const data = payload.data;
  const lines = data.lines || [];
  $('cvLines').innerHTML = lines.length ? lines.map(l => `
    <tr><td>${l.menuLnSq}</td>
      <td class="${l.drcrFg === '3' ? 'dr' : 'cr'}">${l.drcrFg === '3' ? '차변' : '대변'}</td>
      <td>${esc(l.acctCd)}</td>
      <td class="number">${money.format(l.acctAm)}</td>
      <td>${esc(l.trCd || '-')}</td>
      <td>${esc(l.taxFg || '')}</td><td>${esc(l.attrCd || '')}</td>
      <td>${esc(l.rmkDc || '')}</td></tr>`).join('')
    : '<tr><td colspan="8">분개가 없습니다.</td></tr>';
  applyColumnResize();
  // X(아마란스 삭제)는 담긴 건이 이미 비워져 재전송할 게 없다 — 전표 취소로 행만 정리 가능
  $('cvSend').disabled = data.status === 'S' || data.status === 'X';
  $('cvCancelDraft').disabled = data.status === 'S';
  setMsg($('cvSendMsg'), data.status === 'S'
    ? `아마란스 전송 완료 (전표 ${data.a10_voucher_no || '-'})`
    : (data.error_msg || ''), data.status === 'S' ? 'ok' : (data.error_msg ? 'err' : ''));
}

// 아마란스 전송 — 성공하면 응답 data, 실패하면 throw. 확정 흐름(createDraft)과
// 남은 미전송 건을 보내는 버튼(sendDraft)이 같이 쓴다.
async function sendById(id) {
  const response = await fetch(`/api/card-vouchers/drafts/${id}/send`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ requester_usr_seq: usrSeq() }),
  });
  const payload = await response.json();
  if (!payload.success) throw new Error(payload.message);
  return payload.data;
}
function sentMessage(data, prefix) {
  const cars = data.vehicle_lines || 0;
  return `${prefix} (전표 ${data.a10_voucher_no || '-'})${cars ? ` · 업무용승용차 ${cars}건 — 아마란스 관리항목에 차량이 뜨는지 확인하세요` : ''}`;
}
async function sendDraft() {
  if (!selectedDraft) return;
  if (!confirm('아마란스에 전표를 등록합니다.\n취소하려면 아마란스에서 직접 삭제해야 합니다. 진행할까요?')) return;
  const button = $('cvSend');
  button.disabled = true; button.textContent = '전송 중...';
  try {
    const data = await sendById(selectedDraft);
    setMsg($('cvSendMsg'), sentMessage(data, '아마란스로 전송했습니다'), 'ok');
    await loadDrafts();
    await selectDraft(selectedDraft);
  } catch (error) {
    setMsg($('cvSendMsg'), error.message, 'err');
    await loadDrafts();
  } finally {
    button.textContent = '아마란스 전송';
  }
}

// ── 전표 취소 (미전송분만) ──────────────────────────────────────
async function cancelDraft() {
  if (!selectedDraft) return;
  if (!confirm('이 전표를 취소합니다.\n담긴 건들은 다시 확정할 수 있게 됩니다. 진행할까요?')) return;
  const button = $('cvCancelDraft');
  button.disabled = true; button.textContent = '취소 중...';
  try {
    const response = await fetch(
      `/api/card-vouchers/drafts/${selectedDraft}?requester_usr_seq=${usrSeq()}`,
      { method: 'DELETE' });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    setMsg($('cvSendMsg'), `전표를 취소했습니다 (${payload.data.item_count}건 해제).`, 'ok');
    selectedDraft = null;
    $('cvLines').innerHTML = '<tr><td colspan="8">전표를 선택하세요.</td></tr>';
    $('cvSend').disabled = true;
    await loadDrafts();
  } catch (error) {
    setMsg($('cvSendMsg'), error.message, 'err');
  } finally {
    button.textContent = '전표 취소';
    button.disabled = !selectedDraft;
  }
}

// ── 엑셀 내보내기 ────────────────────────────────────────────────
// 화면에서 고친 값(계정·공제·공급가액·적요)까지 그대로 담아야 하므로 목록을
// 서버로 보내 엑셀을 만든다. 데스크톱 앱(pywebview)은 화면에서 만든 Blob을
// 저장하지 못하고 GET 내려받기만 되므로, 보관 토큰을 받아 GET으로 받는다
// (입금 대사 화면과 같은 방식).
async function exportRows() {
  // 인쇄와 같은 기준 — 체크한 건만 담는다 (2026-08-31 사용자 요청, '목록 전부'로
  // 바꿨던 2026-08-26 기준을 되돌림). 순서는 화면 정렬·처리 구분 그대로.
  const rows = visibleItems.filter(it => it.picked);
  if (!rows.length) { window.A10_TOAST('내보낼 건을 체크하세요.', true); return; }
  const button = $('cvExport');
  button.disabled = true; button.textContent = '준비 중...';
  setMsg($('cvMsg'), '');
  try {
    const response = await fetch('/api/card-vouchers/export-prepare', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requester_usr_seq: usrSeq(),
        filename: $('cvFileName').textContent || '',
        items: rows,
      }),
    });
    const payload = await response.json();
    if (!payload.success) throw new Error(payload.message);
    window.A10_DOWNLOAD(`/api/card-vouchers/export.xlsx?token=${encodeURIComponent(payload.data.token)}`);
  } catch (error) {
    setMsg($('cvMsg'), error.message, 'err');
  } finally {
    button.textContent = '엑셀 내보내기';
    button.disabled = !visibleItems.some(it => it.picked);
  }
}

// ── 두 패널 사이 높이 조절 ───────────────────────────────────────
// 검증 목록과 확정된 전표 사이 경계를 끌면 위 표가 늘고 줄어든다. 조절값은
// 브라우저에 남아 다음에 열어도 유지된다 (더블클릭: 기본값).
function attachRowResizer() {
  const workspace = document.querySelector('.cv-split');
  const panels = workspace ? workspace.querySelectorAll(':scope > .list-panel') : [];
  if (panels.length < 2) return;
  const wrap = panels[0].querySelector('.table-wrap');
  if (!wrap) return;

  const KEY = 'a10.cardVouchers.listHeight';
  // 너무 줄이면 표가 사라지고, 너무 늘리면 아래 패널이 화면 밖으로 밀린다.
  const clamp = h => Math.min(Math.max(h, 120), Math.max(200, window.innerHeight - 240));
  const apply = h => { wrap.style.maxHeight = `${Math.round(h)}px`; };

  const handle = document.createElement('div');
  handle.className = 'cv-row-resizer';
  handle.title = '드래그해서 검증 목록 높이 조절 (더블클릭: 기본값)';
  workspace.insertBefore(handle, panels[1]);

  const saved = parseInt(localStorage.getItem(KEY) || '', 10);
  if (saved) apply(clamp(saved));

  handle.addEventListener('dblclick', () => {
    wrap.style.removeProperty('max-height');
    try { localStorage.removeItem(KEY); } catch (error) { /* 저장 못 해도 화면은 산다 */ }
  });
  handle.addEventListener('mousedown', event => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = wrap.getBoundingClientRect().height;
    handle.classList.add('dragging');
    document.body.style.cursor = 'row-resize';
    const onMove = moveEvent => apply(clamp(startHeight + moveEvent.clientY - startY));
    const onUp = () => {
      handle.classList.remove('dragging');
      document.body.style.removeProperty('cursor');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      try { localStorage.setItem(KEY, String(Math.round(wrap.getBoundingClientRect().height))); }
      catch (error) { /* 저장 실패는 무시 */ }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

attachRowResizer();
$('cvDraftSearch').addEventListener('click', loadDrafts);
// ── 인쇄: 내역분류/결재요청 ──────────────────────────────────────
// 재무팀 결재 양식(2026-08-20). 카드사로 묶고 그 안에서 카드번호로 묶은 뒤,
// 사용일자·승인시간 순으로 세운다. 묶음 칸은 rowspan 으로 한 번만 찍는다.
const cardCompanyOf = it => it.card_alias || it.card_partner_name || '(미상)';

function printGroups(rows) {
  const byCompany = new Map();
  rows.forEach(it => {
    const company = cardCompanyOf(it);
    if (!byCompany.has(company)) byCompany.set(company, new Map());
    const byCard = byCompany.get(company);
    const cardNo = it.card_no || '';
    if (!byCard.has(cardNo)) byCard.set(cardNo, []);
    byCard.get(cardNo).push(it);
  });
  const order = (a, b) =>
    String(a.use_date || '').localeCompare(String(b.use_date || '')) ||
    String(a.appr_time || '').localeCompare(String(b.appr_time || ''));
  return [...byCompany.keys()].sort((a, b) => a.localeCompare(b, 'ko')).map(company => {
    const byCard = byCompany.get(company);
    const cards = [...byCard.keys()].sort().map(cardNo => ({
      cardNo, items: byCard.get(cardNo).slice().sort(order),
    }));
    return { company, cards, count: cards.reduce((n, c) => n + c.items.length, 0) };
  });
}

const APPROVERS = ['담당', '차장', '팀장', '재무이사'];

function buildPrintHtml(rows) {
  const dates = rows.map(it => it.use_date).filter(Boolean).sort();
  const period = dates.length
    ? `${fmtUseDate(dates[0])} ~ ${fmtUseDate(dates[dates.length - 1])}` : '';
  const sum = key => rows.reduce((n, it) => n + Number(it[key] || 0), 0);

  const body = printGroups(rows).map(group => {
    let first = true;
    return group.cards.map(card => card.items.map((it, index) => {
      const companyCell = first
        ? `<td class="cv-group" rowspan="${group.count}">${esc(group.company)}</td>` : '';
      const cardCell = index === 0
        ? `<td class="cv-group" rowspan="${card.items.length}">${esc(card.cardNo)}</td>` : '';
      first = false;
      return `<tr>${companyCell}${cardCell}
        <td>${esc(it.user_name || '')}</td>
        <td>${esc(fmtUseDate(it.use_date))}</td>
        <td>${esc(it.appr_time || '')}</td>
        <td>${esc(it.industry || '')}</td>
        <td>${esc(it.merchant || '')}</td>
        <td class="number">${money.format(it.supply || 0)}</td>
        <td class="number">${money.format(it.vat || 0)}</td>
        <td class="number">${money.format(it.total || 0)}</td>
        <td>${esc(it.purpose || '')}</td>
        <td>${it.deductible ? '공제' : '미공제'}</td>
      </tr>`;
    }).join('')).join('');
  }).join('');

  return `<div class="cv-print-head">
      <div class="cv-print-title">
        <h1>내역분류/결재요청</h1>
        <p class="print-meta">조회기간 : ${esc(period)}</p>
      </div>
      <table class="cv-approve">
        <colgroup><col style="width:18px">${APPROVERS.map(() => '<col>').join('')}</colgroup>
        <tr><td class="cv-approve-label" rowspan="2">결<br>재</td>
          ${APPROVERS.map(name => `<th>${name}</th>`).join('')}</tr>
        <tr>${APPROVERS.map(() => '<td class="cv-approve-sign"></td>').join('')}</tr>
      </table>
    </div>
    <table>
      <thead><tr>
        <th>카드별칭</th><th>카드번호</th><th>사용자</th><th>사용일자</th><th>승인시간</th>
        <th>업종</th><th>가맹점</th><th class="number">공급가액</th><th class="number">부가세</th>
        <th class="number">승인금액</th><th>사용용도</th><th>공제대상</th>
      </tr></thead>
      <tbody>${body}</tbody>
      <tfoot><tr class="print-total">
        <td colspan="2">합 계</td>
        <td>${money.format(rows.length)}건</td>
        <td colspan="4"></td>
        <td class="number">${money.format(sum('supply'))}</td>
        <td class="number">${money.format(sum('vat'))}</td>
        <td class="number">${money.format(sum('total'))}</td>
        <td colspan="2"></td>
      </tr></tfoot>
    </table>`;
}

// 표 자연폭이 인쇄폭을 넘으면 zoom 으로 한 장에 맞춘다 (입금 현황과 같은 방식).
const PRINT_USABLE_WIDTH = 990;   // A4 가로 297mm − 여백 20mm ≈ 277mm @96dpi

function fitPrintZoom() {
  const area = $('printArea');
  const table = area.querySelector('table:last-of-type');
  if (!table) return;
  const prev = { display: area.style.display, position: area.style.position, left: area.style.left };
  Object.assign(area.style, { display: 'block', position: 'absolute', left: '-10000px' });
  table.style.zoom = '1';
  const natural = table.scrollWidth;
  table.style.zoom = natural > PRINT_USABLE_WIDTH
    ? (PRINT_USABLE_WIDTH / natural).toFixed(4) : '1';
  Object.assign(area.style, prev);
}

function printList() {
  // 체크한 건만 찍는다 (2026-08-20 사용자 요청) — 결재 올릴 것만 골라 인쇄한다.
  const rows = visibleItems.filter(it => it.picked);
  if (!rows.length) { window.A10_TOAST('인쇄할 건을 체크하세요.', true); return; }
  $('printArea').innerHTML = buildPrintHtml(rows);
  fitPrintZoom();
  // 브라우저가 인쇄 머리말에 document.title 을 찍는다 — 그 순간만 비운다.
  const pageTitle = document.title;
  document.title = ' ';
  try { window.print(); } finally { document.title = pageTitle; }
}

$('cvPrint').addEventListener('click', printList);
$('cvExport').addEventListener('click', exportRows);
$('cvSaveWork').addEventListener('click', () => saveWork(true));
$('cvUpload').addEventListener('click', upload);
$('cvFetchDb').addEventListener('click', fetchDb);
// 기본 조회 기간: 어제~오늘 (수집이 승인 다음날 들어오는 경우가 많다)
{
  const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const today = new Date(); const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  $('cvDbFrom').value = fmt(yesterday); $('cvDbTo').value = fmt(today);
  // 확정된 전표는 당일치부터 — 지난 것은 기간을 넓혀 본다
  $('cvDraftFrom').value = fmt(today); $('cvDraftTo').value = fmt(today);
  // 전표일자 기본값 = 오늘(작업일). 소급 입력할 때만 바꾼다.
  $('cvVoucherDate').value = fmt(today);
  $('cvVoucherDate').max = fmt(today);
}
$('cvCreateDraft').addEventListener('click', createDraft);
$('cvSend').addEventListener('click', sendDraft);
$('cvCancelDraft').addEventListener('click', cancelDraft);
$('cvVoucherDate').addEventListener('change', updateCreateButton);
$('cvDoneFilter').addEventListener('change', renderRows);
$('cvCheckAll').addEventListener('change', event => {
  // 화면에 보이는 건에서 정상구분 '취소' 만 뺀다. 처리된 건도 고른다 (2026-08-31:
  // 처리 구분을 '처리'로 두고 전체 선택 → 엑셀 내보내기가 되어야 한다 — 확정은
  // picked()가 걸러서 안전하다). 숨은 건은 건드리지 않는다.
  visibleItems.forEach(it => {
    if (it.canceled) return;
    it.picked = event.target.checked;
  });
  renderRows();
});

// ── 일괄변경: 체크한 행에 계정(사용용도)·공제를 한 번에 적용 ────────
PURPOSES.forEach(p => {
  const option = document.createElement('option');
  option.value = p; option.textContent = `계정 → ${p}`;
  $('cvBulkPurpose').appendChild(option);
});
$('cvBulkApply').addEventListener('click', () => {
  const purpose = $('cvBulkPurpose').value;
  const deduct = $('cvBulkDeduct').value;
  if (!purpose && !deduct) { setMsg($('cvBulkMsg'), '바꿀 항목(계정·공제)을 먼저 고르세요.', 'err'); return; }
  const targets = items.filter(it => it.picked && !it.processed_status);
  if (!targets.length) { setMsg($('cvBulkMsg'), '체크된 건이 없습니다.', 'err'); return; }
  targets.forEach(it => {
    if (purpose) {
      it.purpose = purpose;
      it.account_code = ACCOUNT_MAP[purpose] || '';
      reapplyRemarkSuffix(it);
      it.auto_purpose = false;   // 사람이 정한 값이면 '자동' 표시를 뗀다
    }
    if (deduct) it.deductible = deduct === '1';
    it.edited = true;
  });
  renderRows();
  const changed = [purpose && `계정 ${purpose}`, deduct && (deduct === '1' ? '공제' : '미공제')]
    .filter(Boolean).join(' · ');
  setMsg($('cvBulkMsg'), `${targets.length}건에 ${changed} 적용됨`, 'ok');
});

// 마지막 작업 복원은 서버 조회 없이 바로 한다 — 열자마자 하던 목록이 보여야 한다.
restoreWork();

// 사용자 확인이 끝난 뒤에 조회한다 (다른 화면과 동일).
window.A10_READY.then(() => loadDrafts().then(syncAmaranth));
