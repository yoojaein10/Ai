// 일괄권한(역할) 관리 화면.
//
// 이름을 붙인 권한 한 벌을 만들어 두고, 권한관리 화면에서 부서·사람에 붙인다.
// 일괄권한은 **참조**라 고치면 쓰는 곳이 함께 바뀐다 — 그래서 이름 옆에 '쓰는 곳
// N군데' 를 늘 보여 주고, 쓰는 곳이 있으면 삭제를 막는다(서버도 막는다).
//
// 메뉴 이름은 권한관리 화면(permissions-preview.js)의 menuGroups 와 같은 것을
// 써야 두 화면이 같은 말을 한다. 지금은 그 파일이 상수를 안 내보내므로 여기에
// 같은 뜻으로 다시 적되, **키는 서버가 준 menu_keys 를 기준**으로 그린다 —
// 메뉴가 늘면 이름 없이라도 키가 뜨게 해서 조용히 빠지는 일이 없게 한다.

const $ = id => document.getElementById(id);

const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
}[c]));

const MENU_NAMES = {
  appraisals: '감정서 LIST',
  payments: '입금 현황',
  receivables: '미수금 현황',
  paymentSms: '입금발송내역',
  allocation: '배분 수금 진행',
  salesStats: '기간별 매출실적',
  workReport: '업무실적 보고',
  feeBasis: '보수기준 점검',
  salesInput: '유치실적',
  bonus: '상여',
  mySales: '개인별 매출실적',
  cardVouchers: '카드전표',
  receivableReconcile: '외상매출금 반제',
  advanceReconcile: '선수금 반제',
  accountLedger: '지사별원장',
  bankReconcile: '일계표 대사',
  shinhanDelay: '신한 발송기한',
  taxBulk: '계산서 등록',
  travelExpense: '출장비',
  dataQuality: '데이터 품질 점검',
  depositMatch: '입금 대사',
  reconcile: '엑셀 대사',
  permissionManage: '권한 관리',
};

// 메뉴 19개를 한 판에 깔면 담당자가 아는 단위로 고를 수가 없다. '수금 쪽만 주자'
// 같은 판단이 이 화면의 실제 일인데, 그러려면 어느 것이 수금인지 눈으로 묶여야
// 한다. 일괄권한과 순서는 **사이드바(context.js A10_MENU)를 그대로** 따른다 —
// 담당자가 사이드바에서 본 자리 그대로 여기서도 찾게 하려는 것이다.
// (tests/test_permission_menu_names.py 가 이름이 갈리지 않게 지킨다.)
// 아이콘 한 글자·설명은 권한관리(permissions-preview.js menuGroups)와 같은 뜻으로
// 적는다 — 두 화면이 **같은 모양·같은 말**이어야 덜 헷갈린다(2026-08-18). 이름은
// MENU_NAMES 를 쓰고(test_permission_menu_names 가 지킨다), 여기선 short·desc 만 둔다.
const MENU_GROUPS = [
  {name: '업무', items: [
    {key: 'appraisals', short: '감', desc: '감정서 조회 및 진행상태 확인'},
  ]},
  {name: '입금·미수', items: [
    {key: 'payments', short: '입', desc: '입금 내역과 수금 현황 조회'},
    {key: 'paymentSms', short: '문', desc: '입금 알림톡 발송 내역(발송은 본사만)'},
    {key: 'receivables', short: '미', desc: '미수금 잔액과 경과 현황 조회'},
    {key: 'allocation', short: '배', desc: '배분과 수금 진행상태 확인'},
    {key: 'bankReconcile', short: '계', desc: '사이버브랜치 입·출금과 아마란스 보통예금 전표 대사'},
    {key: 'shinhanDelay', short: '신', desc: '신한은행 발송기한(접수 후 4영업일) 관리 — 메뉴 밖 독립 화면'},
    {key: 'taxBulk', short: '일', desc: '입금 건 세금계산서 일괄 발급(일반·대주단·국민약식)'},
  ]},
  {name: '매출·실적', items: [
    {key: 'travelExpense', short: '출', desc: '출장비 입력·결재·월별 현황(APWorks 출장비프로그램 이식, 본사)'},
    {key: 'salesStats', short: '실', desc: '기간·부서별 매출 집계'},
    {key: 'workReport', short: '업', desc: '업무실적 집계 보고'},
    {key: 'feeBasis', short: '보', desc: '보수기준 적용 점검'},
    {key: 'salesInput', short: '유', desc: '유치실적 배분·승인 입력'},
    {key: 'bonus', short: '상', desc: '상여 산정·조정 입력'},
    {key: 'mySales', short: '개', desc: '개인별 매출 대시보드'},
  ]},
  {name: '카드·반제', items: [
    {key: 'cardVouchers', short: '카', desc: '카드 명세서로 전표 생성·전송'},
    {key: 'receivableReconcile', short: '외', desc: '외상매출금 반제 내역 확인'},
    {key: 'advanceReconcile', short: '선', desc: '선수금 반제 내역 확인'},
  ]},
  {name: '관리·점검', items: [
    {key: 'accountLedger', short: '원', desc: '지사 계정 원장 조회·메일 발송'},
    {key: 'dataQuality', short: '품', desc: '누락·불일치 데이터 점검'},
    {key: 'depositMatch', short: '대', desc: '입금 건을 감정서에 맞춰 보는 대사'},
    {key: 'reconcile', short: '엑', desc: '회계 자료와 전표 엑셀 대사'},
    {key: 'permissionManage', short: '권', desc: '사용자별 조회범위·메뉴 권한 관리'},
  ]},
];

/** 서버가 준 키를 그룹에 나눠 담는다(아이템 구조). 어느 그룹에도 없는 키는
 *  '기타'로 모은다 — 조용히 사라지면 그 권한은 화면에서 줄 수 없게 된다. */
function groupedMenuItems(keys) {
  const rest = new Set(keys);
  const groups = MENU_GROUPS
    .map(group => ({
      ...group,
      items: group.items.filter(item => rest.delete(item.key) || false),
    }))
    .filter(group => group.items.length);
  if (rest.size) {
    groups.push({name: '기타', items: [...rest].map(k => ({key: k, short: (MENU_NAMES[k] || k).slice(0, 1), desc: ''}))});
  }
  return groups;
}

let roles = [];
// 부서 저장·일괄권한 삭제가 만드는 **숨김 자동일괄권한**의 표식(access_roles.py AUTO_ROLE_MEMO
// 와 같은 문자열). 부서 전용 복사본이라 담당자가 템플릿으로 다룰 것이 아니므로
// 이 목록에서 감춘다 — 권한관리 화면(namedPresets)도 같은 문자열로 거른다.
const AUTO_ROLE_MEMO = '부서 권한 화면에서 만든 묶음';
// 적용 대상·스코프 데이터는 2026-08-18 걷어냈다 — 붙이기와 조회 범위는
// 권한관리 화면으로 옮겼다(일괄권한은 메뉴만 정한다).
let menuKeys = [];
let editing = null;      // null = 편집 안 함, {role_id:null} = 새로 만들기
// 편집칸을 연 순간의 값. 목록을 잘못 눌렀을 때 체크 19개를 다시 찍지 않게 한다.
let snapshot = null;

/** 편집칸을 연 뒤 값이 바뀌었나. */
function isDirty() {
  if (!editing || snapshot === null) return false;
  return JSON.stringify(collect()) !== snapshot;
}

/** 저장 안 한 변경을 버려도 되는지 묻는다. 버려도 되면 true.
 *
 *  체크박스 19개를 손보다 목록을 잘못 누르면 경고 한 번 없이 값이 통째로
 *  날아갔다. 되돌릴 방법이 없어 처음부터 다시 찍는 수밖에 없었다. */
function confirmDiscard() {
  if (!isDirty()) return true;
  return window.confirm('저장하지 않은 변경이 있습니다.\n버리고 이동할까요?');
}

async function load() {
  const res = await fetch('/api/permissions/roles');
  if (!res.ok) {
    $('roleList').innerHTML = '<li class="empty">권한이 없거나 불러오지 못했습니다.</li>';
    return;
  }
  const body = await res.json();
  // 자동(복사본) 일괄권한은 담당자가 다룰 템플릿이 아니라 숨긴다.
  roles = ((body.data && body.data.items) || [])
    .filter(role => role.memo !== AUTO_ROLE_MEMO);
  menuKeys = (body.data && body.data.menu_keys) || [];
  paintList();
}

function paintList() {
  const list = $('roleList');
  const count = $('roleCount');
  if (count) count.textContent = roles.length ? `${roles.length}개` : '';
  if (!roles.length) {
    // 표가 아직 없을 때도 여기로 온다 — 서버가 빈 목록을 준다.
    list.innerHTML = '<li class="empty">일괄권한이 없습니다.</li>';
    return;
  }
  list.innerHTML = roles.map(role => {
    const on = Boolean(editing && editing.role_id === role.role_id);
    // 목록은 전부 로그인 소속의 일괄권한이라(공용 없는 지사별 일괄권한, 소속은 로그인으로 정해짐)
    // 행마다 소속을 적을 필요가 없다. 고른 상태가 클래스에만 있으면 낭독기에 안 들린다.
    return `<li><button type="button" class="role-item${on ? ' on' : ''}"
      data-id="${role.role_id}" aria-pressed="${on ? 'true' : 'false'}"${
      on ? ' aria-current="true"' : ''}>
      <b>${escapeHtml(role.name)}</b>
      <span class="count">메뉴 ${role.menu_keys.length}개</span>
    </button></li>`;
  }).join('');
  list.querySelectorAll('.role-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const role = roles.find(r => String(r.role_id) === btn.dataset.id);
      if (!role || role.role_id === (editing && editing.role_id)) return;
      if (!confirmDiscard()) return;
      openEditor(role);
    });
  });
}

// loadTargetsData·renderTargets·applyTargets 등 적용대상 코드는 2026-08-18
// 걷어냈다. 일괄권한을 부서·사람에 붙이는 일은 권한관리 화면에서 한다.

// 소속 선택칸은 2026-08-18 뺐다 — 소속은 로그인 계정으로 정해진다(서버가 강제).

function openEditor(role, focusForm = true) {
  editing = role;
  $('editorEmpty').hidden = true;
  $('editorEmptyMsg').textContent = '';
  $('roleEditor').hidden = false;
  // 폼에 이름이 없으면 낭독기에는 오른쪽에 무엇이 열렸는지 안 들린다.
  $('editorTitle').textContent = role.role_id ? (role.name || '이름 없는 일괄권한') : '새 일괄권한';
  $('roleName').value = role.name || '';
  // 조회 범위 토글 — 개인내역조회는 모두, **전체지사조회는 본사 로그인일 때만** 편다
  // (지사는 전지사조회를 가질 수 없다, 2026-08-18 사용자 요청). 소속은 로그인 계정.
  const headLogin = String((window.A10_CTX || {}).office_id || '10') === '10';
  const secAll = $('roleViewAllSection');
  if (secAll) secAll.hidden = !headLogin;
  $('roleViewAll').checked = headLogin && role.view_all_offices === true;
  $('roleViewOther').checked = role.view_other_users === true;
  const used = role.used_by || {departments: 0, users: 0};
  const total = (used.departments || 0) + (used.users || 0);
  // 자잘한 안내 문구는 뺐다(2026-08-18 사용자 요청). 쓰는 곳이 있을 때만 숫자로
  // 알린다 — 삭제·수정이 몇 군데에 닿는지가 이 화면에서 유일하게 필요한 사실이다.
  $('roleUsage').textContent = total
    ? `부서 ${used.departments || 0}곳 · 개인 ${used.users || 0}명에 붙어 있습니다.`
    : '';
  $('deleteRole').hidden = !role.role_id;
  const checked = new Set(role.menu_keys || []);
  const source = menuKeys.length ? menuKeys : Object.keys(MENU_NAMES);
  // 권한관리(permissions-preview) 와 **같은 행 구조**로 그린다: 아이콘 + 제목 +
  // 설명 + 토글. 일괄권한은 템플릿이라 모든 메뉴가 선택 가능하다(정책 배지·잠금 없음).
  $('menuChecks').innerHTML = groupedMenuItems(source).map(group => `
    <section class="menu-permission-group${group.muted ? ' muted' : ''}">
      <header class="menu-group-heading">
        <h4>${escapeHtml(group.name)}</h4>
        <span data-group-count="${escapeHtml(group.name)}"></span>
      </header>
      <div>
        ${group.items.map(item => `<label class="menu-permission-row${checked.has(item.key) ? ' allowed' : ''}">
          <span class="menu-row-icon">${escapeHtml(item.short)}</span>
          <span class="menu-row-copy">
            <span class="menu-row-title"><strong>${escapeHtml(MENU_NAMES[item.key] || item.key)}</strong></span>
          </span>
          <span class="inline-switch">
            <input class="menu-permission-toggle" type="checkbox"
              data-menu-key="${escapeHtml(item.key)}"${checked.has(item.key) ? ' checked' : ''}>
            <i class="switch-control"></i>
          </span>
        </label>`).join('')}
      </div>
    </section>`).join('');
  paintMenuCount();
  // 지금 값을 기준점으로 찍어 둔다. collect() 와 같은 모양이어야 비교가 맞으므로
  // 그 함수를 그대로 쓴다 — 비교 기준을 따로 만들면 둘이 갈라진다.
  snapshot = JSON.stringify(collect());
  const msg = $('roleMsg');
  msg.textContent = '';
  // className 까지 되돌린다 — 안 그러면 직전 실패의 빨강이 다음 문구에 남는다.
  msg.className = 'msg';
  paintList();
  // 목록을 innerHTML 로 통째로 갈아 끼우면 포커스가 사라진 노드와 함께 body 로
  // 떨어진다. 새 일괄권한은 바로 이름부터 적게, 기존 일괄권한은 폼 제목으로 옮겨
  // 키보드 사용자가 오른쪽에 무엇이 열렸는지 알게 한다. 저장 직후에는
  // 누르던 자리를 지키는 편이 나아서 호출 쪽에서 false 로 끈다.
  if (focusForm) (role.role_id ? $('roleEditor') : $('roleName')).focus();
}

// 켠 개수가 폼 안에 없어서 '이 일괄권한이 몇 개를 켜고 있는지' 를 목록으로 돌아가야
// 알 수 있었다. 헤딩 옆에 붙여 고르는 중에도 보이게 한다.
// 메뉴 토글만 고른다(.menu-permission-toggle). data-menu-key 로 어느 메뉴인지 안다.
const menuBoxes = () => $('menuChecks').querySelectorAll('.menu-permission-toggle');

function paintMenuCount() {
  const boxes = Array.from(menuBoxes());
  const on = boxes.filter(box => box.checked).length;
  const label = $('menuCount');
  if (label) {
    label.textContent = `${on} / ${boxes.length} 허용`;
    // 메뉴 0개는 '아무것도 못 보는 일괄권한'이 아니라 '로그인이 거절되는 일괄권한'이다.
    label.classList.toggle('warn', boxes.length > 0 && on === 0);
  }
  // 그룹 heading 의 개수와 행의 켜짐 표시(권한관리와 같은 방식).
  $('menuChecks').querySelectorAll('.menu-permission-group').forEach(section => {
    const toggles = Array.from(section.querySelectorAll('.menu-permission-toggle'));
    const lit = toggles.filter(t => t.checked).length;
    const count = section.querySelector('[data-group-count]');
    if (count) count.textContent = `${lit} / ${toggles.length} 허용`;
    toggles.forEach(t => {
      const row = t.closest('.menu-permission-row');
      if (row) row.classList.toggle('allowed', t.checked);
    });
  });
}

// 그룹 제목 옆 체크는 그 일괄권한만 한 번에 켜고 끈다. '수금 쪽만 주자' 가 이 화면의
// 실제 일이라, 네 칸을 하나씩 누르게 하면 그만큼 잘못 누를 자리가 생긴다.
function onMenuToggle() {
  // 토글 하나가 바뀌면 개수·켜짐 표시만 다시 그린다(권한관리와 같은 위임).
  paintMenuCount();
}

function collect() {
  return {
    role_id: editing && editing.role_id ? editing.role_id : null,
    name: $('roleName').value.trim(),
    // 소속(office_id)은 안 보낸다 — 서버가 로그인 계정으로 강제한다(2026-08-18).
    // 메모 입력칸은 화면에서 없앴다(2026-08-15 요청). 그래도 읽어 온 값을 그대로
    // 되돌려 보낸다 — 안 보내면 서버가 None 으로 받아 row.memo 를 덮어, 이미
    // 적어 둔 메모가 다음 저장 때 조용히 지워진다. 컬럼도 테스트도 그대로라
    // 아무도 모르게 사라진다. 정말 지우기로 했다면 그건 별도 결정이다.
    memo: (editing && editing.memo) || null,
    // 개인내역조회는 모두 토글로. 전체지사조회는 **본사 로그인만** 토글에서 읽고,
    // 지사는 null(전지사조회를 못 가짐 — 백엔드도 지사엔 강제로 끈다).
    view_all_offices: (String((window.A10_CTX || {}).office_id || '10') === '10')
      ? $('roleViewAll').checked : null,
    view_other_users: $('roleViewOther').checked,
    // 켜진 토글의 data-menu-key 만 모은다.
    menu_keys: Array.from(menuBoxes()).filter(box => box.checked).map(box => box.dataset.menuKey),
  };
}

async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await res.json(); } catch (error) { data = null; }
  return {ok: res.ok && data && data.success !== false, data, status: res.status};
}

async function save(event) {
  event.preventDefault();
  const msg = $('roleMsg');
  const button = $('saveRole');
  // className 을 안 되돌리면 직전 실패의 빨강이 남아 '저장 중…' 이 빨갛게 뜬다.
  msg.className = 'msg';
  msg.textContent = '저장 중…';
  // 잠그지 않으면 새 일괄권한에서 두 번 눌렸을 때 role_id=null 요청이 두 번 나가고,
  // 두 번째가 중복 이름 검사에 걸려 '이미 있는 일괄권한 이름입니다' 가 뜬다 —
  // 실제로는 저장에 성공했는데 화면에는 실패 문구가 남는다.
  button.disabled = true;
  try {
    let {ok, data, status} = await post('/api/permissions/roles', collect());
    // 이 일괄권한이 붙어 있는 부서 사람이 메뉴 0개가 되면 서버가 409 로 되묻는다.
    // 메뉴 0개는 빈 화면이 아니라 로그인 거절이라, 조용히 저장하면 안 된다.
    if (status === 409 && data && data.code === 'ROLE_LOCKOUT_CONFIRM') {
      if (!window.confirm(`${data.message}

계속할까요?`)) {
        msg.textContent = '저장하지 않았습니다.';
        msg.className = 'msg';
        return;
      }
      ({ok, data} = await post('/api/permissions/roles',
                               {...collect(), confirm_lockout: true}));
    }
    if (!ok) {
      msg.textContent = (data && data.message) || '저장하지 못했습니다.';
      msg.className = 'msg bad';
      return;
    }
    msg.textContent = '저장했습니다.';
    msg.className = 'msg good';
    await load();
    const saved = roles.find(r => r.role_id === (data.data && data.data.role_id));
    // 저장 뒤 목록을 다시 그리면 포커스가 body 로 떨어진다 — 방금 누른 자리를
    // 지켜 준다(폼으로 옮기지 않는다).
    if (saved) openEditor(saved, false);
    button.focus();
  } catch (error) {
    // fetch 자체가 실패하면 지금까지 아무 반응이 없었다.
    msg.textContent = '서버에 연결하지 못했습니다. 잠시 뒤 다시 눌러 주세요.';
    msg.className = 'msg bad';
  } finally {
    button.disabled = false;
  }
}

async function remove() {
  if (!editing || !editing.role_id) return;
  const used = editing.used_by || {departments: 0, users: 0};
  const dept = used.departments || 0;
  const users = used.users || 0;
  const inUse = dept + users > 0;
  const name = editing.name || '이름 없음';
  // 종전에는 확인 없이 곧바로 POST 했고, 쓰는 곳이 있으면 서버가 그냥 막았다.
  // 이제 쓰는 곳이 있으면 그 부서·사람을 **각자 복사본으로 떼어낸 뒤** 지운다
  // (권한은 그대로 유지). 무엇이 일어나는지 먼저 알려 주고 확인받는다.
  const where = [dept ? `부서 ${dept}곳` : '', users ? `개인 ${users}명` : '']
    .filter(Boolean).join(' · ');
  const question = inUse
    ? `일괄권한 「${name}」 을 지웁니다.\n\n지금 이 일괄권한을 쓰는 ${where} 은(는) `
      + `각자 복사본으로 떼어냅니다 — 메뉴·조회범위는 그대로 유지됩니다.\n`
      + `되돌릴 수 없습니다. 계속할까요?`
    : `일괄권한 「${name}」 을 지웁니다.\n되돌릴 수 없습니다. 계속할까요?`;
  if (!window.confirm(question)) return;
  const msg = $('roleMsg');
  const button = $('deleteRole');
  msg.className = 'msg';
  msg.textContent = '';
  button.disabled = true;
  try {
    const {ok, data} = await post(
      `/api/permissions/roles/${editing.role_id}/delete`,
      inUse ? {detach: true} : {});
    if (!ok) {
      msg.textContent = (data && data.message) || '삭제하지 못했습니다.';
      msg.className = 'msg bad';
      return;
    }
    // 폼을 그냥 감추면 '지워졌다' 는 말이 어디에도 안 뜬다 — 화면만 비고
    // 아무 설명이 없었다. 빈 상태 카드에 결과를 남긴다.
    const moved = (data && data.data && data.data.detached) || null;
    editing = null;
    // 기준점도 같이 버린다 — 남겨 두면 다음에 무엇을 눌러도 '저장하지 않은
    // 변경이 있습니다' 가 뜬다.
    snapshot = null;
    $('roleEditor').hidden = true;
    $('editorEmpty').hidden = false;
    $('editorEmptyMsg').textContent = moved && (moved.departments || moved.users)
      ? `「${name}」 일괄권한을 지웠습니다. (부서 ${moved.departments}곳·개인 `
        + `${moved.users}명을 복사본으로 떼어냈습니다.)`
      : `「${name}」 일괄권한을 지웠습니다.`;
    await load();
    $('newRole').focus();
  } catch (error) {
    msg.textContent = '서버에 연결하지 못했습니다. 잠시 뒤 다시 눌러 주세요.';
    msg.className = 'msg bad';
  } finally {
    button.disabled = false;
  }
}

// A10_READY 는 **이벤트가 아니라 Promise** 다 (context.js:176). 사용자 확인이
// 실패하면 영원히 보류돼 이후 조회가 아예 안 돈다 — 다른 화면과 같은 방식을 쓴다.
window.A10_READY.then(() => {
  // 지사 '보기 전용' 잠금은 2026-08-18 걷어냈다 — 이제 각 소속(본사·지사)이 자기
  // 일괄권한을 만들고 고친다. 소속은 로그인 계정으로 정해지고, 서버가 남의 소속 일괄권한
  // 쓰기를 막는다(save_role/delete_role 의 소속 소유 검사). 담당자(permissionManage)
  // 만 이 화면에 들어오므로, 지사 담당자는 자기 지사 일괄권한을 관리할 수 있다.

  $('newRole').addEventListener('click', () => {
    if (!confirmDiscard()) return;
    openEditor({
      // memo 는 새 일괄권한에 없다 — collect() 가 editing.memo 를 그대로 되돌려 보내는데,
      // 빈 문자열을 넣어 두면 '' || null 로 null 이 되어 어차피 같다. 안 적는다.
      role_id: null, name: '', menu_keys: [],
      view_all_offices: false, view_other_users: false, used_by: {departments: 0, users: 0},
    });
  });
  $('roleEditor').addEventListener('submit', save);
  $('deleteRole').addEventListener('click', remove);
  // 체크를 건드릴 때마다 legend 옆 '19개 중 7개 켬' 과 일괄권한별 개수가 따라 움직이고,
  // 그룹 제목의 전체선택이면 그 일괄권한을 통째로 켜고 끈다.
  // 위임으로 건다 — menuChecks 안쪽은 편집칸을 열 때마다 다시 그려진다.
  $('menuChecks').addEventListener('change', onMenuToggle);
  // load(목록 조회·렌더) 실패는 아래 인증오류 catch 로 뭉뚱그리지 않는다 — fetch·렌더
  // 실패인데 '사용자 확인 실패' 로 뜨면 담당자가 엉뚱한 데를 본다(2026-08-19 감사).
  return load().catch(() => {
    const list = $('roleList');
    if (list) list.innerHTML = '<li class="empty">일괄권한을 불러오지 못했습니다. 새로고침해 주세요.</li>';
  });
}).catch(error => {
  const list = $('roleList');
  if (list) list.innerHTML = '<li class="empty">사용자 확인에 실패했습니다.</li>';
});
