// 계산서 등록 — 발급 원장 조회 (2026-09-11). 감정서 LIST·입금현황처럼 조회 조건으로 거르고 쪽으로 넘긴다.
// 재무팀 요청(같은 날): 헤더 눌러 정렬, '감정서번호 없는 것만' 필터, 엑셀 추출, 감정서번호 수정(엑셀로 등록한 건만).
// 엑셀 등록(tax-bulk-external.js)은 [계산서Excel등록] 버튼으로 팝업을 연다 — 팝업을 닫으면 목록을 다시 조회한다(2026-09-11).
// 전역 이름이 새지 않게 함수 안에 가둔다 (같은 페이지에 tax-bulk-external.js 가 있다).
(function () {
  const $ = id => document.getElementById(id);
  const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const num = v => money.format(Math.round(Number(v || 0)));
  const biz = v => { const d = String(v || '').replace(/[^0-9]/g, ''); return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d; };
  const requester = () => Number((window.A10_CTX || {}).usr_seq || 0);
  const COLS = 11;   // 승인번호 칸은 화면에서 뺐다(2026-09-11) — 검색·엑셀에는 있다
  const state = { page: 1, pageSize: 100, total: 0, sortBy: '', sortOrder: 'desc', items: [] };

  function toast(msg, err) {
    const t = $('toast');
    t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 7000);
  }

  // 조건(쪽 없이) — 엑셀 추출도 같은 조건·같은 정렬
  function conditions() {
    return new URLSearchParams({
      office_code: window.A10_OFFICE(), date_from: $('dateFrom').value, date_to: $('dateTo').value,
      doc_type: $('docType').value, source: $('sourceFilter').value, keyword: $('keyword').value.trim(),
      missing_doc: $('docFilter').value === 'missing' ? 'true' : 'false',
      sort_by: state.sortBy, sort_order: state.sortOrder,
    });
  }

  async function load() {
    $('ledgerRows').innerHTML = `<tr><td colspan="${COLS}" class="tb-hint">불러오는 중...</td></tr>`;
    const q = conditions();
    q.set('page', String(state.page)); q.set('page_size', String(state.pageSize));
    const res = await fetch(`/api/taxinvoice/external/ledger?${q}`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    render(p.data);
  }

  function docCell(r) {
    if (!r.editable) return esc(r.doc_id);
    return `<span class="doc-text">${esc(r.doc_id) || '<em class="need">없음</em>'}</span> <button class="doc-fix" type="button" data-id="${r.id}" title="감정서번호 고치기">✎</button>`;
  }

  function render(data) {
    state.total = data.total; state.items = data.items;
    const s = data.sums;
    $('ledgerSummary').textContent = `${num(data.total)}건 · 공급가액 ${num(s.supply_cost)} · 세액 ${num(s.tax)} · 합계 ${num(s.total)}원`;
    const pages = Math.max(1, Math.ceil(data.total / state.pageSize));
    $('pageInfo').textContent = `${state.page} / ${pages}`;
    $('prevPage').disabled = state.page <= 1;
    $('nextPage').disabled = state.page >= pages;
    document.querySelectorAll('#ledgerTable th[data-sort]').forEach(th => {
      th.dataset.mark = th.dataset.sort === state.sortBy ? (state.sortOrder === 'asc' ? '▲' : '▼') : '';
    });
    if (!data.items.length) {
      $('ledgerRows').innerHTML = `<tr><td colspan="${COLS}" class="tb-hint">조건에 맞는 계산서가 없습니다.</td></tr>`;
      return;
    }
    $('ledgerRows').innerHTML = data.items.map(r => `<tr class="${r.total < 0 ? 'minus' : ''}">
      <td>${esc(r.write_date)}</td><td>${esc(r.doc_type)}</td><td class="doc-cell">${docCell(r)}</td>
      <td class="clip" title="${esc(r.receiver_name)}">${esc(r.receiver_name)}</td><td>${esc(biz(r.receiver_corp_num))}</td>
      <td class="number">${num(r.supply_cost)}</td><td class="number">${num(r.tax)}</td><td class="number">${num(r.total)}</td>
      <td>${esc(r.source)}</td><td>${esc(r.issue_dt)}</td><td>${esc(r.created_at)}</td>
    </tr>`).join('');
    $('ledgerRows').querySelectorAll('.doc-fix').forEach(b => b.addEventListener('click', () => openDocEdit(b)));
  }

  // 감정서번호 고치기 — 칸 안에서 바로 적고 [저장] (엑셀로 등록한 출처만 버튼이 보인다)
  function openDocEdit(button) {
    const id = Number(button.dataset.id);
    const row = state.items.find(r => r.id === id);
    const cell = button.closest('td');
    cell.innerHTML = `<input class="doc-input" value="${esc(row ? row.doc_id : '')}" placeholder="감정서번호" style="width:120px"> <button class="doc-save" type="button">저장</button> <button class="doc-cancel" type="button">취소</button>`;
    const input = cell.querySelector('.doc-input');
    input.focus(); input.select();
    const save = () => saveDoc(id, input.value.trim());
    cell.querySelector('.doc-save').addEventListener('click', save);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') load().catch(showError); });
    cell.querySelector('.doc-cancel').addEventListener('click', () => { cell.innerHTML = docCell(row || { id, doc_id: '', editable: true }); cell.querySelector('.doc-fix').addEventListener('click', e => openDocEdit(e.currentTarget)); });
  }

  async function saveDoc(id, docId) {
    if (!docId) { toast('감정서번호를 적으세요.', true); return; }
    try {
      const res = await fetch(`/api/taxinvoice/external/ledger/${id}/doc`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requester_usr_seq: requester(), doc_id: docId }),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      toast(`감정서번호를 ${p.data.before || '(없음)'} → ${p.data.doc_id} 로 고쳤습니다.`);
      await load();
    } catch (e) {
      toast(e.message, true);
    }
  }

  const showError = e => {
    $('ledgerRows').innerHTML = `<tr><td colspan="${COLS}" class="tb-hint">${esc(e.message)}</td></tr>`;
    toast(e.message, true);
  };
  const search = () => { state.page = 1; load().catch(showError); };

  // 엑셀 등록 팝업 — 열면서 바로 파일 선택 창을 띄운다(같은 클릭 안이라 브라우저가 허락한다).
  // 닫히면(× · Esc) 올린 목록을 비우고 원장 목록을 다시 조회한다 (2026-09-11 사용자).
  function openUpload() {
    $('extDialog').showModal();
    $('exFile').click();
  }
  window.A10_TAX_LIST_RELOAD = () => load().catch(showError);
  $('extDialog').addEventListener('close', () => {
    if (window.A10_EXT_RESET) window.A10_EXT_RESET();
    load().catch(showError);
  });

  $('searchButton').addEventListener('click', search);
  $('keyword').addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
  ['docType', 'sourceFilter', 'officeCode', 'docFilter'].forEach(id => $(id).addEventListener('change', search));
  $('prevPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; load().catch(showError); } });
  $('nextPage').addEventListener('click', () => { state.page += 1; load().catch(showError); });
  $('openUpload').addEventListener('click', openUpload);
  $('closeUpload').addEventListener('click', () => $('extDialog').close());
  // 헤더 정렬 — 같은 칸을 다시 누르면 방향이 바뀐다 (열 너비 손잡이 클릭은 column-resize.js 가 막는다)
  document.querySelectorAll('#ledgerTable th[data-sort]').forEach(th => th.addEventListener('click', () => {
    const key = th.dataset.sort;
    state.sortOrder = state.sortBy === key && state.sortOrder === 'desc' ? 'asc' : 'desc';
    state.sortBy = key;
    search();
  }));
  $('exportExcel').addEventListener('click', () => {
    if (!state.total) { toast('내려받을 건이 없습니다. 먼저 조회하세요.', true); return; }
    window.A10_DOWNLOAD(`/api/taxinvoice/external/ledger/export.xlsx?${conditions()}`);
  });

  window.A10_READY.then(ctx => {
    // 이번 달 1일 ~ 오늘
    const d = new Date();
    const ymd = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
    $('dateFrom').value = ymd(new Date(d.getFullYear(), d.getMonth(), 1)); $('dateTo').value = ymd(d);
    if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('ledgerTable'), 'a10.taxRegister.columnWidths');
    if (ctx.office_id !== '10' || !ctx.is_operations) {   // 서버 API 도 같은 조건으로 막는다
      $('ledgerRows').innerHTML = `<tr><td colspan="${COLS}" class="tb-hint">계산서 등록은 본사 재무팀·집행부만 사용할 수 있습니다.</td></tr>`;
      $('searchButton').disabled = true; $('openUpload').disabled = true; $('exportExcel').disabled = true;
      return;
    }
    load().catch(showError);
  });
})();
