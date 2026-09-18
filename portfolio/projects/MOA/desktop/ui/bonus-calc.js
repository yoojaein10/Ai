// 상여 지급액 미리보기 (2026-08-27) — 공제 다이얼로그에서 체크를 바꿀 때마다 그 사람의 지급액을 다시 계산한다.
// app/services/bonus/engine.py 의 사람 합계 수식을 그대로 옮긴 것. 저장하면 서버가 다시 계산하므로 여기는 미리보기다.
// 주주: 블록별 Q = q_pre − (가변비+미납비이월+감정서경비+기타, 주 블록만) → 상여 = Q<0?0:Q×요율
//       Y = ROUNDDOWN(상여+처리비−화환+물건조사비, −3) − 선지급, 소득세 = ROUNDDOWN(Y×30%, −3), 주민세 = ROUNDDOWN(소득세×10%, −1)
// 평·동: AD = ROUNDDOWN(상여+처리수당−화환, −3)×지급률 − 선지급, 소득세 = ROUNDDOWN(AD×세율, −3), 지방세 10%
(function () {
  const STAGE = {
    VARIABLE_ADJ: 'variable_cost', VARIABLE_CREDIT: 'variable_credit', UNPAID_CARRY: 'carry_in',
    DOC_EXPENSE: 'doc_expense', EXPENSE_CREDIT: 'expense_credit', MISC: 'misc', HANDLING: 'handling',
    WREATH: 'wreath', PENALTY: 'wreath', INSURANCE: 'wreath', OTHER_EXPENSE: 'wreath',
    ADVANCE_PAID: 'advance_paid', OTHER_DEDUCT: 'other_deduct',
  };
  const EMPTY = () => ({ variable_cost: 0, variable_credit: 0, carry_in: 0, doc_expense: 0, expense_credit: 0, misc: 0, handling: 0, wreath: 0, advance_paid: 0, other_deduct: 0 });

  // 엑셀 ROUNDDOWN — 0 방향 절사. digits=-3 천원, -1 십원. 부동소수 오차는 소수 6자리에서 끊는다.
  function rounddown(value, digits) {
    const unit = Math.pow(10, -digits);
    const q = Number((value / unit).toFixed(6));
    return (q < 0 ? Math.ceil(q) : Math.floor(q)) * unit;
  }

  function buckets(items) {
    const b = EMPTY();
    for (const item of items || []) {
      const key = STAGE[String(item.kind || '').toUpperCase()];
      if (key) b[key] += Number(item.amount || 0);
    }
    return b;
  }

  // 주주 합계 — applied 는 지금 서버 결과에 들어 있는 공제(합계값에서 빼서 바탕값을 되찾는다)
  function shareholder(entry, items, applied) {
    const t = entry.totals || {};
    const was = buckets(applied);
    const b = buckets(items);
    const variable = Number(t.variable_auto || 0) + b.variable_cost - b.variable_credit;
    const carry = (Number(t.carry_in || 0) - was.carry_in) + b.carry_in;
    const docExpense = (Number(t.doc_expense || 0) - was.doc_expense + was.expense_credit) + b.doc_expense - b.expense_credit;
    const personLevel = variable + carry + docExpense + b.misc;
    let payment = 0, pretax = 0, bonus = 0;
    for (const blk of entry.blocks || []) {
      const q = Number(blk.q_pre || 0) - (blk.main ? personLevel : 0);
      const blockBonus = (q < 0 || blk.rate == null) ? 0 : q * Number(blk.rate) / 100;
      const wreath = (blk.main && q >= 0) ? b.wreath : 0;
      const handling = blk.main ? b.handling : 0;
      const advance = blk.main ? b.advance_paid : 0;
      const pre = rounddown(blockBonus + handling - wreath + Number(blk.survey_fee || 0), -3) - advance;
      const tax = rounddown(pre * 0.30, -3);
      const resident = rounddown(tax * 0.10, -1);
      const other = blk.main ? b.other_deduct : 0;
      payment += pre - tax - resident - other; pretax += pre; bonus += blockBonus;
    }
    return { payment, pretax, bonus };
  }

  // 평·동(소속·공통건) 합계 — 상여 AA 는 공제와 무관하다
  function associate(entry, items) {
    const t = entry.totals || {};
    const b = buckets(items);
    const bonus = Number(t.bonus || 0);
    const pre = rounddown(bonus + b.handling - b.wreath, -3) * Number(t.pay_ratio == null ? 1 : t.pay_ratio) - b.advance_paid;
    const tax = rounddown(pre * Number(t.tax_rate == null ? 0.15 : t.tax_rate), -3);
    const resident = rounddown(tax * 0.10, -1);
    return { payment: pre - tax - resident - b.other_deduct, pretax: pre, bonus };
  }

  // 사람 전체 지급액 — 공제는 주주 블록이 있으면 거기서, 없으면 공통건, 그것도 없으면 소속 합계에서 뺀다 (report.py 와 같은 순서)
  function preview(report, person, items) {
    const find = group => (report[group] || []).find(p => p.name === person);
    const sh = find('shareholders'), co = find('common'), as = find('associates');
    const applied = (report.deductions && report.deductions[person]) || [];
    let total = 0;
    const server = [sh, co, as].reduce((s, e) => s + (e ? Number(e.totals.payment || 0) : 0), 0);
    if (sh) total += shareholder(sh, items, applied).payment;
    if (co) total += (sh ? Number(co.totals.payment || 0) : associate(co, items).payment);
    if (as) total += (sh || co ? Number(as.totals.payment || 0) : associate(as, items).payment);
    return { payment: total, server };
  }

  window.BonusCalc = { rounddown, buckets, shareholder, associate, preview };
})();
