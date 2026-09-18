// 출장비 입력 탭 (2026-09-10) — 델파이 '출장비입력(CulEdit)' 이식. travel-expense.js 의 A10_TE 도우미를 쓴다.
// 기준 출장비는 소재지 지역(REG)으로 서버가 찾아 주고, 서울(11)은 시내·그 밖은 시외 칸에 비율만큼 넣는다.
(function () {
  const TE = window.A10_TE;
  const $ = id => document.getElementById(id);
  const AMOUNTS = ['cul_in', 'cul_out', 'regis_copy', 'toji_use', 'toji_dae', 'build_dae', 'jijuck', 'mul_amt'];
  const BILLS = ['yebi', 'muljosabi', 'tojosabi', 'gongbu', 'silbi', 'yongyeuk'];
  let current = null;   // 열려 있는 폼의 draft
  let mine = [];        // 이번 달 내가 적은 건

  const val = id => TE.digits($(id).value);
  const setAmt = (id, v) => { $(id).value = TE.num(v); };

  function recalc() {
    const cul = val('f_cul_in') + val('f_cul_out');
    const gong = ['f_regis_copy', 'f_toji_use', 'f_toji_dae', 'f_build_dae', 'f_jijuck', 'f_mul_amt'].reduce((s, id) => s + val(id), 0);
    $('sumCul').textContent = TE.num(cul); $('sumGong').textContent = TE.num(gong); $('sumAll').textContent = TE.num(cul + gong);
    $('sumBill').value = TE.num(BILLS.reduce((s, k) => s + val('f_' + k), 0));
  }

  // 델파이 GET_BASICCUL — 비율 라디오가 바뀌면 기준액을 시내/시외 칸에 넣는다 (다른 칸은 0)
  function applyRatio() {
    if (!current) return;
    const ratio = Number(document.querySelector('input[name=ratio]:checked').value);
    const rate = current.rate || {};
    const base = Number(rate.ManCul_Amt || 0);
    const stored = { 80: rate.PAMT_80, 50: rate.PAMT_50, 20: rate.PAMT_20 }[ratio];
    const amount = ratio === 100 ? base : (stored != null ? Number(stored) : Math.round(base * ratio / 100));
    setAmt('f_cul_in', current.is_seoul ? amount : 0); setAmt('f_cul_out', current.is_seoul ? 0 : amount);
    recalc();
  }

  function fill(d) {
    current = d;
    $('enForm').hidden = false;
    $('fmDocId').textContent = d.doc_id;
    $('fmState').textContent = d.seq ? (d.total_result === 'Y' ? '완료' : '입력됨') : '새 입력';
    $('fmManager').value = d.manager || ''; $('fmAddr').value = d.address || '';
    $('fmRegion').value = `${d.reg || '-'} · ${d.is_seoul ? '시내(서울)' : '시외'}`;
    $('fmDate').value = d.cul_date || new Date().toISOString().slice(0, 10);
    const r = d.rate || {};
    $('fmBase').textContent = `기준 ${TE.num(r.ManCul_Amt)}원 · 80% ${TE.num(r.PAMT_80)} · 20% ${TE.num(r.PAMT_20)}${r.PAMT_50 ? ` · 50% ${TE.num(r.PAMT_50)}` : ''}`;
    document.querySelector('input[name=ratio][value="50"]').disabled = false;
    AMOUNTS.forEach(k => setAmt('f_' + k, d[k] || 0));
    BILLS.forEach(k => setAmt('f_' + k, d[k] || 0));
    $('f_mul_remark').value = d.mul_remark || '';
    $('f_bigo').value = (d.bigo || '').replace(new RegExp('^' + d.doc_id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*'), '');
    $('fmDelete').hidden = !d.seq;
    $('fmMsg').textContent = d.seq ? `저장된 건 (분기 ${d.bungi || '-'})` : '';
    if (!d.seq) { document.querySelector('input[name=ratio][value="100"]').checked = true; applyRatio(); } else recalc();
  }

  async function open(docId, seq) {
    if (!docId) { TE.toast('감정서번호를 적으세요.', true); return; }
    try {
      const q = new URLSearchParams({ doc_id: docId, seq: String(seq || 0) });
      const p = await TE.api('GET', `/api/travel-expense/draft?${q}`);
      fill(p.data);
      $('enForm').scrollIntoView({ block: 'nearest' });
    } catch (e) { TE.toast(e.message, true); }
  }

  async function save() {
    if (!current) return;
    if (!$('fmDate').value) { TE.toast('출장일자를 고르세요.', true); return; }
    const body = { seq: current.seq || 0, doc_id: current.doc_id, cul_date: $('fmDate').value, mul_remark: $('f_mul_remark').value.trim(), bigo: $('f_bigo').value.trim() };
    AMOUNTS.forEach(k => { body[k] = val('f_' + k); });
    BILLS.forEach(k => { body[k] = val('f_' + k); });
    if (body.cul_in + body.cul_out <= 0 && !confirm('출장비가 0원입니다. 공부발급비만 저장할까요?')) return;
    $('fmSave').disabled = true;
    try {
      const p = await TE.api('POST', '/api/travel-expense/save', body);
      TE.toast(`저장 완료 · ${current.doc_id} (분기 ${p.data.bungi})`);
      await open(current.doc_id, p.data.seq);
      await Promise.all([loadDocs(), loadMine()]);
    } catch (e) { TE.toast(e.message, true); }
    finally { $('fmSave').disabled = false; }
  }

  async function remove() {
    if (!current || !current.seq) return;
    if (!confirm(`${current.doc_id} 출장비를 삭제합니다. 진행할까요?`)) return;
    try {
      await TE.api('POST', '/api/travel-expense/delete', { seq: current.seq, doc_id: current.doc_id });
      TE.toast('삭제 완료'); current = null; $('enForm').hidden = true;
      await Promise.all([loadDocs(), loadMine()]);
    } catch (e) { TE.toast(e.message, true); }
  }

  async function loadDocs() {
    $('enSummary').textContent = '조회 중...';
    try {
      const p = await TE.api('GET', '/api/travel-expense/my-docs');
      const items = p.data.items || [];
      $('enSummary').textContent = items.length ? `${items.length}건 — 출장비를 적을 감정서` : '적을 감정서가 없습니다. 번호를 직접 넣어 불러올 수도 있습니다.';
      $('enDocs').innerHTML = items.length ? items.map(d => `<tr class="pick" data-doc="${TE.esc(d.doc_id)}">
        <td>${TE.esc(d.doc_id)}</td><td title="${TE.esc(d.address)}">${TE.esc(d.address)}</td><td>${TE.esc(d.status || '')}</td><td>${TE.esc(d.manager || '')}</td>
        <td>${TE.esc(d.receipt_date || '')}</td><td class="number">${TE.num(d.total)}</td><td class="number">${TE.num(d.base_amount)}</td></tr>`).join('')
        : '<tr><td colspan="7" class="te-hint">없음</td></tr>';
      $('enDocs').querySelectorAll('tr.pick').forEach(tr => tr.addEventListener('click', () => {
        $('enDocs').querySelectorAll('tr').forEach(x => x.classList.remove('selected')); tr.classList.add('selected');
        $('enDocId').value = tr.dataset.doc; open(tr.dataset.doc, 0);
      }));
    } catch (e) { $('enSummary').textContent = e.message; }
  }

  async function loadMine() {
    const me = TE.me || {};
    try {
      const q = new URLSearchParams({ bungi: me.current_month || '' });
      const p = await TE.api('GET', `/api/travel-expense/list?${q}`);
      mine = (p.data.items || []).filter(r => r.write_name === me.name);
      const total = mine.reduce((s, r) => s + r.amount_total, 0);
      $('enMineSummary').textContent = mine.length ? `${mine.length}건 · 합계 ${TE.num(total)}원 · 미상신 ${mine.filter(r => r.appro_state === 0).length}건` : '이번 달에 적은 건이 없습니다.';
      $('enMine').innerHTML = mine.length ? mine.map((r, i) => `<tr data-i="${i}" class="${r.editable ? 'pick' : ''}">
        <td class="center"><input class="pick" type="checkbox"${r.appro_state === 0 ? '' : ' disabled'}></td>
        <td>${TE.esc(r.doc_id)}</td><td>${TE.esc(r.cul_date || '')}</td><td class="center">${TE.stateBadge(r)}</td>
        <td class="number">${TE.num(r.cul_total)}</td><td class="number">${TE.num(r.gong_total)}</td><td class="number">${TE.num(r.amount_total)}</td><td title="${TE.esc(r.bigo)}">${TE.esc(r.bigo)}</td></tr>`).join('')
        : '<tr><td colspan="8" class="te-hint">-</td></tr>';
      $('enMine').querySelectorAll('tr.pick').forEach(tr => tr.addEventListener('dblclick', () => { const r = mine[Number(tr.dataset.i)]; $('enDocId').value = r.doc_id; open(r.doc_id, r.seq); }));
      $('enMine').querySelectorAll('input.pick').forEach(b => b.addEventListener('change', updateSubmit));
      updateSubmit();
    } catch (e) { $('enMineSummary').textContent = e.message; }
  }

  function selectedMine() {
    return Array.from($('enMine').querySelectorAll('tr[data-i]')).filter(tr => { const b = tr.querySelector('input.pick'); return b && b.checked && !b.disabled; }).map(tr => mine[Number(tr.dataset.i)]);
  }
  function updateSubmit() {
    const n = selectedMine().length;
    $('enSubmit').disabled = n === 0; $('enSubmit').textContent = n ? `선택 제출 (${n}건)` : '선택 제출';
  }
  async function submitMine() {
    const sel = selectedMine(); if (!sel.length) return;
    if (!confirm(`${sel.length}건을 결재에 올립니다. 제출한 뒤에는 고칠 수 없습니다. 진행할까요?`)) return;
    try {
      const p = await TE.api('POST', '/api/travel-expense/approve', { action: 'submit', targets: sel.map(r => ({ seq: r.seq, doc_id: r.doc_id })) });
      TE.toast(p.message); await loadMine();
    } catch (e) { TE.toast(e.message, true); }
  }

  AMOUNTS.concat(BILLS).forEach(k => {
    const el = $('f_' + k);
    el.addEventListener('input', recalc);
    el.addEventListener('blur', () => { el.value = TE.num(TE.digits(el.value)); recalc(); });
  });
  document.querySelectorAll('input[name=ratio]').forEach(r => r.addEventListener('change', applyRatio));
  $('enLoad').addEventListener('click', () => open($('enDocId').value.trim(), 0));
  $('enDocId').addEventListener('keydown', e => { if (e.key === 'Enter') open($('enDocId').value.trim(), 0); });
  $('enRefresh').addEventListener('click', loadDocs);
  $('fmSave').addEventListener('click', save);
  $('fmDelete').addEventListener('click', remove);
  $('fmNew').addEventListener('click', () => { if (current) open(current.doc_id, 0); });
  $('enMineAll').addEventListener('change', () => { $('enMine').querySelectorAll('input.pick').forEach(b => { if (!b.disabled) b.checked = $('enMineAll').checked; }); updateSubmit(); });
  $('enSubmit').addEventListener('click', submitMine);

  window.A10_TE_ENTRY = { open, init: () => { loadDocs(); loadMine(); }, reloadMine: loadMine };
})();
