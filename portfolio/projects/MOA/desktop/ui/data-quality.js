// 데이터 품질 점검 (본사 전용). 회계 입력 실수를 자동 감지해 정정 목록을 보여준다.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const inputDate = d => { const o = d.getTimezoneOffset() * 60000; return new Date(d - o).toISOString().slice(0, 10); };

let lastData = null;

async function runChecks() {
  const from = $('dateFrom').value, to = $('dateTo').value;
  if (!from || !to) { showToast('기간을 선택하세요.', true); return; }
  $('summary').textContent = '점검 중...';
  $('checks').innerHTML = '';
  $('searchButton').disabled = true;
  try {
    const res = await fetch(`/api/data-quality?date_from=${from}&date_to=${to}`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    lastData = p.data;
    render(p.data);
  } catch (e) {
    $('summary').textContent = '점검하지 못했습니다: ' + e.message;
  } finally {
    $('searchButton').disabled = false;
  }
}

function render(data) {
  const total = data.total_issues;
  $('summary').innerHTML = total === 0
    ? `점검 완료 · <b style="color:#1b7a43">이상 없음</b> (${data.period.from} ~ ${data.period.to})`
    : `점검 완료 · 발견 <b>${money.format(total)}건</b> (${data.period.from} ~ ${data.period.to}) — 아래에서 항목별 확인`;
  $('checks').innerHTML = data.checks.map((c, i) => {
    const zero = c.count === 0;
    const rows = c.items.map(it => `<tr>
      <td class="doc" data-doc="${esc(it.doc || '')}">${esc(it.doc || '(빈값)')}</td>
      <td class="num">${money.format(Math.round(it.amount || 0))}</td>
      <td class="num">${'lines' in it && it.lines != null ? it.lines : ''}</td>
      <td class="remark" title="${esc(it.remark || '')}">${esc(it.remark || '')}</td>
      <td class="reason" title="${esc(it.reason || '')}">${esc(it.reason || '')}</td>
    </tr>`).join('');
    return `<section class="dq-check">
      <div class="dq-head" data-i="${i}">
        <div><h2>${esc(c.title)} <span class="cnt ${zero ? 'zero' : 'some'}">${money.format(c.count)}건</span></h2>
          <p class="dq-desc">${esc(c.desc)}</p></div>
        <div>${zero ? '' : `합계 ${money.format(Math.round(c.amount))}원 · <button class="dq-export" data-k="${c.key}" type="button">엑셀</button>`}</div>
      </div>
      <div class="dq-body" id="body-${i}">
        ${zero ? '<div class="dq-empty">이상 없음 ✅</div>' :
          `<table class="dq-table"><colgroup><col class="c-doc"><col class="c-amt"><col class="c-lines"><col class="c-rmk"><col></colgroup><thead><tr><th>관리번호/감정서번호</th><th class="num">금액</th><th class="num">행수</th><th>적요</th><th>문제 원인</th></tr></thead><tbody>${rows}</tbody></table>`}
      </div>
    </section>`;
  }).join('');
  // 접기/펴기
  document.querySelectorAll('.dq-head').forEach(h => h.addEventListener('click', e => {
    if (e.target.closest('.dq-export')) return;
    const body = $('body-' + h.dataset.i);
    body.style.display = body.style.display === 'none' ? '' : 'none';
  }));
  document.querySelectorAll('.dq-export').forEach(b => b.addEventListener('click', () => exportCsv(b.dataset.k)));
  if (window.A10_COLUMN_RESIZE)
    document.querySelectorAll('.dq-table').forEach((t, i) =>
      window.A10_COLUMN_RESIZE(t, `a10.dataQuality.columnWidths.${i}`));
  // 관리번호 클릭 → 오른쪽에 전표
  document.querySelectorAll('.dq-table td.doc').forEach(td => td.addEventListener('click', () => {
    document.querySelectorAll('.dq-table tr.sel').forEach(r => r.classList.remove('sel'));
    td.parentElement.classList.add('sel');
    loadVoucher(td.dataset.doc);
  }));
}

async function loadVoucher(doc) {
  const box = $('detail');
  if (!doc) { box.className = 'ph'; box.textContent = '관리번호가 비어 있어 전표를 조회할 수 없습니다.'; return; }
  box.className = 'ph'; box.textContent = `${doc} 전표 불러오는 중...`;
  try {
    const res = await fetch(`/api/appraisals/${encodeURIComponent(doc)}/vouchers`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    const items = p.data.items || [];
    const lines = items.flatMap(v => (v.lines || []).map(ln => {
      const amt = Number(ln.amount || 0), dr = String(ln.debit_credit) === '3';
      return `<tr${ln.offset ? ' class="offset"' : ''}>
        <td>${esc((v.voucher_date || '').slice(0, 10))}</td>
        <td title="${esc(ln.offset_note || '')}">${ln.offset ? '<span class="offset-badge">반제</span>' : ''}${esc(ln.account_name || ln.account_code || '')}</td>
        <td class="num ${dr ? 'dr' : ''}">${dr ? money.format(amt) : ''}</td>
        <td class="num ${dr ? '' : 'cr'}">${dr ? '' : money.format(amt)}</td>
        <td title="${esc(ln.remark || '')}">${esc((ln.remark || '').slice(0, 18))}</td>
      </tr>`;
    })).join('');
    // 세금계산서·현금영수증 (MOA 발급분 + TAMS)
    const taxes = p.data.tax_invoices || [];
    const taxRows = taxes.map(t => `<tr>
      <td>${esc((t.tax_date || '').slice(0, 10))}</td>
      <td title="${esc(t.company_name || '')}">${esc((t.company_name || '-').slice(0, 12))}</td>
      <td>${esc(t.issue_type || '-')}</td>
      <td class="num">${money.format(Math.round(t.supply_amount || 0))}</td>
      <td class="num">${money.format(Math.round(t.total_amount || 0))}</td>
    </tr>`).join('');
    const taxHtml = taxes.length
      ? `<div style="font-weight:700;margin:12px 0 4px">세금계산서 / 현금영수증</div>
         <table class="dq-vtable"><thead><tr><th>일자</th><th>상호</th><th>구분</th><th class="num">공급가</th><th class="num">합계</th></tr></thead><tbody>${taxRows}</tbody></table>`
      : `<div style="font-weight:700;margin:12px 0 4px">세금계산서 / 현금영수증</div><div class="ph" style="padding:10px 0">발행 내역 없음</div>`;

    box.className = '';
    box.innerHTML = (lines
      ? `<div style="font-weight:700;margin-bottom:4px">${esc(doc)} · 전표</div>
         <table class="dq-vtable"><thead><tr><th>전표일</th><th>계정</th><th class="num">차변</th><th class="num">대변</th><th>적요</th></tr></thead><tbody>${lines}</tbody></table>`
      : `<div class="ph">${esc(doc)} — 연결된 전표가 없습니다.</div>`) + taxHtml;
  } catch (e) {
    box.className = 'ph'; box.textContent = '전표 조회 실패: ' + e.message;
  }
}

// 데스크톱 앱(pywebview)은 Blob 다운로드가 안 되므로 서버가 만든 엑셀을 받는다.
function exportCsv(key) {
  if (!lastData) { showToast('먼저 점검을 실행하세요.', true); return; }
  window.A10_DOWNLOAD(`/api/data-quality/export.xlsx?date_from=${lastData.period.from}`
    + `&date_to=${lastData.period.to}&office_code=10&check=${encodeURIComponent(key)}`);
}

function showToast(msg, err) { const t = $('toast'); if (!t) { alert(msg); return; } t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden'); clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 4000); }

const today = new Date();
$('dateFrom').value = `${today.getFullYear()}-01-01`;
$('dateTo').value = inputDate(today);
$('searchButton').addEventListener('click', runChecks);

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('summary').textContent = '데이터 품질 점검은 본사만 사용할 수 있습니다.';
    document.querySelector('.dq-toolbar').classList.add('hidden');
    return;
  }
  runChecks();
});
