// 일계표 대사 (본사 재무 개별권한) — 사이버브랜치 입·출금 ↔ 아마란스 보통예금 전표.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const STATUS_TEXT = { MATCHED: '일치', TOTAL_ONLY: '합계 일치·건수 다름', DIFF: '차이', UNMAPPED: '매핑 필요' };
let lastData = null;
let opened = new Set();   // 펼쳐 둔 계좌 행 (다시 그려도 유지)

function showToast(msg, err) {
  const t = $('toast');
  if (!t) { alert(msg); return; }
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 4000);
}

function query() {
  return new URLSearchParams({
    date_from: $('dateFrom').value, date_to: $('dateTo').value, division: $('division').value || '',
  }).toString();
}

async function run() {
  if (!$('dateFrom').value || !$('dateTo').value) { showToast('거래일을 고르세요.', true); return; }
  $('runButton').disabled = true; $('exportButton').disabled = true;
  $('rows').innerHTML = '<tr><td colspan="11" class="br-hint">대사 중... (사이버브랜치·전표 캐시를 읽습니다)</td></tr>';
  try {
    const res = await fetch(`/api/bank-reconcile?${query()}`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    lastData = p.data;
    fillDivisions(p.data.division_totals);
    render(p.data);
    $('exportButton').disabled = false;
  } catch (e) {
    lastData = null;
    $('rows').innerHTML = `<tr><td colspan="11" class="br-hint">${esc(e.message)}</td></tr>`;
    $('summary').innerHTML = '';
  } finally {
    $('runButton').disabled = false;
  }
}

// 회계단위 선택지는 실제 전표에 나온 것으로 채운다 (지사 코드는 아마란스가 정한다)
function fillDivisions(totals) {
  const select = $('division');
  const current = select.value;
  const codes = new Set(['1000', ...totals.map(t => t.division_code)]);
  select.innerHTML = '<option value="">전체</option>' + [...codes].sort().map(code =>
    `<option value="${esc(code)}">${esc(code)}${code === '1000' ? ' 본사' : ''}</option>`).join('');
  select.value = [...codes].includes(current) ? current : (current === '' ? '' : current);
  if (select.value !== current) select.value = '';
}

function diffCell(n) {
  return `<td class="num ${n === 0 ? 'diff0' : 'diffx'}">${n === 0 ? '0' : money.format(n)}</td>`;
}

function render(d) {
  const s = d.summary;
  const good = s.mismatched === 0 && s.unmapped === 0;
  $('summary').innerHTML =
    `<span>전표 캐시 <b>${esc(d.synced_at || '—')}</b></span>` +
    `<span>계좌 <b>${s.accounts}</b></span>` +
    `<span class="${s.mismatched ? 'bad' : 'ok'}">차이 <b>${s.mismatched}</b></span>` +
    `<span class="muted">합계만 일치 <b>${s.total_only}</b></span>` +
    `<span class="${s.unmapped ? 'bad' : 'muted'}">매핑 필요 <b>${s.unmapped}</b></span>` +
    `<span>입금 은행 <b>${money.format(s.deposit.bank_total)}</b> / 전표 <b>${money.format(s.deposit.voucher_total)}</b> / 차이 <b class="${s.deposit.diff ? 'bad' : 'ok'}">${money.format(s.deposit.diff)}</b></span>` +
    `<span>출금 은행 <b>${money.format(s.withdrawal.bank_total)}</b> / 전표 <b>${money.format(s.withdrawal.voucher_total)}</b> / 차이 <b class="${s.withdrawal.diff ? 'bad' : 'ok'}">${money.format(s.withdrawal.diff)}</b></span>` +
    (good ? '<span class="ok">모두 일치</span>' : '');

  // 회계단위 소계 표는 뺐다(2026-08-26 사용자 결정) — 회계단위 선택지만 division_totals 로 채운다.
  renderRows(d);
  renderVoucherOnly(d.voucher_only || []);
}

function rowKey(r) { return `${r.day}|${r.bank_cd}|${r.acct_no}`; }

function renderRows(d) {
  const diffOnly = $('diffOnly').checked;
  const rows = d.rows.filter(r => !diffOnly || r.status !== 'MATCHED');
  $('rowsCount').textContent = `${rows.length}건`;
  if (!rows.length) {
    $('rows').innerHTML = `<tr><td colspan="11" class="br-hint">${d.rows.length ? '차이 나는 계좌가 없습니다 — 모두 일치' : '이 기간에 거래·전표가 없습니다.'}</td></tr>`;
    return;
  }
  $('rows').innerHTML = rows.map(r => {
    const key = rowKey(r);
    const acct = r.acct_no ? `${esc(r.nickname || '')} <span class="muted">…${esc(String(r.acct_no).slice(-4))}</span>` : esc(r.nickname || '');
    const main = `<tr class="acct" data-key="${esc(key)}">
      <td>${esc(r.day)}</td><td title="${esc(r.acct_no || '')}">${acct}</td>
      <td title="${esc(r.partner_code || '')}">${esc(r.partner_name || (r.mapped ? '' : '— 매핑 없음'))}</td>
      <td>${esc(r.divisions.join(', ') || '-')}</td>
      <td class="num">${money.format(r.deposit.bank_total)} <span class="muted">(${r.deposit.bank_count})</span></td>
      <td class="num">${money.format(r.deposit.voucher_total)} <span class="muted">(${r.deposit.voucher_count})</span></td>
      ${diffCell(r.deposit.diff)}
      <td class="num">${money.format(r.withdrawal.bank_total)} <span class="muted">(${r.withdrawal.bank_count})</span></td>
      <td class="num">${money.format(r.withdrawal.voucher_total)} <span class="muted">(${r.withdrawal.voucher_count})</span></td>
      ${diffCell(r.withdrawal.diff)}
      <td><span class="br-badge ${esc(r.status)}">${STATUS_TEXT[r.status] || r.status}</span>${(r.deposit.unapproved_count + r.withdrawal.unapproved_count) ? ' <span class="muted" title="미승인 전표줄">미승인</span>' : ''}</td>
    </tr>`;
    return main + (opened.has(key) ? `<tr class="detail"><td colspan="11">${detail(r)}</td></tr>` : '');
  }).join('');
  document.querySelectorAll('#rows tr.acct').forEach(tr => tr.addEventListener('click', () => {
    const key = tr.dataset.key;
    if (opened.has(key)) opened.delete(key); else opened.add(key);
    renderRows(lastData);
  }));
  const resize = window.A10_COLUMN_RESIZE;
  if (resize) resize($('rowsTable'), 'a10.bankReconcile.columnWidths');
}

const fmtTime = t => (t && t.length >= 4) ? `${t.slice(0, 2)}:${t.slice(2, 4)}` : '';

// 한 방향(입금↔차변 / 출금↔대변)의 상세 — 머리에 양쪽 합계·차이·상태, 아래에 남은 건을
// 은행 쪽·아마란스 쪽으로 나눠 머리글 있는 표로 보인다 (2026-08-26 사용자 요청: 한눈에 들어오게).
function sideCard(label, side) {
  const head = `<div class="br-side-head"><strong>${label}</strong>` +
    `<span>은행 <b>${side.bank_count}</b>건 · <b>${money.format(side.bank_total)}</b></span>` +
    `<span>전표 <b>${side.voucher_count}</b>건 · <b>${money.format(side.voucher_total)}</b></span>` +
    `<span class="${side.diff === 0 ? 'ok' : 'bad'}">차이 <b>${money.format(side.diff)}</b></span>` +
    `<span class="br-badge ${esc(side.status)}">${STATUS_TEXT[side.status] || side.status}</span></div>`;
  const bankRows = side.unmatched_bank.map(b =>
    `<tr><td class="t">${fmtTime(b.time)}</td><td>${esc(b.jeokyo)}</td><td class="muted">${esc(b.memo)}</td><td class="num">${money.format(b.amount)}</td></tr>`).join('');
  const lineRows = side.unmatched_lines.map(l =>
    `<tr><td class="t">${esc(l.voucher_no)}/${esc(l.line_no)}</td><td class="t">${esc(l.division_code)}</td>` +
    `<td>${esc(l.remark)}${l.approved ? '' : ' <span class="br-badge DIFF">미승인</span>'}</td><td class="muted">${esc(l.management_no)}</td><td class="num">${money.format(l.amount)}</td></tr>`).join('');
  const bankTable = bankRows ? `<h4>전표 없는 거래 <span>은행에만 있음 · ${side.unmatched_bank.length}건</span></h4>` +
    `<div class="br-mini-wrap"><table class="br-mini"><thead><tr><th class="t">시각</th><th>적요</th><th>메모</th><th class="num">금액</th></tr></thead><tbody>${bankRows}</tbody></table></div>` : '';
  const lineTable = lineRows ? `<h4>거래 없는 전표줄 <span>아마란스에만 있음 · ${side.unmatched_lines.length}건</span></h4>` +
    `<div class="br-mini-wrap"><table class="br-mini"><thead><tr><th class="t">전표/줄</th><th class="t">회계단위</th><th>적요</th><th>관리번호</th><th class="num">금액</th></tr></thead><tbody>${lineRows}</tbody></table></div>` : '';
  const none = !bankRows && !lineRows ? '<div class="br-none">남는 건 없음 — 전부 짝지어졌습니다</div>' : '';
  const note = side.status === 'TOTAL_ONLY'
    ? '<div class="br-note">합계는 같고 건수만 다릅니다 — 은행 여러 건이 전표 한 줄로(또는 그 반대) 기표된 것이라 오류가 아닙니다.</div>' : '';
  const kinds = side.pairs.reduce((acc, p) => { acc[p.kind] = (acc[p.kind] || 0) + 1; return acc; }, {});
  const pairs = side.pairs.length
    ? `<div class="br-pairs">짝지음 ${side.pairs.length}묶음 · 배치 묶음 ${kinds.bundle || 0} · 1:1 ${kinds.exact || 0} · 소집합 ${kinds.group || 0}</div>` : '';
  return `<section class="br-side ${esc(side.status)}">${head}${note}${none}${bankTable}${lineTable}${pairs}</section>`;
}

function detail(r) {
  const cancelled = (r.cancelled || []).length
    ? `<div class="br-cancel">취소로 상쇄된 입·출금 ${r.cancelled.length}쌍 (${r.cancelled.map(c => money.format(c.amount)).join(', ')}) — 전표 없는 게 맞습니다</div>` : '';
  return `<div class="br-detail">${cancelled}${sideCard('입금 ↔ 차변', r.deposit)}${sideCard('출금 ↔ 대변', r.withdrawal)}</div>`;
}

function renderVoucherOnly(items) {
  $('voucherOnlyCount').textContent = items.length ? `${items.length}건` : '없음';
  $('voucherOnly').innerHTML = items.length ? items.map(v =>
    `<tr><td>${esc(v.day)}</td><td title="${esc(v.partner_code)}">${esc(v.partner_name)}</td><td>${esc(v.divisions.join(', '))}</td>` +
    `<td class="num">${v.deposit_count}</td><td class="num">${money.format(v.deposit_total)}</td>` +
    `<td class="num">${v.withdrawal_count}</td><td class="num">${money.format(v.withdrawal_total)}</td></tr>`).join('')
    : '<tr><td colspan="7" class="br-hint">없음</td></tr>';
}

function exportXlsx() {
  if (!lastData) return;
  window.A10_DOWNLOAD(`/api/bank-reconcile/export.xlsx?${query()}`);
}

function defaultDates() {
  const d = new Date(); d.setDate(d.getDate() - 1);      // 기본은 전일
  const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  $('dateFrom').value = iso; $('dateTo').value = iso;
}

$('runButton').addEventListener('click', run);
$('exportButton').addEventListener('click', exportXlsx);
$('diffOnly').addEventListener('change', () => { if (lastData) renderRows(lastData); });
$('voucherOnlyToggle').addEventListener('click', () => {
  const card = $('voucherOnlyCard');
  card.classList.toggle('br-collapsed');
  $('voucherOnlyToggle').textContent = card.classList.contains('br-collapsed') ? '펼치기' : '접기';
});
defaultDates();

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('rows').innerHTML = '<tr><td colspan="11" class="br-hint">일계표 대사는 본사만 사용할 수 있습니다.</td></tr>';
    document.querySelector('.toolbar').classList.add('hidden');
    return;
  }
  run();
});
