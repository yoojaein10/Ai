// 탭 껍데기 — 메뉴를 탭으로 띄우고, 탭을 바꿀 때 감추고 보여주기만 한다.
// 페이지를 갈아끼우지 않으므로 하던 작업(올린 엑셀·고친 계정 등)이 살아 있다
// (2026-08-20 사용자 요청). 화면 자체는 하나도 고치지 않고 iframe 으로 태운다.
(function () {
  const MAX_TABS = 8;          // 열어 둔 화면만큼 메모리를 쓴다 — 상한을 둔다
  const LAST_KEY = 'moa.shell.openTabs';

  const tabsBox = document.getElementById('shellTabs');
  const framesBox = document.getElementById('shellFrames');
  const emptyBox = document.getElementById('shellEmpty');
  const tabs = new Map();      // href → {button, frame, label}
  let activeHref = '';

  const esc = v => String(v ?? '').replace(/[&<>'"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));

  // context.js 가 메뉴 링크에 ?usr= 를 붙인다. 탭은 주소 그대로가 아니라 경로로
  // 다뤄야 이름을 찾고, 사람이 바뀌어도 지난 탭이 되살아난다 (2026-08-20 제보:
  // 탭에 '/desktop/card-vouchers?usr=813' 이 그대로 찍혔다).
  const pathOf = href => {
    try { return new URL(href, location.origin).pathname; } catch (_) { return href; }
  };

  // 그 경로의 사이드바 링크(= ?usr= 가 붙은 실제 주소)를 쓴다. 없으면 경로 그대로.
  const hrefFor = path => {
    const link = [...document.querySelectorAll('.side-nav a')]
      .find(a => pathOf(a.getAttribute('href')) === path);
    return link ? link.getAttribute('href') : path;
  };

  // 이름은 사이드바에 그려진 글자를 그대로 쓴다. context.js 의 A10_MENU 는 const 라
  // window 에 붙지 않아 window.A10_MENU 로는 못 읽는다 (2026-08-20: 그래서 탭에
  // 주소가 그대로 찍혔다 — 시험 하네스가 window.A10_MENU 를 직접 만들어 놔서
  // 그때는 안 걸렸다).
  function labelFor(path) {
    const link = [...document.querySelectorAll('.side-nav a')]
      .find(a => pathOf(a.getAttribute('href')) === path);
    if (link && link.textContent.trim()) return link.textContent.trim();
    const menu = (typeof A10_MENU !== 'undefined' ? A10_MENU : window.A10_MENU) || [];
    for (const entry of menu) {
      for (const item of (entry.items || [entry])) {
        if (pathOf(item.href) === path) return item.label;
      }
    }
    return path;
  }

  function remember() {
    try { localStorage.setItem(LAST_KEY, JSON.stringify([...tabs.keys()])); }
    catch (error) { /* 저장 못 해도 탭은 돈다 */ }
  }

  function activate(path) {
    if (!tabs.has(path)) return;
    activeHref = path;
    tabs.forEach((tab, key) => {
      const on = key === path;
      tab.button.classList.toggle('active', on);
      tab.button.setAttribute('aria-selected', String(on));
      tab.frame.classList.toggle('hidden', !on);
    });
    document.title = `MOA · ${labelFor(path)}`;
    // 사이드바에서 지금 보고 있는 메뉴를 굵게
    document.querySelectorAll('.side-nav a').forEach(a => {
      const on = pathOf(a.getAttribute('href')) === path;
      a.classList.toggle('active', on);
      if (on) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    emptyBox.classList.add('hidden');
  }

  function close(path) {
    const tab = tabs.get(path);
    if (!tab) return;
    tab.button.remove();
    tab.frame.remove();
    tabs.delete(path);
    remember();
    if (activeHref === path) {
      const next = [...tabs.keys()].pop();
      if (next) activate(next);
      else { activeHref = ''; document.title = 'MOA'; emptyBox.classList.remove('hidden'); }
    }
  }

  function open(target, { focus = true } = {}) {
    const path = pathOf(target);
    if (tabs.has(path)) { if (focus) activate(path); return; }
    if (tabs.size >= MAX_TABS) {
      window.A10_TOAST(`화면은 ${MAX_TABS}개까지 열 수 있습니다. 안 쓰는 탭을 닫아 주세요.`, true);
      return;
    }
    const label = labelFor(path);

    const button = document.createElement('div');
    button.className = 'shell-tab';
    button.setAttribute('role', 'tab');
    button.innerHTML = `<span>${esc(label)}</span>`
      + `<button type="button" class="close" title="닫기" aria-label="${esc(label)} 닫기">×</button>`;
    button.addEventListener('click', event => {
      if (event.target.closest('.close')) { close(path); return; }
      activate(path);
    });
    tabsBox.appendChild(button);

    const frame = document.createElement('iframe');
    frame.src = hrefFor(path);   // ?usr= 가 붙은 실제 주소로 연다
    frame.title = label;
    frame.className = 'hidden';
    framesBox.appendChild(frame);

    tabs.set(path, { button, frame, label });
    remember();
    if (focus) activate(path);
  }

  // 사이드바 클릭을 가로채 탭으로 연다. context.js 가 권한대로 걸러 그린 뒤라
  // 여기 보이는 링크는 이미 열어도 되는 것들이다.
  document.querySelector('.side-nav').addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || link.classList.contains('hidden')) return;
    event.preventDefault();
    open(link.getAttribute('href'));
  });

  // 안쪽 화면(iframe)이 껍데기에 부탁하는 일들.
  window.addEventListener('message', event => {
    if (event.origin !== location.origin) return;      // 남의 창은 안 듣는다
    const data = event.data || {};
    if (data.type === 'a10:download' && typeof data.path === 'string'
        && data.path.startsWith('/')) {
      // EXE 저장 다리(window.pywebview)는 맨 위 창에만 있다 — 여기서 대신 받는다.
      window.A10_DOWNLOAD(data.path);
    } else if (data.type === 'a10:open' && typeof data.href === 'string'
        && data.href.startsWith('/desktop/')) {
      open(data.href);
    } else if (data.type === 'a10:toast' && typeof data.message === 'string') {
      window.A10_TOAST(data.message, Boolean(data.isError));
    }
  });

  window.A10_READY.then(() => {
    // 지난번에 열어 둔 탭을 되살린다. 권한이 빠진 메뉴는 사이드바에 없으므로 건너뛴다.
    const allowed = new Set(
      [...document.querySelectorAll('.side-nav a')]
        .filter(a => !a.classList.contains('hidden'))
        .map(a => pathOf(a.getAttribute('href'))),
    );
    let restored = [];
    try { restored = JSON.parse(localStorage.getItem(LAST_KEY) || '[]'); }
    catch (error) { restored = []; }
    restored.map(pathOf).filter(path => allowed.has(path)).slice(0, MAX_TABS)
      .forEach(path => open(path, { focus: false }));

    const wanted = new URL(location.href).searchParams.get('open');
    if (wanted && allowed.has(pathOf(wanted))) open(wanted);
    else if (tabs.size) activate([...tabs.keys()][0]);
  });
})();
