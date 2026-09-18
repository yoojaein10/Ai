// 업무실적 보고: 반월·기준으로 감정서를 조회하고 협회 양식 엑셀로 내보낸다.
// 지사는 자기 지사(A10_OFFICE)만 본다. 수기 추가/제외는 조회·다운로드에 반영.
// 기재사항(포함·제외 + 사유)은 (지사, 년, 월, 반월) 단위로 저장되며 기준과 무관하게 공유된다.
(function(){
  const $ = id => document.getElementById(id);
  let lastRows = [];  // 마지막 조회 결과(제외 체크 상태 유지용)
  let addingExtra = false;
  let notesLoaded = true;   // 저장소를 못 읽으면 편집을 잠근다(덮어쓰기 방지)
  let reasonSuggestions = [];
  const draft = new Map();  // 담당자가 실제로 건드린 감정서만 저장 대상

  function initControls(){
    const monthSelect = $('month');
    monthSelect.innerHTML = Array.from({length: 12}, (_, i) =>
      `<option value="${i + 1}">${i + 1}</option>`).join('');
    // 기본값: 앱 실행 시점 기준 (브라우저 로컬 날짜)
    const now = new Date();
    $('year').value = now.getFullYear();
    monthSelect.value = String(now.getMonth() + 1);
    // 업무실적은 지사별로 생성하므로 '전체'(all) 선택지는 제거 (context.js가 넣었다면)
    const office = $('officeCode');
    if(office){
      Array.from(office.options).forEach(opt => { if(opt.value === 'all') opt.remove(); });
    }
  }

  function params(){
    const query = new URLSearchParams({
      office_code: window.A10_OFFICE(),
      year: $('year').value,
      month: $('month').value,
      half: $('half').value,
      basis: $('basis').value,
    });
    // 기재사항 저장에 '누가 적었는지'가 필요하다. 엑셀 다운로드는 커스텀 헤더를
    // 실을 수 없어서(pywebview가 urllib로 경로만 요청) 쿼리로 보낸다.
    if(window.A10_USR) query.set('usr_seq', window.A10_USR);
    return query;
  }

  function extraDocs(){
    return $('extra').value.split(',').map(s => s.trim()).filter(Boolean);
  }

  function excludedDocs(){
    return Array.from(document.querySelectorAll('.wr-exclude:not(:checked)'))
      .map(cb => cb.dataset.doc);
  }

  const won = value => (value == null ? '' : Number(value).toLocaleString('ko-KR'));
  const esc = value => String(value == null ? '' : value)
    .replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function showActionStatus(message, isError, autoHide = true){
    let status = $('actionStatus');
    if(!status){
      status = document.createElement('span');
      status.id = 'actionStatus';
      status.className = 'wr-action-status';
      $('summary').appendChild(status);
    }
    status.textContent = message;
    status.classList.toggle('error', !!isError);
    clearTimeout(showActionStatus.timer);
    if(autoHide){
      showActionStatus.timer = setTimeout(() => {
        status.textContent = '';
        status.classList.remove('error');
      }, 5000);
    }
  }

  function kapaBadge(row){
    if(row.KAPA_REGISTERED === true) return '<span class="wr-badge reg">등록</span>';
    if(row.KAPA_REGISTERED === false) return '<span class="wr-badge unreg">미등록</span>';
    return '-';
  }

  // 입금 신호로만 잡혔는데 감정수수료(4010001) 계상이 전혀 없는 건 — 실비만 입금.
  function noFeeBadge(row){
    if(!row.NO_FEE) return '';
    return '<br><span class="wr-badge nofee" title="감정수수료 계상이 없는 입금(실비·기타수수료만)으로 보여 기본 제외했습니다. 보고하려면 체크하세요.">실비만</span>';
  }

  function staleBadge(row){
    if(!row.NOTE_STALE) return '';
    return '<br><span class="wr-badge stale" title="기재사항을 저장한 뒤 감정평가액·수수료가 바뀌었습니다. 내용을 다시 확인하세요.">금액변경</span>';
  }

  // 선례(PRECEDENT*)와 비대상(OUT_OF_SCOPE)은 배지로 표시하지 않는다(2026-08-06 사용자 결정).
  // 비대상 건은 기본 체크 해제 + 행 취소선으로 드러나고, 건수는 요약줄에 남긴다.

  // 담당자가 손대지 않았을 때의 기본 제외 사유들.
  // NOT_SENT(정비사업 발송전)는 여기 넣지 않는다 — 협회가 발송 전 상태로도 받는다고
  // 확인됐고(2026-08-07), 기본 제외로 두면 '발송 여부와 무관하게 보고한다'는 요구가
  // 무의미해진다. 대신 발송일·수수료가 비어 있으니 요약줄에 건수로 알린다.
  function autoExcluded(row){
    return !!row.NO_FEE || !!row.OUT_OF_SCOPE;
  }

  // 3상태 — 저장값이 있으면 그것이 이긴다. 없을 때만 자동기본값을 쓴다.
  // `saved || autoExcluded(row)` 같은 falsy 병합은 '일부러 포함(false)'을 되살려 버린다.
  function effectiveExcluded(row){
    const d = draft.get(row.ID_NUM);
    if(d && d.excluded != null) return d.excluded === true;
    if(row.NOTE_EXCLUDED != null) return row.NOTE_EXCLUDED === true;
    return autoExcluded(row);
  }

  function effectiveReason(row){
    const d = draft.get(row.ID_NUM);
    if(d && d.reason != null) return d.reason;
    return row.NOTE_REASON || '';
  }

  function touch(docId, patch){
    const row = lastRows.find(r => r.ID_NUM === docId) || {};
    const current = draft.get(docId) || {};
    draft.set(docId, Object.assign({
      excluded: row.NOTE_EXCLUDED != null ? row.NOTE_EXCLUDED : autoExcluded(row),
      reason: row.NOTE_REASON || '',
    }, current, patch));
    const tr = document.querySelector(`tr[data-doc="${CSS.escape(docId)}"]`);
    if(tr) tr.classList.add('dirty');
    updateSaveButton();
  }

  function updateSaveButton(){
    const button = $('saveNotesButton');
    if(!button) return;
    button.disabled = !notesLoaded || draft.size === 0;
    button.textContent = draft.size ? `기재사항 저장 (${draft.size})` : '기재사항 저장';
  }

  function render(data){
    lastRows = data.rows || [];
    draft.clear();
    notesLoaded = data.notes_loaded !== false;
    reasonSuggestions = data.reason_suggestions || [];
    const summary = $('summary');
    const kapaNote = data.kapa_checked
      ? ` · 협회 등록 <b>${data.kapa_registered_count}</b> / 미등록 <b>${data.count - data.kapa_registered_count}</b>`
      : ' · <span style="color:#c62828">협회 등록여부 확인불가</span>';
    const noFeeCount = lastRows.filter(row => row.NO_FEE).length;
    const noFeeNote = noFeeCount
      ? ` · 실비만 입금(기본 제외) <b>${noFeeCount}</b>건` : '';
    const outCount = lastRows.filter(row => row.OUT_OF_SCOPE).length;
    const outNote = outCount
      ? ` · 컨설팅 비대상(1천만↑, 기본 제외) <b>${outCount}</b>건` : '';
    // 정비사업+시군구라 발송 전인데 선례 규칙으로 끌어온 건. 협회 양식 필수칸
    // (발송일·수수료·물건구분)이 비어 있어 담당자가 채워야 한다.
    const notSent = lastRows.filter(row => row.NOT_SENT).length;
    const precNote = notSent
      ? ` · <b style="color:#c05f10">정비사업 발송전 ${notSent}건</b>(보고 대상 — 발송일·수수료 비어 있으니 확인)` : '';
    const noteNote = notesLoaded
      ? (data.note_count ? ` · 기재사항 <b>${data.note_count}</b>건` : '')
      : ' · <span style="color:#c62828">기재사항을 불러오지 못해 편집이 잠겼습니다</span>';
    // 저장본 복원 여부 — 복원 중이면 자동선택을 돌리지 않았으므로 그 사실을 분명히 알린다.
    const savedMeta = data.saved_list || {};
    const savedWhen = savedMeta.saved_at
      ? ` ${esc(String(savedMeta.saved_at).slice(0, 16).replace('T', ' '))}`
      + `${savedMeta.saved_by ? ' ' + esc(savedMeta.saved_by) : ''}` : '';
    const savedNote = data.restored
      ? ` · <b style="color:#1c7c3f">저장본 복원 ${savedMeta.count || data.count}건</b>(${savedWhen.trim() || '저장됨'})`
      : (savedMeta.count ? ` · 저장본 <b>${savedMeta.count}</b>건 있음` : '');
    const pickedLabel = data.restored ? '목록' : '자동선택';
    summary.innerHTML = `분기 <b>${esc(data.bungi)}</b> · ${esc($('month').value)}월 ${esc($('half').value)} `
      + `· 기준 <b>${esc($('basis').value)}</b> · ${pickedLabel} <b>${data.count}</b>건`
      + `${savedNote}${kapaNote}${noFeeNote}${outNote}${precNote}${noteNote}`
      + '<span id="actionStatus" class="wr-action-status"></span>';
    updateSaveButton();
    if(!lastRows.length){
      $('tableWrap').innerHTML = '';
      $('empty').textContent = '해당 조건에 자동 선택된 감정서가 없습니다. 필요하면 수기로 추가하세요.';
      $('empty').style.display = '';
      return;
    }
    $('empty').style.display = 'none';
    const lock = notesLoaded ? '' : ' disabled';
    const body = lastRows.map(row => {
      const off = effectiveExcluded(row);
      // 목록 안에서 찾기용 — 한 줄에 검색 대상 값을 모아둔다(소문자).
      // 배지를 안 쓰기로 했으니 '발송전'으로 검색해 찾을 수 있게 토큰을 넣는다.
      const hay = [row.ID_NUM, row.PNAME, row.PCODE, row.YNAME, row.GNAME, row.CUST,
                   row.WORK_INFO, row.NOT_SENT ? '발송전' : '']
                  .filter(Boolean).join(' ').toLowerCase();
      return `<tr data-doc="${esc(row.ID_NUM)}" data-find="${esc(hay)}"${off ? ' class="excluded"' : ''}>
      <td><input type="checkbox" class="wr-exclude" data-doc="${esc(row.ID_NUM)}"${off ? '' : ' checked'}></td>
      <td>${kapaBadge(row)}${noFeeBadge(row)}${staleBadge(row)}</td>
      <td>${esc(row.ID_NUM)}</td>
      <td title="코드 ${esc(row.PCODE)}">${esc(row.PNAME || row.PCODE)}</td>
      <td title="코드 ${esc(row.YCODE)}">${esc(row.YNAME || row.YCODE)}</td>
      <td class="name">${esc(row.GNAME)}</td>
      <td>${esc(row.CUST)}</td>
      <td class="num">${won(row.GAMGA)}</td>
      <td class="num">${won(row.FEE)}</td>
      <td class="note"><input type="text" class="wr-note" list="reasonList" data-doc="${esc(row.ID_NUM)}"
        value="${esc(effectiveReason(row))}" placeholder="사유"${lock}
        title="${row.NOTE_UPDATED_BY ? esc(row.NOTE_UPDATED_BY) + ' 작성' : ''}"
        ><button type="button" class="wr-note-reset" data-doc="${esc(row.ID_NUM)}"
        title="자동값으로 되돌리기(저장된 기재사항 삭제)"${lock}>↺</button></td>
    </tr>`;
    }).join('');
    $('tableWrap').innerHTML = `<datalist id="reasonList">${
        reasonSuggestions.map(s => `<option value="${esc(s)}"></option>`).join('')
      }</datalist>
      <table id="wrTable" class="wr-table">
      <colgroup><col style="width:44px"><col style="width:64px"><col style="width:130px">
      <col style="width:170px"><col style="width:90px"><col style="width:320px">
      <col style="width:170px"><col style="width:110px"><col style="width:100px">
      <col style="width:220px"></colgroup>
      <thead><tr><th class="num">포함</th><th>협회</th><th>감정서번호</th><th>목적</th><th>구분</th>
      <th>건명</th><th>의뢰처</th><th class="num">감정평가액</th><th class="num">청구수수료</th>
      <th>기재사항</th></tr></thead>
      <tbody>${body}</tbody></table>`;
    applyFind(false);
    document.querySelectorAll('.wr-exclude').forEach(cb =>
      cb.addEventListener('change', () => {
        cb.closest('tr').classList.toggle('excluded', !cb.checked);
        if(notesLoaded) touch(cb.dataset.doc, {excluded: !cb.checked});
      }));
    document.querySelectorAll('.wr-note').forEach(input =>
      input.addEventListener('change', () => touch(input.dataset.doc, {reason: input.value})));
    document.querySelectorAll('.wr-note-reset').forEach(button =>
      button.addEventListener('click', () => resetNote(button.dataset.doc)));
    if (window.A10_COLUMN_RESIZE)
      window.A10_COLUMN_RESIZE(document.getElementById('wrTable'), 'a10.workReport.columnWidths');
  }

  async function resetNote(docId){
    if(!notesLoaded) return;
    if(!window.confirm(`${docId}의 저장된 기재사항을 지우고 자동값으로 되돌립니다.\n계속할까요?`)){
      showActionStatus('전송을 취소했습니다.');
      return;
    }
    const ok = await sendNotes({[docId]: null});
    if(ok) await run();
  }

  async function sendNotes(payload){
    const query = params();
    try{
      const response = await fetch(`/api/work-report/notes?${query.toString()}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({notes: payload}),
      });
      const body = await response.json();
      if(!response.ok || !body.success){
        throw new Error(body.detail || body.message || '기재사항을 저장하지 못했습니다.');
      }
      const rejected = (body.data && body.data.rejected) || [];
      if(rejected.length){
        showActionStatus(`${rejected[0].doc_id}: ${rejected[0].message}`, true);
      }else{
        showActionStatus(body.message);
      }
      return true;
    }catch(error){
      showActionStatus(error.message, true);
      return false;
    }
  }

  async function saveNotes(){
    if(!draft.size) return;
    const payload = {};
    draft.forEach((value, docId) => {
      payload[docId] = {excluded: !!value.excluded, reason: value.reason || ''};
    });
    const button = $('saveNotesButton');
    button.disabled = true;
    try{
      if(await sendNotes(payload)) await run();
    }finally{
      updateSaveButton();
    }
  }

  // 조회된 목록에서 '어디 있는지' 찾아준다. 거르지 않는다 —
  // 맞는 행을 표시하고 그 위치로 스크롤할 뿐, 목록은 그대로 둔다.
  // (행을 숨기거나 다시 그리면 체크 상태와 입력 중인 기재사항이 흐트러진다)
  let findHits = [];
  let findIndex = 0;

  function applyFind(jumpNext){
    const input = $('rowFilter');
    const table = document.getElementById('wrTable');
    const label = $('filterCount');
    if(!input || !table) return;
    const q = input.value.trim().toLowerCase();
    findHits = [];
    table.querySelectorAll('tbody tr').forEach(tr => {
      tr.classList.remove('found-current');
      const hit = !!q && (tr.dataset.find || '').includes(q);
      tr.classList.toggle('found', hit);
      if(hit) findHits.push(tr);
    });
    if(!q){ findIndex = 0; if(label) label.textContent = ''; return; }
    if(!findHits.length){
      findIndex = 0;
      if(label) label.textContent = '찾는 건이 없습니다';
      return;
    }
    findIndex = jumpNext ? (findIndex + 1) % findHits.length : 0;
    const target = findHits[findIndex];
    target.classList.add('found-current');
    target.scrollIntoView({block: 'center', behavior: 'smooth'});
    if(label){
      label.textContent = findHits.length > 1
        ? `${findIndex + 1} / ${findHits.length}건 (Enter로 다음)`
        : '1건';
    }
  }

  function selectUnregisteredOnly(){
    if(!lastRows.length){ window.A10_TOAST('먼저 조회하세요.', true); return; }
    if(lastRows[0].KAPA_REGISTERED === null || lastRows[0].KAPA_REGISTERED === undefined){
      window.A10_TOAST('협회 등록여부를 확인하지 못한 조회입니다.', true); return;
    }
    const byDoc = Object.fromEntries(lastRows.map(row => [row.ID_NUM, row]));
    let picked = 0, skippedNoFee = 0, skippedNote = 0;
    document.querySelectorAll('.wr-exclude').forEach(cb => {
      const row = byDoc[cb.dataset.doc] || {};
      // 담당자가 남긴 결정(저장분·편집분)은 일괄 선택이 덮지 않는다.
      if(row.NOTE_EXCLUDED != null || draft.has(cb.dataset.doc)){
        skippedNote += 1;
        return;
      }
      // 미등록만 체크하되, 자동 제외 사유가 있는 건(실비만 입금·컨설팅 비대상)은 계속 제외
      const keep = row.KAPA_REGISTERED === false && !autoExcluded(row);
      if(row.KAPA_REGISTERED === false && autoExcluded(row)) skippedNoFee += 1;
      cb.checked = keep;
      cb.closest('tr').classList.toggle('excluded', !keep);
      if(keep) picked += 1;
    });
    const notes = [];
    if(skippedNoFee) notes.push(`자동 제외 ${skippedNoFee}건 유지`);
    if(skippedNote) notes.push(`기재사항 있는 ${skippedNote}건 그대로 유지`);
    window.A10_TOAST(`미등록 ${picked}건만 선택했습니다.${notes.length ? ` (${notes.join(', ')})` : ''}`);
  }

  async function run(fresh){
    if(draft.size && !window.confirm(
      `저장하지 않은 기재사항 ${draft.size}건이 있습니다.\n다시 조회하면 사라집니다. 계속할까요?`)) return null;
    const query = params();
    query.set('extra', extraDocs().join(','));
    // fresh=true 면 저장본을 무시하고 원천에서 다시 뽑는다.
    if(fresh) query.set('fresh', 'true');
    $('empty').textContent = '조회 중...';
    $('empty').style.display = '';
    try{
      const response = await fetch(`/api/work-report/preview?${query.toString()}`);
      const payload = await response.json();
      if(!payload.success) throw new Error(payload.message || '조회에 실패했습니다.');
      render(payload.data);
      return payload.data;
    }catch(error){
      window.A10_TOAST(error.message, true);
      $('empty').textContent = '조회에 실패했습니다.';
      return null;
    }
  }

  async function addExtra(){
    if(addingExtra) return;
    const requested = extraDocs();
    if(!requested.length){
      showActionStatus('추가할 감정서번호를 입력하세요.', true);
      return;
    }
    const button = $('addExtraButton');
    addingExtra = true;
    button.disabled = true;
    button.textContent = '추가 중';
    showActionStatus('추가 중', false, false);
    try{
      const data = await run();
      if(!data){
        showActionStatus('추가하지 못했습니다.', true);
        return;
      }
      const found = new Set((data.rows || []).map(row => row.ID_NUM));
      if(requested.every(doc => found.has(doc))){
        showActionStatus('추가되었습니다.');
      }else{
        showActionStatus('추가되지 않은 감정서번호가 있습니다. 번호와 소속 지사를 확인하세요.', true);
      }
    }finally{
      addingExtra = false;
      button.disabled = false;
      button.textContent = '추가';
    }
  }

  async function importExcel(file){
    if(!file){
      showActionStatus('엑셀 파일을 선택하세요.', true);
      return;
    }
    const button = $('importExcelButton');
    const form = new FormData();
    form.append('file', file);
    button.disabled = true;
    button.textContent = '불러오는 중...';
    try{
      const response = await fetch('/api/work-report/import', {method: 'POST', body: form});
      const payload = await response.json();
      if(!payload.success) throw new Error(payload.message || '엑셀을 불러오지 못했습니다.');
      $('extra').value = (payload.data.doc_ids || []).join(', ');
      await addExtra();
    }catch(error){
      showActionStatus(error.message, true);
    }finally{
      button.disabled = false;
      button.textContent = '엑셀 업로드';
      $('importExcelFile').value = '';
    }
  }

  function exportXlsx(){
    const query = params();
    query.set('extra', extraDocs().join(','));
    query.set('exclude', excludedDocs().join(','));
    window.A10_DOWNLOAD(`/api/work-report/export.xlsx?${query.toString()}`);
  }

  async function submitToKapa(){
    const include = document.querySelectorAll('.wr-exclude:checked').length;
    if(!lastRows.length || !include){
      window.A10_TOAST('먼저 "조회"로 전송할 목록을 확인하세요.', true);
      return;
    }
    if(draft.size && !window.confirm(
      `저장하지 않은 기재사항 ${draft.size}건이 있습니다.\n저장하지 않고 전송할까요?`)){
      showActionStatus('전송을 취소했습니다.');
      return;
    }
    const extra = extraDocs().length ? ` (+수기 ${extraDocs().length})` : '';
    if(!window.confirm(
      `선택한 업무실적 ${include}건${extra} 중 미등록 건을 협회에 추가합니다.\n`
      + `협회 기존 자료를 먼저 불러와 보존한 상태로 전체 병합 전송합니다.\n`
      + `전송 이력은 협회에서 모니터링되며 되돌릴 수 없습니다.\n계속할까요?`)) return;
    const button = document.getElementById('submitButton');
    button.disabled = true;
    button.textContent = '전송 중...';
    showActionStatus('협회로 전송 중...', false, false);
    try{
      const query = params();
      query.set('extra', extraDocs().join(','));
      query.set('exclude', excludedDocs().join(','));
      query.set('confirm', 'true');
      const response = await fetch(`/api/work-report/submit?${query.toString()}`, {method: 'POST'});
      const payload = await response.json();
      const d = payload.data || {};
      if(d.success){
        const done = `협회 전송 완료 · 기존 보존 ${d.preserved_count ?? '?'}건 / `
          + `신규 추가 ${d.added_count ?? '?'}건 / 전체 ${d.count ?? '?'}건`;
        window.A10_TOAST(done);
        showActionStatus(done, false, false);   // 토스트가 사라져도 남는다
      }else{
        // 서버가 붙여 준 안내(어느 감정서가 문제인지)가 협회 원문보다 쓸모 있다.
        const reason = (payload.message || '').startsWith('전송 실패')
          ? payload.message : `전송 실패: ${d.message || payload.message}`;
        window.A10_TOAST(reason, true);
        showActionStatus(reason, true, false);
      }
    }catch(error){
      window.A10_TOAST(`전송 오류: ${error.message}`, true);
      showActionStatus(`전송 오류: ${error.message}`, true, false);
    }finally{
      button.disabled = false;
      button.textContent = '협회 전송';
    }
  }

  // ── 여러 달 누락분 확인 ──────────────────────────────────────────────────
  // 기간을 지정해 여러 회차를 훑어 협회 미등록(누락) 건을 모으고, 고른 건을 현재
  // 열어둔 회차의 '수기 추가'로 넣는다(추가는 기존 addExtra 배관을 그대로 쓴다).
  let missingRows = [];

  function pad2(n){ return String(n).padStart(2, '0'); }
  function monthInputValue(year, month){ return `${year}-${pad2(month)}`; }
  function parseMonthInput(value){
    const match = /^(\d{4})-(\d{2})$/.exec(value || '');
    if(!match) return null;
    return {year: Number(match[1]), month: Number(match[2])};
  }

  function openMissing(){
    // 기본값: 기준은 현재 화면, 끝은 현재 회차 월, 시작은 3개월 전.
    $('missingBasis').value = $('basis').value;
    const year = Number($('year').value);
    const month = Number($('month').value);
    $('missingTo').value = monthInputValue(year, month);
    const fromIndex = year * 12 + (month - 1) - 3;
    $('missingFrom').value = monthInputValue(Math.floor(fromIndex / 12), fromIndex % 12 + 1);
    missingRows = [];
    $('missingBody').innerHTML = '<p class="wr-hint">기준과 기간(최대 12개월)을 고르고 '
      + '"누락 조회"를 누르세요. 그 달 보고 대상인데 협회에 아직 없는 건을 모아 보여줍니다.</p>';
    $('missingPick').textContent = '';
    $('missingAdd').disabled = true;
    $('missingStatus').textContent = '';
    $('missingOverlay').hidden = false;
  }

  function closeMissing(){ $('missingOverlay').hidden = true; }

  async function runMissingScan(){
    const from = parseMonthInput($('missingFrom').value);
    const to = parseMonthInput($('missingTo').value);
    if(!from || !to){
      setMissingStatus('기간(시작~끝)을 올바르게 고르세요.', true); return;
    }
    const query = new URLSearchParams({
      office_code: window.A10_OFFICE(),
      basis: $('missingBasis').value,
      from_year: from.year, from_month: from.month,
      to_year: to.year, to_month: to.month,
      cur_year: $('year').value, cur_month: $('month').value,
    });
    const button = $('missingRun');
    button.disabled = true;
    setMissingStatus('협회 조회 중… 달마다 협회 서버를 확인하므로 다소 걸립니다.', false);
    try{
      const response = await fetch(`/api/work-report/missing?${query.toString()}`);
      const payload = await response.json();
      if(!payload.success) throw new Error(payload.message || '누락 조회에 실패했습니다.');
      renderMissing(payload.data);
    }catch(error){
      setMissingStatus(error.message, true);
      $('missingBody').innerHTML = '<p class="wr-hint">누락을 확인하지 못했습니다.</p>';
      missingRows = [];
      $('missingAdd').disabled = true;
      $('missingPick').textContent = '';
    }finally{
      button.disabled = false;
    }
  }

  function setMissingStatus(message, isError){
    const el = $('missingStatus');
    el.textContent = message;
    el.classList.toggle('error', !!isError);
  }

  function missFlags(row){
    const flags = [];
    if(row.NO_FEE) flags.push('실비만 입금');
    if(row.OUT_OF_SCOPE) flags.push('컨설팅 초과');
    if(row.NOT_SENT) flags.push('발송전');
    return flags.length ? `<span class="wr-miss-flag">${esc(flags.join(' · '))}</span>` : '';
  }

  function renderMissing(data){
    missingRows = data.rows || [];
    setMissingStatus(
      `${data.from}~${data.to} · 기준 ${data.basis} · 협회 등록 ${data.registered_count}건 확인`, false);
    if(!missingRows.length){
      $('missingBody').innerHTML = '<p class="wr-hint">이 기간에 협회 미등록(누락) 건이 없습니다.</p>';
      $('missingPick').textContent = '';
      $('missingAdd').disabled = true;
      return;
    }
    const body = missingRows.map((row, index) => `<tr>
      <td><input type="checkbox" class="wr-miss-cb" data-index="${index}"${row.default_include ? ' checked' : ''}></td>
      <td>${esc(row.period_label)}</td>
      <td>${esc(row.ID_NUM)}</td>
      <td>${esc(row.PNAME || '')}</td>
      <td class="name">${esc(row.GNAME || '')}${missFlags(row)}</td>
      <td>${esc(row.CUST || '')}</td>
      <td class="num">${won(row.GAMGA)}</td>
      <td class="num">${won(row.SUSU != null ? row.SUSU : row.FEE)}</td>
    </tr>`).join('');
    $('missingBody').innerHTML = `<table class="wr-miss-table">
      <thead><tr><th>추가</th><th>회차</th><th>감정서번호</th><th>목적</th><th>건명</th>
      <th>의뢰처</th><th class="num">감정평가액</th><th class="num">수수료</th></tr></thead>
      <tbody>${body}</tbody></table>`;
    document.querySelectorAll('.wr-miss-cb').forEach(cb =>
      cb.addEventListener('change', updateMissingPick));
    updateMissingPick();
  }

  function updateMissingPick(){
    const picked = document.querySelectorAll('.wr-miss-cb:checked').length;
    const cur = `${$('year').value}.${pad2($('month').value)} ${$('half').value}`;
    $('missingPick').textContent = picked
      ? `${picked}건 선택 — 현재 회차(${cur})에 추가됩니다`
      : `추가할 건을 선택하세요 (현재 회차 ${cur})`;
    $('missingAdd').disabled = picked === 0;
  }

  async function addSelectedMissing(){
    const picked = Array.from(document.querySelectorAll('.wr-miss-cb:checked'))
      .map(cb => missingRows[Number(cb.dataset.index)])
      .filter(Boolean).map(row => String(row.ID_NUM).trim()).filter(Boolean);
    if(!picked.length) return;
    // 기존 수기 추가값과 합치되 중복은 뺀다.
    const merged = Array.from(new Set([...extraDocs(), ...picked]));
    $('extra').value = merged.join(', ');
    closeMissing();
    await addExtra();
  }

  // 화면에 떠 있는 목록 전체 — 저장에 그대로 보낸다(멤버십 + 체크 + 사유).
  function currentRows(){
    return Array.from(document.querySelectorAll('#wrTable tbody tr')).map(tr => {
      const checkbox = tr.querySelector('.wr-exclude');
      const note = tr.querySelector('.wr-note');
      return {
        doc_id: tr.dataset.doc,
        excluded: checkbox ? !checkbox.checked : false,  // 체크 = 포함
        reason: note ? note.value : '',
      };
    }).filter(row => row.doc_id);
  }

  // 작업 저장 — 목록을 통째로 남긴다. 다시 열면 이 목록이 그대로 복원된다.
  async function saveList(){
    const rows = currentRows();
    if(!rows.length){ window.A10_TOAST('먼저 조회하세요.', true); return; }
    const button = $('saveListButton');
    button.disabled = true;
    button.textContent = '저장 중...';
    try{
      const response = await fetch(`/api/work-report/list?${params().toString()}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rows}),
      });
      const body = await response.json();
      if(!response.ok || !body.success){
        throw new Error(body.detail || body.message || '작업 목록을 저장하지 못했습니다.');
      }
      draft.clear();
      updateSaveButton();
      showActionStatus(body.message);
      window.A10_TOAST(body.message);
    }catch(error){
      showActionStatus(error.message, true);
      window.A10_TOAST(error.message, true);
    }finally{
      button.disabled = false;
      button.textContent = '작업 저장';
    }
  }

  window.A10_READY.then(() => {
    initControls();
    // run 을 그대로 넘기면 DOM 이 첫 인자로 PointerEvent 를 줘서 fresh 가 항상 참이 된다.
    $('runButton').addEventListener('click', () => run(false));
    $('freshButton').addEventListener('click', () => run(true));
    $('saveListButton').addEventListener('click', saveList);
    $('missingButton').addEventListener('click', openMissing);
    $('missingClose').addEventListener('click', closeMissing);
    $('missingRun').addEventListener('click', runMissingScan);
    $('missingAdd').addEventListener('click', addSelectedMissing);
    $('missingOverlay').addEventListener('click', event => {
      if(event.target === $('missingOverlay')) closeMissing();  // 바깥 클릭으로 닫기
    });
    $('extra').addEventListener('keydown', async event => {
      if(event.key !== 'Enter' || event.isComposing) return;
      event.preventDefault();
      await addExtra();
    });
    $('addExtraButton').addEventListener('click', addExtra);
    $('importExcelButton').addEventListener('click', () => importExcel($('importExcelFile').files[0]));
    $('exportButton').addEventListener('click', exportXlsx);
    $('selectUnregButton').addEventListener('click', selectUnregisteredOnly);
    $('submitButton').addEventListener('click', submitToKapa);
    $('saveNotesButton').addEventListener('click', saveNotes);
    $('rowFilter').addEventListener('input', () => applyFind(false));
    $('rowFilter').addEventListener('keydown', event => {
      if(event.key === 'Escape'){ $('rowFilter').value = ''; applyFind(false); return; }
      if(event.key === 'Enter' && !event.isComposing){
        event.preventDefault();
        applyFind(true);   // 같은 검색어로 다음 건
      }
    });
    updateSaveButton();
  });
})();
