// 출장비 인쇄 (2026-09-10) — 델파이 CulJangList 양식 '시내·외 출장비 및 공부발급비 청구서'.
// 작성자마다 페이지를 나누고, 각 페이지 머리(표 제목줄)·꼬리(청구 및 영수함·직급·성명)는 thead/tfoot 이
// 인쇄 페이지마다 반복된다. 마지막 페이지 아래에 합계·※비고. 결재란은 넣었다가 뺐다(사용자 2026-09-10 저녁).
(function () {
  const TE = window.A10_TE;
  const esc = TE.esc, num = v => (Number(v || 0) ? TE.num(v) : '');
  const md = d => (d && /^\d{4}-\d{2}-\d{2}/.test(d)) ? d.slice(5, 10) : (d || '');

  const CSS = `
    @page { size: A4 landscape; margin: 8mm 7mm; }
    body { font-family: '맑은 고딕', Malgun Gothic, sans-serif; color: #000; margin: 0; font-size: 9.5pt; }
    .sheet { page-break-after: always; }
    .sheet:last-child { page-break-after: auto; }
    h1 { text-align: center; font-size: 15pt; letter-spacing: 3px; margin: 0 0 6px; }
    .amount { display: flex; gap: 14px; align-items: baseline; margin: 0 0 6px; font-size: 10.5pt; }
    .amount b { font-size: 12pt; }
    table.bill { border-collapse: collapse; width: 100%; table-layout: fixed; }
    table.bill th, table.bill td { border: 1px solid #000; padding: 2px 2px; font-size: 8pt; line-height: 1.25; overflow: hidden; white-space: nowrap; }
    table.bill td.num { padding-right: 3px; }
    table.bill th { font-weight: 700; text-align: center; background: #fff; }
    table.bill td.num { text-align: right; font-variant-numeric: tabular-nums; }
    table.bill td.c { text-align: center; }
    table.bill tr.total td { background: #fff3a3; font-weight: 700; }
    table.bill tfoot td { border: 0; padding-top: 10px; font-size: 9pt; }
    .foot { display: flex; justify-content: flex-end; gap: 40px; padding-right: 20px; }
    .foot .sig { display: flex; gap: 40px; }
    .notes { margin: 6px 0 0; font-size: 8.5pt; }
    .notes div { margin: 2px 0; }
    @media screen { body { background: #ddd; padding: 12px; } .sheet { background: #fff; padding: 10mm; margin: 0 auto 12px; width: 277mm; box-sizing: border-box; } }
  `;

  const HEAD = `<thead>
    <tr><th rowspan="3" style="width:11mm">출장일</th><th rowspan="3" style="width:22mm">감 정 서<br>번 호</th><th rowspan="3" style="width:13mm">담당<br>평가사</th><th rowspan="3" style="width:30mm">출장지</th><th rowspan="3" style="width:12mm">감정서<br>발송일</th>
      <th colspan="3">출 장 비</th><th colspan="8">공부발급비 및 임대차확인비용</th><th rowspan="3" style="width:16mm">합 계</th></tr>
    <tr><th rowspan="2" style="width:14mm">시 내</th><th rowspan="2" style="width:14mm">시 외</th><th rowspan="2" style="width:15mm">소 계</th><th rowspan="2" style="width:11mm">등기부<br>등본</th><th colspan="4">지 적 공 부</th><th colspan="2">임대차및물건조사비</th><th rowspan="2" style="width:14mm">소 계</th></tr>
    <tr><th style="width:11mm">토지이용<br>계획</th><th style="width:11mm">토지대장</th><th style="width:11mm">건축물<br>대장</th><th style="width:11mm">지적도및<br>교통비</th><th style="width:14mm">내 역</th><th style="width:12mm">비 용</th></tr>
  </thead>`;

  const row = r => `<tr>
    <td class="c">${esc(md(r.cul_date))}</td><td class="c">${esc(r.doc_id)}</td><td class="c">${esc(r.manager || '')}</td><td title="${esc(r.address)}">${esc(r.address)}</td><td class="c">${esc(md(r.send_date))}</td>
    <td class="num">${num(r.cul_in)}</td><td class="num">${num(r.cul_out)}</td><td class="num">${num(r.cul_total)}</td>
    <td class="num">${num(r.regis_copy)}</td><td class="num">${num(r.toji_use)}</td><td class="num">${num(r.toji_dae)}</td><td class="num">${num(r.build_dae)}</td><td class="num">${num(r.jijuck)}</td>
    <td class="c">${esc(r.mul_remark || '')}</td><td class="num">${num(r.mul_amt)}</td><td class="num">${num(r.gong_total)}</td><td class="num">${num(r.amount_total)}</td></tr>`;

  const totalRow = t => `<tr class="total"><td colspan="5" class="c">합&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;계</td>
    <td class="num">${num(t.cul_in)}</td><td class="num">${num(t.cul_out)}</td><td class="num">${num(t.cul_total)}</td>
    <td class="num">${num(t.regis_copy)}</td><td class="num">${num(t.toji_use)}</td><td class="num">${num(t.toji_dae)}</td><td class="num">${num(t.build_dae)}</td><td class="num">${num(t.jijuck)}</td>
    <td></td><td class="num">${num(t.mul_amt)}</td><td class="num">${num(t.gong_total)}</td><td class="num">${num(t.amount_total)}</td></tr>`;

  function sheet(w, data) {
    const foot = `<tfoot><tr><td colspan="17"><div class="foot"><span>위와 같이 청구 및 영수함.</span><span>${esc(data.date_label)}</span></div>
      <div class="foot sig"><span>직&nbsp;&nbsp;&nbsp;급 :&nbsp; ${esc(w.position || '')}</span><span>성&nbsp;&nbsp;&nbsp;명 :&nbsp; ${esc(w.name)}</span></div></td></tr></tfoot>`;
    return `<section class="sheet">
      <h1>시내 · 외 출장비 및 공부발급비 청구서</h1>
      <div class="amount"><b>金</b><span>${esc(w.korean_total)}</span><span>(₩${TE.num(w.totals.amount_total)})</span></div>
      <table class="bill">${HEAD}${foot}<tbody>${w.rows.map(row).join('')}${totalRow(w.totals)}</tbody></table>
      ${w.notes.length ? `<div class="notes">${w.notes.map(n => `<div>※&nbsp; ${esc(n)}</div>`).join('')}</div>` : ''}
    </section>`;
  }

  // 새 창(window.open)은 데스크톱 EXE(pywebview)에서 열리지 않는다 — taxinvoice-dialog 도 그래서 피한다.
  // 숨은 iframe 에 양식을 넣고 그 창을 인쇄하면 브라우저·EXE 둘 다 같은 인쇄 창이 뜬다 (2026-09-10).
  function printHtml(title, html) {
    const old = document.getElementById('tePrintFrame');
    if (old) old.remove();
    const frame = document.createElement('iframe');
    frame.id = 'tePrintFrame';
    frame.setAttribute('title', title);
    Object.assign(frame.style, { position: 'fixed', right: '0', bottom: '0', width: '0', height: '0', border: '0', opacity: '0' });
    document.body.appendChild(frame);
    frame.onload = () => {
      const w = frame.contentWindow;
      w.document.title = title;
      w.addEventListener('afterprint', () => setTimeout(() => frame.remove(), 500));
      setTimeout(() => { w.focus(); w.print(); }, 150);
    };
    frame.srcdoc = html;
  }

  async function print(query) {
    const p = await TE.api('GET', `/api/travel-expense/print?${query}`);
    const data = p.data;
    if (!data.writers.length) { TE.toast('인쇄할 건이 없습니다. 먼저 조회하세요.', true); return; }
    printHtml('출장비 청구서', `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>출장비 청구서</title><style>${CSS}</style></head><body>${data.writers.map(w => sheet(w, data)).join('')}</body></html>`);
    TE.toast(`청구서 ${data.writers.length}명분 인쇄 창을 엽니다. 용지가 세로로 잡히면 가로로 바꿔 주세요.`);
  }

  // ── 총괄표 (2026-09-10 사용자 양식) — 성명·시내출장비·시외출장비·공부발급비·기타정산·계·비고, 맨 아래 합계 ──
  const SUMMARY_CSS = `
    @page { size: A4 portrait; margin: 12mm 12mm; }
    body { font-family: '맑은 고딕', Malgun Gothic, sans-serif; color: #000; margin: 0; }
    h1 { text-align: center; font-size: 16pt; margin: 0 0 8px; }
    table { border-collapse: collapse; width: 178mm; table-layout: fixed; }   /* 세로 A4 인쇄면 186mm 안 — 비고가 밖으로 나가 선이 잘렸다 (2026-09-10) */
    th, td { border: 1px solid #000; padding: 3px 5px; font-size: 10pt; white-space: nowrap; overflow: hidden; }
    th { background: #4a7fc1; color: #fff; text-align: center; font-weight: 700; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    td.num { text-align: right; font-variant-numeric: tabular-nums; }
    td.name { text-align: center; }
    tr.total td { background: #fff3a3; font-weight: 700; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    @media screen { body { background: #ddd; padding: 12px; } .sheet { background: #fff; padding: 12mm; margin: 0 auto; width: 210mm; box-sizing: border-box; } }
  `;
  const dash = v => (Number(v || 0) ? TE.num(v) : '-');

  async function printSummary(query) {
    const p = await TE.api('GET', `/api/travel-expense/print-summary?${query}`);
    const d = p.data;
    if (!d.items.length) { TE.toast('인쇄할 건이 없습니다. 먼저 조회하세요.', true); return; }
    const rows = d.items.map(r => `<tr><td class="name">${esc(r.name)}</td><td class="num">${dash(r.cul_in)}</td><td class="num">${dash(r.cul_out)}</td><td class="num">${dash(r.gong_total)}</td><td class="num">-</td><td class="num">${dash(r.amount_total)}</td><td></td></tr>`).join('');
    const t = d.total;
    const total = `<tr class="total"><td class="name">합 계</td><td class="num">${dash(t.cul_in)}</td><td class="num">${dash(t.cul_out)}</td><td class="num">${dash(t.gong_total)}</td><td class="num">-</td><td class="num">${dash(t.amount_total)}</td><td></td></tr>`;
    printHtml(d.title, `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>${esc(d.title)}</title><style>${SUMMARY_CSS}</style></head><body><section class="sheet">
      <h1>${esc(d.title)}</h1>
      <table><colgroup><col style="width:22mm"><col style="width:26mm"><col style="width:26mm"><col style="width:24mm"><col style="width:22mm"><col style="width:28mm"><col style="width:30mm"></colgroup><thead><tr><th>성 명</th><th>시내출장비</th><th>시외출장비</th><th>공부발급비</th><th>기타정산</th><th>계</th><th>비 고</th></tr></thead>
      <tbody>${rows}${total}</tbody></table></section></body></html>`);
    TE.toast(`${d.title} 인쇄 창을 엽니다.`);
  }

  window.A10_TE_PRINT = print;
  window.A10_TE_PRINT_SUMMARY = printSummary;
})();
