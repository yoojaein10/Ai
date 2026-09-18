// 계정별원장 (본사 전용) — 지사 계정 원장을 뽑아 메일로 보낸다.
// 지금은 출력해서 팩스로 보내던 일이다 (2026-08-21 사용자 요청).
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const inputDate = d => { const o = d.getTimezoneOffset() * 60000; return new Date(d - o).toISOString().slice(0, 10); };

let accounts = [];
let lastPreview = null;
// 계정 → 담당자 목록. 왼쪽 목록에 '담당자 n' 을 붙이고, 발송 전에 빈 지사를 알린다.
let recipients = {};

// 본사(1410001)·본지점 손익(1410017)은 지사에 보낼 것이 아니라 기본으로 안 고른다.
const SEND_SKIP = new Set(['1410001', '1410017']);

const toCount = code => (recipients[code] || []).filter(p => p.kind === 'TO').length;

function renderAccounts() {
  $('accountList').innerHTML = accounts.map(a => {
    const n = toCount(a.account_code);
    // 담당자 수는 보여만 준다 — 고치는 곳은 위의 '관리' 버튼 하나다.
    const who = SEND_SKIP.has(a.account_code) ? ''
      : `<span class="who${n ? '' : ' none'}">${n ? `담당자 ${n}` : '담당자 없음'}</span>`;
    return `
    <label data-code="${esc(a.account_code)}">
      <input type="checkbox" class="acct" value="${esc(a.account_code)}"${SEND_SKIP.has(a.account_code) ? '' : ' checked'}>
      <span class="code">${esc(a.account_code)}</span>
      <span>${esc(a.account_name || '-')}</span>${who}
    </label>`;
  }).join('');
  document.querySelectorAll('#accountList label').forEach(label => {
    const box = label.querySelector('input');
    const paint = () => label.classList.toggle('on', box.checked);
    paint();
    box.addEventListener('change', () => { paint(); updateSummary(); });
    // 글자를 누르면 미리보기가 뜬다 — 체크는 발송 대상, 클릭은 확인용으로 나눈다.
    label.addEventListener('click', event => {
      if (event.target === box) return;
      event.preventDefault();
      showView('ledger');
      preview(label.dataset.code);
    });
  });
  updateSummary();
}

const picked = () => Array.from(document.querySelectorAll('#accountList .acct:checked')).map(c => c.value);

function updateSummary() {
  const codes = picked();
  const missing = codes.filter(c => !toCount(c)).length;
  const warn = missing ? ` · 담당자 없는 계정 <b style="color:#b4232a">${money.format(missing)}</b>개` : '';
  $('summary').innerHTML = `계정 <b>${money.format(accounts.length)}</b>개 · 발송 대상 <b>${money.format(codes.length)}</b>개${warn}`;
}

async function loadAccounts() {
  try {
    const res = await fetch('/api/account-ledger/accounts');
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    accounts = p.data.items || [];
    renderAccounts();
  } catch (e) {
    $('summary').textContent = '계정을 불러오지 못했습니다: ' + e.message;
  }
}

async function preview(code) {
  const from = $('dateFrom').value, to = $('dateTo').value;
  if (!from || !to) { showToast('기간을 고르세요.', true); return; }
  $('preview').className = 'ph';
  $('preview').textContent = '불러오는 중...';
  try {
    const res = await fetch(`/api/account-ledger?account_code=${encodeURIComponent(code)}`
      + `&date_from=${from}&date_to=${to}&fmt=html`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    lastPreview = code;
    $('preview').className = '';
    // 전기이월이 없으면 전일이월이 0 에서 시작해 원장이 통째로 틀린다. 숫자만
    // 보면 알 수 없으므로 눈에 띄게 세워 둔다 — 발송도 서버가 막는다.
    const year = (p.data.carry_from || '').slice(0, 4);
    const warn = p.data.opening && p.data.opening.known ? '' :
      `<p class="al-warn">${year}년 전기이월이 없습니다 — 전일이월이 틀립니다.`
      + ' 이 계정은 발송되지 않습니다.</p>';
    $('preview').innerHTML = warn + p.data.html;
  } catch (e) {
    $('preview').className = 'ph';
    $('preview').textContent = '불러오지 못했습니다: ' + e.message;
  }
}

// ── 보기 전환 ───────────────────────────────────────────────────────────
const PANES = { ledger: 'paneLedger', logs: 'paneLogs' };
const TABS = { logs: 'viewLogs' };

function showView(view) {
  Object.entries(PANES).forEach(([k, id]) => $(id).classList.toggle('hidden', k !== view));
  Object.entries(TABS).forEach(([k, id]) => $(id).classList.toggle('on', k === view));
}

// ── 지사별 담당자 ───────────────────────────────────────────────────────
async function loadRecipients() {
  try {
    const res = await fetch('/api/account-ledger/recipients');
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    recipients = {};
    (p.data.items || []).forEach(person => {
      (recipients[person.account_code] = recipients[person.account_code] || []).push(person);
    });
  } catch (e) {
    showToast('담당자를 불러오지 못했습니다: ' + e.message, true);
  }
}

// ── 발송 로그 ───────────────────────────────────────────────────────────
async function loadLogs() {
  showView('logs');
  const body = $('logRows');
  body.innerHTML = '<tr><td colspan="7">불러오는 중...</td></tr>';
  try {
    const res = await fetch('/api/account-ledger/logs?limit=200');
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    const items = p.data.items || [];
    $('logScope').textContent = `${money.format(items.length)}건`;
    body.innerHTML = items.length ? items.map(log => `
      <tr>
        <td>${esc(log.sent_at)}</td>
        <td>${esc(log.account_code)} ${esc(log.account_name)}</td>
        <td>${esc(log.period.from)} ~ ${esc(log.period.to)}</td>
        <td>${esc(log.to_email || '-')}</td>
        <td>${esc(log.cc_email || '-')}</td>
        <td class="num">${money.format(log.item_count)}</td>
        <td class="${log.status === 'SENT' ? (log.test_mode ? 'test' : 'ok') : 'bad'}">
          ${log.status === 'SENT' ? (log.test_mode ? '테스트' : '보냄') : '실패'}
          ${log.fail_reason ? `<span style="font-weight:400;color:var(--muted)"> — ${esc(log.fail_reason)}</span>` : ''}
        </td>
      </tr>`).join('') : '<tr><td colspan="7">보낸 기록이 없습니다.</td></tr>';
  } catch (e) {
    body.innerHTML = `<tr><td colspan="7">불러오지 못했습니다: ${esc(e.message)}</td></tr>`;
  }
}

async function sendMail() {
  const codes = picked();
  if (!codes.length) { showToast('보낼 계정을 고르세요.', true); return; }
  const from = $('dateFrom').value, to = $('dateTo').value;
  if (!from || !to) { showToast('기간을 고르세요.', true); return; }
  const override = $('mailTo').value.trim();
  // 담당자가 없는 지사는 나가지 않는다 — 보내고 나서 알면 늦다.
  const missing = override ? [] : codes.filter(c => !toCount(c));
  const warn = missing.length
    ? `\n담당자가 없어 빠지는 계정 ${missing.length}개: ${missing.join(', ')}` : '';
  const target = override ? `\n받는 사람: ${override} (직접 지정)` : '\n받는 사람: 지사별 담당자';
  if (!confirm(`${codes.length}개 계정의 원장을 메일로 보냅니다.\n기간 ${from} ~ ${to}${target}${warn}\n진행할까요?`)) return;
  const button = $('sendButton');
  button.disabled = true; button.textContent = '보내는 중...';
  try {
    const res = await fetch('/api/account-ledger/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requester_usr_seq: Number((window.A10_CTX || {}).usr_seq || 0),
        date_from: from, date_to: to, accounts: codes, to: override,
      }),
    });
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    showToast(p.message);
    // 로그를 보고 있었으면 방금 보낸 것이 바로 보여야 한다.
    if (!$('paneLogs').classList.contains('hidden')) loadLogs();
  } catch (e) {
    showToast(e.message, true);
  } finally {
    button.disabled = false; button.textContent = '선택 계정 메일 발송';
  }
}

function showToast(msg, err) {
  const t = $('toast');
  if (!t) { alert(msg); return; }
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 5000);
}

// 매일 보내는 것이라 기본 기간은 **전날 하루**다 (2026-08-21 사용자 확인).
// 오늘 것은 전표가 아직 다 안 들어와 있어 보내면 빠진 채로 나간다.
const yesterday = new Date();
yesterday.setDate(yesterday.getDate() - 1);
$('dateFrom').value = inputDate(yesterday);
$('dateTo').value = inputDate(yesterday);
$('searchButton').addEventListener('click', () => { showView('ledger'); if (lastPreview) preview(lastPreview); });
$('viewLogs').addEventListener('click', loadLogs);
$('sendButton').addEventListener('click', sendMail);
// 지사 메일 주소를 고치거나 추가하는 곳. 보고 있던 계정이 있으면 그 지사로 데려간다.
$('manageButton').addEventListener('click', () => {
  location.href = '/desktop/ledger-recipients'
    + (lastPreview ? '?account=' + encodeURIComponent(lastPreview) : '');
});
$('checkAll').addEventListener('change', () => {
  document.querySelectorAll('#accountList .acct').forEach(c => { c.checked = $('checkAll').checked; });
  document.querySelectorAll('#accountList label').forEach(l =>
    l.classList.toggle('on', l.querySelector('input').checked));
  updateSummary();
});

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('summary').textContent = '계정별원장은 본사만 사용할 수 있습니다.';
    document.querySelector('.toolbar').classList.add('hidden');
    return;
  }
  // 담당자를 먼저 읽어야 계정 목록에 '담당자 없음'이 바로 뜬다.
  loadRecipients().then(loadAccounts);
});
