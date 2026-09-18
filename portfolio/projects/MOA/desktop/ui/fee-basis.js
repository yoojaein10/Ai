// 보수기준 점검: 업무실적 모집단에서 수수료청구서 입력값 vs 자동판별 보수기준 비교.
// 자동판별 근거(목적·본문 발췌·이력)를 행 안에 함께 보여준다. 본사 전용 화면.
(function(){
  const $ = id => document.getElementById(id);

  function initControls(){
    const monthSelect = $('month');
    monthSelect.innerHTML = Array.from({length: 12}, (_, i) =>
      `<option value="${i + 1}">${i + 1}</option>`).join('');
    const now = new Date();
    $('year').value = now.getFullYear();
    monthSelect.value = String(now.getMonth() + 1);
    const office = $('officeCode');
    if(office){
      Array.from(office.options).forEach(opt => { if(opt.value === 'all') opt.remove(); });
    }
  }

  function params(){
    return new URLSearchParams({
      office_code: window.A10_OFFICE(),
      year: $('year').value,
      month: $('month').value,
      half: $('half').value,
      basis: $('basis').value,
      flt: $('flt').value,
    });
  }

  const esc = value => String(value == null ? '' : value)
    .replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function verdictBadge(item){
    const map = {'일치': 'match', '불일치': 'mismatch', '미입력': 'missing'};
    const cls = map[item.verdict] || 'noparse';
    const noparse = item.parsed ? '' : '<br><span class="fb-badge noparse" title="감정서 PDF가 파싱되지 않아 본문 근거 없이 목적·이력만으로 판별했습니다">파싱없음</span>';
    return `<span class="fb-badge ${cls}">${esc(item.verdict)}</span>${noparse}`;
  }

  function candidateList(item){
    const rows = (item.candidates || []).map(cand => {
      const page = cand.page ? ` p${cand.page}` : '';
      return `<li><span class="src">${esc(cand.source)}${page}</span>`
        + `<span class="lbl">${esc(cand.label)}</span>`
        + `<span class="ev">${esc(cand.evidence)}</span></li>`;
    });
    return `<ul class="fb-cand">${rows.join('')}</ul>`;
  }

  function render(data){
    const s = data.summary || {};
    $('summary').innerHTML = `총 <b>${s.total ?? 0}</b>건`
      + ` · 일치 <b>${s.match ?? 0}</b>`
      + ` · <span style="color:#c62828">불일치 <b>${s.mismatch ?? 0}</b></span>`
      + ` · <span style="color:#c05f10">미입력 <b>${s.missing ?? 0}</b></span>`
      + ` · 본문 파싱 <b>${s.parsed ?? 0}</b>건`;
    const items = data.items || [];
    if(!items.length){
      $('tableWrap').innerHTML = '';
      $('empty').textContent = '조건에 맞는 감정서가 없습니다.';
      $('empty').style.display = '';
      return;
    }
    $('empty').style.display = 'none';
    const body = items.map(item => `<tr>
      <td>${verdictBadge(item)}</td>
      <td class="fb-doc">${esc(item.doc_id)}</td>
      <td class="fb-doc">${esc(item.receipt_date || '')}</td>
      <td>${esc(item.cust_name)}</td>
      <td>${esc(item.work)}${item.purpose ? ' / ' + esc(item.purpose) : ''}</td>
      <td>${esc(item.manager)}</td>
      <td class="fb-entered">${esc(item.entered_label) || '<span style="color:var(--muted)">-</span>'}${item.entered_bigo ? `<br><small>${esc(item.entered_bigo)}</small>` : ''}</td>
      <td>${candidateList(item)}</td>
    </tr>`).join('');
    $('tableWrap').innerHTML = `<table id="fbTable" class="fb-table">
      <colgroup><col style="width:78px"><col style="width:126px"><col style="width:92px">
      <col style="width:170px"><col style="width:180px"><col style="width:90px">
      <col style="width:220px"><col></colgroup>
      <thead><tr><th>판정</th><th>감정서번호</th><th>접수일</th><th>거래처</th>
      <th>업무 / 세부목적</th><th>유치자</th><th>입력된 보수기준</th><th>자동판별 (근거)</th></tr></thead>
      <tbody>${body}</tbody></table>`;
    if (window.A10_COLUMN_RESIZE)
      window.A10_COLUMN_RESIZE(document.getElementById('fbTable'), 'a10.feeBasis.columnWidths');
  }

  async function run(){
    const button = $('runButton');
    button.disabled = true;
    $('tableWrap').innerHTML = '';
    $('empty').textContent = '조회 중... (모집단 선택 + 본문 스캔에 30초 안팎 걸립니다)';
    $('empty').style.display = '';
    try{
      const query = params();
      query.set('page_size', '1000');
      const response = await fetch(`/api/fee-basis?${query.toString()}`);
      const payload = await response.json();
      if(!payload.success) throw new Error(payload.message || '조회에 실패했습니다.');
      render(payload.data);
    }catch(error){
      window.A10_TOAST(error.message, true);
      $('empty').textContent = '조회에 실패했습니다.';
    }finally{
      button.disabled = false;
    }
  }

  function exportXlsx(){
    window.A10_DOWNLOAD(`/api/fee-basis/export.xlsx?${params().toString()}`);
  }

  window.A10_READY.then(() => {
    initControls();
    $('runButton').addEventListener('click', run);
    $('exportButton').addEventListener('click', exportXlsx);
  });
})();
