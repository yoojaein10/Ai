// 데스크톱 공통 부트스트랩: ?usr= 사용자 확인 → 배지/지사셀렉트 구성 → A10_READY 이행.
// usr 파라미터가 없으면 MOA 로그인창(APWorks 아이디·비밀번호)을 띄운다.
// 확인 실패 시 화면을 차단하고 A10_READY를 영원히 보류시켜 이후 조회가 실행되지 않게 한다.
const LOGIN_STORAGE_KEY = 'moa_usr_seq';

// 탭 껍데기(shell) 안에서 도는지 — 껍데기가 상단바·사이드바를 그리므로 안쪽
// 화면은 자기 것을 감춘다. 껍데기 자신은 메뉴 관문에서도 빼야 한다(그 주소에
// 대응하는 메뉴가 없어서, 안 그러면 첫 허용 메뉴로 튕긴다).
const A10_IS_SHELL = location.pathname === '/desktop/shell'
  || location.pathname === '/desktop';
const A10_IN_SHELL = (() => {
  try { return window.top !== window.self; } catch (_) { return true; }
})();
window.A10_IN_SHELL = A10_IN_SHELL;
if (A10_IN_SHELL) {
  document.documentElement.classList.add('in-shell');
  // 감추는 규칙을 여기서 직접 넣는다 — desktop.css 에만 두면 그 파일이 캐시된
  // 화면에서 상단바·사이드바가 겹쳐 보인다 (2026-08-20 보수기준 점검 제보:
  // 그 화면만 ?v 없이 걸려 있어 옛 CSS 를 쓰고 있었다).
  const shellStyle = document.createElement('style');
  shellStyle.textContent = '.in-shell .topbar,.in-shell .sidebar{display:none !important}'
    + '.in-shell .app-shell{display:block}'
    + '.in-shell body{background:#fff}'
    + '.in-shell main{padding-top:16px}';
  document.head.appendChild(shellStyle);
}
// 로그인 증표(app/services/auth_token.py). 권한을 **바꾸는** API 가 요구한다 —
// 서버가 X-MOA-USR-SEQ 숫자 하나만 믿던 것을 막기 위한 것이다.
// EXE 로 바로 들어온 사람에게는 없다. 조회는 종전대로 되고, 권한을 바꾸려 할
// 때만 서버가 401 로 다시 로그인하라고 한다.
const AUTH_TOKEN_KEY = 'REDACTED_CONFIGURE_LOCALLY';
const CONTEXT_PARAMS = new URLSearchParams(location.search);
const IS_LOOPBACK_WEB = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
window.A10_PERMISSION_PREVIEW = IS_LOOPBACK_WEB
  ? CONTEXT_PARAMS.get('permission_preview') || ''
  : '';

let previewUsrSeq = '';
if(window.A10_PERMISSION_PREVIEW){
  try{
    const normalized = window.A10_PERMISSION_PREVIEW.replace(/-/g, '+').replace(/_/g, '/');
    const decoded = JSON.parse(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')));
    if(decoded.v === 1 && Number.isInteger(decoded.usr_seq) && decoded.usr_seq > 0){
      previewUsrSeq = String(decoded.usr_seq);
    }
  }catch(_error){
    previewUsrSeq = '';
  }
}

window.A10_USR = previewUsrSeq
  || CONTEXT_PARAMS.get('usr')
  || localStorage.getItem(LOGIN_STORAGE_KEY) || '';

// EXE가 넘긴 ?usr= 세션을 유지한다: 파라미터가 빠진 화면·새로고침에서도 로그인 창이
// 다시 뜨지 않도록 localStorage에 보존한다. 다음 실행에서 새 ?usr=가 오면 그게 우선.
if (window.A10_USR && !window.A10_PERMISSION_PREVIEW) {
  localStorage.setItem(LOGIN_STORAGE_KEY, window.A10_USR);
}

// ── 업무 메뉴 ─────────────────────────────────────────────────────────────
// 메뉴는 **여기 한 곳에서만** 정한다. 예전에는 16개 화면 HTML 이 저마다
// <nav class="side-nav"> 를 통째로 품고 있어서, 메뉴 하나 고치려면 16곳을
// 똑같이 손대야 했다(2026-08-07 확인 시점엔 다행히 16개가 모두 같았다).
// 화면이 늘수록 어긋날 게 뻔해 한 곳으로 모은다.
//
// 누구에게 보일지는 **여기서 정하지 않는다.** 아래 menuKeyForUrl 이 주소를 메뉴
// 키로 바꾸고, 서버가 내려준 그 사람의 권한으로 감춘다(fail-closed). 종전 메뉴
// 개편안은 hq:true 로 본사/지사만 갈랐는데, 그러면 같은 본사 안에서 재무와
// 총무를 못 가른다. 묶음(group)은 자식이 모두 숨으면 머리글까지 함께 숨는다.
// 노출은 **여기서 정하지 않는다** (2026-08-11 권한 체계 병합).
// 전에는 항목마다 `hq: true` 를 달아 소속(본사/지사)으로 갈랐는데, 소속만
// 보면 본사 전 직원이 카드전표·권한관리를 보게 된다 — 실측으로 본사 136명 중
// 전 메뉴가 정당한 사람은 8명(재무 4·전산정보팀 4)뿐이다.
// 이제 아래 menuKeyForUrl 이 주소를 메뉴 키로 바꾸고, 서버가 내려준
// menu_permissions 가 켜고 끈다. 매핑이 없는 주소는 **숨긴다**(fail-closed).
const A10_MENU = [
  { label: '감정서 LIST', href: '/desktop/dashboard' },
  { group: '입금·미수', items: [
    // 입금·미수는 한 화면(mode 전환)이었다가 2026-09-01 두 화면으로 분리했다.
    // 옛 주소(?mode=outstanding)는 서버가 /desktop/outstanding 으로 보낸다.
    { label: '입금 현황', href: '/desktop/receivables' },
    { label: '입금발송내역', href: '/desktop/payment-sms' },
    { label: '미수금 현황', href: '/desktop/outstanding' },
    { label: '배분 수금 진행', href: '/desktop/collection' },
    { label: '일계표 대사', href: '/desktop/bank-reconcile' },
    { label: '계산서 등록', href: '/desktop/tax-bulk' },   // 2026-09-11 계산서 일괄발급 → 엑셀 등록만
  ] },
  { group: '매출·실적', items: [
    // 전체 공개를 위로 — 지사 사용자가 볼 것이 위에 모인다.
    { label: '기간별 매출실적', href: '/desktop/sales-stats' },
    { label: '업무실적 보고', href: '/desktop/work-report' },
    // 업무실적 보고 바로 밑 — 보고서를 쓰다 보수기준을 확인하러 간다
    // (2026-08-10 요청). '관리·점검' 에 있었지만 실제 동선은 여기다.
    { label: '보수기준 점검', href: '/desktop/fee-basis' },
    // 2026-08-10 origin/main 에서 '매출 입력' → '유치실적' 으로 바뀌었다.
    // 그쪽은 16개 HTML 사이드바를 고쳤고 우리는 그걸 여기 한 곳으로 모았다
    // — 같은 뜻이 되도록 이름만 받는다.
    { label: '유치실적', href: '/desktop/allocation' },
    { label: '상여', href: '/desktop/bonus' },
    { label: '출장비', href: '/desktop/travel-expense' },
    // 상여 밑 (2026-08-10 요청). 전체 공개인데 hq 항목 아래에 오지만,
    // 지사 사용자에게는 위의 hq 셋이 통째로 숨어 바로 위로 붙는다.
    { label: '개인별 매출실적', href: '/desktop/my-sales' },
  ] },
  { group: '카드·반제', items: [
    { label: '카드전표', href: '/desktop/card-vouchers' },
    { label: '외상매출금 반제', href: '/desktop/banje-receivable' },
    { label: '선수금 반제', href: '/desktop/banje-advance' },
  ] },
  { group: '관리·점검', items: [
    { label: '지사별원장', href: '/desktop/account-ledger' },
    { label: '데이터 품질 점검', href: '/desktop/data-quality' },
    // '입금·미수' 에 있었다 — 재무팀이 통장을 보며 하는 일이라 그리 묶었는데,
    // 실제로는 하루치를 훑어 맞는지 확인하는 점검 성격이라 내렸다 (2026-08-10 요청).
    // '감정서 조회' 였던 이름은 그대로 두고 주소도 안 바꾼다(북마크·EXE 가 물고 있다).
    { label: '입금 대사', href: '/desktop/gamjun-chat' },
    // '카드·반제' 에 있었다 — 전표를 만드는 일이 아니라 맞는지 대조하는 일이라
    // 입금 대사 옆으로 내렸다 (2026-08-10 요청). 대사 둘이 나란히 선다.
    { label: '엑셀 대사', href: '/desktop/reconcile' },
    { label: '권한 관리', href: '/desktop/permissions' },
    // '권한 묶음' 은 사이드바에서 내렸다(2026-08-16). 부서 저장이 묶음을 자동
    // 처리하게 되면서 그 화면의 남은 일은 '세트에 이름 붙이기'뿐이라, 권한 관리
    // 화면 안의 링크로 들어간다. 주소·키 매핑(menuKeyForUrl)은 그대로 둔다 —
    // 화면 자체는 살아 있고 permissionManage 로 지킨다.
  ] },
];

// 지금 보고 있는 화면인가. 입금 현황·미수금 현황은 주소가 같고 mode 로만
// 갈리므로 물음표 뒤까지 본다. mode 가 없으면 화면 기본값은 received 다
// (receivables.js:10).
function a10MenuActive(href){
  const url = new URL(href, location.origin);
  if(url.pathname !== location.pathname) return false;
  const want = url.searchParams.get('mode');
  if(!want) return true;
  return (new URLSearchParams(location.search).get('mode') || 'received') === want;
}

// 묶음은 **접힌 채로** 시작한다 (2026-08-07 요청) — 대분류만 먼저 보이고
// 누르면 아래로 열린다. 다만 두 가지는 예외다:
//  · 지금 보고 있는 화면이 든 묶음은 언제나 열어 둔다. 안 그러면 내가 어디에
//    있는지 알 수 없다.
//  · 사람이 직접 열어 둔 묶음은 기억한다. 매번 다시 여는 것이 제일 성가시다.
const A10_NAV_OPEN_KEY = 'a10.nav.open.v1';

function a10NavOpened(){
  try{
    const raw = localStorage.getItem(A10_NAV_OPEN_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  }catch(_){ return new Set(); }
}

function a10NavRemember(name, open){
  try{
    const set = a10NavOpened();
    if(open) set.add(name); else set.delete(name);
    localStorage.setItem(A10_NAV_OPEN_KEY, JSON.stringify([...set]));
  }catch(_){ /* 저장 못 해도 메뉴는 돌아야 한다 */ }
}

// 메뉴는 사용자 확인을 기다리지 않고 **바로** 그린다 — 기다리면 사이드바가
// 잠깐 비어 보인다. 권한에 따른 감춤과 usr 전달은 확인이 끝난 뒤에 한다.
function a10RenderMenu(){
  const nav = document.querySelector('.side-nav');
  if(!nav) return;
  const esc = v => String(v).replace(/[&<>'"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const link = it => {
    const on = a10MenuActive(it.href);
    const cls = on ? 'active' : '';
    return `<a${cls ? ` class="${cls}"` : ''}${on ? ' aria-current="page"' : ''}`
      + ` href="${esc(it.href)}">${esc(it.label)}</a>`;
  };
  const remembered = a10NavOpened();
  nav.innerHTML = A10_MENU.map(entry => {
    if(!entry.group) return link(entry);
    const here = entry.items.some(it => a10MenuActive(it.href));
    const open = here || remembered.has(entry.group);
    // 머리글은 버튼이다 — 키보드로도 열고 닫을 수 있어야 한다.
    return `<div class="nav-group${open ? ' open' : ''}"`
      + ` data-group="${esc(entry.group)}">`
      + `<button type="button" class="nav-group-title" aria-expanded="${open}">`
      + `<span>${esc(entry.group)}</span><i aria-hidden="true">⌄</i></button>`
      + entry.items.map(link).join('')
      + '</div>';
  }).join('');
  // fail-closed: 권한 확인이 끝날 때까지 사이드바를 숨긴다. 예전엔 모든 메뉴를
  // 먼저 그려 두고(fail-open) 나중에 권한 없는 것을 감췄는데, 그 로딩 창 동안 권한
  // 없는 메뉴가 잠깐 보이고 빨리 누르면 그 화면으로 들어가졌다(2026-08-19 신고).
  // 아래 bootstrap 이 권한대로 거른 뒤 다시 드러낸다.
  nav.style.visibility = 'hidden';

  nav.addEventListener('click', event => {
    const title = event.target.closest('.nav-group-title');
    if(!title) return;
    const box = title.closest('.nav-group');
    const open = box.classList.toggle('open');
    title.setAttribute('aria-expanded', String(open));
    a10NavRemember(box.dataset.group, open);
  });
}

a10RenderMenu();

// 본문·상단바도 nav 와 같은 fail-closed — 권한 확인이 끝날 때까지 숨긴다. 지사가 본사
// 전용 화면 주소(북마크·URL)로 직접 들어와도 제목·표 머리글이 리다이렉트 전에 잠깐
// 보이지 않게 한다(2026-08-19 감사 #8: ctx-ready 는 받쳐 주는 CSS 가 없어 죽은 코드였다).
document.querySelectorAll('.app-shell, .topbar, .permission-page').forEach(el => { el.style.visibility = 'hidden'; });
function a10RevealShell(){
  document.querySelectorAll('.app-shell, .topbar, .permission-page').forEach(el => el.style.removeProperty('visibility'));
}

// 자식이 모두 숨은 묶음은 머리글까지 감춘다 — '카드·반제' 같은 빈 제목만
// 남는 것을 막는다. 권한으로 감춘 뒤에 부른다.
function a10HideEmptyGroups(){
  document.querySelectorAll('.side-nav .nav-group').forEach(box => {
    const shown = [...box.querySelectorAll('a')].filter(a => !a.classList.contains('hidden'));
    if(!shown.length) box.classList.add('hidden');
  });
}

window.A10_READY = (async function bootstrap(){
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(
    /[&<>'"]/g,
    character => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[character]),
  );

  function clearLoginAndOpenLogin(){
    localStorage.removeItem(LOGIN_STORAGE_KEY);
    const url = new URL(location.href);
    url.searchParams.delete('usr');
    url.searchParams.delete('permission_preview');
    location.href = url.pathname + url.search + url.hash;
  }

  function block(message, options = {}){
    const {
      title = '사용자 확인 실패',
      hint = 'APWorks에서 다시 실행해 주세요.',
      primaryLabel = '다시 시도',
      onPrimary = clearLoginAndOpenLogin,
      secondaryLabel = '',
      onSecondary = null,
    } = options;
    document.querySelectorAll('.app-shell, .topbar, .permission-page').forEach(el => el.classList.add('hidden'));
    const panel = document.createElement('div');
    panel.className = 'ctx-error';
    panel.innerHTML = `<div class="ctx-error-card">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(message)}</p>
      <p class="ctx-error-hint">${escapeHtml(hint)}</p>
      <div class="ctx-error-actions">
        <button type="button" data-action="primary">${escapeHtml(primaryLabel)}</button>
        ${secondaryLabel ? `<button type="button" class="secondary" data-action="secondary">${escapeHtml(secondaryLabel)}</button>` : ''}
      </div>
    </div>`;
    panel.querySelector('[data-action="primary"]').addEventListener('click', onPrimary);
    if(secondaryLabel && onSecondary){
      panel.querySelector('[data-action="secondary"]').addEventListener('click', onSecondary);
    }
    document.body.appendChild(panel);
    return new Promise(() => {});  // 이후 단계 진행 차단
  }

  function showLogin(){
    document.querySelectorAll('.app-shell, .topbar, .permission-page').forEach(el => el.classList.add('hidden'));
    return new Promise(resolve => {
      const panel = document.createElement('div');
      panel.className = 'ctx-error';
      panel.innerHTML = `<form class="ctx-error-card login-card">
        <img class="login-logo" src="/ui/moa-icon.svg" alt="">
        <h2>MOA 로그인</h2>
        <p class="ctx-error-hint">APWorks 아이디와 비밀번호를 입력하세요.</p>
        <input id="loginId" name="username" autocomplete="username" placeholder="아이디" required>
        <input id="loginPw" name="password" type="password" autocomplete="current-password" placeholder="비밀번호" required>
        <p class="login-error" id="loginError" role="alert"></p>
        <button type="submit">로그인</button>
      </form>`;
      document.body.appendChild(panel);
      const form = panel.querySelector('form');
      const error = panel.querySelector('#loginError');
      panel.querySelector('#loginId').focus();
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const button = form.querySelector('button');
        button.disabled = true; error.textContent = '';
        try{
          const response = await fetch('/api/auth/login', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              usr_id: panel.querySelector('#loginId').value.trim(),
              password: panel.querySelector('#loginPw').value,
            }),
          });
          const payload = await response.json();
          if(!payload.success) throw new Error(payload.message || '로그인에 실패했습니다.');
          const usrSeq = String(payload.data.usr_seq);
          localStorage.setItem(LOGIN_STORAGE_KEY, usrSeq);
          if(payload.data.auth_token) localStorage.setItem(AUTH_TOKEN_KEY, payload.data.auth_token);
          panel.remove();
          document.querySelectorAll('.app-shell, .topbar, .permission-page').forEach(el => el.classList.remove('hidden'));
          resolve(usrSeq);
        }catch(err){
          error.textContent = err.message;
          button.disabled = false;
        }
      });
    });
  }

  if(window.A10_PERMISSION_PREVIEW && !previewUsrSeq){
    return block('권한 테스트 주소가 올바르지 않습니다.', {
      title: '권한 테스트 실패',
      hint: '권한 시안에서 직원을 다시 선택해 테스트를 시작해 주세요.',
      primaryLabel: '권한 시안으로 돌아가기',
      onPrimary: () => { location.href = '/desktop/permissions-preview'; },
    });
  }

  if(!window.A10_USR){
    window.A10_USR = await showLogin();
  }

  let payload;
  try{
    const contextUrl = window.A10_PERMISSION_PREVIEW
      ? `/api/users/${encodeURIComponent(window.A10_USR)}/context-preview?permission_preview=${encodeURIComponent(window.A10_PERMISSION_PREVIEW)}`
      : `/api/users/${encodeURIComponent(window.A10_USR)}/context`;
    const response = await fetch(contextUrl);
    payload = await response.json();
  }catch(error){
    return block(`서버와 통신할 수 없습니다: ${error.message}`);
  }
  if(!payload.success){
    return block(payload.message || '사용자 확인에 실패했습니다.');
  }

  const ctx = payload.data;
  window.A10_CTX = ctx;
  window.A10_CAN = menuKey => !!(ctx.menu_permissions && ctx.menu_permissions[menuKey]);

  // 이후 모든 동일 출처 API 호출에 로그인 사용자를 전달한다.
  // 서버는 이 값으로 메뉴·지사·평가사 데이터 범위를 다시 검사한다.
  const originalFetch = window.fetch.bind(window);

  // 저장(쓰기)은 비밀번호 증표를 요구한다. ?usr= 나 EXE 로 들어와 증표가 없거나
  // 만료됐으면 서버가 401(AUTH_TOKEN_REQUIRED)로 되돌린다. 종전에는 화면이 그
  // 메시지만 보여 주고 끝나 '로그인하라면서 로그인할 창이 없는' 막다른 길이었다
  // (2026-08-17 사용자 지적). 여기서 로그인 모달을 띄워 증표를 받고 원래 저장을
  // 한 번 다시 시도한다. 증표의 usr_seq 는 세션 usr_seq 와 같아야 서버가 받으므로
  // (require_menu_write 의 AUTH_TOKEN_MISMATCH) **같은 계정으로만** 받는다.
  let pendingReauth = null;
  function reauthForToken(){
    if(pendingReauth) return pendingReauth;
    pendingReauth = new Promise(resolve => {
      const panel = document.createElement('div');
      panel.className = 'ctx-error';
      panel.innerHTML = `<form class="ctx-error-card login-card">
        <img class="login-logo" src="/ui/moa-icon.svg" alt="">
        <h2>권한 변경 확인</h2>
        <p class="ctx-error-hint">${escapeHtml(ctx.emp_name || '')} 님, 권한을 바꾸려면
          APWorks 비밀번호로 한 번 더 확인해 주세요.</p>
        <input id="reauthId" name="username" autocomplete="username" placeholder="아이디" required>
        <input id="reauthPw" name="password" type="password" autocomplete="current-password" placeholder="비밀번호" required>
        <p class="login-error" id="reauthError" role="alert"></p>
        <div class="ctx-error-actions">
          <button type="submit">확인</button>
          <button type="button" class="secondary" data-action="cancel">취소</button>
        </div>
      </form>`;
      document.body.appendChild(panel);
      const form = panel.querySelector('form');
      const error = panel.querySelector('#reauthError');
      panel.querySelector('#reauthId').focus();
      const done = value => { panel.remove(); resolve(value); };
      panel.querySelector('[data-action="cancel"]').addEventListener('click', () => done(false));
      form.addEventListener('submit', async event => {
        event.preventDefault();
        const button = form.querySelector('button[type="submit"]');
        button.disabled = true; error.textContent = '';
        try{
          const res = await originalFetch('/api/auth/login', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
              usr_id: panel.querySelector('#reauthId').value.trim(),
              password: panel.querySelector('#reauthPw').value,
            }),
          });
          const payload = await res.json().catch(() => null);
          if(!payload || !payload.success){
            throw new Error((payload && payload.message) || '로그인에 실패했습니다.');
          }
          // 증표는 로그인한 사람 것이다. 지금 세션과 다른 사람이면 서버가 어차피
          // 거절하므로(AUTH_TOKEN_MISMATCH) 여기서 먼저 막고 이유를 알려 준다.
          if(String(payload.data.usr_seq) !== String(ctx.usr_seq)){
            throw new Error('지금 열려 있는 계정과 다른 사람입니다. 같은 계정으로 로그인해 주세요.');
          }
          if(payload.data.auth_token) localStorage.setItem(AUTH_TOKEN_KEY, payload.data.auth_token);
          done(true);
        }catch(err){
          error.textContent = err.message;
          button.disabled = false;
        }
      });
    }).finally(() => { pendingReauth = null; });
    return pendingReauth;
  }

  // 이후 모든 동일 출처 API 호출에 로그인 사용자를 전달한다.
  // 서버는 이 값으로 메뉴·지사·평가사 데이터 범위를 다시 검사한다.
  window.fetch = async function(resource, options = {}){
    const rawUrl = typeof resource === 'string' ? resource : resource.url;
    const url = new URL(rawUrl, location.origin);
    if(url.origin !== location.origin || !url.pathname.startsWith('/api/')){
      return originalFetch(resource, options);
    }
    const method = String(
      options.method || (typeof resource !== 'string' && resource.method) || 'GET'
    ).toUpperCase();
    if(window.A10_PERMISSION_PREVIEW && !['GET', 'HEAD', 'OPTIONS'].includes(method)){
      return Promise.resolve(new Response(JSON.stringify({
        success: false,
        code: 'PREVIEW_READ_ONLY',
        message: '권한 테스트에서는 저장·승인·발급·변경할 수 없습니다.',
        data: null,
      }), {
        status: 403,
        headers: {'Content-Type': 'application/json; charset=utf-8'},
      }));
    }
    const headers = new Headers(options.headers || (typeof resource !== 'string' ? resource.headers : undefined));
    headers.set('X-MOA-USR-SEQ', String(ctx.usr_seq));
    // 증표가 있으면 늘 함께 보낸다. 서버는 권한을 **바꾸는** API 에서만 이걸
    // 요구한다 — 조회는 종전대로 돌아 EXE 로 들어온 사람도 영향이 없다.
    const authToken = localStorage.getItem(AUTH_TOKEN_KEY);
    if(authToken) headers.set('X-MOA-AUTH', authToken);
    if(window.A10_PERMISSION_PREVIEW){
      headers.set('X-MOA-PREVIEW-POLICY', window.A10_PERMISSION_PREVIEW);
    }
    const response = await originalFetch(resource, {...options, headers});
    // 쓰기 증표가 없거나 만료돼 401 이 오면, 로그인 모달로 증표를 새로 받고
    // **딱 한 번** 다시 시도한다(__moaReauthRetried 로 무한 루프를 막는다).
    // 권한 테스트(읽기 전용)에서는 재시도하지 않는다 — 어차피 쓰기가 막혀 있다.
    if(response.status === 401 && !options.__moaReauthRetried && !window.A10_PERMISSION_PREVIEW){
      const peek = await response.clone().json().catch(() => null);
      if(peek && (peek.code === 'AUTH_TOKEN_REQUIRED' || peek.code === 'AUTH_TOKEN_MISMATCH')){
        const ok = await reauthForToken();
        if(ok){
          return window.fetch(resource, {...options, __moaReauthRetried: true});
        }
      }
    }
    return response;
  };

  // 사이드바·톱니 링크에 로그인 또는 로컬 권한 테스트 컨텍스트를 전달한다.
  document.querySelectorAll('.side-nav a, a.gear-link').forEach(link => {
    const url = new URL(link.getAttribute('href'), location.origin);
    if(window.A10_PERMISSION_PREVIEW){
      url.searchParams.delete('usr');
      url.searchParams.set('permission_preview', window.A10_PERMISSION_PREVIEW);
    }else{
      url.searchParams.set('usr', window.A10_USR);
    }
    link.setAttribute('href', url.pathname + url.search);
  });

  const menuKeyForUrl = url => {
    if(url.pathname === '/desktop/dashboard') return 'appraisals';
    if(url.pathname === '/desktop/outstanding') return 'receivables';
    if(url.pathname === '/desktop/receivables'){
      // 옛 링크(?mode=outstanding)가 캐시된 화면에 남아 있을 수 있다.
      return url.searchParams.get('mode') === 'outstanding' ? 'receivables' : 'payments';
    }
    return ({
      '/desktop/allocation': 'salesInput',
      '/desktop/sales-stats': 'salesStats',
      '/desktop/bonus': 'bonus',
      // 상여의 딸림 화면(사람·요율·지분 설정) — 사이드바에는 없고 같은 키로 지킨다.
      '/desktop/bonus-settings': 'bonus',
      '/desktop/bonus-legacy': 'bonus',
      '/desktop/bonus-deductions': 'bonus',
      '/desktop/account-ledger': 'accountLedger',
      // 계정별원장의 딸림 화면(메일 주소 관리) — 사이드바에는 없고 같은 키로 지킨다.
      '/desktop/ledger-recipients': 'accountLedger',
      '/desktop/data-quality': 'dataQuality',
      '/desktop/reconcile': 'reconcile',
      '/desktop/collection': 'allocation',
      '/desktop/banje-receivable': 'receivableReconcile',
      '/desktop/banje-advance': 'advanceReconcile',
      '/desktop/work-report': 'workReport',
      '/desktop/permissions': 'permissionManage',
      '/desktop/permissions-preview': 'permissionManage',
      '/desktop/permission-roles': 'permissionManage',
      '/desktop/payment-sms': 'paymentSms',
      '/desktop/card-vouchers': 'cardVouchers',
      '/desktop/fee-basis': 'feeBasis',
      '/desktop/my-sales': 'mySales',
      '/desktop/gamjun-chat': 'depositMatch',
      '/desktop/bank-reconcile': 'bankReconcile',
      '/desktop/tax-bulk': 'taxBulk',
      '/desktop/travel-expense': 'travelExpense',
    })[url.pathname] || null;
  };

  // 메뉴 표시는 서버가 내려준 동일한 메뉴 키 정책을 사용한다.
  //
  // 매핑이 없는 링크(key === null)는 **숨긴다**. 예전에는 `if(key && ...)` 라 매핑을
  // 빠뜨린 메뉴가 전원에게 노출됐다(실측: /desktop/fee-basis 가 지사 일반직원까지 보였고,
  // 메뉴 0개 사용자는 firstAllowedMenu 가 그 링크를 집어 그 화면으로 튕겼다).
  // 종전 main 은 hq-only 클래스로 무조건 숨겼으므로 이 방식이 더 열려 있었다 — fail-closed 로 되돌린다.
  document.querySelectorAll('.side-nav a, a.gear-link').forEach(link => {
    const key = menuKeyForUrl(new URL(link.href, location.origin));
    if(!key || !window.A10_CAN(key)) link.classList.add('hidden');
  });
  // 링크를 감춘 **뒤에** 빈 묶음을 접는다. 순서가 뒤집히면 자식이 다 숨은 채
  // '카드·반제' 같은 머리글만 남는다.
  a10HideEmptyGroups();
  // 권한대로 다 걸렀으니 이제 사이드바를 드러낸다(a10RenderMenu 의 fail-closed 숨김 해제).
  document.querySelector('.side-nav')?.style.removeProperty('visibility');
  // 남은 .hq-only 요소(메뉴가 아닌 화면 안 버튼 등)는 지사 사용자에게 숨긴다.
  // 메뉴 자체는 위에서 메뉴 키로 이미 갈렸다 — 소속만으로는 본사 안에서
  // 재무와 총무를 못 가르기 때문이다.
  if(ctx.office_id !== '10'){
    document.querySelectorAll('.hq-only').forEach(el => el.classList.add('hidden'));
  }
  // 권한 계산이 끝난 뒤에야 메뉴를 노출한다 (새로고침 시 전체 메뉴가 깜빡이는 FOUC 방지).
  document.body.classList.add('ctx-ready');

  // 사용자 배지 (+ 로그인으로 들어온 경우 로그아웃 버튼)
  const badge = document.createElement('div');
  badge.className = 'user-badge';
  const badgeName = document.createElement('span');
  badgeName.textContent = window.A10_PERMISSION_PREVIEW
    ? `권한 테스트 · ${ctx.emp_name} · ${ctx.office_name}`
    : `${ctx.emp_name} · ${ctx.office_name}`;
  badge.appendChild(badgeName);
  if(window.A10_PERMISSION_PREVIEW){
    const exitPreview = document.createElement('button');
    exitPreview.type = 'button';
    exitPreview.className = 'logout-button';
    exitPreview.textContent = '테스트 종료';
    exitPreview.addEventListener('click', () => {
      location.href = '/desktop/permissions-preview';
    });
    badge.appendChild(exitPreview);
  }else if(localStorage.getItem(LOGIN_STORAGE_KEY)){
    const logout = document.createElement('button');
    logout.type = 'button';
    logout.className = 'logout-button';
    logout.textContent = '로그아웃';
    logout.addEventListener('click', () => {
      localStorage.removeItem(LOGIN_STORAGE_KEY);
      const url = new URL(location.href);
      url.searchParams.delete('usr');
      location.href = url.pathname + url.search;
    });
    badge.appendChild(logout);
  }
  const sidebar = document.querySelector('.sidebar');
  if(sidebar) sidebar.insertBefore(badge, sidebar.firstChild);
  if(window.A10_PERMISSION_PREVIEW){
    const previewNotice = document.createElement('div');
    previewNotice.className = 'permission-test-notice';
    previewNotice.innerHTML = '<strong>권한 테스트</strong><span>읽기 전용 · 저장/승인/발급/변경 차단</span>';
    document.querySelector('.topbar')?.appendChild(previewNotice);
  }

  // 로그인은 허용하되 현재 메뉴 권한이 없으면 업무 화면/API 조회만 막는다.
  // 다른 허용 메뉴가 있으면 그 메뉴로 이동하고, 하나도 없으면 빈 메뉴 화면을 보여준다.
  // 매핑이 없는 화면(currentMenuKey === null)도 막는다. 매핑을 빠뜨린 화면이
  // 무조건 열리면 서버 가드가 유일한 방어선이 되는데, 그 가드가 없는 라우터가 있다.
  const currentMenuKey = A10_IS_SHELL ? null : menuKeyForUrl(new URL(location.href));
  if(!A10_IS_SHELL && (!currentMenuKey || !window.A10_CAN(currentMenuKey))){
    // 허용된 첫 메뉴로 보낸다. .side-nav DOM 대신 A10_MENU 를 A10_CAN 으로 거른다 —
    // 권한 관리 화면(permissions-preview/roles)엔 사이드바가 없어, DOM 만 읽으면
    // 실제로는 메뉴가 있어도 못 찾아 '메뉴 없음' 으로 잘못 튕겼다(2026-08-19 감사).
    let firstAllowedHref = null;
    for(const entry of A10_MENU){
      for(const it of (entry.items || [entry])){
        const k = menuKeyForUrl(new URL(it.href, location.origin));
        if(k && window.A10_CAN(k)){ firstAllowedHref = it.href; break; }
      }
      if(firstAllowedHref) break;
    }
    if(firstAllowedHref){
      location.replace(firstAllowedHref);
      return new Promise(() => {});
    }

    document.querySelector('.sidebar-label')?.classList.add('hidden');
    document.querySelector('.side-nav')?.setAttribute('aria-label', '사용 가능한 메뉴 없음');
    const pageTitle = document.querySelector('.topbar h1');
    if(pageTitle) pageTitle.textContent = 'MOA';
    const main = $('main-content');
    if(main){
      main.replaceChildren();
      const empty = document.createElement('section');
      empty.className = 'no-menu-empty';
      empty.innerHTML = `<div class="no-menu-empty-icon" aria-hidden="true">MOA</div>
        <h2>사용 가능한 메뉴가 없습니다</h2>
        <p>현재 계정에 부여된 MOA 메뉴 권한이 없습니다.</p>`;
      main.appendChild(empty);
    }
    a10RevealShell();  // '메뉴 없음' 안내 화면·MOA 상단바는 보여준다
    return new Promise(() => {});  // 페이지별 업무 API 호출 차단
  }
  a10RevealShell();  // 여기 도달 = 현재 화면 권한 확인·가드 통과 — 본문·상단바를 드러낸다

  // 지사 셀렉트: 권한에 따라 목록/잠금 결정
  const select = $('officeCode');
  if(select){
    const options = ctx.offices.map(
      office => `<option value="${office.office_code}">${office.office_name}</option>`
    );
    if(ctx.view_all_offices) options.push('<option value="all">전체</option>');
    select.innerHTML = options.join('');
    select.value = ctx.office_id;
    select.disabled = !ctx.view_all_offices;
  }

  return ctx;
})();

// 알림 토스트 (페이지에 #toast가 없으면 알림창으로 대체)
window.A10_TOAST = function(message, isError){
  const toast = document.getElementById('toast');
  if(!toast){ window.alert(message); return; }
  toast.textContent = message;
  toast.classList.toggle('error', !!isError);
  toast.classList.remove('hidden');
  clearTimeout(window.A10_TOAST.timer);
  window.A10_TOAST.timer = setTimeout(() => toast.classList.add('hidden'), 5000);
};

// 엑셀 내보내기 공통.
// 데스크톱 앱(pywebview) 창은 브라우저처럼 다운로드를 처리하지 못해 그냥 눌러도 반응이 없다.
// 그래서 앱 안에서는 파이썬 브리지(DesktopApi.download)로 받아 저장 대화상자를 띄우고,
// 웹 브라우저에서는 기존처럼 주소 이동으로 내려받는다.
window.A10_DOWNLOAD = function(path){
  const url = new URL(path, location.origin);
  if(window.A10_CTX && url.origin === location.origin){
    url.searchParams.set('usr_seq', String(window.A10_CTX.usr_seq));
    if(window.A10_PERMISSION_PREVIEW){
      url.searchParams.set('permission_preview', window.A10_PERMISSION_PREVIEW);
    }
    path = url.pathname + url.search;
  }
  if(A10_IN_SHELL){
    // EXE 저장 다리는 맨 위 창에만 붙는다 — 껍데기가 대신 받게 넘긴다.
    window.parent.postMessage({type:'a10:download', path}, location.origin);
    return;
  }
  const api = window.pywebview && window.pywebview.api;
  if(api && api.download){
    window.A10_TOAST('파일을 준비하고 있습니다...');
    api.download(path)
      .then(message => { if(message) window.A10_TOAST(message, !/^(저장했습니다|열었습니다)/.test(message)); })
      .catch(error => window.A10_TOAST(`내려받지 못했습니다: ${error}`, true));
    return;
  }
  window.location.href = path;
};

// 현재 선택된 지사 코드 (셀렉트가 없으면 사용자 소속 지사)
window.A10_OFFICE = function(){
  const select = document.getElementById('officeCode');
  if(select && select.value) return select.value;
  return (window.A10_CTX && window.A10_CTX.office_id) || '10';
};
