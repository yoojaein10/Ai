// 상여 화면 (본사 전용) — 성과상여 엑셀의 자동 계산부(주주/평·동/총괄표)를 재현한다.
// 실적월 = 입금월. 주주 적용률(40/45/35/30%)은 감정서 행별로 선택한다.
// 수기 항목(지분율·가변비)은 반영하지 않는다 (엑셀 대조용).
// TODO: 실사용 단계에서는 본인 것만 보이도록 제한 예정 (2026-07-22 사용자 결정).
const $=id=>document.getElementById(id);
const money=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:0});
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

let currentData=null;
let currentTab='shareholders';
const TAB_TITLES={shareholders:'주주',associates:'평·동',summary:'총괄표'};

function monthQuery(){
  const [year,month]=$('perfMonth').value.split('-');
  return new URLSearchParams({year,month:Number(month)});
}

async function loadReport(){
  $('resultSummary').textContent='조회 중...';
  const response=await fetch(`/api/bonus?${monthQuery()}`);
  const payload=await response.json();
  if(!payload.success)throw new Error(payload.message);
  currentData=payload.data;
  render();
}

function render(){
  if(!currentData)return;
  const {period}=currentData;
  $('tabTitle').textContent=TAB_TITLES[currentTab];
  $('resultSummary').textContent=`실적월 ${period.from} ~ ${period.to} (입금일 기준) · 본사`;
  if(currentTab==='summary')renderSummary();
  else renderGroups(currentTab);
  fitTableHeight();
}

// 표 높이를 화면에 맞춘다 — 탭·안내문 때문에 공용 고정 높이(calc)로는 표 바닥이
// 화면 밖으로 내려가 가로 스크롤바가 안 보인다. 표 위 요소들 위치 기준으로 재계산.
function fitTableHeight(){
  const wrap=document.querySelector('.list-panel > .table-wrap');
  if(!wrap)return;
  const top=wrap.getBoundingClientRect().top+window.scrollY;
  wrap.style.height=`${Math.max(360,window.innerHeight-top-30)}px`;
}
window.addEventListener('resize',fitTableHeight);

const num=value=>value==null?'-':money.format(Math.round(value));

function renderGroups(tab){
  const groups=currentData[tab];
  const isShareholder=tab==='shareholders';
  const colCount=27;
  // 주주 40/45/35/30, 평·동 20 기본(구간 10~40)·공통건 3
  const rateOptions=isShareholder?[40,45,35,30]:[20,3,10,15,25,30,35,40];
  const defaultRate=rateOptions[0];
  // 주주·평·동 공통 = 재무팀 성과상여 시트 헤더(총계 1~19 순서). 감정서 행은 해당 컬럼을 채우고
  // 사람 단위 항목은 합계 행에서 합·수식으로 나타난다. 평·동 차이: 순수수료가 입력(FEE 보정),
  // 산정수수료는 계산 표시, 협회비 면제(0), 손배는 순수수료 × 담보1.5%/그외1% ROUND.
  // 성명~거래처는 가로 스크롤 시 왼쪽 고정(data-stick, setStickyOffsets가 left 계산).
  const headCells=`<th data-stick="0">성명</th><th data-stick="1">감정서번호</th><th data-stick="2">업무구분</th><th data-stick="3">거래처</th>
      <th>담당자</th><th>조사자</th><th class="number">적용률·상여</th>
      <th class="number">1.순수수료</th><th class="number">2.부족<br>출장비</th><th class="number">3.토지<br>조사비</th><th class="number">4.산정수수료<br>(1-2+3)</th>
      <th class="number">5.가변비<br>(전월)</th><th class="number">6.손해배상<br>충당금</th><th class="number">7.미납비<br>이월</th><th class="number">8.당월<br>감정서경비</th>
      <th class="number">9.협회비,<br>공제료</th><th class="number">10.상여기준액<br>{4-(5~9)}</th><th class="number">11.산정<br>상여금</th><th class="number">12.화환<br>공제등</th>
      <th class="number">13.물건<br>조사비</th><th class="number">14.세전상여금<br>(11-12+13)</th><th class="number">15.제세공과<br>(14x33%)</th><th class="number">16.세후상여금<br>(14-15)</th>
      <th class="number">17.기타<br>공제</th><th class="number">18.지급상여금<br>(16-17)</th><th class="number">19.카드<br>(4x5%)</th><th>입금일</th>`;
  // 상단 고정 머리말(스크롤해도 따라옴) + 사람 블록마다 반복되는 제목 줄(엑셀 양식)
  setLayout('docsShV5',`<tr>${headCells}</tr>`);
  const headRow=`<tr class="group-head">${headCells.replaceAll('<th','<td').replaceAll('</th>','</td>')}</tr>`;
  $('emptyList').classList.toggle('hidden',groups.length!==0);
  $('bonusRows').innerHTML=groups.map(group=>{
    const totals=group.totals;
    // 성명 칸: rowspan을 쓰지 않는다 — 가로 고정(sticky)과 rowspan이 충돌해 컬럼이 틀어짐.
    // 첫 행에만 이름을 쓰고 나머지는 빈 칸. 성명~거래처(0~3)는 가로 스크롤 고정.
    const stick=index=>` data-stick="${index}"`;
    const nameCell=index=>`<td class="person-cell"${stick(0)}>${index===0
      ?`${escapeHtml(group.name)}${group.retired?'<span class="retired-badge">퇴사</span>':''}<span class="dept">${totals.count}건</span>`:''}</td>`;
    const rows=group.docs.map((doc,index)=>{
      const feeBadge=doc.manual?' <span class="common-badge">수기</span>'
        :doc.adjusted?' <span class="common-badge adjusted-badge">보정</span>'
        :doc.estimated?' <span class="common-badge">추정</span>':'';
      const docCells=doc.manual
        ?`<td${stick(1)}><input class="mini-input row-doc" value="${escapeHtml(doc.doc_id)}"><button class="remove-row" type="button" title="수기 행 삭제">✕</button></td>
          <td${stick(2)}><input class="mini-input row-work" value="${escapeHtml(doc.work_type||'')}" placeholder="업무분류"></td>
          <td${stick(3)}><input class="mini-input row-cust" value="${escapeHtml(doc.customer_name||'')}" placeholder="거래처"></td>
          <td>${escapeHtml(group.name)}</td><td>-</td>`
        :`<td${stick(1)}>${escapeHtml(doc.doc_id)}</td>
          <td${stick(2)}>${escapeHtml(doc.work_type||'-')}${doc.common?' <span class="common-badge">공통</span>':''}</td>
          <td${stick(3)} title="${escapeHtml(doc.customer_name||'')}">${escapeHtml(doc.customer_name||'-')}</td>
          <td>${escapeHtml(doc.manager||'-')}</td>
          <td>${escapeHtml(doc.investigator||'-')}</td>`;
      const docRate=doc.rate||defaultRate;
      const rateCell=`<td class="number"><select class="rate-select row-rate">
        ${rateOptions.map(rate=>`<option value="${rate}"${docRate===rate?' selected':''}>${rate}%</option>`).join('')}
      </select><span class="row-bonus">${doc.bonus_amount!=null?num(doc.bonus_amount):''}</span></td>`;
      // 주주: 순수수료 고정·산정금액 입력. 평·동: 순수수료 입력·산정은 계산(즉시 재계산용
      // data-fee-adj = 토지-여비, data-indemnity-rate = 손배 요율)
      const costsAttr=` data-costs="${doc.indemnity+doc.association_fee}"`+(isShareholder?''
        :` data-fee-adj="${Math.round((doc.land_fee||0)-(doc.travel_fee||0))}" data-indemnity-rate="${(doc.work_type||'').trim()==='담보'?0.015:0.01}"`);
      const feeCell=isShareholder
        ?`<td class="number">${doc.manual?'-':num(doc.base_fee)}</td>`
        :`<td class="number"><input class="amount-input fee-input" inputmode="numeric" data-orig="${doc.auto_fee==null?'':Math.round(doc.auto_fee)}" value="${money.format(Math.round(doc.base_fee))}">${feeBadge}</td>`;
      const assessedCell=isShareholder
        ?`<td class="number"><input class="amount-input assessed-input" inputmode="numeric" data-orig="${doc.auto_assessed==null?'':Math.round(doc.auto_assessed)}" value="${money.format(Math.round(doc.assessed))}">${feeBadge}</td>`
        :`<td class="number row-assessed">${num(doc.assessed)}</td>`;
      // 감정서 행: 1~4,6,9,13은 값, 5·7·8·12·17은 행별 입력칸, 10·11은 행별 계산값.
      // 14~19(세전~카드)는 천원 절사·제세공과가 사람 단위 수식이라 합계 행에서만 계산 → 행은 '-'
      const expenseAuto=Math.round(doc.expense_fee||0);
      const valueCells=`${feeCell}
      <td class="number">${doc.manual?'-':num(doc.travel_fee)}</td>
      <td class="number">${num(doc.land_fee)}</td>
      ${assessedCell}
      <td class="number">${docFieldInput('가변비',doc.variable_cost)}</td>
      <td class="number row-indemnity">${num(doc.indemnity)}</td>
      <td class="number">${docFieldInput('미납비이월',doc.unpaid_carry)}</td>
      <td class="number"><input class="mini-input amount-input doc-field-input" inputmode="numeric" data-field="감정서경비" data-auto="${expenseAuto}" value="${money.format(Math.round(doc.doc_expense||0))}">
        <span class="settle-auto${Math.round(doc.doc_expense||0)===expenseAuto?'':' overridden'}" title="자동값 = 아마란스 본사 경비 전표(용역비·세금과공과금·잡급·도서인쇄비) 중 적요의 감정서번호로 귀속한 금액 안분">자동 ${money.format(expenseAuto)}</span></td>
      <td class="number">${num(doc.association_fee)}</td>
      <td class="number row-base">${num(doc.payout_base)}</td>
      <td class="number row-bonus-amount">${num(doc.bonus_amount)}</td>
      <td class="number">${docFieldInput('화환공제',doc.wreath)}</td>
      <td class="number">${doc.manual?'-':num(doc.survey_fee)}</td>
      <td class="number">-</td><td class="number">-</td><td class="number">-</td>
      <td class="number">${docFieldInput('기타공제',doc.other_deduct)}</td>
      <td class="number">-</td><td class="number">-</td>
      <td>${escapeHtml(doc.paid_date||'-')}</td>`;
      return `<tr${index===0?' class="group-start"':''} data-docid="${escapeHtml(doc.doc_id)}"${doc.manual?' data-manual="1"':''}${costsAttr}>
      ${nameCell(index)}
      ${docCells}${rateCell}
      ${valueCells}
    </tr>`;}).join('');
    const deductions=group.deductions||[];
    // 합계 행 = 재무팀 시트 총계(19컬럼) 합계·수식만 표시 (수정은 감정서 행에서)
    const totalRow=`<tr class="person-total">
      <td data-stick="0"></td>
      <td colspan="3" class="total-label" data-stick="1">합&nbsp;&nbsp;계</td>
      <td>-</td><td>-</td>
      <td class="number total-bonus">${num(totals.bonus_selected)}</td>
      <td class="number st-fee">${num(totals.base_fee)}</td>
      <td class="number">${num(totals.travel_fee)}</td>
      <td class="number">${num(totals.land_fee)}</td>
      <td class="number st-assessed">${num(totals.assessed)}</td>
      <td class="number st-variable" data-auto="${Math.round(totals.variable_auto||0)}" title="전월 가변비(APW_IW_MONGABUNBI) 자동 ${money.format(Math.round(totals.variable_auto||0))}원 포함 — 행별 입력은 추가 조정분">${num(totals.variable_cost)}</td>
      <td class="number st-indemnity">${num(totals.indemnity)}</td>
      <td class="number st-unpaid">${num(totals.unpaid_carry)}</td>
      <td class="number st-expense">${num(totals.doc_expense)}</td>
      <td class="number">${num(totals.association_fee)}</td>
      <td class="number st-base">${num(totals.payout_base)}</td>
      <td class="number st-bonus">${num(totals.bonus_selected)}</td>
      <td class="number st-wreath">${num(totals.wreath)}</td>
      <td class="number st-survey" data-survey="${Math.round(totals.survey_fee||0)}">${num(totals.survey_fee)}</td>
      <td class="number st-pretax">${num(totals.pretax)}</td>
      <td class="number st-tax">${num(totals.tax)}</td>
      <td class="number st-after">${num(totals.after_tax)}</td>
      <td class="number st-other">${num(totals.other_deduct)}</td>
      <td class="number st-pay">${num(totals.payment)}</td>
      <td class="number st-card">${num(totals.card)}</td>
      <td>-</td>
    </tr>`;
    const deductHtml=`<span class="adjust-label">추가 공제:</span>
      <span class="deduct-list">${deductions.map(item=>`<span class="deduct-item">
        <input class="mini-input deduct-label-input" value="${escapeHtml(item.label)}" placeholder="항목">
        <input class="mini-input amount-input deduct-amount" inputmode="numeric" value="${money.format(Math.round(item.amount))}">
        <button class="remove-deduct" type="button">✕</button></span>`).join('')}</span>
      <button class="add-deduct small-button" type="button">+ 공제</button>`;
    // 공통건은 요율이 수기(3%/20% 혼재) — 행별 콤보로 직접 선택하라는 안내
    const commonNote=!isShareholder&&totals.common_count
      ?`<span class="adjust-hint">공통 ${totals.common_count}건은 요율 수기 — 행별 적용률 콤보로 선택</span>`:'';
    // 감정서번호 없이 적요에 이름만 있는 경비 전표 — 참고(합산 안 함, 필요 시 행별 입력)
    const expenseNotes=(group.expense_notes||[]);
    const notesHtml=expenseNotes.length
      ?`<span class="adjust-hint" title="${escapeHtml(expenseNotes.map(n=>`${n.voucher_date} ${n.account_name} ${money.format(Math.round(n.amount))}원 — ${n.remark}`).join('\n'))}">경비 전표(감정서 미지정) ${expenseNotes.length}건 ${money.format(Math.round(expenseNotes.reduce((s,n)=>s+n.amount,0)))}원 — 마우스를 올려 확인</span>`:'';
    return headRow+rows+totalRow+`
    <tr class="adjust-row group-end" data-person="${escapeHtml(group.name)}"><td data-stick="0"></td><td colspan="${colCount-1}"><div class="adjust-inner">
      ${deductHtml}
      <button class="add-row small-button" type="button">+ 행 추가</button>
      <button class="save-adjust primary-button small-button" type="button">저장</button>
      <span class="adjust-hint">저장하면 합계·정산이 다시 계산됩니다</span>${commonNote}${notesHtml}
    </div></td></tr>`;
  }).join('');
  wireGroupEvents(tab);
  applyResize('docsShV5');
  setStickyOffsets();
}

// 감정서 행별 수기 입력칸 (가변비·미납비이월·화환공제·기타공제 — 감정서경비는 자동값 배지가 붙어 별도 생성)
function docFieldInput(field,value){
  return `<input class="mini-input amount-input doc-field-input" inputmode="numeric" data-field="${field}" value="${money.format(Math.round(value||0))}">`;
}

// 탭별 컬럼 폭(기본값) — 폭 조절값은 A10_COLUMN_RESIZE가 localStorage에 저장한다
const BONUS_LAYOUTS={
  // 주주·평·동 공통: 성명~거래처(고정) + 담당자·조사자·입금일·적용률 + 재무팀 시트 총계 1~19
  docsShV5:[85,150,100,180,75,75,110,110,90,90,175,110,105,110,120,105,120,110,110,95,115,105,115,110,115,95,95],
  summary:[65,95,80,70,135,135,135,135],
};

// 성명~거래처 왼쪽 고정 — colgroup 폭 합으로 left를 계산한다 (폭 조절 후 다시 호출)
function setStickyOffsets(){
  const cells=document.querySelectorAll('#bonusTable [data-stick]');
  if(!cells.length)return;
  const widths=Array.from($('bonusCols').children).map(col=>parseInt(col.style.width,10)||0);
  const lefts=[0,widths[0],widths[0]+widths[1],widths[0]+widths[1]+widths[2]];
  cells.forEach(cell=>{cell.style.left=`${lefts[Number(cell.dataset.stick)]||0}px`});
}
// 컬럼 폭 드래그/더블클릭(기본 복원) 후 고정 컬럼 left 재계산
document.addEventListener('mouseup',()=>setTimeout(setStickyOffsets,0));
document.addEventListener('dblclick',()=>setTimeout(setStickyOffsets,0));

function setLayout(kind,headHtml){
  $('bonusCols').innerHTML=BONUS_LAYOUTS[kind].map(width=>`<col style="width:${width}px">`).join('');
  $('bonusHead').innerHTML=headHtml;
}

function applyResize(kind){
  if(window.A10_COLUMN_RESIZE)window.A10_COLUMN_RESIZE($('bonusTable'),`bonus-cols-${kind}`);
}

function wireGroupEvents(tab){
  document.querySelectorAll('#bonusRows .amount-input').forEach(input=>input.addEventListener('input',()=>{
    input.value=money.format(parseAmount(input.value));
  }));
  document.querySelectorAll('#bonusRows .remove-row').forEach(button=>button.addEventListener('click',()=>{
    button.closest('tr').remove();  // 저장 시 반영
  }));
  document.querySelectorAll('#bonusRows .remove-deduct').forEach(button=>button.addEventListener('click',()=>{
    button.closest('.deduct-item').remove();
  }));
  document.querySelectorAll('#bonusRows .add-deduct').forEach(button=>button.addEventListener('click',()=>{
    const span=document.createElement('span');
    span.className='deduct-item';
    span.innerHTML=`<input class="mini-input deduct-label-input" placeholder="항목(가변비 등)">
      <input class="mini-input amount-input deduct-amount" inputmode="numeric" value="0">
      <button class="remove-deduct" type="button">✕</button>`;
    button.previousElementSibling.appendChild(span);
    span.querySelector('.amount-input').addEventListener('input',event=>{event.target.value=money.format(parseAmount(event.target.value))});
    span.querySelector('.remove-deduct').addEventListener('click',()=>span.remove());
    span.querySelector('.deduct-label-input').focus();
  }));
  document.querySelectorAll('#bonusRows .add-row').forEach(button=>button.addEventListener('click',()=>addManualRow(button.closest('tr'))));
  document.querySelectorAll('#bonusRows .save-adjust').forEach(button=>button.addEventListener('click',()=>saveAdjust(button.closest('tr'),tab)));
}

function addManualRow(adjustRow){
  const person=adjustRow.dataset.person;
  // 합계 행 앞(감정서 행들 뒤)에 새 행을 넣는다
  const blockRows=[];
  let cursor=adjustRow;
  while(cursor&&!cursor.classList.contains('group-head')){cursor=cursor.previousElementSibling;if(cursor&&!cursor.classList.contains('group-head'))blockRows.unshift(cursor)}
  const isShareholder=currentTab==='shareholders';
  const firstTotal=blockRows.find(row=>row.classList.contains('person-total'));
  const tr=document.createElement('tr');
  tr.dataset.manual='1';tr.dataset.docid='';
  const commonCells=`<td class="person-cell" data-stick="0"></td>
    <td data-stick="1"><input class="mini-input row-doc" placeholder="감정서번호/내역"><button class="remove-row" type="button" title="수기 행 삭제">✕</button></td>
    <td data-stick="2"><input class="mini-input row-work" placeholder="업무분류"></td>
    <td data-stick="3"><input class="mini-input row-cust" placeholder="거래처"></td>
    <td>${escapeHtml(person)}</td><td>-</td>`;
  // 수기 행: 주주 = 산정금액 입력(손배·협회비 없음), 평·동 = 순수수료 입력(손배 1% 즉시 계산)
  tr.dataset.costs='0';
  if(!isShareholder){tr.dataset.feeAdj='0';tr.dataset.indemnityRate='0.01';}
  const rateOptions=isShareholder?[40,45,35,30]:[20,3,10,15,25,30,35,40];
  const feeCell=isShareholder
    ?'<td class="number">-</td>'
    :'<td class="number"><input class="amount-input fee-input" inputmode="numeric" data-orig="" value="0"></td>';
  const assessedCell=isShareholder
    ?'<td class="number"><input class="amount-input assessed-input" inputmode="numeric" data-orig="" value="0"></td>'
    :'<td class="number row-assessed"></td>';
  tr.innerHTML=`${commonCells}
    <td class="number"><select class="rate-select row-rate">
      ${rateOptions.map(rate=>`<option value="${rate}">${rate}%</option>`).join('')}</select><span class="row-bonus"></span></td>
    ${feeCell}
    <td class="number">-</td><td class="number">-</td>
    ${assessedCell}
    <td class="number">${docFieldInput('가변비',0)}</td>
    <td class="number row-indemnity">-</td>
    <td class="number">${docFieldInput('미납비이월',0)}</td>
    <td class="number"><input class="mini-input amount-input doc-field-input" inputmode="numeric" data-field="감정서경비" data-auto="0" value="0"></td>
    <td class="number">-</td>
    <td class="number row-base"></td><td class="number row-bonus-amount"></td>
    <td class="number">${docFieldInput('화환공제',0)}</td>
    <td class="number">-</td><td class="number">-</td><td class="number">-</td><td class="number">-</td>
    <td class="number">${docFieldInput('기타공제',0)}</td>
    <td class="number">-</td><td class="number">-</td><td>-</td>`;
  firstTotal.before(tr);
  tr.querySelectorAll('.amount-input').forEach(input=>input.addEventListener('input',event=>{event.target.value=money.format(parseAmount(event.target.value))}));
  tr.querySelector('.remove-row').addEventListener('click',()=>tr.remove());
  setStickyOffsets();
  tr.querySelector('.row-doc').focus();
}

function parseAmount(value){
  // 음수 유지 (재산정 취소 등 마이너스 산정금액 행)
  const negative=/^\s*-/.test(String(value));
  const digits=Number(String(value).replace(/[^0-9]/g,''))||0;
  return negative?-digits:digits;
}

// ── 행별 적용률·정산 즉시 재계산 (저장 전 미리보기 — 저장하면 서버 계산값으로 갱신) ──
// 서버와 같은 규칙: 행 산출액 = 산정금액(입력값) - 손배·협회비(data-costs) - 행별 수기(가변비·미납비·경비),
// 자유 항목 공제(추가 공제)만 행별 산출액 비율로 안분 후 행별 요율 적용.
// 합계 행은 합·수식만 표시: 세전 = 상여 합 - 화환공제 합 + 물건조사비 (천원 절사), 제세공과 = 세전 × 33%.
function adjustRowOf(el){
  let tr=el.closest('tr');
  while(tr&&!tr.classList.contains('adjust-row'))tr=tr.nextElementSibling;
  return tr;
}

const floorThousand=value=>Math.trunc(value/1000)*1000;

function recalcBlock(adjustRow){
  if(!adjustRow)return;
  const blockRows=[];
  let cursor=adjustRow.previousElementSibling;
  while(cursor&&!cursor.classList.contains('group-head')){blockRows.unshift(cursor);cursor=cursor.previousElementSibling}
  const docRows=blockRows.filter(row=>row.dataset.costs!==undefined&&row.querySelector('.row-rate')&&row.querySelector('.assessed-input,.fee-input'));
  if(!docRows.length)return;
  const rowField=(row,field)=>{
    const input=row.querySelector(`.doc-field-input[data-field="${field}"]`);
    return input?parseAmount(input.value):0;
  };
  // 행 수치: 주주 = 산정 입력·손배 고정(data-costs), 평·동 = 순수 입력에서 산정·손배 즉시 계산
  const rowNumbers=row=>{
    const assessedInput=row.querySelector('.assessed-input');
    if(assessedInput)return{assessed:parseAmount(assessedInput.value),costs:Number(row.dataset.costs)};
    const fee=parseAmount(row.querySelector('.fee-input').value);
    return{
      assessed:fee+Number(row.dataset.feeAdj||0),
      costs:Math.round(fee*Number(row.dataset.indemnityRate||0.01)),
      fee,
    };
  };
  const rowPayout=row=>{
    const nums=rowNumbers(row);
    return nums.assessed-nums.costs-rowField(row,'가변비')-rowField(row,'미납비이월')-rowField(row,'감정서경비');
  };
  const deductTotal=Array.from(adjustRow.querySelectorAll('.deduct-amount'))
    .reduce((sum,input)=>sum+parseAmount(input.value),0);
  // 사람 단위 가변비(전월 자동값) — 합계 행 data-auto에 담겨 온다. 공제처럼 행별 안분.
  const totalRowEarly=blockRows.find(row=>row.classList.contains('person-total'));
  const personVariable=Number(totalRowEarly?.querySelector('.st-variable')?.dataset.auto)||0;
  const spreadTotal=deductTotal+personVariable;
  const positiveTotal=docRows.reduce((sum,row)=>sum+Math.max(rowPayout(row),0),0);
  let bonusSum=0;
  docRows.forEach(row=>{
    const raw=rowPayout(row);
    const payout=Math.max(raw,0);
    const rate=Number(row.querySelector('.row-rate').value)||0;
    const share=positiveTotal>0?spreadTotal*payout/positiveTotal:0;
    const amount=Math.max(payout-share,0)*rate/100;
    bonusSum+=amount;
    const span=row.querySelector('.row-bonus');
    if(span)span.textContent=num(amount);
    // 행별 상여기준액(10)·산정상여금(11) 컬럼 갱신
    const baseCell=row.querySelector('.row-base');
    if(baseCell)baseCell.textContent=num(raw-share);
    const bonusCell=row.querySelector('.row-bonus-amount');
    if(bonusCell)bonusCell.textContent=num(amount);
    // 평·동: 순수수료 입력에 따라 산정수수료(4)·손배(6)도 즉시 갱신
    if(row.querySelector('.fee-input')){
      const nums=rowNumbers(row);
      const assessedCell=row.querySelector('.row-assessed');
      if(assessedCell)assessedCell.textContent=num(nums.assessed);
      const indemnityCell=row.querySelector('.row-indemnity');
      if(indemnityCell)indemnityCell.textContent=num(nums.costs);
    }
    // 감정서경비·가변비 자동/수기 배지 상태 (배지는 입력칸과 같은 셀에 있다)
    row.querySelectorAll('.doc-field-input[data-auto]').forEach(input=>{
      const badge=input.parentElement.querySelector('.settle-auto');
      if(badge)badge.classList.toggle('overridden',parseAmount(input.value)!==Number(input.dataset.auto));
    });
  });
  const totalRow=blockRows.find(row=>row.classList.contains('person-total'));
  if(!totalRow)return;
  const totalCell=totalRow.querySelector('.total-bonus');
  if(totalCell)totalCell.textContent=num(bonusSum);
  // 합계 행 갱신 — 산정수수료(4)·행별 수기 합(5,7,8,12,17)·기준액(10)·상여(11)·세전 이후(14~19)
  const sumField=field=>docRows.reduce((sum,row)=>sum+rowField(row,field),0);
  const assessedSum=docRows.reduce((sum,row)=>sum+rowNumbers(row).assessed,0);
  const payoutBase=docRows.reduce((sum,row)=>sum+rowPayout(row),0)-spreadTotal;
  // 평·동은 순수수료·손배 합도 입력에 따라 변한다
  if(docRows.every(row=>row.querySelector('.fee-input'))){
    const set2=(selector,value)=>{const cell=totalRow.querySelector(selector);if(cell)cell.textContent=num(value)};
    set2('.st-fee',docRows.reduce((sum,row)=>sum+rowNumbers(row).fee,0));
    set2('.st-indemnity',docRows.reduce((sum,row)=>sum+rowNumbers(row).costs,0));
  }
  const wreathSum=sumField('화환공제');
  const otherSum=sumField('기타공제');
  const survey=Number(totalRow.querySelector('.st-survey')?.dataset.survey)||0;
  const pretax=floorThousand(bonusSum-wreathSum+survey);
  const tax=Math.round(pretax*0.33);
  const set=(selector,value)=>{const cell=totalRow.querySelector(selector);if(cell)cell.textContent=num(value)};
  set('.st-assessed',assessedSum);
  set('.st-variable',sumField('가변비')+personVariable);
  set('.st-unpaid',sumField('미납비이월'));
  set('.st-expense',sumField('감정서경비'));
  set('.st-base',payoutBase);
  set('.st-bonus',bonusSum);
  set('.st-wreath',wreathSum);
  set('.st-pretax',pretax);
  set('.st-tax',tax);
  set('.st-after',pretax-tax);
  set('.st-other',otherSum);
  set('.st-pay',pretax-tax-otherSum);
  set('.st-card',floorThousand(assessedSum*0.05));
}

// 렌더마다 다시 걸지 않도록 컨테이너에 한 번만 위임 등록
$('bonusRows').addEventListener('change',event=>{
  if(event.target.classList.contains('row-rate'))recalcBlock(adjustRowOf(event.target));
});
$('bonusRows').addEventListener('input',event=>{
  if(event.target.classList.contains('deduct-amount')||event.target.classList.contains('assessed-input')
    ||event.target.classList.contains('fee-input')||event.target.classList.contains('doc-field-input'))
    recalcBlock(adjustRowOf(event.target));
});
$('bonusRows').addEventListener('click',event=>{
  if(event.target.classList.contains('remove-deduct')){
    const adjustRow=adjustRowOf(event.target);
    if(adjustRow)setTimeout(()=>recalcBlock(adjustRow),0);  // 항목 제거 후 재계산
  }
},true);

async function saveAdjust(adjustRow,tab){
  const person=adjustRow.dataset.person;
  // 이 사람 블록의 행들 수집 (group-head 이후 ~ adjust-row 이전)
  const blockRows=[];
  let cursor=adjustRow.previousElementSibling;
  while(cursor&&!cursor.classList.contains('group-head')){blockRows.unshift(cursor);cursor=cursor.previousElementSibling}
  const fees=[],assessedOverrides=[],rows=[],docRates=[],fields=[];
  // 행별 수기 항목 — 감정서경비는 행 자동값과 다를 때만 저장(같으면 자동값 유지), 나머지는 0이 아니면 저장
  const collectFields=(row,docId)=>row.querySelectorAll('.doc-field-input').forEach(input=>{
    const label=input.dataset.field;
    const amount=parseAmount(input.value);
    if(label==='감정서경비'){
      if(amount!==Number(input.dataset.auto))fields.push({doc_id:docId,label,amount});
    }else if(amount!==0)fields.push({doc_id:docId,label,amount});
  });
  blockRows.filter(row=>row.querySelector('.fee-input,.assessed-input')).forEach(row=>{
    const isAssessed=!!row.querySelector('.assessed-input');  // 주주 = 산정금액, 평·동 = 순수수료
    const input=row.querySelector('.assessed-input')||row.querySelector('.fee-input');
    const value=parseAmount(input.value);
    const rateSelect=row.querySelector('.row-rate');
    const rate=rateSelect&&rateSelect.value?Number(rateSelect.value):null;
    if(row.dataset.manual){
      const doc=row.querySelector('.row-doc').value.trim();
      if(!doc&&!value)return;  // 완전히 빈 수기 행은 무시
      const docId=doc||'(수기)';
      rows.push({
        doc_id:docId,
        work_type:row.querySelector('.row-work').value.trim()||null,
        customer_name:row.querySelector('.row-cust').value.trim()||null,
        amount:value,
      });
      if(rate)docRates.push({doc_id:docId,rate});
      collectFields(row,docId);
    }else{
      const orig=input.dataset.orig;
      if(orig!==''&&value!==Number(orig)){
        if(isAssessed)assessedOverrides.push({doc_id:row.dataset.docid,assessed:value});
        else fees.push({doc_id:row.dataset.docid,fee:value});
      }
      if(rate)docRates.push({doc_id:row.dataset.docid,rate});
      collectFields(row,row.dataset.docid);
    }
  });
  const deductions=Array.from(adjustRow.querySelectorAll('.deduct-item')).map(item=>({
    label:item.querySelector('.deduct-label-input').value.trim()||'공제',
    amount:parseAmount(item.querySelector('.deduct-amount').value),
  })).filter(item=>item.amount!==0);
  const [year,month]=$('perfMonth').value.split('-');
  const button=adjustRow.querySelector('.save-adjust');
  button.disabled=true;
  try{
    const response=await fetch('/api/bonus/adjust',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        requester_usr_seq:Number(window.A10_CTX.usr_seq),
        year:Number(year),month:Number(month),person,
        fees,assessed_overrides:assessedOverrides,rows,deductions,
        doc_rates:docRates,fields,
      }),
    });
    const payload=await response.json();
    if(!payload.success)throw new Error(payload.message);
    showToast(payload.message);
    await loadReport();
  }catch(error){
    showToast(error.message,true);
    button.disabled=false;
  }
}

function showToast(message,isError=false){const toast=$('toast');toast.textContent=message;toast.classList.toggle('error',isError);toast.classList.remove('hidden');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.add('hidden'),4500)}

function renderSummary(){
  const rows=currentData.summary;
  setLayout('summary',`<tr>
    <th>구분</th><th>성명</th><th>부서</th><th class="number">건수</th>
    <th class="number">순수수료 합계</th><th class="number">산정금액 합계</th>
    <th class="number">산출액</th><th class="number">상여 참고</th>
  </tr>`);
  $('emptyList').classList.toggle('hidden',rows.length!==0);
  const totalRow=rows.reduce((acc,row)=>({
    count:acc.count+row.count,base_fee:acc.base_fee+row.base_fee,
    assessed:acc.assessed+row.assessed,payout_base:acc.payout_base+row.payout_base,
    bonus_ref:acc.bonus_ref+(row.bonus_ref||0),
  }),{count:0,base_fee:0,assessed:0,payout_base:0,bonus_ref:0});
  $('bonusRows').innerHTML=rows.map(row=>`<tr>
    <td>${escapeHtml(row.kind)}</td>
    <td>${escapeHtml(row.name)}</td>
    <td>${row.dept?escapeHtml(row.dept):'<span class="dept-unknown">미확인</span>'}</td>
    <td class="number">${num(row.count)}</td>
    <td class="number">${num(row.base_fee)}</td>
    <td class="number">${num(row.assessed)}</td>
    <td class="number">${num(row.payout_base)}</td>
    <td class="number">${num(row.bonus_ref)}</td>
  </tr>`).join('')+`<tr class="grand-total">
    <td colspan="3">합계</td>
    <td class="number">${num(totalRow.count)}</td>
    <td class="number">${num(totalRow.base_fee)}</td>
    <td class="number">${num(totalRow.assessed)}</td>
    <td class="number">${num(totalRow.payout_base)}</td>
    <td class="number">${num(totalRow.bonus_ref)}</td>
  </tr>`;
  applyResize('summary');
}

function showError(error){$('resultSummary').textContent='조회하지 못했습니다';$('bonusRows').innerHTML='';$('bonusHead').innerHTML='';$('emptyList').classList.remove('hidden');$('emptyList').textContent=error.message}

document.querySelectorAll('.bonus-tabs button').forEach(button=>button.addEventListener('click',()=>{
  currentTab=button.dataset.tab;
  document.querySelectorAll('.bonus-tabs button').forEach(other=>other.classList.toggle('active',other===button));
  render();
}));

// 기본 실적월 = 지난달 (상여월의 전월 실적)
const now=new Date();
const lastMonth=new Date(now.getFullYear(),now.getMonth()-1,1);
$('perfMonth').value=`${lastMonth.getFullYear()}-${String(lastMonth.getMonth()+1).padStart(2,'0')}`;

$('searchButton').addEventListener('click',()=>loadReport().catch(showError));
$('perfMonth').addEventListener('keydown',event=>{if(event.key==='Enter')$('searchButton').click()});
$('exportButton').addEventListener('click',()=>{window.A10_DOWNLOAD(`/api/bonus/export.xlsx?${monthQuery()}&tab=${currentTab}`);});

window.A10_READY.then(ctx=>{
  if(ctx.office_id!=='10'){
    $('bonusRows').innerHTML='';$('resultSummary').textContent='';
    $('emptyList').classList.remove('hidden');$('emptyList').textContent='상여 화면은 본사만 사용할 수 있습니다.';
    return;
  }
  loadReport().catch(showError);
});

// 사람·요율·지분 설정(딸림 화면). 권한 키는 상여를 같이 쓴다 (2026-08-25).
$('settingsButton').addEventListener('click', () => { location.href = '/desktop/bonus-settings'; });
