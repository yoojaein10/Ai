// 배분 수금 진행. 산정액(청구금액) 대비 입금 진행률 (지사는 자기 지사만, 서버가 강제).
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const inputDate = d => { const o = d.getTimezoneOffset() * 60000; return new Date(d - o).toISOString().slice(0, 10); };
let lastItems = [];
let myOfficeId = '10';  // A10_READY에서 로그인 사용자 지사로 설정. 서버가 자기 지사로 다시 강제.

// 감정서번호를 넣으면 서버가 발송일 조건을 빼고 전체 기간에서 찾는다.
function buildQuery() {
  const query = new URLSearchParams({
    date_from: $('dateFrom').value, date_to: $('dateTo').value, office_code: myOfficeId,
  });
  const doc = $('docQuery').value.trim();
  if (doc) query.set('doc_id', doc);
  const manager = $('managerQuery').value.trim();
  if (manager) query.set('manager', manager);
  return query;
}

async function load() {
  const from = $('dateFrom').value, to = $('dateTo').value;
  if (!from || !to) { showToast('기간을 선택하세요.', true); return; }
  $('summary').textContent = '조회 중...'; $('rows').innerHTML = ''; $('searchButton').disabled = true;
  try {
    const res = await fetch(`/api/collection-progress?${buildQuery()}`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    lastItems = p.data.items;
    $('summary').innerHTML = `부분수금 <b>${money.format(p.data.count)}건</b> · 산정 <b>${money.format(Math.round(p.data.assessed_total))}</b> · 입금 <b>${money.format(Math.round(p.data.received_total))}</b> · 미입금 <b style="color:#c62828">${money.format(Math.round(p.data.unpaid_total))}</b>`;
    $('rows').innerHTML = p.data.items.map(it => {
      const rate = Math.max(0, Math.min(100, it.rate || 0));
      return `<tr>
        <td>${esc(it.doc)}</td>
        <td title="${esc(it.cust)}">${esc(it.cust || '-')}</td>
        <td>${esc((it.send_date || '').slice(0, 10) || '-')}</td>
        <td class="num">${money.format(Math.round(it.assessed))}</td>
        <td class="num">${money.format(Math.round(it.received))}</td>
        <td class="num unpaid">${money.format(Math.round(it.unpaid))}</td>
        <td><div class="cl-bar"><span style="width:${rate}%"></span><em>${rate}%</em></div></td>
      </tr>`;
    }).join('');
    $('emptyList').classList.toggle('hidden', p.data.count !== 0);
    if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('clTable'), 'a10.clTable.columnWidths');
  } catch (e) {
    $('summary').textContent = '조회 실패: ' + e.message;
  } finally {
    $('searchButton').disabled = false;
  }
}

// 데스크톱 앱(pywebview)은 Blob 다운로드가 안 되므로 서버가 만든 엑셀을 받는다.
function exportCsv() {
  if (!lastItems.length) { showToast('내보낼 내역이 없습니다.', true); return; }
  window.A10_DOWNLOAD(`/api/collection-progress/export.xlsx?${buildQuery()}`);
}

function showToast(msg, err) { const t = $('toast'); if (!t) { alert(msg); return; } t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden'); clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 4000); }

const today = new Date();
$('dateFrom').value = `${today.getFullYear()}-01-01`;
$('dateTo').value = inputDate(today);
$('searchButton').addEventListener('click', load);
$('exportButton').addEventListener('click', exportCsv);
['docQuery', 'managerQuery'].forEach(id =>
  $(id).addEventListener('keydown', e => { if (e.key === 'Enter') load(); }));

window.A10_READY.then(ctx => {
  // 본사=10, 지사=자기 지사 코드. 서버가 resolve_office_scope로 자기 지사로 다시 강제한다.
  myOfficeId = ctx.office_id;
  load();
});
