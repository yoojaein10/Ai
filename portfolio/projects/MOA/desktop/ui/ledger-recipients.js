// 지사 메일 주소 관리 (본사 전용) — 계정별원장이 나갈 주소를 지사별로 적어 둔다.
// 계정별원장 화면 오른쪽 위 버튼으로 들어온다 (2026-08-24 사용자 요청).
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const MAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// 본사(1410001)·본지점 손익(1410017)은 지사에 보낼 계정이 아니라 여기 없다.
const SEND_SKIP = new Set(['1410001', '1410017']);

let accounts = [];
let recipients = {};        // 계정 → 담당자 목록
const dirty = new Set();    // 고친 계정만 저장한다

function markDirty(code) {
  dirty.add(code);
  const card = document.querySelector(`.lr-acct[data-code="${code}"]`);
  if (card) card.classList.add('dirty');
  updateSummary();
}

function updateSummary() {
  const none = accounts.filter(a => !toCount(a.account_code)).length;
  const warn = none ? ` · 주소 없는 지사 <b class="none">${money.format(none)}</b>곳` : '';
  const pending = dirty.size ? ` · 저장 안 한 지사 <b>${money.format(dirty.size)}</b>곳` : '';
  $('summary').innerHTML = `지사 <b>${money.format(accounts.length)}</b>곳${warn}${pending}`;
}

const toCount = code => (recipients[code] || []).filter(p => p.kind === 'TO').length;

function personRow(code, person) {
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="r-name" maxlength="60" value="${esc(person.name || '')}" placeholder="담당자"></td>
    <td><input class="r-email" type="email" maxlength="200" value="${esc(person.email || '')}" placeholder="contact@example.com"></td>
    <td><select class="r-kind">
      <option value="TO"${person.kind === 'CC' ? '' : ' selected'}>받는사람</option>
      <option value="CC"${person.kind === 'CC' ? ' selected' : ''}>참조</option>
    </select></td>
    <td><input class="r-memo" maxlength="200" value="${esc(person.memo || '')}" placeholder="메모"></td>
    <td><button type="button" class="del" title="빼기">×</button></td>`;
  row.querySelectorAll('input, select').forEach(field =>
    field.addEventListener('input', () => markDirty(code)));
  row.querySelector('.del').addEventListener('click', () => { row.remove(); markDirty(code); });
  return row;
}

function accountCard(account) {
  const code = account.account_code;
  const card = document.createElement('section');
  card.className = 'lr-acct';
  card.dataset.code = code;
  const n = toCount(code);
  card.innerHTML = `
    <div class="lr-head">
      <span class="code">${esc(code)}</span>
      <h3>${esc(account.account_name || '-')}</h3>
      <span class="state${n ? '' : ' none'}">${n ? `받는사람 ${n}명` : '주소 없음 — 발송되지 않습니다'}</span>
      <button type="button" class="add">담당자 추가</button>
    </div>
    <table class="lr-rows">
      <thead><tr><th style="width:18%">이름</th><th style="width:34%">메일 주소</th><th style="width:14%">구분</th><th>메모</th><th style="width:44px"></th></tr></thead>
      <tbody></tbody>
    </table>`;
  const body = card.querySelector('tbody');
  (recipients[code] || []).forEach(person => body.appendChild(personRow(code, person)));
  if (!body.children.length) body.appendChild(personRow(code, { kind: 'TO' }));
  card.querySelector('.add').addEventListener('click', () => {
    body.appendChild(personRow(code, { kind: 'TO' }));
    markDirty(code);
  });
  return card;
}

function render() {
  const list = $('accountList');
  list.innerHTML = '';
  accounts.forEach(account => list.appendChild(accountCard(account)));
  updateSummary();
}

function readRows(code) {
  const card = document.querySelector(`.lr-acct[data-code="${code}"]`);
  return Array.from(card.querySelectorAll('tbody tr')).map(row => ({
    name: row.querySelector('.r-name').value.trim(),
    email: row.querySelector('.r-email').value.trim(),
    kind: row.querySelector('.r-kind').value,
    memo: row.querySelector('.r-memo').value.trim(),
  })).filter(person => person.email);
}

async function saveAll() {
  if (!dirty.size) { showToast('바뀐 것이 없습니다.'); return; }
  // 주소가 하나라도 틀리면 그 지사만 조용히 빠진다 — 저장 전에 다 본다.
  for (const code of dirty) {
    const bad = readRows(code).find(person => !MAIL.test(person.email));
    if (bad) { showToast(`${code} 메일 주소를 확인하세요: ${bad.email}`, true); return; }
  }
  const button = $('saveAll');
  button.disabled = true; button.textContent = '저장 중...';
  const failed = [];
  try {
    for (const code of Array.from(dirty)) {
      const res = await fetch(`/api/account-ledger/recipients/${encodeURIComponent(code)}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          requester_usr_seq: Number((window.A10_CTX || {}).usr_seq || 0),
          office_id: '', people: readRows(code),
        }),
      });
      const p = await res.json();
      if (!p.success) { failed.push(`${code}: ${p.message}`); continue; }
      recipients[code] = p.data.items || [];
      dirty.delete(code);
    }
    render();
    showToast(failed.length ? `저장 실패 ${failed.length}곳 — ${failed[0]}` : '저장했습니다.',
      failed.length > 0);
  } catch (e) {
    showToast(e.message, true);
  } finally {
    button.disabled = false; button.textContent = '변경 저장';
  }
}

async function load() {
  try {
    const [accountRes, recipientRes] = await Promise.all([
      fetch('/api/account-ledger/accounts'),
      fetch('/api/account-ledger/recipients'),
    ]);
    const accountPayload = await accountRes.json();
    const recipientPayload = await recipientRes.json();
    if (!accountPayload.success) throw new Error(accountPayload.message);
    if (!recipientPayload.success) throw new Error(recipientPayload.message);
    accounts = (accountPayload.data.items || []).filter(a => !SEND_SKIP.has(a.account_code));
    recipients = {};
    (recipientPayload.data.items || []).forEach(person => {
      (recipients[person.account_code] = recipients[person.account_code] || []).push(person);
    });
    render();
    // 계정별원장에서 특정 지사를 눌러 들어오면 그 지사로 데려간다.
    const wanted = new URLSearchParams(location.search).get('account');
    const card = wanted && document.querySelector(`.lr-acct[data-code="${wanted}"]`);
    if (card) {
      card.scrollIntoView({ block: 'center' });
      card.querySelector('.r-email').focus();
    }
  } catch (e) {
    $('summary').textContent = '불러오지 못했습니다: ' + e.message;
  }
}

function showToast(msg, err) {
  const t = $('toast');
  if (!t) { alert(msg); return; }
  t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
  clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 5000);
}

// 저장하지 않고 나가면 적어 둔 주소가 사라진다 — 한 번 잡아 준다.
window.addEventListener('beforeunload', event => {
  if (!dirty.size) return;
  event.preventDefault();
  event.returnValue = '';
});

$('saveAll').addEventListener('click', saveAll);

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('summary').textContent = '지사 메일 주소는 본사만 관리할 수 있습니다.';
    $('saveAll').classList.add('hidden');
    return;
  }
  load();
});
