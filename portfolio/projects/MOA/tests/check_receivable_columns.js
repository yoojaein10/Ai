// 입금현황 표의 헤더 수와 실제로 만들어지는 셀 수가 맞는지 검사한다.
//
// 개수만 세는 정적 검사로는 부족하다. 열을 옮기다 보면 칸 수는 맞는 채로 내용만
// 서로 밀리는 일이 생긴다. 그래서 화면·인쇄 표를 실제로 렌더링해서 <td> 수와
// 헤더 이름에 맞는 값이 들어갔는지 함께 본다.
//
// 실행: node tests/check_receivable_columns.js   (실패하면 종료코드 1)
const fs = require('fs');
const path = require('path');

const file = path.join(__dirname, '..', 'desktop', 'ui', 'receivables.js');
const src = fs.readFileSync(file, 'utf8');

/**
 * `const 이름=` 부터 그 선언이 끝나는 `;` 까지 잘라낸다.
 * 여러 줄 짜리(`=>{ … };`)와 한 줄 짜리(`=>\`…\`;`)가 섞여 있어서, 괄호·따옴표
 * 깊이를 세며 깊이 0 의 `;` 를 찾는다. 예전처럼 `\n};` 만 찾으면 한 줄 짜리에서
 * 다음 헬퍼까지 통째로 삼켜 '이미 선언됨' 오류가 난다.
 */
function block(name) {
  const start = src.indexOf(`const ${name}=`);
  if (start < 0) throw new Error(`${name} 정의를 찾을 수 없다`);
  let depth = 0;
  let quote = null;
  for (let i = start; i < src.length; i++) {
    const ch = src[i];
    if (quote) {
      if (ch === '\\') i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === "'" || ch === '"' || ch === '`') quote = ch;
    else if ('({['.includes(ch)) depth++;
    else if (')}]'.includes(ch)) depth--;
    else if (ch === ';' && depth === 0) return src.slice(start, i + 1);
  }
  throw new Error(`${name} 의 끝을 찾을 수 없다`);
}

/** `map(row=>\`...\`).join` 안의 템플릿 문자열. */
function rowTemplate(marker) {
  const line = src.split('\n').find(l => l.includes(marker));
  if (!line) throw new Error(`${marker} 를 찾을 수 없다`);
  const open = line.indexOf('map(row=>`') + 'map(row=>`'.length;
  const close = line.indexOf('`).join', open);
  if (close < 0) throw new Error('행 템플릿의 끝을 찾을 수 없다');
  return line.slice(open, close);
}

function headerCount(name) {
  const match = src.match(new RegExp(`const ${name}='(.*?)';`, 's'));
  if (!match) throw new Error(`${name} 을 찾을 수 없다`);
  return (match[1].match(/<th/g) || []).length;
}

function colCount(name) {
  const match = src.match(new RegExp(`const ${name}='(.*?)';`, 's'));
  if (!match) throw new Error(`${name} 을 찾을 수 없다`);
  return (match[1].match(/<col/g) || []).length;
}

const SAMPLE = {
  doc_id: 'D', purpose: '담보', category: '구분건물', customer_name: 'C', address: 'A', manager: 'M',
  receipt_date: null, send_date: null, last_received_date: null,
  base_fee: 1, appraisal_cost: 2, sales_amount: 3, vat_amount: 4, invoice_total: 5,
  // 선수금 6을 받아 전액 상계한 건 — 받은 금액 6 / 잔액 0 이어야 한다.
  advance_received: 6, advance_offset: 6, advance_amount: 0,
  existing_received_amount: 7, daily_received_amount: 8, outstanding_amount: 10,
  billed_amount: 11, received_amount: 12, overpaid_amount: 0,
  travel_expense: 1, other_expense: 1,
  // 세금계산서·현금영수증 발행여부 (2026-08-07 / 2026-08-13) — 목록 맨 오른쪽 두 칸
  tax_issued: '발행', tax_issued_amount: 1500000, tax_issued_slips: 2,
  cash_issued: '발행', cash_issued_amount: 490600, cash_issued_slips: 1,
};

/** 화면 행을 실제로 만들어 <td> 목록을 돌려준다. */
function renderRow() {
  const stubs = {
    state: { mode: 'received', selected: null },
    money: new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }),
    escapeHtml: v => String(v ?? ''),
    dateText: v => String(v ?? '-'),
    statusOf: () => '완납',
  };
  // 행 템플릿이 부르는 헬퍼를 소스에서 자동으로 찾아 붙인다. 헬퍼가 또 다른 헬퍼를
  // 부를 수 있으므로 더 나올 게 없을 때까지 따라간다. 이름을 하나하나 적어두면
  // 헬퍼가 늘어날 때마다 검사가 먼저 깨진다.
  const template = rowTemplate("$('rows').innerHTML=data.items.map");
  const calledIn = text => [...new Set(
    (text.match(/(\w+)\(/g) || []).map(m => m.slice(0, -1))
  )].filter(name => !(name in stubs) && src.includes(`const ${name}=`));

  const helpers = [];
  const pending = calledIn(template);
  while (pending.length) {
    const name = pending.shift();
    if (helpers.includes(name)) continue;
    helpers.unshift(name);              // 부르는 쪽보다 먼저 정의되게 앞에 둔다
    pending.push(...calledIn(block(name)));
  }
  const code = helpers.map(block).join('\n') + '\nreturn `' + template + '`;';
  return new Function(...Object.keys(stubs), 'row', code)(
    ...Object.values(stubs), SAMPLE
  );
}

/** 인쇄 표의 헤더·행·합계를 각각 렌더링한다. */
function printParts() {
  // buildPrintHtml 안의 '입금현황' 분기만 잘라낸다 (그 뒤는 미수금현황 분기).
  const from = src.indexOf('function buildPrintHtml');
  const start = src.indexOf("if(state.mode==='received'){", from);
  if (start < 0) throw new Error('인쇄 분기를 찾을 수 없다');
  const chunk = src.slice(start, src.indexOf('</tfoot>', start));
  const headMatch = chunk.match(/<thead>([\s\S]*?)<\/thead>/);
  const bodyMatch = chunk.match(/const rows=items\.map\(row=>`([\s\S]*?)`\)\.join/);
  const footMatch = chunk.match(/<tfoot>([\s\S]*)$/);
  if (!headMatch || !bodyMatch || !footMatch) throw new Error('인쇄 표를 찾을 수 없다');

  const stubs = {
    money: new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }),
    escapeHtml: v => String(v ?? ''),
    dateText: v => String(v ?? '-'),
    statusOf: () => '완납',   // 진행상태 열 (2026-08-04 인쇄 개선)
    sum: () => 0,
    items: [SAMPLE],
  };
  const run = tpl => new Function(...Object.keys(stubs), 'row', 'return `' + tpl + '`;')(
    ...Object.values(stubs), SAMPLE
  );
  return { head: run(headMatch[1]), body: run(bodyMatch[1]), foot: run(footMatch[1]) };
}

const cellsOf = html => [...html.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map(m => m[1].trim());
const headsOf = html => [...html.matchAll(/<th[^>]*>([\s\S]*?)<\/th>/g)].map(m => m[1].trim());

const failures = [];

// ── 화면 표 ────────────────────────────────────────────────────────────────
const base = headerCount('receivedHeaders');
if (base !== colCount('receivedColumns')) {
  failures.push(`화면 헤더 ${base} ≠ colgroup ${colCount('receivedColumns')}`);
}
const screenRow = renderRow();
const screenCells = cellsOf(screenRow);
if (screenCells.length !== base) {
  failures.push(`화면: 헤더 ${base} / 셀 ${screenCells.length}`);
}

// ── 인쇄 표 ────────────────────────────────────────────────────────────────
const { head, body, foot } = printParts();
const printHeads = headsOf(head);
const printCells = cellsOf(body);
// 합계는 colspan 이 여러 칸을 덮으므로 span 을 세어서 폭을 구한다.
const footWidth = [...foot.matchAll(/<td(?:\s+colspan="(\d+)")?[^>]*>/g)]
  .reduce((total, m) => total + (m[1] ? Number(m[1]) : 1), 0);
if (printHeads.length !== printCells.length) {
  failures.push(`인쇄: 헤더 ${printHeads.length} / 행 ${printCells.length}`);
}
if (footWidth !== printHeads.length) {
  failures.push(`인쇄: 합계 폭 ${footWidth} / 헤더 ${printHeads.length}`);
}

// ── 헤더 이름에 맞는 값이 들어갔는지 ──────────────────────────────────────
// 칸 수만 맞고 내용이 서로 밀린 적이 있어서, 자리마다 기대값을 박아둔다.
const screenHeads = headsOf(src.match(/const receivedHeaders='(.*?)';/s)[1]);
const pair = (heads, cells, where) => (name, expected, why) => {
  const index = heads.indexOf(name);
  if (index < 0) { failures.push(`${where}: '${name}' 헤더가 없다`); return; }
  const got = cells[index] || '';
  if (!got.includes(expected)) failures.push(`${where}: '${name}' 칸에 "${got}" (${why})`);
};
for (const [heads, cells, where] of [
  [screenHeads, screenCells, '화면'],
  [printHeads, printCells, '인쇄'],
]) {
  const check = pair(heads, cells, where);
  check('물건종류', '구분건물', '물건종류가 와야 한다');
  check('선수금(기)', '6', '받은 금액이 와야 한다');
  check('선수금', '0', '남은 잔액이 와야 한다 (전액 상계면 0)');
  check('입금액(기)', '7', '기존 입금액이 와야 한다');
  check('미수금', '10', '미수금이 와야 한다');
}
// 증빙 발행여부는 화면에만 있다 (인쇄표는 열 구성을 그대로 둔다).
pair(screenHeads, screenCells, '화면')(
  '세금계산서/현금영수증', '발행', '발행여부가 와야 한다');

if (failures.length) {
  console.error('입금현황 열 검사 실패:');
  failures.forEach(f => console.error('  - ' + f));
  process.exit(1);
}
console.log(`입금현황 열 검사 통과 (화면 ${base}열, 인쇄 ${printHeads.length}열)`);
