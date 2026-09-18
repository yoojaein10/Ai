// 엑셀 대사 (본사 전용). 올린 엑셀의 감정서번호·금액을 우리 매출과 맞춰본다.
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
let lastData = null;

async function submit(useCols) {
  const f = $('file').files[0];
  if (!f) { showToast('엑셀 파일을 선택하세요.', true); return; }
  const fd = new FormData();
  fd.append('file', f);
  fd.append('date_from', $('dateFrom').value);
  fd.append('date_to', $('dateTo').value);
  if (useCols) { fd.append('doc_col', $('docCol').value); fd.append('amount_col', $('amountCol').value); }
  $('runButton').disabled = true; $('rerunButton').disabled = true;
  $('empty').textContent = '대사 중...';
  try {
    const res = await fetch('/api/reconcile', { method: 'POST', body: fd });
    const p = await res.json();
    if (!p.success) {
      if (p.data && p.data.analysis) { lastData = p.data; fillColumns(p.data.analysis, -1, -1); $('colRow').classList.add('show'); }
      throw new Error(p.message);
    }
    lastData = p.data;
    render(p.data);
  } catch (e) {
    $('empty').textContent = e.message; $('empty').classList.remove('hidden');
    $('groups').innerHTML = ''; $('summary').innerHTML = '';
  } finally {
    $('runButton').disabled = false; $('rerunButton').disabled = false;
  }
}

function colLabel(c) {
  const head = c.sample ? ` (${c.sample})` : '';
  return `${c.index + 1}열${head}`;
}
function fillColumns(analysis, usedDoc, usedAmt) {
  const opts = analysis.columns.map(c => `<option value="${c.index}">${esc(colLabel(c))}</option>`).join('');
  $('docCol').innerHTML = opts; $('amountCol').innerHTML = opts;
  $('docCol').value = (usedDoc >= 0 ? usedDoc : analysis.suggested_doc_col);
  $('amountCol').value = (usedAmt >= 0 ? usedAmt : analysis.suggested_amount_col);
}

function render(d) {
  $('empty').classList.add('hidden');
  if (d.analysis) { fillColumns(d.analysis, d.used_doc_col, d.used_amount_col); $('colRow').classList.add('show'); }
  const diffCls = Math.abs(d.diff) < 1 ? 'diff0' : 'diffx';
  $('summary').innerHTML =
    `<span>엑셀 <b>${money.format(d.excel_docs)}건</b> · ${money.format(Math.round(d.excel_total))}원</span>
     <span>우리 <b>${money.format(d.our_docs)}건</b> · ${money.format(Math.round(d.our_total))}원</span>
     <span>차이 <b class="${diffCls}">${money.format(Math.round(d.diff))}원</b></span>
     <span style="color:var(--muted)">인식 ${money.format(d.parsed_rows)}행</span>`;
  $('groups').innerHTML = d.groups.map((g, i) => {
    const cols = g.key === 'amount_diff'
      ? '<tr><th>감정서번호</th><th class="num">엑셀</th><th class="num">우리</th><th class="num">차이</th></tr>'
      : (g.key === 'excel_only'
        ? '<tr><th>감정서번호</th><th class="num">금액</th><th>장부에 있는 번호(추정)</th></tr>'
        : '<tr><th>감정서번호</th><th class="num">금액</th></tr>');
    const colWidths = g.key === 'amount_diff' ? [150, 120, 120, 120]
      : (g.key === 'excel_only' ? [150, 120, 240] : [150, 120]);
    const colgroup = `<colgroup>${colWidths.map(w => `<col style="width:${w}px">`).join('')}</colgroup>`;
    const rows = g.items.map(it => {
      if (g.key === 'amount_diff') return `<tr><td>${esc(it.doc)}</td><td class="num">${money.format(Math.round(it.excel))}</td><td class="num">${money.format(Math.round(it.ours))}</td><td class="num down">${money.format(Math.round(it.diff))}</td></tr>`;
      if (g.key === 'excel_only') return `<tr><td>${esc(it.doc)}</td><td class="num">${money.format(Math.round(it.amount))}</td><td>${esc(it.partner || '-')}</td></tr>`;
      return `<tr><td>${esc(it.doc)}</td><td class="num">${money.format(Math.round(it.amount))}</td></tr>`;
    }).join('');
    return `<section class="rc-check">
      <div class="rc-head" data-i="${i}">
        <h2>${esc(g.title)} <span class="cnt">${money.format(g.count)}건</span></h2>
        <div>${g.count ? `${money.format(Math.round(g.amount))}원 · <button class="rc-export" data-k="${g.key}" type="button">엑셀</button>` : '없음'}</div>
      </div>
      <div class="rc-body" id="g-${i}">${g.count ? `<table class="rc-table">${colgroup}<thead>${cols}</thead><tbody>${rows}</tbody></table>` : ''}</div>
    </section>`;
  }).join('');
  document.querySelectorAll('.rc-head').forEach(h => h.addEventListener('click', e => {
    if (e.target.closest('.rc-export')) return;
    const b = $('g-' + h.dataset.i); b.style.display = b.style.display === 'none' ? '' : 'none';
  }));
  document.querySelectorAll('.rc-export').forEach(b => b.addEventListener('click', () => exportCsv(b.dataset.k)));
  if (window.A10_COLUMN_RESIZE)
    document.querySelectorAll('.rc-table').forEach((t, i) =>
      window.A10_COLUMN_RESIZE(t, `a10.reconcile.columnWidths.${i}`));
}

// 데스크톱 앱(pywebview)은 Blob 다운로드가 안 되므로, 대사 때 서버가 보관해 둔
// 결과(export_token)로 서버가 만든 엑셀을 받는다.
function exportCsv(key) {
  if (!lastData || !lastData.export_token) {
    showToast('내보내기 정보가 없습니다. 다시 대사한 뒤 내보내세요.', true);
    return;
  }
  window.A10_DOWNLOAD(`/api/reconcile/export.xlsx?token=${encodeURIComponent(lastData.export_token)}`
    + `&key=${encodeURIComponent(key)}`);
}

function showToast(msg, err) { const t = $('toast'); if (!t) { alert(msg); return; } t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden'); clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 4000); }

const _t = new Date();
$('dateFrom').value = `${_t.getFullYear()}-01-01`;
$('dateTo').value = new Date(_t.getTime() - _t.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
$('runButton').addEventListener('click', () => submit(false));
$('rerunButton').addEventListener('click', () => submit(true));

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('empty').textContent = '엑셀 대사는 본사만 사용할 수 있습니다.';
    document.querySelector('.toolbar').classList.add('hidden');
  }
});
