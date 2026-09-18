// 전자세금계산서 발급 팝업 (공통). 감정서 LIST·입금현황에서 우클릭 → 발급.
// window.A10_TAX_ISSUE(docId) 하나로 연다. 다이얼로그 DOM·스타일은 이 파일이 자체 주입한다.
// POPBILL_IS_TEST=true면 팝빌 테스트 서버로만 발급된다(국세청·거래처 미전송).
(function () {
  const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const $ = id => document.getElementById(id);
  let current = null; // {doc_id, receiver}

  function inject() {
    if ($('taxIssueDialog')) return;
    const style = document.createElement('style');
    style.textContent = `
      #taxIssueDialog{border:none;border-radius:16px;padding:0;max-width:560px;width:92vw;box-shadow:0 24px 60px rgba(20,40,30,.28)}
      #taxIssueDialog::backdrop{background:rgba(20,33,29,.45)}
      .tax-card{padding:22px 24px;font-size:13px;color:var(--ink,#17211d)}
      .tax-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:14px}
      .tax-head h2{margin:2px 0 0;font-size:17px}
      .tax-close{border:none;background:none;font-size:22px;cursor:pointer;color:#8a949f;line-height:1}
      .tax-tabs{display:flex;gap:6px;margin-bottom:12px}
      .tax-tab{flex:1;height:34px;border:1px solid var(--line,#d7ded9);background:#fff;border-radius:9px;font-weight:700;cursor:pointer;color:#68736e}
      .tax-tab.active{background:var(--green,#1b7a43);color:#fff;border-color:var(--green,#1b7a43)}
      .tax-sec{border:1px solid var(--line,#e3e9e6);border-radius:12px;padding:12px 14px;margin-bottom:12px}
      .tax-sec h3{margin:0 0 8px;font-size:12px;color:var(--muted,#68736e);font-weight:750}
      .tax-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px 12px}
      .tax-grid label{display:flex;flex-direction:column;gap:3px;font-size:11px;color:var(--muted,#68736e)}
      .tax-grid label.wide{grid-column:1 / -1}
      .tax-grid input,.tax-grid select{height:32px;border:1px solid var(--line,#d7ded9);border-radius:8px;padding:0 8px;font:inherit}
      .tax-amt{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;align-items:end}
      .tax-amt label{font-size:11px;color:var(--muted,#68736e);display:flex;flex-direction:column;gap:4px}
      .tax-amt input{height:34px;box-sizing:border-box;width:100%;border:1px solid var(--line,#d7ded9);border-radius:8px;padding:0 8px;text-align:right;font:inherit;font-weight:700}
      .tax-amt .total{height:34px;display:flex;align-items:center;justify-content:flex-end;font-size:16px;font-weight:800;color:var(--green,#1b7a43)}
      /* flex-wrap: 버튼이 늘어 폭이 넘치면 줄바꿈 — flex-end 정렬에서 넘친 만큼
         왼쪽부터 잘려 '수정발급' 버튼이 사라졌던 사고 방지 (2026-09-02) */
      .tax-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:6px;margin-top:6px}
      .tax-actions button{height:38px;padding:0 12px;border-radius:9px;border:1px solid var(--line,#d7ded9);background:#fff;font-weight:700;cursor:pointer;white-space:nowrap;flex:0 0 auto}
      .tax-actions .primary{background:var(--green,#1b7a43);color:#fff;border-color:var(--green,#1b7a43)}
      .tax-actions .primary:disabled{opacity:.5;cursor:default}
      .tax-actions .danger{color:#c62828;border-color:#e0b8b8}
      .tax-actions .danger:disabled{opacity:.5;cursor:default}
      /* 취소(사유+버튼)는 왼쪽, 인쇄·발급·닫기는 오른쪽으로 갈라 놓는다 */
      .tax-actions #cashCancelBtn{margin-right:auto}
      .tax-actions select,.tax-actions input{height:38px;box-sizing:border-box;border:1px solid var(--line,#d7ded9);border-radius:9px;padding:0 8px;font:inherit;font-weight:700;background:#fff;flex:0 0 auto;width:auto}
      .tax-search{display:flex;gap:6px;margin-bottom:8px}
      .tax-search input{flex:1;height:32px;border:1px solid var(--line,#d7ded9);border-radius:8px;padding:0 8px;font:inherit}
      .tax-search button{height:32px;padding:0 14px;border-radius:8px;border:1px solid var(--line,#d7ded9);background:#fff;font-weight:700;cursor:pointer}
      .tax-cust-results{max-height:150px;overflow:auto;border:1px solid var(--line,#e3e9e6);border-radius:8px;margin-bottom:10px}
      .tax-cust-results button{display:block;width:100%;text-align:left;border:none;background:#fff;border-bottom:1px solid #f0f3f1;padding:7px 10px;cursor:pointer;font:inherit}
      .tax-cust-results button:hover{background:#f2f7f4}
      .tax-cust-results small{color:#68736e}
      .req{color:#c62828;font-style:normal;font-weight:800}
      .tax-grid input.invalid,.tax-amt input.invalid,#taxWriteDate.invalid{border-color:#c62828;background:#fff6f6}
      .tax-msg{font-size:12px;margin:8px 0 0;min-height:16px}
      .tax-msg.err{color:#c62828}.tax-msg.ok{color:#1b7a43}
      .tax-warn{background:#fff8e6;border:1px solid #f0e0b0;color:#7a611c;border-radius:8px;padding:8px 10px;font-size:12px;margin-bottom:10px}
      .tax-modify{background:#f7f4ee;border:1px solid #ddd4c4;border-radius:10px;padding:10px 12px;margin:0 0 10px}
      .tax-modify p{margin:0 0 8px;font-size:12px;color:#645b4d;line-height:1.45}
      .tax-register-row{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:9px}
      .tax-register-row span{font-size:11px;color:var(--muted,#68736e)}
      .tax-register-row button{height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--line,#d7ded9);background:#fff;font-weight:700;cursor:pointer;white-space:nowrap}
      .tax-register-row button:disabled{opacity:.5;cursor:default}
      #taxCombineDocs{width:100%;box-sizing:border-box;border:1px solid var(--line,#d7ded9);border-radius:8px;padding:6px 8px;font:inherit;font-size:13px;resize:vertical}
      .tax-combine-actions{display:flex;gap:10px;align-items:flex-start;font-size:12px;color:#56625c}
      .tax-combine-actions button{height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--line,#d7ded9);background:#fff;font-weight:700;cursor:pointer;white-space:nowrap}
      .tax-combine-actions .bad{color:#c62828}
      .tax-combine-actions .ok{color:#1b7a43;font-weight:700}
      .tax-pool-toggle{display:flex;flex-direction:row;align-items:center;gap:8px;font-size:12px;font-weight:650;color:#244f68}
      .tax-pool-toggle input{width:16px;height:16px;margin:0}
    `;
    document.head.appendChild(style);
    const dlg = document.createElement('dialog');
    dlg.id = 'taxIssueDialog';
    dlg.innerHTML = `
      <form method="dialog" class="tax-card">
        <div class="tax-head">
          <div><h2><span id="taxTitle">세금계산서</span> 발급 <span id="taxDocId" style="font-size:13px;color:#68736e"></span></h2></div>
          <button class="tax-close" value="cancel" aria-label="닫기">×</button>
        </div>
        <div class="tax-tabs">
          <button type="button" id="tabTax" class="tax-tab active">세금계산서</button>
          <button type="button" id="tabCash" class="tax-tab">현금영수증</button>
        </div>
        <div id="taxWarn" class="tax-warn hidden"></div>
        <div class="tax-sec" id="taxReceiverSec">
          <h3>공급받는자 (거래처) — 자동으로 안 채워지면 검색하거나 직접 입력</h3>
          <div class="tax-search">
            <input id="taxCustSearch" type="search" placeholder="거래처명 또는 사업자번호로 검색">
            <button type="button" id="taxCustSearchBtn">검색</button>
          </div>
          <div id="taxCustResults" class="tax-cust-results hidden"></div>
          <div class="tax-grid">
            <label><span>사업자번호 <em class="req">*</em></span><input id="taxRcvCorpNum" inputmode="numeric"></label>
            <label><span>상호 <em class="req">*</em></span><input id="taxRcvName"></label>
            <label><span>대표자 <em class="req">*</em></span><input id="taxRcvCeo"></label>
            <label>업태<input id="taxRcvBizType" list="bizTypeList" autocomplete="off"></label>
            <label>종목<input id="taxRcvBizClass" list="bizClassList" autocomplete="off"></label>
            <label><span>이메일 <em class="req">*</em></span><input id="taxRcvEmail" type="email" placeholder="전자계산서 수신"></label>
            <label class="wide">주소<input id="taxRcvAddr"></label>
            <datalist id="bizTypeList"><option value="부동산업"><option value="서비스"><option value="금융"><option value="관공서"><option value="도소매"><option value="제조"><option value="건설"><option value="종합건설"><option value="금융서비스"></datalist>
            <datalist id="bizClassList"><option value="임대"><option value="점포"><option value="은행"><option value="부동산담보신탁"><option value="세무사"><option value="주택신축판매"><option value="비영리"><option value="일반건축공사"></datalist>
          </div>
          <div class="tax-register-row">
            <span>Amaranth에 없는 거래처면 위 정보를 입력한 뒤 등록하세요.</span>
            <button type="button" id="taxCustRegisterBtn">입력한 정보로 거래처 등록</button>
          </div>
        </div>
        <div class="tax-sec hidden" id="cashSec">
          <h3>현금영수증 정보 — 지출증빙용은 거래처 사업자번호로 자동 채움, 소득공제용(휴대폰번호)은 직접 입력</h3>
          <div class="tax-grid">
            <label>거래구분<select id="cashUsage"><option value="소득공제용">소득공제용(개인)</option><option value="지출증빙용">지출증빙용(사업자)</option></select></label>
            <label><span>식별번호 <em class="req">*</em></span><input id="cashIdentity" inputmode="numeric" placeholder="휴대폰번호 또는 사업자번호"></label>
            <label>고객명<input id="cashCustomer"></label>
            <label>수신 이메일<input id="cashEmail" type="email"></label>
          </div>
        </div>
        <div class="tax-sec">
          <h3>금액 (청구액 자동 · 수정 가능)</h3>
          <div class="tax-amt">
            <label><span>공급가액 <em class="req">*</em></span><input id="taxSupply" inputmode="numeric"></label>
            <label>세액<input id="taxVat" inputmode="numeric"></label>
            <label>합계<span id="taxTotal" class="total">0</span></label>
          </div>
          <div class="tax-grid" id="taxDateRow" style="margin-top:10px">
            <label><span>작성일자 <em class="req">*</em></span><input id="taxWriteDate" type="date"></label>
            <label>영수/청구<select id="taxPurpose"><option>청구</option><option>영수</option></select></label>
            <label class="wide">품목<input id="taxItemName" maxlength="100"></label>
            <label>계정과목<select id="taxAccountCode">
              <option value="4010001">감정수수료</option>
              <option value="4010002">기타수수료</option>
              <option value="4010003">공시지가등수익</option>
              <option value="4010004">용역수수료</option>
              <option value="4010005">임대수수료</option>
              <option value="9090000">주차장수익</option>
            </select></label>
            <label>팩스 전송<input id="taxFaxNo" inputmode="numeric" maxlength="20" placeholder="번호 입력 시 발급 후 자동 전송"></label>
            <label>비고1 (상단)<input id="taxRemark1" maxlength="120" placeholder="비워두면 미표기"></label>
            <label>비고 (품목 줄)<input id="taxItemRemark" maxlength="100" placeholder="비워두면 미표기"></label>
          </div>
          <div class="tax-grid" id="taxPoolRow" style="margin-top:10px">
            <label class="wide tax-pool-toggle"><input id="taxPoolMode" type="checkbox"> 입금 적용용으로 발행 — 대표번호 한 장으로 크게 끊고, 같은 거래처 감정서에 입금이 잡힐 때마다 자동으로 나눠 붙입니다</label>
            <div class="wide tax-combine-actions" id="taxPoolInfo"></div>
          </div>
          <div class="tax-grid" id="taxCombineRow" style="margin-top:10px">
            <label class="wide">합산 발행 — 같은 거래처의 다른 감정서번호를 적으면 한 장으로 끊습니다 (쉼표·줄바꿈 구분, 한 장에 99건까지)
              <textarea id="taxCombineDocs" rows="2" placeholder="01-2609-3-0001, 01-2609-3-0002"></textarea></label>
            <div class="wide tax-combine-actions"><button type="button" id="taxCombineCheck">묶을 감정서 확인</button><span id="taxCombineInfo"></span></div>
          </div>
        </div>
        <div id="taxModifySec" class="tax-modify hidden">
          <p id="taxModifyHelp"></p>
          <div class="tax-grid">
            <label id="taxCancelTypeWrap">수정 사유<select id="taxCancelType" aria-label="세금계산서 수정사유">
              <option value="1">기재사항 착오정정</option>
              <option value="2">공급가액 변동</option>
              <option value="3">환입</option>
              <option value="4">계약의 해제</option>
              <option value="5">내국신용장 사후개설</option>
              <option value="6">착오에 의한 이중발급</option>
            </select></label>
            <label id="taxCancelDateWrap" class="hidden"><span id="taxCancelDateLabel">사유 발생일</span><input id="taxCancelDate" type="date"></label>
            <label id="taxAdjustSupplyWrap" class="hidden"><span id="taxAdjustSupplyLabel">공급가액</span><input id="taxAdjustSupply" inputmode="numeric"></label>
            <label id="taxAdjustVatWrap" class="hidden"><span id="taxAdjustVatLabel">세액</span><input id="taxAdjustVat" inputmode="numeric"></label>
            <label class="wide">수정발급 비고<input id="taxCancelMemo" maxlength="120" placeholder="선택 입력"></label>
          </div>
        </div>
        <p id="taxMsg" class="tax-msg"></p>
        <div class="tax-actions">
          <select id="cashCancelType" class="hidden" aria-label="취소사유">
            <option value="1">거래취소</option>
            <option value="2">오류발급취소</option>
            <option value="3">기타</option>
          </select>
          <button id="cashCancelBtn" type="button" class="danger hidden">현금영수증 취소</button>
          <button id="taxFaxBtn" type="button" class="hidden">팩스 전송</button>
          <button id="taxMailBtn" type="button" class="hidden"
            title="위 이메일 칸의 주소로 발행된 세금계산서 안내메일을 다시 보냅니다">메일 재전송</button>
          <button id="taxVoucherBtn" type="button" class="hidden">전표 생성</button>
          <button id="taxPrintBtn" type="button" class="hidden">인쇄</button>
          <button id="taxMoreBtn" type="button" class="hidden"
            title="착수금 계산서 뒤에 잔금 계산서처럼, 같은 감정서로 세금계산서를 한 장 더 발행합니다">추가 발행</button>
          <button id="taxIssueBtn" class="primary" type="button">발급</button>
          <button value="cancel">닫기</button>
        </div>
      </form>`;
    document.body.appendChild(dlg);
    // 공급가액 수정 시 세액 = 공급가액 10% 자동 계산 (세액 직접 수정도 가능 —
    // 이후 공급가액을 다시 고치면 10%로 재계산된다)
    $('taxSupply').addEventListener('input', () => {
      reformat($('taxSupply'), fmtMoney);
      $('taxVat').value = fmtMoney(String(Math.round(Number(digits($('taxSupply').value) || 0) * 0.1)));
      recalc();
    });
    $('taxVat').addEventListener('input', () => { reformat($('taxVat'), fmtMoney); recalc(); });
    $('taxRcvCorpNum').addEventListener('input', () => reformat($('taxRcvCorpNum'), fmtBiz));
    $('taxIssueBtn').addEventListener('click', doIssue);
    $('taxFaxBtn').addEventListener('click', doFax);
    $('taxMailBtn').addEventListener('click', doMail);
    $('taxVoucherBtn').addEventListener('click', doVoucher);
    $('taxPrintBtn').addEventListener('click', doPrint);
    $('taxMoreBtn').addEventListener('click', startAdditional);
    $('cashCancelBtn').addEventListener('click', doCancelCash);
    $('taxCancelType').addEventListener('change', syncTaxModifyFields);
    $('taxAdjustSupply').addEventListener('input', () => reformat($('taxAdjustSupply'), fmtMoney));
    $('taxAdjustVat').addEventListener('input', () => reformat($('taxAdjustVat'), fmtMoney));
    $('tabTax').addEventListener('click', () => setMode('tax'));
    $('tabCash').addEventListener('click', () => setMode('cash'));
    $('cashUsage').addEventListener('change', fillCashFromTax);
    $('cashIdentity').addEventListener('input', () => { $('cashIdentity').dataset.auto = ''; });
    ['taxRcvName', 'taxRcvCeo', 'taxRcvCorpNum', 'taxRcvEmail', 'cashIdentity', 'taxWriteDate'].forEach(
      id => $(id).addEventListener('input', validate));
    $('taxCustSearchBtn').addEventListener('click', searchCustomer);
    $('taxCombineCheck').addEventListener('click', checkCombine);
    $('taxPoolMode').addEventListener('change', togglePoolMode);
    $('taxCustSearch').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); searchCustomer(); } });
    $('taxCustRegisterBtn').addEventListener('click', registerCustomer);
    // method="dialog" 폼은 입력칸 Enter가 암시적 제출 = 팝업 닫힘이라 전부 막는다.
    dlg.querySelector('form').addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') e.preventDefault();
    });
  }

  // 공급받는자 그리드에 입력된 값을 그대로 Amaranth 거래처로 등록한다.
  // 성공(또는 기등록)하면 그 거래처를 선택 상태로 만든다.
  async function registerCustomer() {
    const name = $('taxRcvName').value.trim();
    const bizNo = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
    if (!name) { setTaxMsg('상호를 입력하세요.', true); $('taxRcvName').focus(); return; }
    if (bizNo.length !== 10) { setTaxMsg('사업자번호 10자리를 입력하세요.', true); $('taxRcvCorpNum').focus(); return; }
    if (!window.confirm(`"${name}" (사업자번호 ${fmtBiz(bizNo)})\nAmaranth 거래처로 바로 등록합니다. 계속할까요?`)) return;
    const btn = $('taxCustRegisterBtn');
    btn.disabled = true; btn.textContent = '등록 중...';
    try {
      const res = await fetch('/api/taxinvoice/register-customer', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name, business_no: bizNo,
          representative: $('taxRcvCeo').value.trim() || null,
          business_type: $('taxRcvBizType').value.trim() || null,
          business_item: $('taxRcvBizClass').value.trim() || null,
          address1: $('taxRcvAddr').value.trim() || null,
          email: $('taxRcvEmail').value.trim() || null,
        }),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message || '거래처 등록에 실패했습니다.');
      const partner = p.data || {};
      if (partner.partner_code) current.receiver = { ...(current.receiver || {}), tr_cd: partner.partner_code };
      current.warns = (current.warns || []).filter(w => !w.startsWith('거래처 사업자번호가 없습니다'));
      renderModeState();
      setTaxMsg(p.code === 'PARTNER_DUPLICATE'
        ? `이미 등록된 거래처입니다 (코드 ${partner.partner_code || '-'}) — 선택 상태로 두었습니다.`
        : `거래처가 등록되었습니다 (코드 ${partner.partner_code || '-'}).`, false);
    } catch (e) {
      setTaxMsg(`거래처 등록 실패: ${e.message}`, true);
    } finally {
      btn.disabled = false; btn.textContent = '입력한 정보로 거래처 등록';
    }
  }

  function setTaxMsg(text, isError) {
    $('taxMsg').textContent = text;
    $('taxMsg').className = isError ? 'tax-msg err' : 'tax-msg ok';
  }

  async function searchCustomer() {
    const q = $('taxCustSearch').value.trim();
    if (!q) return;
    const box = $('taxCustResults');
    box.classList.remove('hidden');
    box.innerHTML = '<button type="button" disabled>검색 중...</button>';
    try {
      const res = await fetch(`/api/taxinvoice/customer-search?q=${encodeURIComponent(q)}`);
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      const items = (p.data && p.data.items) || [];
      if (!items.length) { box.innerHTML = '<button type="button" disabled>결과 없음</button>'; return; }
      box.innerHTML = items.map((it, i) =>
        `<button type="button" data-i="${i}"><strong>${esc(it.name || '-')}</strong> <small>${esc(fmtBiz(it.business_no || '') || '사업자번호 없음')} · ${esc(it.representative || '대표 미등록')}</small></button>`
      ).join('');
      box.querySelectorAll('button[data-i]').forEach(b => b.addEventListener('click', () => { pickCustomer(items[Number(b.dataset.i)]); box.classList.add('hidden'); }));
    } catch (e) {
      box.innerHTML = `<button type="button" disabled>${esc(e.message)}</button>`;
    }
  }

  function pickCustomer(it) {
    current.receiver = { tr_cd: it.partner_code || '', hp: it.hp || '' };
    $('taxRcvCorpNum').value = fmtBiz(it.business_no || '');
    $('taxRcvName').value = it.name || '';
    $('taxRcvCeo').value = it.representative || '';
    $('taxRcvBizType').value = it.business_type || '';
    $('taxRcvBizClass').value = it.business_item || '';
    // 이메일은 기본정보가 아니라 아마란스 담당자탭(고객사담당자 '정') 기준 —
    // 세금계산서 화면과 같은 원천. 은행 지점은 기본정보 email이 대부분 빈칸이다.
    $('taxRcvEmail').value = '';
    if (it.partner_code) fillContactEmail(it.partner_code);
    $('taxRcvAddr').value = [it.address1, it.address2].filter(Boolean).join(' ');
    if ($('taxRcvCorpNum').value.replace(/[^0-9]/g, '').length === 10)
      current.warns = current.warns.filter(w => !w.startsWith('거래처 사업자번호가 없습니다'));
    renderModeState();
  }

  async function fillContactEmail(trCd) {
    try {
      const res = await fetch(`/api/taxinvoice/contact-email?tr_cd=${encodeURIComponent(trCd)}`);
      const p = await res.json();
      const email = (p.data && p.data.email) || '';
      // 응답이 오는 사이 다른 거래처를 골랐거나 수기 입력했으면 덮어쓰지 않는다
      if (email && current && current.receiver && current.receiver.tr_cd === trCd
          && !$('taxRcvEmail').value.trim()) {
        $('taxRcvEmail').value = email;
        // 프로그램이 채운 값은 input 이벤트가 없어 검증이 다시 안 돈다 — 채워
        // 놓고도 빨간 테두리(발급 잠김)가 남아 다시 쳐야 풀렸다(2026-08-28).
        validate();
      }
    } catch (e) { /* 조회 실패 시 수기 입력 */ }
  }

  let mode = 'tax';
  function syncModeEvidence() {
    if (!current) return;
    const issued = mode === 'cash' ? current.issuedCash : current.issuedTax;
    current.issued = !!issued;
    current.issuedType = issued ? mode : null;
  }

  function evidenceRemaining() {
    const combined = (current && current.combinedTotals) || { supply: 0, tax: 0, total: 0 };
    return {
      supply: Math.max(0, ((current && current.fullSupply) || 0) - (combined.supply || 0)),
      tax: Math.max(0, ((current && current.fullTax) || 0) - (combined.tax || 0)),
      total: Math.max(0, ((current && current.fullTotal) || 0) - (combined.total || 0)),
    };
  }

  function prefillEvidenceRemaining() {
    if (!current || !current.loaded || current.issued) return;
    const combined = current.combinedTotals || { total: 0 };
    if (!(combined.total > 0)) return;
    const remain = evidenceRemaining();
    $('taxSupply').value = fmtMoney(remain.supply);
    $('taxVat').value = fmtMoney(remain.tax);
    recalc();
  }

  function setMode(m) {
    mode = m;
    $('tabTax').classList.toggle('active', m === 'tax');
    $('tabCash').classList.toggle('active', m === 'cash');
    $('taxReceiverSec').classList.toggle('hidden', m !== 'tax');
    $('cashSec').classList.toggle('hidden', m !== 'cash');
    $('taxDateRow').classList.toggle('hidden', m !== 'tax');  // 작성일자·영수청구는 세금계산서만
    $('taxCombineRow').classList.toggle('hidden', m !== 'tax');
    $('taxPoolRow').classList.toggle('hidden', m !== 'tax');
    $('taxTitle').textContent = m === 'tax' ? '세금계산서' : '현금영수증';
    // 탭 전환 시 이전 탭의 결과 메시지를 지우고, 이 탭 기준의 경고·버튼 상태로 다시 그린다.
    if (!$('taxIssueBtn').dataset.loading) { $('taxMsg').textContent = ''; $('taxMsg').className = 'tax-msg'; }
    if (m === 'cash') fillCashFromTax();
    syncModeEvidence();
    prefillEvidenceRemaining();
    renderModeState();
  }

  // 경고(기발행 등)와 발급 버튼 상태 표시. 각 증빙 유형은 이미 발급된 탭만 잠그고,
  // 다른 탭에는 전체 청구액에서 기발행 합계를 뺀 잔액을 발급할 수 있게 둔다.
  // 발급된 건은 인쇄 버튼을 활성화한다 — 발급된 유형의 양식(세금계산서/현금영수증)으로 인쇄.
  function renderModeState() {
    if (!current) return;
    const warns = current.warns || [];
    $('taxWarn').innerHTML = warns.map(esc).join('<br>');
    $('taxWarn').classList.toggle('hidden', !warns.length);
    const printBtn = $('taxPrintBtn');
    printBtn.classList.toggle('hidden', !current.issued);
    if (current.issued) {
      // 푸터 폭 절약 — 어느 양식인지는 툴팁으로
      printBtn.textContent = '인쇄';
      printBtn.title = `${current.issuedType === 'cash' ? '현금영수증' : '세금계산서'} 인쇄`;
    }
    // 팩스는 발행된 세금계산서만 — 위 팩스번호 칸의 번호로 (재)전송한다
    $('taxFaxBtn').classList.toggle('hidden', !(current.issued && current.issuedType === 'tax'));
    $('taxMailBtn').classList.toggle('hidden', !(current.issued && current.issuedType === 'tax'));
    // 취소는 팝빌로 발행한 건만 — 홈택스 수기 발급분은 여기 안 잡힌다.
    // 현금영수증과 세금계산서 모두 취소 사유를 선택한다. 세금계산서는 수정사유별
    // 필수 날짜·증감액·환입액 입력을 별도 패널에 표시한다.
    const canCancel = !!(current.issued && current.issuedType);
    $('cashCancelBtn').classList.toggle('hidden', !canCancel);
    $('cashCancelType').classList.toggle('hidden', !(canCancel && current.issuedType === 'cash'));
    $('taxCancelTypeWrap').classList.toggle('hidden', !(canCancel && current.issuedType === 'tax'));
    syncTaxModifyFields();
    if (canCancel) $('cashCancelBtn').textContent = current.issuedType === 'cash' ? '현금영수증 취소' : '세금계산서 수정발급';
    // 전표 생성 — 발급 완료 후에만 (발급 → 전표 순서여야 승인번호·세무구분이
    // 전표에 자동 반영된다). 이미 전표가 있으면(재무팀 수기분 포함) '전표 생성됨'으로
    // 잠근다. 거래처 선택 다이얼로그는 호스트 화면이 제공한다(감정서 LIST의
    // A10_CREATE_VOUCHER) — 없는 화면에서는 생성할 수 없어 기생성 표시만 남긴다.
    const vBtn = $('taxVoucherBtn');
    const vKnown = current.voucherExists === true || current.voucherExists === false;
    const canCreate = typeof window.A10_CREATE_VOUCHER === 'function'
      || typeof window.A10_CREATE_VOUCHER_CASH === 'function';
    const issuedCombined = (current.combinedTotals && current.combinedTotals.total) || 0;
    // 증빙이 하나라도 발행돼 있으면 버튼을 보인다. 예전엔 '발행 합계 >= 청구액'일 때만
    // 보여서 부분 발행·실비 종결 건은 버튼 자체가 없었다 (2026-09-08 01-2608-3-2484).
    // 청구액보다 적은 건은 서버가 막고 화면이 "증빙 금액으로 만들까요?"를 묻는다.
    const evidenceComplete = !current.fullTotal || issuedCombined > 0;
    // 증빙을 취소하고 세금계산서를 다시 발행한 건 — 마이너스 전표 + 새 전표 (2026-09-02)
    const mixedComplete = current.issuedCash && current.issuedTax;
    const recreatable = current.voucherExists === true
      && (current.voucherRecreate === true || mixedComplete)
      && current.issuedType === 'tax' && canCreate;
    // 증빙 발행이 청구액 전액 완료되면 단일/혼합 여부와 무관하게 전표 버튼을 표시한다.
    // 자동 전표가 누락된 경우에도 수동 생성할 수 있어야 한다.
    vBtn.classList.toggle('hidden', !(current.issued && evidenceComplete && vKnown));
    vBtn.disabled = current.voucherExists === true && !recreatable;
    vBtn.textContent = recreatable ? '전표 재생성'
      : (current.voucherExists === true ? '전표 생성됨' : '전표 생성');
    vBtn.title = recreatable
      ? '취소된 증빙의 전표를 마이너스 전표로 상쇄하고, 새 세금계산서 기준 전표를 만듭니다' : '';
    const btn = $('taxIssueBtn');
    if (btn.dataset.loading) return;
    // 추가 발행(착수금 계산서 뒤 잔금 계산서)은 발행된 세금계산서 탭에서만,
    // 모드를 켜기 전까지 보인다 (2026-08-31 사용자 요청).
    $('taxMoreBtn').classList.toggle('hidden',
      !(mode === 'tax' && current.issued && current.issuedType === 'tax'
        && !current.additional && evidenceRemaining().total > 0));
    if (current.issued && !(mode === 'tax' && current.additional)) {
      btn.textContent = '발급 완료'; btn.disabled = true;
    } else {
      const base = current.additional ? '추가 발급' : '발급';
      btn.textContent = current.isTest ? `${base} (테스트)` : base;
      validate();
    }
  }

  function syncTaxModifyFields() {
    const isTax = !!(current && current.issued && current.issuedType === 'tax');
    const code = Number($('taxCancelType').value);
    $('taxModifySec').classList.toggle('hidden', !isTax);
    const needsDate = isTax && [2, 3, 4, 5].includes(code);
    const needsAmount = isTax && [2, 3].includes(code);
    $('taxCancelDateWrap').classList.toggle('hidden', !needsDate);
    $('taxAdjustSupplyWrap').classList.toggle('hidden', !needsAmount);
    $('taxAdjustVatWrap').classList.toggle('hidden', !needsAmount);
    if (needsDate && !$('taxCancelDate').value) $('taxCancelDate').value = localToday();
    const dateLabels = {2: '공급가액 변동일', 3: '환입일', 4: '계약 해제일', 5: '내국신용장 개설일'};
    $('taxCancelDateLabel').textContent = dateLabels[code] || '사유 발생일';
    $('taxAdjustSupplyLabel').textContent = code === 2 ? '공급가액 증감액 (+/-)' : '환입 공급가액';
    $('taxAdjustVatLabel').textContent = code === 2 ? '세액 증감액 (+/-)' : '환입 세액';
    const helps = {
      1: '위 거래처·작성일자·금액·품목을 올바른 내용으로 고치세요. 기존 음수 1장과 정정 양수 1장이 발행됩니다.',
      2: '최종 금액이 아니라 기존 금액에서 늘거나 줄어든 금액만 입력하세요. 감소는 음수(-)로 입력합니다.',
      3: '실제로 환입된 공급가액과 세액을 양수로 입력하세요. 발행 시 음수로 처리됩니다.',
      4: '계약 해제일을 작성일자로 하여 기존 금액 전체를 음수로 발행합니다.',
      5: '기존 과세분 음수 1장과 영세율 양수 1장이 발행됩니다.',
      6: '당초 작성일자로 기존 금액 전체를 음수로 발행합니다.',
    };
    $('taxModifyHelp').textContent = helps[code] || '';
  }

  // 발급 팝업을 닫고 호스트 화면의 거래처 선택 → 기본전표 생성 흐름으로 넘긴다.
  // 현금영수증은 거래처가 늘 '현금영수증(국세청)' 하나뿐이라 고르는 창을 건너뛴다
  // (2026-08-20 사용자 요청). 코드는 호스트 화면이 안다.
  function doVoucher() {
    // 재생성(취소 증빙 + 세금계산서 재발행 건)은 전표가 있어도 진행한다 (2026-09-02)
    const recreatable = !!(current && current.voucherExists === true
      && (current.voucherRecreate === true || (current.issuedCash && current.issuedTax))
      && current.issuedType === 'tax');
    if (!current || !current.issued || (current.voucherExists && !recreatable)) return;
    const docId = current.doc_id;
    const mixedEvidence = !!(current.issuedCash && current.issuedTax);
    const trCd = String((current.receiver && current.receiver.tr_cd) || '').trim();
    // 혼합 분할발행 전표는 세금계산서 거래처와 현금영수증 고정 거래처를 서비스가
    // 각각 나누므로, 현재 탭이 현금영수증이어도 세금계산서 거래처를 넘긴다.
    if (mixedEvidence && trCd && typeof window.A10_CREATE_VOUCHER_TAX === 'function') {
      $('taxIssueDialog').close();
      window.A10_CREATE_VOUCHER_TAX(docId,
        { code: trCd, name: $('taxRcvName').value.trim() },
        { evidence: true, recreate: recreatable });
      return;
    }
    if (mixedEvidence) {
      if (typeof window.A10_CREATE_VOUCHER === 'function') {
        $('taxIssueDialog').close();
        window.A10_CREATE_VOUCHER(docId);
      }
      return;
    }
    if (current.issuedType === 'cash'
        && typeof window.A10_CREATE_VOUCHER_CASH === 'function') {
      $('taxIssueDialog').close();
      window.A10_CREATE_VOUCHER_CASH(docId, { evidence: true });
      return;
    }
    // 세금계산서도 거래처를 고르는 창 없이 바로 아마란스로 — 계산서의 공급받는자
    // (아마란스 거래처코드)가 곧 전표 거래처다 (2026-08-27 재무팀 요청, 현금영수증과 같은 흐름).
    // 코드가 없는 수기 입력 거래처만 예전처럼 선택 창을 연다.
    if (current.issuedType === 'tax' && trCd
        && typeof window.A10_CREATE_VOUCHER_TAX === 'function') {
      $('taxIssueDialog').close();
      window.A10_CREATE_VOUCHER_TAX(docId, { code: trCd, name: $('taxRcvName').value.trim() },
        { evidence: true, recreate: recreatable });
      return;
    }
    if (current.issuedType === 'tax' && !trCd) {
      // 거래처코드가 없으면 조용히 선택 창으로 빠지지 말고 알린다 (2026-09-08 사용자 요청).
      const note = '아마란스 거래처가 없습니다. 위 거래처 칸에서 검색해 고르거나 "입력한 정보로 거래처 등록"을 누른 뒤 전표를 만드세요.';
      $('taxMsg').textContent = note; $('taxMsg').className = 'tax-msg err';
      if (window.A10_TOAST) window.A10_TOAST(note, true);
      return;
    }
    if (recreatable) return;   // 재생성은 거래처코드 있는 세금계산서 건만
    if (typeof window.A10_CREATE_VOUCHER !== 'function') return;
    $('taxIssueDialog').close();
    window.A10_CREATE_VOUCHER(docId);
  }

  // 기본전표 존재 여부 — 응답이 오기 전(null)에는 버튼을 숨겨 둔다.
  // 조회가 실패해도 발급 흐름은 막지 않는다(전표는 감정서 LIST 우클릭으로도 가능).
  async function loadVoucherStatus(docId) {
    try {
      const res = await fetch(
        `/api/appraisals/${encodeURIComponent(docId)}/vouchers/default/status`);
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      // 응답이 오는 사이 다른 감정서로 다시 열렸으면 버리기
      if (current && current.doc_id === docId) {
        current.voucherExists = !!(p.data && p.data.exists);
        current.voucherRecreate = !!(p.data && p.data.recreate);
        renderModeState();
      }
    } catch (e) {
      // 조회가 실패해도 버튼은 보인다 — 숨겨 두면 이유 없이 '전표 생성'이 사라져
      // 담당자가 손쓸 길이 없다 (2026-09-08). 이미 전표가 있으면 서버가
      // '이미 기본 매출전표가 생성된 감정서입니다'로 막는다.
      if (current && current.doc_id === docId && current.voucherExists === null) {
        current.voucherExists = false;
        current.voucherRecreate = false;
        renderModeState();
      }
    }
  }

  // 발행된 세금계산서를 위 팩스번호 칸의 번호로 전송 — 기발행 건 재전송용.
  async function doFax() {
    if (!current || !current.issued || current.issuedType !== 'tax') return;
    const fax = ($('taxFaxNo').value || '').replace(/[^0-9]/g, '');
    if (fax.length < 8) {
      $('taxMsg').textContent = '팩스번호를 입력하세요 (위 팩스 전송 칸).';
      $('taxMsg').className = 'tax-msg err'; $('taxFaxNo').focus(); return;
    }
    if (!confirm(`${fax} 번호로 세금계산서를 팩스 전송합니다 (포인트 과금). 진행할까요?`)) return;
    const btn = $('taxFaxBtn');
    btn.disabled = true; btn.textContent = '전송 중...';
    try {
      const res = await fetch('/api/taxinvoice/fax', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: current.doc_id, fax_no: fax }),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message || '팩스 전송에 실패했습니다.');
      $('taxMsg').textContent = `팩스 전송 접수 완료 (${fax})`;
      $('taxMsg').className = 'tax-msg ok';
      if (window.A10_TOAST) window.A10_TOAST('팩스 전송 접수');
    } catch (e) {
      $('taxMsg').textContent = `팩스 전송 실패: ${e.message}`;
      $('taxMsg').className = 'tax-msg err';
    } finally {
      btn.disabled = false; btn.textContent = '팩스 전송';
    }
  }

  // 발행된 세금계산서 안내메일을 위 이메일 칸의 주소로 재전송 — 담당자가 바뀌었거나
  // 다른 부서로 다시 보내 달라는 요청용 (2026-09-01). 팩스와 같은 UX: 칸에 주소를
  // 고쳐 넣고 누른다. 발급 당시 수신자와 달라도 된다.
  async function doMail() {
    if (!current || !current.issued || current.issuedType !== 'tax') return;
    const addr = ($('taxRcvEmail').value || '').trim();
    if (!addr || !addr.includes('@')) {
      $('taxMsg').textContent = '이메일 주소를 확인하세요 (위 이메일 칸).';
      $('taxMsg').className = 'tax-msg err'; $('taxRcvEmail').focus(); return;
    }
    if (!confirm(`${addr} 주소로 세금계산서 안내메일을 다시 보냅니다. 진행할까요?`)) return;
    const btn = $('taxMailBtn');
    btn.disabled = true; btn.textContent = '전송 중...';
    try {
      const res = await fetch('/api/taxinvoice/email', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ doc_id: current.doc_id, email: addr }),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message || '메일 재전송에 실패했습니다.');
      $('taxMsg').textContent = `메일 재전송 접수 완료 (${addr})`;
      $('taxMsg').className = 'tax-msg ok';
      if (window.A10_TOAST) window.A10_TOAST('메일 재전송 접수');
    } catch (e) {
      $('taxMsg').textContent = `메일 재전송 실패: ${e.message}`;
      $('taxMsg').className = 'tax-msg err';
    } finally {
      btn.disabled = false; btn.textContent = '메일 재전송';
    }
  }

  // 발급된 유형의 인쇄 팝업 — 팝빌 URL은 30초 내 접속해야 해서 창을 먼저 열고 URL을 넣는다
  // (fetch 후 window.open은 팝업 차단에 걸린다).
  // 데스크톱 앱(pywebview)은 window.open을 OS에 넘겨서 about:blank가
  // "열 수 있는 앱이 없습니다" 오류창이 되므로, 선오픈 없이 URL을 받아 바로 연다
  // (셸에서는 팝업 차단이 없고 기본 브라우저로 열린다).
  async function doPrint() {
    if (!current || !current.issued) return;
    const docType = current.issuedType === 'cash' ? '현금영수증' : '세금계산서';
    const win = window.pywebview ? null : window.open('about:blank', '_blank', 'width=900,height=800');
    try {
      const res = await fetch(`/api/taxinvoice/print-url?doc_id=${encodeURIComponent(current.doc_id)}&doc_type=${encodeURIComponent(docType)}`);
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      if (win) win.location = p.data.url; else window.open(p.data.url, '_blank');
    } catch (e) {
      if (win) win.close();
      $('taxMsg').textContent = `인쇄 팝업 실패: ${e.message}`;
      $('taxMsg').className = 'tax-msg err';
    }
  }

  // 발급 취소/수정 — 현금영수증은 취소분, 세금계산서는 국세청 수정사유 1~6의
  // 규칙에 따라 음수·양수 수정세금계산서를 발행한다.
  async function doCancelCash() {
    if (!current || !current.issued || !current.issuedType) return;
    const isCash = current.issuedType === 'cash';
    const label = isCash ? '현금영수증' : '세금계산서';
    let url, body, question;
    if (isCash) {
      const typeSel = $('cashCancelType');
      const reason = typeSel.options[typeSel.selectedIndex].text;
      url = '/api/taxinvoice/cashbill/cancel';
      body = { doc_id: current.doc_id, cancel_type: Number(typeSel.value) };
      question = `현금영수증을 취소합니다 (사유: ${reason}).\n국세청에 취소분이 전송되며 되돌리기 어렵습니다. 진행할까요?`;
    } else {
      const typeSel = $('taxCancelType');
      const reasonCode = Number(typeSel.value);
      const reason = typeSel.options[typeSel.selectedIndex].text;
      const needsDate = [2, 3, 4, 5].includes(reasonCode);
      const reasonDate = needsDate ? $('taxCancelDate').value : null;
      if (needsDate && !reasonDate) {
        $('taxMsg').textContent = '수정사유 발생일을 입력하세요.';
        $('taxMsg').className = 'tax-msg err';
        $('taxCancelDate').focus();
        return;
      }
      const amount = id => Number(digits($(id).value) || 0);
      const adjustSupply = [2, 3].includes(reasonCode) ? amount('taxAdjustSupply') : null;
      const adjustTax = [2, 3].includes(reasonCode) ? amount('taxAdjustVat') : null;
      if ((reasonCode === 2 && adjustSupply === 0)
          || (reasonCode === 3 && adjustSupply === 0 && adjustTax === 0)) {
        $('taxMsg').textContent = reasonCode === 2 ? '증감액을 입력하세요.' : '환입 금액을 입력하세요.';
        $('taxMsg').className = 'tax-msg err';
        $('taxAdjustSupply').focus();
        return;
      }
      if (reasonCode === 3 && (adjustSupply < 0 || adjustTax < 0)) {
        $('taxMsg').textContent = '환입 금액은 양수로 입력하세요.';
        $('taxMsg').className = 'tax-msg err';
        return;
      }
      if (reasonCode === 2
          && ((adjustSupply > 0 && adjustTax < 0) || (adjustSupply < 0 && adjustTax > 0))) {
        $('taxMsg').textContent = '공급가액과 세액의 증감 방향을 맞춰 주세요.';
        $('taxMsg').className = 'tax-msg err';
        return;
      }
      let replacement = null;
      if (reasonCode === 1) {
        const corpNum = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
        const writeDate = ($('taxWriteDate').value || '').replace(/-/g, '');
        if (corpNum.length !== 10 || writeDate.length !== 8 || !$('taxRcvName').value.trim()) {
          $('taxMsg').textContent = '정정할 거래처 사업자번호·상호·작성일자를 확인하세요.';
          $('taxMsg').className = 'tax-msg err';
          return;
        }
        replacement = {
          write_date: writeDate, supply_cost: amount('taxSupply'), tax: amount('taxVat'),
          purpose: $('taxPurpose').value, item_name: $('taxItemName').value.trim() || null,
          item_remark: $('taxItemRemark').value.trim(), remark1: $('taxRemark1').value.trim(),
          receiver: {
            ...current.receiver, corp_num: corpNum, corp_name: $('taxRcvName').value.trim(),
            ceo_name: $('taxRcvCeo').value.trim(), biz_type: $('taxRcvBizType').value.trim(),
            biz_class: $('taxRcvBizClass').value.trim(), addr: $('taxRcvAddr').value.trim(),
            email: $('taxRcvEmail').value.trim(),
          },
        };
      }
      url = '/api/taxinvoice/cancel';
      body = {
        doc_id: current.doc_id, reason_code: reasonCode, reason_date: reasonDate,
        adjust_supply: adjustSupply, adjust_tax: adjustTax, replacement,
        memo: $('taxCancelMemo').value.trim(),
      };
      const dateNote = reasonDate ? ` · 사유일: ${reasonDate}` : '';
      const issueNotes = {
        1: '음수 취소분과 정정 양수분 2장', 2: '입력한 증감액 1장',
        3: '입력한 환입액의 음수 1장', 4: '전액 음수 1장',
        5: '과세 음수분과 영세율 양수분 2장', 6: '전액 음수 1장',
      };
      question = `세금계산서를 수정발급합니다 (사유: ${reason}${dateNote}).\n국세청에 ${issueNotes[reasonCode]}이 발행되며 되돌리기 어렵습니다. 진행할까요?`;
    }
    if (!confirm(question)) return;
    const btn = $('cashCancelBtn');
    btn.disabled = true; btn.textContent = isCash ? '취소 중...' : '수정발급 중...';
    try {
      const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message || '취소에 실패했습니다.');
      const data = p.data || {};
      const confirmNum = data.confirm_num;
      const remainsIssued = isCash ? false : data.cancelled === false;
      if (!remainsIssued) {
        if (isCash) {
          current.issuedCash = false;
          current.cashIssuedTotals = { supply: 0, tax: 0, total: 0 };
        } else {
          current.issuedTax = false;
          current.issuedTotals = { supply: 0, tax: 0, total: 0 };
        }
        const cash = current.cashIssuedTotals || { supply: 0, tax: 0, total: 0 };
        const tax = current.issuedTotals || { supply: 0, tax: 0, total: 0 };
        current.combinedTotals = { supply: cash.supply + tax.supply,
          tax: cash.tax + tax.tax, total: cash.total + (tax.total || tax.supply + tax.tax) };
        current.issued = false; current.issuedType = null;
        current.warns = (current.warns || []).filter(w => !w.startsWith('이미 현금영수증') && !w.startsWith('이미 세금계산서'));
        current.warns.push(`${label}이(가) 취소되었습니다${confirmNum ? ` (취소분 승인번호 ${confirmNum})` : ''}. 재발급이 가능합니다.`);
      } else {
        current.warns.push(`${data.reason || '세금계산서'} 수정발급 완료${confirmNum ? ` (승인번호 ${confirmNum})` : ''}.`);
      }
      // 수정발급 성공 시 서버가 전표를 자동 재생성한다 — 결과를 안내에 붙인다
      // (2026-09-04). 실패(대상 아님 포함)면 '전표 재생성' 버튼으로 직접 만들 수 있다.
      let voucherNote = '';
      if (isCash && data.cancel_voucher_created) {
        const vr = data.cancel_voucher_created;
        voucherNote = vr.done
          ? ` · 취소 전표 자동 생성 완료${vr.voucher_no ? ` (${vr.voucher_no})` : ''}`
          : ` · 현금영수증은 취소됐지만 취소 전표 생성 실패 (${vr.reason || '원인 미상'})`;
      } else if (remainsIssued && data.voucher_recreated) {
        const vr = data.voucher_recreated;
        voucherNote = vr.done
          ? ' · 전표 자동 재생성 완료'
          : ` · 전표 자동 재생성 안 됨(${vr.reason || ''}) — 필요하면 '전표 재생성'을 누르세요`;
      }
      const okMsg = (remainsIssued ? '세금계산서 수정발급 완료' : `${label} 취소 완료`) + voucherNote;
      $('taxMsg').textContent = okMsg;
      $('taxMsg').className = 'tax-msg ok';
      renderModeState();
      // 자동 재생성으로 전표 상태가 바뀌었으니 버튼 표시도 새로고침한다.
      if (current && current.doc_id) loadVoucherStatus(current.doc_id);
      if (window.A10_TOAST) window.A10_TOAST(okMsg);
    } catch (e) {
      $('taxMsg').textContent = `${label} ${isCash ? '취소' : '수정발급'} 실패: ${e.message}`; $('taxMsg').className = 'tax-msg err';
    } finally {
      btn.disabled = false;
      if (current && current.issued) btn.textContent = isCash ? '현금영수증 취소' : '세금계산서 수정발급';
    }
  }

  // 현금영수증 탭 자동 채움: 지출증빙용=거래처 사업자번호, 소득공제용=거래처 담당자 휴대폰(있을 때만).
  // 수기 입력값은 덮지 않고, 자동으로 넣은 값은 거래구분 전환 시 그 구분의 후보로 갈아끼운다.
  function fillCashFromTax() {
    const identity = $('cashIdentity');
    const deduction = $('cashUsage').value !== '지출증빙용';
    let candidate = '';
    if (deduction) {
      candidate = String((current && current.receiver && current.receiver.hp) || '').trim();
    } else {
      const corp = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
      if (corp.length === 10) candidate = fmtBiz(corp);
    }
    if (!identity.value.trim() || identity.dataset.auto === '1') {
      identity.value = candidate; identity.dataset.auto = candidate ? '1' : '';
      if (deduction && candidate) {
        $('taxMsg').textContent = '거래처 담당자 휴대폰을 참고로 채웠습니다. 입금자 본인 번호인지 확인하세요.';
        $('taxMsg').className = 'tax-msg';
      }
    }
    if (!$('cashCustomer').value.trim()) $('cashCustomer').value = $('taxRcvName').value.trim();
    if (!$('cashEmail').value.trim()) $('cashEmail').value = $('taxRcvEmail').value.trim();
    validate();
  }

  const digits = s => String(s || '').replace(/[^0-9-]/g, '');
  function fmtMoney(v) { const n = digits(v); return n === '' || n === '-' ? n : money.format(Number(n)); }
  function fmtBiz(v) {   // 2148746436 -> 214-87-46436 (3-2-5)
    const d = String(v || '').replace(/[^0-9]/g, '').slice(0, 10);
    if (d.length <= 3) return d;
    if (d.length <= 5) return d.slice(0, 3) + '-' + d.slice(3);
    return d.slice(0, 3) + '-' + d.slice(3, 5) + '-' + d.slice(5);
  }
  // 입력 중 커서 뒤 자릿수를 유지하며 재포맷
  function reformat(el, fn) {
    const before = el.value, digitsAfterCaret = digits(before.slice(el.selectionStart)).length;
    el.value = fn(before);
    let pos = el.value.length, seen = 0;
    for (let i = el.value.length; i >= 0; i--) { if (/[0-9]/.test(el.value[i - 1] || '')) { if (seen === digitsAfterCaret) { pos = i; break; } seen++; } pos = i; }
    try { el.setSelectionRange(pos, pos); } catch (e) {}
  }

  function recalc() {
    const s = Number(digits($('taxSupply').value)), v = Number(digits($('taxVat').value));
    $('taxTotal').textContent = money.format((s || 0) + (v || 0));
    validate();
  }

  // 필수: 세금계산서=사업자번호(10)·상호·대표자·이메일·공급가·작성일 / 현금영수증=식별번호·공급가
  function validate() {
    const supplyOk = Number(digits($('taxSupply').value)) > 0;
    let checks;
    if (mode === 'cash') {
      checks = [
        [$('cashIdentity'), $('cashIdentity').value.replace(/[^0-9]/g, '').length >= 8],
        [$('taxSupply'), supplyOk],
      ];
    } else {
      checks = [
        [$('taxRcvCorpNum'), $('taxRcvCorpNum').value.replace(/[^0-9]/g, '').length === 10],
        [$('taxRcvName'), !!$('taxRcvName').value.trim()],
        [$('taxRcvCeo'), !!$('taxRcvCeo').value.trim()],
        [$('taxRcvEmail'), /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test($('taxRcvEmail').value.trim())],
        [$('taxSupply'), supplyOk],
        [$('taxWriteDate'), !!$('taxWriteDate').value],
      ];
    }
    let allOk = true;
    checks.forEach(([el, ok]) => { el.classList.toggle('invalid', !ok); if (!ok) allOk = false; });
    const btn = $('taxIssueBtn');
    const issued = !!(current && current.issued);
    if (!btn.dataset.loading) btn.disabled = !allOk || (issued && !(mode === 'tax' && current.additional));
    return allOk;
  }

  function localToday() {
    const d = new Date(); const o = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - o).toISOString().slice(0, 10);
  }

  async function open(docId) {
    inject();
    current = { doc_id: docId, receiver: {}, warns: [], issued: false, voucherExists: null, additional: false };
    setMode('tax');
    const dlg = $('taxIssueDialog');
    $('taxDocId').textContent = docId;
    $('cashIdentity').value = ''; $('cashIdentity').dataset.auto = '';
    $('cashCustomer').value = ''; $('cashEmail').value = '';
    $('taxCustSearch').value = ''; $('taxCustResults').classList.add('hidden'); $('taxCustResults').innerHTML = '';
    $('taxMsg').textContent = ''; $('taxMsg').className = 'tax-msg';
    $('taxWarn').classList.add('hidden');
    $('taxIssueBtn').disabled = true; $('taxIssueBtn').textContent = '불러오는 중...';
    $('taxWriteDate').value = localToday();
    $('taxCancelType').value = '6';
    $('taxCancelDate').value = localToday();
    $('taxAdjustSupply').value = ''; $('taxAdjustVat').value = ''; $('taxCancelMemo').value = '';
    $('taxPurpose').value = '청구';
    // 품목은 기본 문구(수정 가능), 비고1·비고는 기본 빈칸 (2026-08-03 사용자 확정)
    $('taxItemName').value = `감정평가수수료 ${docId}`;
    $('taxRemark1').value = ''; $('taxItemRemark').value = '';
    $('taxFaxNo').value = ''; $('taxAccountCode').value = '4010001';
    $('taxCombineDocs').value = ''; $('taxCombineInfo').textContent = ''; current.combine = null;
    $('taxPoolMode').checked = false; $('taxPoolInfo').textContent = ''; current.pool = null;
    dlg.showModal();
    loadVoucherStatus(docId);
    try {
      const res = await fetch(`/api/taxinvoice/draft?doc_id=${encodeURIComponent(docId)}`);
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      const d = p.data, r = d.receiver || {};
      current.receiver = r;
      current.isTest = !!d.is_test;
      // 증빙별·전체 기발행 합계. 현금영수증 50% + 세금계산서 50% 같은 분할발행에 쓴다.
      current.issuedTotals = d.issued_totals || { supply: 0, tax: 0 };
      current.cashIssuedTotals = d.cash_issued_totals || { supply: 0, tax: 0, total: 0 };
      current.combinedTotals = d.combined_issued_totals || {
        supply: current.issuedTotals.supply || 0, tax: current.issuedTotals.tax || 0,
        total: (current.issuedTotals.supply || 0) + (current.issuedTotals.tax || 0),
      };
      current.fullSupply = d.supply_cost || 0;
      current.fullTax = d.tax || 0;
      current.fullTotal = d.total || current.fullSupply + current.fullTax;
      $('taxRcvCorpNum').value = fmtBiz(r.corp_num || '');
      $('taxRcvName').value = r.corp_name || '';
      $('taxRcvCeo').value = r.ceo_name || '';
      $('taxRcvBizType').value = r.biz_type || '';
      $('taxRcvBizClass').value = r.biz_class || '';
      $('taxRcvEmail').value = r.email || '';
      $('taxRcvAddr').value = r.addr || '';
      $('taxSupply').value = fmtMoney(d.supply_cost || 0);
      $('taxVat').value = fmtMoney(d.tax || 0);
      // 계정과목 기본값은 서버의 전표 규칙(약식 -6- 은 기타수수료)과 같게 — 여기서 고른 값이 전표 매출 줄에 간다
      $('taxAccountCode').value = d.account_code || '4010001';
      // 작성일자 기본값 = 최종 입금일 (수정 가능, 입금 전이면 오늘 유지)
      if (d.paid_date) $('taxWriteDate').value = d.paid_date;
      recalc();
      const issuedTax = !!(d.already && !d.already.error);
      const issuedCash = !!(d.already_cash && !d.already_cash.error);
      current.issuedTax = issuedTax;
      current.issuedCash = issuedCash;
      current.loaded = true;
      if (issuedTax) {
        // 작성일자 칸은 열릴 때 오늘로 초기화된다 — 발행된 건은 팝빌의 실제 작성일자로
        // 바꿔 보여준다 (2026-09-08: 9/7 작성분이 9/8 로 보여 "잘못 발행됐다"는 오해).
        if (d.already.write_date) $('taxWriteDate').value = d.already.write_date;
        current.warns.push(`세금계산서 기발행: 작성일자 ${d.already.write_date || '-'} · 공급가 ${fmtMoney(current.issuedTotals.supply)}원 · 세액 ${fmtMoney(current.issuedTotals.tax)}원 (승인번호 ${d.already.nts_confirm || '-'}).`);
      }
      if (issuedCash) current.warns.push(`현금영수증 기발행: 공급가 ${fmtMoney(current.cashIssuedTotals.supply)}원 · 세액 ${fmtMoney(current.cashIssuedTotals.tax)}원 (승인번호 ${d.already_cash.confirm_num || '-'}).`);
      if (!issuedTax && !issuedCash && !r.corp_num) current.warns.push('거래처 사업자번호가 없습니다. 약식/현금영수증 건이거나 거래처 미등록일 수 있어요. 확인 후 입력하세요.');
      // 발행된 유형의 탭으로 연다 — 현금영수증 건인데 세금계산서 탭이 뜨면 헷갈린다
      if (issuedCash) setMode('cash');
      else setMode('tax');
    } catch (e) {
      $('taxMsg').textContent = e.message; $('taxMsg').className = 'tax-msg err';
      $('taxIssueBtn').textContent = '발급';
    }
  }

  // 추가 발행: 착수금 계산서를 끊고 잔금 계산서를 또 끊는 경우 (2026-08-31 사용자
  // 요청). 문서번호는 서버가 -R{차수}로 새로 따므로 발급 경로는 그대로다.
  // 남은 공급가(전체 청구 − 기발행)를 미리 채우되 금액은 수정할 수 있다.
  function startAdditional() {
    if (!current || !current.issued || current.issuedType !== 'tax') return;
    const t = current.issuedTotals || { supply: 0, tax: 0 };
    if (!confirm(`이미 세금계산서가 발행된 감정서입니다 (기발행 공급가 ${fmtMoney(t.supply)}원 · 세액 ${fmtMoney(t.tax)}원).\n추가 발행 모드를 켭니다 — 금액을 확인·수정한 뒤 발급하세요.`)) return;
    current.additional = true;
    const remain = evidenceRemaining();
    $('taxSupply').value = fmtMoney(remain.supply);
    $('taxVat').value = fmtMoney(remain.tax);
    recalc();
    renderModeState();
    $('taxMsg').textContent = remain.total > 0
      ? '추가 발행 모드 — 남은 공급가를 미리 채웠습니다. 금액을 확인하세요.'
      : '추가 발행 모드 — 발행할 공급가액을 입력하세요.';
    $('taxMsg').className = 'tax-msg';
  }

  // 합산 발행 (2026-09-10): 같은 거래처의 다른 감정서를 적고 '확인'을 누르면 서버가 건별 남은
  // 청구액·거래처 일치를 보고, 통과하면 그 합을 금액 칸에 채운다(수정 가능).
  async function checkCombine() {
    const raw = $('taxCombineDocs').value.replace(/\n/g, ',');
    const extras = raw.split(',').map(s => s.trim()).filter(Boolean).filter((v, i, a) => a.indexOf(v) === i && v !== current.doc_id);
    const info = $('taxCombineInfo');
    current.combine = null;
    if (!extras.length) { info.textContent = ''; prefillEvidenceRemaining(); return; }
    const corpNum = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
    if (corpNum.length !== 10) { info.innerHTML = '<span class="bad">공급받는자 사업자번호를 먼저 채우세요.</span>'; return; }
    info.textContent = '확인 중...';
    try {
      const q = new URLSearchParams({ doc_id: current.doc_id, extra: extras.join(','), corp_num: corpNum });
      const p = await (await fetch(`/api/taxinvoice/combined-preview?${q}`)).json();
      if (!p.success) throw new Error(p.message);
      const d = p.data;
      info.innerHTML = d.docs.map(x => `${esc(x.doc_id)} 남은 청구액 ${fmtMoney(x.remaining_total)}원${x.problems.length ? ` <span class="bad">${esc(x.problems.join(', '))}</span>` : ''}`).join('<br>')
        + (d.ok ? `<br><span class="ok">${d.docs.length}건 합산 상한 ${fmtMoney(d.cap_total)}원</span>` : '<br><span class="bad">위 문제를 해결해야 합산할 수 있습니다.</span>');
      if (!d.ok) return;
      current.combine = { docs: d.docs.map(x => x.doc_id), extras, cap: d.cap_total };
      const supply = Math.round(d.cap_total / 1.1);
      $('taxSupply').value = fmtMoney(supply); $('taxVat').value = fmtMoney(d.cap_total - supply);
      $('taxItemName').value = `감정평가수수료 ${current.doc_id} 외 ${extras.length}건`;
      recalc();
    } catch (e) { info.innerHTML = `<span class="bad">${esc(e.message)}</span>`; }
  }

  // 입금 적용용 (2026-09-10): 켜면 서버가 그 거래처 감정서들의 미발행 청구액 합(상한)을 내려주고
  // 금액 칸에 채운다(줄여도 된다). 합산 발행과 같이 켤 수 없다.
  async function togglePoolMode() {
    const info = $('taxPoolInfo');
    current.pool = null;
    if (!$('taxPoolMode').checked) { info.textContent = ''; prefillEvidenceRemaining(); $('taxItemName').value = `감정평가수수료 ${current.doc_id}`; return; }
    const corpNum = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
    if (corpNum.length !== 10) { info.innerHTML = '<span class="bad">공급받는자 사업자번호를 먼저 채우세요.</span>'; $('taxPoolMode').checked = false; return; }
    $('taxCombineDocs').value = ''; $('taxCombineInfo').textContent = ''; current.combine = null;
    info.textContent = '거래처 감정서 확인 중...';
    try {
      const q = new URLSearchParams({ doc_id: current.doc_id, corp_num: corpNum });
      const p = await (await fetch(`/api/taxinvoice/pool-cap?${q}`)).json();
      if (!p.success) throw new Error(p.message);
      const d = p.data;
      if (!d.cap_total) { info.innerHTML = '<span class="bad">이 거래처에 미발행 청구액이 없습니다.</span>'; $('taxPoolMode').checked = false; return; }
      const paid = d.docs.filter(x => x.received > 0).length;
      info.innerHTML = `<span class="ok">상한 ${fmtMoney(d.cap_total)}원</span> — 미발행 감정서 ${d.doc_count}건 (입금 있는 건 ${paid}건은 발행 즉시 적용)<br>`
        + d.docs.slice(0, 8).map(x => `${esc(x.doc_id)} ${fmtMoney(x.remaining_total)}원${x.received > 0 ? ' · 입금' : ''}`).join(' / ') + (d.docs.length > 8 ? ` / 외 ${d.docs.length - 8}건` : '');
      current.pool = { cap: d.cap_total, docCount: d.doc_count };
      const supply = Math.round(d.cap_total / 1.1);
      $('taxSupply').value = fmtMoney(supply); $('taxVat').value = fmtMoney(d.cap_total - supply);
      $('taxItemName').value = `감정평가수수료 ${current.doc_id} 외`;
      recalc();
    } catch (e) { info.innerHTML = `<span class="bad">${esc(e.message)}</span>`; $('taxPoolMode').checked = false; }
  }

  async function doIssue() {
    if (!validate()) { $('taxMsg').textContent = '빨간 테두리 항목(필수)을 입력하세요.'; $('taxMsg').className = 'tax-msg err'; return; }
    const num = id => Number(($(id).value || '0').replace(/[^0-9-]/g, ''));
    // 청구액보다 적게 발행하려 하면 한 번 묻는다 — 자릿수 실수를 잡기 위해
    // (2026-09-07 01-2609-6-0487: 55,000 청구건에 5,500 발행 → 전표 생성이 막혔다).
    // 착수금·잔금 분할이나 추가 발행은 정상이므로 막지 않고 확인만 받는다.
    const willIssue = num('taxSupply') + num('taxVat');
    // 합산 발행이면 상한·기발행은 묶은 감정서 기준 (남은 청구액 합, 기발행은 이미 뺀 값)
    const combine = mode === 'tax' ? current.combine : null;
    const pool = mode === 'tax' ? current.pool : null;
    const already = (combine || pool) ? 0 : ((current.combinedTotals || {}).total || 0);
    const billed = pool ? pool.cap : combine ? combine.cap : (current.fullTotal || 0);
    if (billed > 0 && willIssue > 0 && willIssue + already < billed
        && !confirm(`청구액은 ${fmtMoney(billed)}원인데 `
          + `${fmtMoney(willIssue)}원만 발행합니다`
          + `${already ? ` (기발행 ${fmtMoney(already)}원 포함해도 ${fmtMoney(willIssue + already)}원)` : ''}.
`
          + `자릿수를 확인하세요. 이대로 발행할까요?`)) {
      $('taxMsg').textContent = '발행을 취소했습니다. 금액을 확인하세요.';
      $('taxMsg').className = 'tax-msg err';
      return;
    }
    const isLive = !(current && current.isTest);
    let url, body, label;
    if (mode === 'cash') {
      const identity = $('cashIdentity').value.replace(/[^0-9]/g, '');
      if (!identity) { $('taxMsg').textContent = '식별번호(휴대폰번호 또는 사업자번호)를 입력하세요.'; $('taxMsg').className = 'tax-msg err'; return; }
      url = '/api/taxinvoice/cashbill/issue'; label = '현금영수증';
      body = {
        doc_id: current.doc_id, trade_usage: $('cashUsage').value,
        identity_num: identity, supply_cost: num('taxSupply'), tax: num('taxVat'),
        customer_name: $('cashCustomer').value.trim(), email: $('cashEmail').value.trim(),
        hp: $('cashUsage').value === '소득공제용' ? identity : '',
      };
    } else {
      const corpNum = $('taxRcvCorpNum').value.replace(/[^0-9]/g, '');
      if (corpNum.length !== 10) { $('taxMsg').textContent = '공급받는자 사업자번호 10자리를 확인하세요.'; $('taxMsg').className = 'tax-msg err'; return; }
      const writeDate = ($('taxWriteDate').value || '').replace(/-/g, '');
      if (writeDate.length !== 8) { $('taxMsg').textContent = '작성일자를 확인하세요.'; $('taxMsg').className = 'tax-msg err'; return; }
      url = '/api/taxinvoice/issue'; label = '세금계산서';
      body = {
        doc_id: current.doc_id, write_date: writeDate,
        supply_cost: num('taxSupply'), tax: num('taxVat'),
        email: $('taxRcvEmail').value.trim(), purpose: $('taxPurpose').value,
        item_name: $('taxItemName').value.trim() || null,
        item_remark: $('taxItemRemark').value.trim(),
        remark1: $('taxRemark1').value.trim(),
        fax_no: $('taxFaxNo').value.trim(),
        account_code: $('taxAccountCode').value,
        receiver: {
          ...current.receiver,
          corp_num: corpNum, corp_name: $('taxRcvName').value.trim(),
          ceo_name: $('taxRcvCeo').value.trim(), biz_type: $('taxRcvBizType').value.trim(),
          biz_class: $('taxRcvBizClass').value.trim(), addr: $('taxRcvAddr').value.trim(),
          email: $('taxRcvEmail').value.trim(),
        },
      };
    }
    // 현금영수증+세금계산서 전체 발행합계가 청구액을 넘지 않게 화면에서도 막는다.
    const prior = (combine || pool) ? { supply: 0, tax: 0, total: 0 } : (current.combinedTotals || { supply: 0, tax: 0, total: 0 });
    const requestTotal = num('taxSupply') + num('taxVat');
    const afterTotal = (prior.total || 0) + requestTotal;
    if (pool) {
      if (requestTotal > pool.cap) {
        $('taxMsg').textContent = `발행 합계 ${fmtMoney(requestTotal)}원이 이 거래처 감정서 ${pool.docCount}건의 미발행 청구액 합 ${fmtMoney(pool.cap)}원을 초과합니다.`;
        $('taxMsg').className = 'tax-msg err';
        return;
      }
      body.pool = true;
    } else if (combine) {
      if (requestTotal > combine.cap) {
        $('taxMsg').textContent = `발행 합계 ${fmtMoney(requestTotal)}원이 묶은 감정서 ${combine.docs.length}건의 남은 청구액 합 ${fmtMoney(combine.cap)}원을 초과합니다.`;
        $('taxMsg').className = 'tax-msg err';
        return;
      }
      body.extra_doc_ids = combine.extras;
    } else if (current.fullTotal > 0 && afterTotal > current.fullTotal) {
      $('taxMsg').textContent = `발행 후 증빙 합계 ${fmtMoney(afterTotal)}원이 청구액 ${fmtMoney(current.fullTotal)}원을 초과합니다.`;
      $('taxMsg').className = 'tax-msg err';
      return;
    }
    if (mode === 'tax' && current.additional) {
      const t = current.issuedTotals || { supply: 0, tax: 0 };
      const sum = (t.supply || 0) + num('taxSupply');
      if (!confirm(`추가 발행입니다. 기발행 세금계산서 공급가 ${fmtMoney(t.supply)}원 + 이번 ${fmtMoney(num('taxSupply'))}원 = ${fmtMoney(sum)}원\n진행할까요?`)) return;
    }
    if (pool && !confirm(`입금 적용용 계산서 ${fmtMoney(requestTotal)}원을 ${current.doc_id} 번호로 한 장 발행합니다.\n같은 거래처 감정서 ${pool.docCount}건에 입금이 잡힐 때마다 자동으로 나눠 붙습니다.\n진행할까요?`)) return;
    if (combine && !confirm(`감정서 ${combine.docs.length}건을 세금계산서 한 장으로 합산 발행합니다.\n${combine.docs.join(', ')}\n진행할까요?`)) return;
    if (isLive && !confirm(
      `실제로 국세청에 ${label}을(를) 발급합니다.\n\n`+
      `공급가액 ${fmtMoney(body.supply_cost)}원 + 세액 ${fmtMoney(body.tax)}원 = 총 ${fmtMoney(body.supply_cost + body.tax)}원\n\n`+
      `되돌리기 어렵습니다. 진행할까요?`
    )) return;
    const btn = $('taxIssueBtn');
    btn.dataset.loading = '1'; btn.disabled = true; btn.textContent = '발급 중...';
    $('taxMsg').textContent = ''; $('taxMsg').className = 'tax-msg';
    try {
      const res = await fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      const info = (p.data && p.data.info) || {};
      const confirmNum = info.nts_confirm || info.confirm_num;
      // 발급과 함께 팩스를 요청했으면 그 결과도 같은 줄에 알린다 — 팩스 실패는
      // 발급 성공을 뒤집지 않으며, 푸터의 '팩스 전송' 버튼으로 재시도할 수 있다.
      const fax = p.data && p.data.fax;
      const faxNote = !fax ? ''
        : fax.success ? ` · 팩스 전송 접수(${fax.receive_num})`
        : ` · 팩스 실패: ${fax.message || '전송 오류'}`;
      $('taxMsg').className = 'tax-msg ok';
      const poolRes = p.data && p.data.pool;
      const poolNote = poolRes ? ` · 입금 적용용 (즉시 적용 ${(poolRes.applied || []).length}건 · 잔액 ${fmtMoney(poolRes.balance)}원)` : '';
      const combinedNote = poolNote || ((p.data && p.data.combined && p.data.combined.length > 1) ? ` · ${p.data.combined.length}건 합산` : '');
      $('taxMsg').textContent = `${label} 발급 완료${combinedNote}${confirmNum ? ' · 국세청승인번호 ' + confirmNum : ''}${faxNote}`;
      if (combine) { current.combine = null; $('taxCombineDocs').value = ''; $('taxCombineInfo').textContent = ''; }
      if (pool) { current.pool = null; $('taxPoolMode').checked = false; }
      delete btn.dataset.loading;
      const issuedAmount = { supply: body.supply_cost, tax: body.tax,
        total: body.supply_cost + body.tax };
      if (mode === 'cash') {
        const t = current.cashIssuedTotals || { supply: 0, tax: 0, total: 0 };
        current.cashIssuedTotals = { supply: t.supply + issuedAmount.supply,
          tax: t.tax + issuedAmount.tax, total: t.total + issuedAmount.total };
        current.issuedCash = true;
      } else {
        const t = current.issuedTotals || { supply: 0, tax: 0, total: 0 };
        current.issuedTotals = { supply: t.supply + issuedAmount.supply,
          tax: t.tax + issuedAmount.tax, total: (t.total || 0) + issuedAmount.total };
        current.issuedTax = true;
        current.additional = false;
      }
      current.combinedTotals = { supply: prior.supply + issuedAmount.supply,
        tax: prior.tax + issuedAmount.tax, total: prior.total + issuedAmount.total };
      syncModeEvidence();
      // Refresh recreate state after issuance; an existing voucher may become recreatable now.
      loadVoucherStatus(current.doc_id);
      current.warns.push(mode === 'tax'
        ? `세금계산서 발행 완료: 공급가 ${fmtMoney(body.supply_cost)}원 · 세액 ${fmtMoney(body.tax)}원 (승인번호 ${confirmNum || '-'}).`
        : `현금영수증 발행 완료: 공급가 ${fmtMoney(body.supply_cost)}원 · 세액 ${fmtMoney(body.tax)}원 (승인번호 ${confirmNum || '-'}).`);
      renderModeState();
      if (window.A10_TOAST) window.A10_TOAST(`${label} 발급 완료`);
      if (mode === 'tax' && current.receiver && current.receiver.tr_cd) maybeUpdateCustomer();
    } catch (e) {
      $('taxMsg').textContent = e.message; $('taxMsg').className = 'tax-msg err';
      delete btn.dataset.loading; btn.textContent = '발급'; validate();
    }
  }

  // 발급 후: 거래처 마스터의 빈 항목을 지금 입력한 값으로 조용히 채운다.
  // 확인창 없음(2026-08-14 사용자 지시) — 빈 칸만 채우고 기존 값은 안 덮는다.
  async function maybeUpdateCustomer() {
    const values = {
      corp_num: $('taxRcvCorpNum').value.replace(/[^0-9]/g, ''),
      ceo_name: $('taxRcvCeo').value.trim(), biz_type: $('taxRcvBizType').value.trim(),
      biz_class: $('taxRcvBizClass').value.trim(), addr: $('taxRcvAddr').value.trim(),
      email: $('taxRcvEmail').value.trim(),
    };
    const body = { tr_cd: current.receiver.tr_cd, values };
    try {
      const res = await fetch('/api/taxinvoice/update-customer', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, apply: true }),
      });
      const p = await res.json();
      const d = p.data || {};
      const filled = d.applied && (Object.keys(d.fillable || {}).length || d.contact_email);
      if (p.success && filled && window.A10_TOAST) window.A10_TOAST('거래처 빈 항목을 채웠습니다.');
    } catch (e) { /* 발급은 이미 끝났으니 조용히 넘어간다 */ }
  }

  window.A10_TAX_ISSUE = open;
})();
