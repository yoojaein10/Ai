// 반제 리스트 (본사 전용). window.BANJE_KIND = 'receivable' | 'advance'.
// 모드: settled(반제 내역, 기간=반제일) / open(미반제 잔액, 조건=잔액 기준일만).
const $ = id => document.getElementById(id);
const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
const inputDate = d => { const o = d.getTimezoneOffset() * 60000; return new Date(d - o).toISOString().slice(0, 10); };
const KIND = window.BANJE_KIND || 'receivable';
const KIND_LABEL = KIND === 'advance' ? '선수금' : '외상매출금';
const num = v => money.format(Math.round(v || 0));
const day = v => (v || '').slice(0, 10);

// 선수금은 외상매출금과 순서가 반대다. 외상매출금은 청구(발생) 후 입금(반제)이지만,
// 선수금은 돈을 먼저 받고(발생=보통예금 차변) 나중에 매출로 대체(반제=감정수수료 대변)한다.
// 그래서 같은 컬럼이라도 이름이 달라야 한다 — 선수금의 '발생'이 실제 입금일이다.
const LBL = KIND === 'advance'
  ? { genDate: '입금일', genAmt: '입금금액', settleDate: '정산일', settleAmt: '정산금액',
      lastSettle: '최종정산일', settleCum: '정산누계',
      basisSettle: '정산일', basisGen: '입금일',
      periodSettled: '정산일(전표일자)', periodGen: '입금일(전표일자)' }
  : { genDate: '생성일', genAmt: '발생금액', settleDate: '입금일', settleAmt: '반제금액',
      lastSettle: '최종반제일', settleCum: '반제누계',
      // 외상매출금은 열 이름이 '입금일'이지만 기간 기준 이름은 '반제일'로 맞춘다 (기간 라벨과 일치).
      basisSettle: '반제일', basisGen: '생성일',
      periodSettled: '반제일(전표일자)', periodGen: '생성일(전표일자)' };

// 감정서번호 칸. 서버가 관리번호를 정규화해 주므로(members = 풀어낸 감정서 목록)
// 묶음이면 '외 N건', 못 푼 값이면 '비표준' 배지를 달고 원본은 툴팁에 남긴다.
function docCell(it) {
  const ms = it.members || [];
  const bundle = ms.length > 1 ? ` <span class="tag-bundle">외 ${ms.length - 1}건</span>` : '';
  const nonstd = ms.length === 0 ? ' <span class="tag-nonstd">비표준</span>' : '';
  const tip = [ms.length > 1 ? ms.join(', ') : '', it.raw ? `원본 관리번호: ${it.raw}` : '']
    .filter(Boolean).join('\n');
  return `<span${tip ? ` title="${esc(tip)}"` : ''}>${esc(it.doc || '-')}</span>${bundle}${nonstd}`;
}

// 모드별 표 구성. 내보내기는 서버가 만들므로(A10_DOWNLOAD) 여기엔 화면 렌더링만 둔다.
const MODES = {
  settled: {
    empty: `해당 기간 ${KIND_LABEL} 반제 내역이 없습니다.`,
    columns: [
      { th: '감정서번호', col: 'c-doc', cell: docCell },
      { th: '거래처', cell: it => `<span title="${esc(it.partner || '')}">${esc(it.partner || '-')}</span>` },
      { th: LBL.genDate, col: 'c-date', cell: it => esc(day(it.gen_date) || '-') },
      { th: LBL.settleDate, col: 'c-date', cell: it => esc(day(it.date)) },
      { th: LBL.genAmt, col: 'c-amt', num: true, cell: it => (it.gen_amount == null ? '-' : num(it.gen_amount)) },
      { th: LBL.settleAmt, col: 'c-amt', num: true, cell: it => num(it.amount) },
      { th: '잔액', col: 'c-amt', num: true, cls: it => ((it.balance || 0) > 0 ? 'bal' : ''), cell: it => (it.balance == null ? '-' : num(it.balance)) },
      { th: '적요', remark: true, cell: it => esc(it.remark || '') },
    ],
  },
  open: {
    empty: `잔액 기준일 시점에 잔액이 남은 ${KIND_LABEL}이(가) 없습니다.`,
    columns: [
      { th: '감정서번호', col: 'c-doc', cell: docCell },
      { th: '거래처', cell: it => `<span title="${esc(it.partner || '')}">${esc(it.partner || '-')}</span>` },
      { th: LBL.genDate, col: 'c-date', cell: it => esc(day(it.gen_date) || '-') },
      { th: LBL.lastSettle, col: 'c-date', cell: it => esc(day(it.date) || '-') },
      { th: LBL.genAmt, col: 'c-amt', num: true, cell: it => num(it.gen_amount) },
      { th: LBL.settleCum, col: 'c-amt', num: true, cell: it => num(it.amount) },
      { th: '잔액', col: 'c-amt', num: true, cls: () => 'bal', cell: it => num(it.balance) },
      { th: '적요', remark: true, cell: it => esc(it.remark || '') },
    ],
  },
};

let lastCount = 0;

// 조회와 내보내기가 같은 조건을 쓰도록 질의 문자열을 한 곳에서 만든다.
// 미반제 잔액(open)은 잔액 기준일 하나만 조건이라 기간을 아예 보내지 않는다.
function buildQuery() {
  const mode = currentMode(), open = mode === 'open';
  const q = currentDoc();
  const nonstd = open && $('nonstd').checked;
  const asOf = open && $('asOf').value ? `&as_of=${$('asOf').value}` : '';
  const basis = open ? '' : `&date_basis=${currentBasis()}`;
  // 감정서번호로 찾을 땐 기간을 안 보낸다 — 반제가 언제 됐는지 몰라서 찾는 것이라
  // 기간을 걸면 작년에 반제된 건이 빠져 검색이 무의미해진다.
  const period = (open || q) ? '' : `&date_from=${$('dateFrom').value}&date_to=${$('dateTo').value}`;
  const doc = q ? `&doc=${encodeURIComponent(q)}` : '';
  return `kind=${KIND}&mode=${mode}${period}&include_nonstd=${nonstd}${asOf}${basis}${doc}`;
}

const currentDoc = () => ($('docQuery') ? $('docQuery').value.trim() : '');
const currentMode = () => ($('mode') && $('mode').value === 'open' ? 'open' : 'settled');
const currentBasis = () => ($('basis') && $('basis').value === 'gen' ? 'gen' : 'settle');

function applyMode() {
  const mode = currentMode();
  const spec = MODES[mode];
  $('dateLabel').textContent = currentBasis() === 'gen' ? LBL.periodGen : LBL.periodSettled;
  // 미반제 잔액은 잔액 기준일만 조건이므로 기간 입력 자체를 숨긴다.
  $('dateWrap').classList.toggle('hidden', mode === 'open');
  $('basisWrap').classList.toggle('hidden', mode !== 'settled');
  $('nonstdWrap').classList.toggle('hidden', mode !== 'open');
  $('asOfWrap').classList.toggle('hidden', mode !== 'open');
  $('cols').innerHTML = spec.columns.map(c => `<col${c.col ? ` class="${c.col}"` : ''}>`).join('');
  $('head').innerHTML = `<tr>${spec.columns.map(c => `<th${c.num ? ' class="num"' : ''}>${c.th}</th>`).join('')}</tr>`;
  $('emptyList').textContent = spec.empty;
  $('rows').innerHTML = '';
  $('emptyList').classList.add('hidden');
  lastCount = 0;
  $('summary').textContent = mode === 'open'
    ? '잔액 기준일을 확인하고 조회하세요.' : '기간을 선택하고 조회하세요.';
  applyDocMode();
}

// 감정서번호를 넣으면 기간을 안 쓴다. 조건이 살아 있는 것처럼 보이면 오해하므로
// 기간·기준 칸을 흐리게 만들어 지금 안 걸린다는 걸 눈으로 알린다.
function applyDocMode() {
  const searching = !!currentDoc();
  ['dateWrap', 'basisWrap', 'asOfWrap'].forEach(id => {
    const el = $(id);
    if (el) el.classList.toggle('muted', searching);
  });
  ['dateFrom', 'dateTo', 'basis', 'asOf'].forEach(id => {
    const el = $(id);
    if (el) el.disabled = searching;
  });
}

async function load() {
  const mode = currentMode();
  if (!currentDoc() && mode !== 'open' && (!$('dateFrom').value || !$('dateTo').value)) {
    showToast('기간을 선택하거나 감정서번호를 입력하세요.', true); return;
  }
  const spec = MODES[mode];
  $('summary').textContent = '조회 중...';
  $('rows').innerHTML = ''; $('searchButton').disabled = true;
  try {
    const open = mode === 'open';
    const res = await fetch(`/api/banje?${buildQuery()}`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    lastCount = p.data.count;
    const label = open ? '잔액 합계' : '합계';
    const asOfNote = p.data.as_of ? ` · <b>${p.data.as_of}</b> 시점 잔액` : '';
    const ex = p.data.excluded;
    const why = open ? '묶음 정산이라 잔액이 부정확' : `묶음 정산이라 ${LBL.genDate}을 알 수 없음`;
    const exNote = ex && ex.count
      ? ` <span class="ex-note">비표준 관리번호 ${money.format(ex.count)}건 ${num(ex.amount)}원 제외 (${why})</span>`
      : '';
    const periodNote = p.data.period ? ` (${p.data.period.from} ~ ${p.data.period.to})` : '';
    const q = p.data.doc_query || '';
    const docNote = q
      ? ` <span class="ex-note">'${esc(q)}' 검색 · 기간 조건 없이 전체에서 찾음</span>` : '';
    $('summary').innerHTML = `총 <b>${money.format(p.data.count)}건</b> · ${label} <b>${num(p.data.total)}원</b>${periodNote}${asOfNote}${docNote}${exNote}`;
    // 미반제 화면에서 다 반제된 번호를 찾으면 결과가 0건이다. 왜 없는지 말해 준다.
    $('emptyList').textContent = q
      ? (p.data.settled_only
        ? `'${q}' 은(는) 잔액이 없습니다 — ${money.format(p.data.settled_only)}건 모두 반제 완료. '반제 내역'에서 보세요.`
        : `'${q}' 에 해당하는 ${KIND_LABEL} 내역이 없습니다.`)
      : spec.empty;
    $('rows').innerHTML = p.data.items.map(it => `<tr data-doc="${esc(it.doc || '')}">${spec.columns.map(c => {
      const cls = [c.num ? 'num' : '', c.remark ? 'remark' : '', c.cls ? c.cls(it) : ''].filter(Boolean).join(' ');
      const title = c.remark ? ` title="${esc(it.remark || '')}"` : '';
      return `<td${cls ? ` class="${cls}"` : ''}${title}>${c.cell(it)}</td>`;
    }).join('')}</tr>`).join('');
    document.querySelectorAll('#rows tr').forEach(tr => tr.addEventListener('click', () => {
      document.querySelectorAll('#rows tr.sel').forEach(r => r.classList.remove('sel'));
      tr.classList.add('sel');
      loadVoucher(tr.dataset.doc);
    }));
    if (window.A10_COLUMN_RESIZE) window.A10_COLUMN_RESIZE($('banjeTable'), `a10.banjeTable.${mode}.columnWidths`);
    $('emptyList').classList.toggle('hidden', p.data.count !== 0);
  } catch (e) {
    $('summary').textContent = '조회 실패: ' + e.message;
  } finally {
    $('searchButton').disabled = false;
  }
}

// 서버가 엑셀을 만들어 주고 A10_DOWNLOAD가 받는다. 화면에서 Blob으로 만들면
// 데스크톱 앱(pywebview)이 다운로드를 처리하지 못해 눌러도 아무 일이 안 일어난다.
function exportXlsx() {
  if (!lastCount) { showToast('내보낼 내역이 없습니다.', true); return; }
  window.A10_DOWNLOAD(`/api/banje/export.xlsx?${buildQuery()}`);
}

async function loadVoucher(doc) {
  const box = $('detail');
  if (!doc) { box.className = 'ph'; box.textContent = '관리번호가 비어 전표를 조회할 수 없습니다.'; return; }
  box.className = 'ph'; box.textContent = `${doc} 전표 불러오는 중...`;
  try {
    const res = await fetch(`/api/appraisals/${encodeURIComponent(doc)}/vouchers`);
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    const items = p.data.items || [];
    const lines = items.flatMap(v => (v.lines || []).map(ln => {
      const amt = Number(ln.amount || 0), dr = String(ln.debit_credit) === '3';
      return `<tr><td>${esc((v.voucher_date || '').slice(0, 10))}</td><td>${esc(ln.account_name || ln.account_code || '')}</td><td class="num ${dr ? 'dr' : ''}">${dr ? money.format(amt) : ''}</td><td class="num ${dr ? '' : 'cr'}">${dr ? '' : money.format(amt)}</td><td title="${esc(ln.remark || '')}">${esc((ln.remark || '').slice(0, 16))}</td></tr>`;
    })).join('');
    const taxes = p.data.tax_invoices || [];
    const taxRows = taxes.map(t => `<tr><td>${esc((t.tax_date || '').slice(0, 10))}</td><td title="${esc(t.company_name || '')}">${esc((t.company_name || '-').slice(0, 12))}</td><td>${esc(t.issue_type || '-')}</td><td class="num">${money.format(Math.round(t.total_amount || 0))}</td></tr>`).join('');
    const taxHtml = `<div style="font-weight:700;margin:12px 0 4px">세금계산서 / 현금영수증</div>` +
      (taxes.length ? `<table class="bj-vtable"><thead><tr><th>일자</th><th>상호</th><th>구분</th><th class="num">합계</th></tr></thead><tbody>${taxRows}</tbody></table>` : `<div class="ph" style="padding:10px 0">발행 내역 없음</div>`);
    box.className = '';
    box.innerHTML = (lines
      ? `<div style="font-weight:700;margin-bottom:4px">${esc(doc)} · 전표</div><table class="bj-vtable"><thead><tr><th>전표일</th><th>계정</th><th class="num">차변</th><th class="num">대변</th><th>적요</th></tr></thead><tbody>${lines}</tbody></table>`
      : `<div class="ph">${esc(doc)} — 연결된 전표가 없습니다.</div>`) + taxHtml;
  } catch (e) {
    box.className = 'ph'; box.textContent = '전표 조회 실패: ' + e.message;
  }
}

function showToast(msg, err) { const t = $('toast'); if (!t) { alert(msg); return; } t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden'); clearTimeout(showToast.t); showToast.t = setTimeout(() => t.classList.add('hidden'), 4000); }

const today = new Date();
$('dateFrom').value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-01`;
$('dateTo').value = inputDate(today);
$('asOf').value = inputDate(today);   // 잔액 기준일 기본값 = 오늘(현재 잔액)
$('basis').options[0].textContent = LBL.basisSettle;  // 반제일 / 정산일
$('basis').options[1].textContent = LBL.basisGen;     // 생성일 / 입금일
$('searchButton').addEventListener('click', load);
$('exportButton').addEventListener('click', exportXlsx);
$('mode').addEventListener('change', applyMode);
$('basis').addEventListener('change', applyMode);
$('nonstd').addEventListener('change', load);
$('docQuery').addEventListener('input', applyDocMode);
// 번호를 치고 엔터를 누르는 게 자연스럽다. 지우고 엔터를 치면 원래 기간 조회로 돌아간다.
$('docQuery').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); load(); } });
$('docQuery').addEventListener('search', load);   // 입력칸의 x 버튼

window.A10_READY.then(ctx => {
  if (ctx.office_id !== '10') {
    $('summary').textContent = '반제 리스트는 본사만 사용할 수 있습니다.';
    document.querySelector('.toolbar').classList.add('hidden');
    return;
  }
  applyMode();
  load();
});
