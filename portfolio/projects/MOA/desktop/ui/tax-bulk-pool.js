// 계산서 적용 탭 (2026-09-10) — 입금 적용용으로 끊은 모계산서의 잔액·감정서별 적용 내역, 지금 적용,
// 수동 적용·해제. /api/taxinvoice/pool. tax-bulk.js 와 같은 페이지라 함수 안에 가둔다.
(function () {
  const $ = id => document.getElementById(id);
  const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const num = v => money.format(Math.round(Number(v || 0)));
  const digits = v => Number(String(v ?? '').replace(/[^0-9]/g, '') || 0);
  const requester = () => Number((window.A10_CTX || {}).usr_seq || 0);

  function toast(msg, err) {
    const t = $('toast');
    t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 7000);
  }

  async function post(url, body) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requester_usr_seq: requester(), ...body }) });
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    return p;
  }

  async function load() {
    $('poolList').innerHTML = '<p class="tb-hint">불러오는 중...</p>';
    try {
      const res = await fetch(`/api/taxinvoice/pool?include_done=${$('poolIncludeDone').checked ? 'true' : 'false'}`);
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      render(p.data.pools || []);
    } catch (e) { $('poolList').innerHTML = `<p class="tb-hint">${esc(e.message)}</p>`; }
  }

  function render(pools) {
    const open = pools.filter(x => x.balance > 0);
    $('poolSummary').textContent = pools.length
      ? `모계산서 ${pools.length}건 · 잔액 남은 것 ${open.length}건 · 잔액 합계 ${num(open.reduce((s, x) => s + x.balance, 0))}원`
      : '입금 적용용으로 끊은 계산서가 없습니다. 감정서 발급 팝업에서 "입금 적용용으로 발행"을 켜면 여기 나타납니다.';
    $('poolList').innerHTML = pools.map(pool => `<div class="pool-card" data-id="${pool.id}">
      <div class="pool-head">
        <span>대표 <b>${esc(pool.doc_id)}</b></span><span>${esc(pool.receiver_name || '-')} ${esc(pool.receiver_corp_num || '')}</span>
        <span>작성일 ${esc(pool.write_date || '-')}</span><span>승인번호 <small>${esc(pool.nts_confirm || '-')}</small></span>
        <span>발행 <b>${num(pool.total)}</b>원</span><span class="bal${pool.balance > 0 ? '' : ' zero'}">잔액 ${num(pool.balance)}원</span>
        ${pool.balance > 0 ? `<button class="apply-one" type="button">이 계산서 지금 적용</button>` : ''}
      </div>
      <table class="pool-apps"><thead><tr><th>감정서</th><th>구분</th><th class="number">공급가</th><th class="number">세액</th><th class="number">합계</th><th>적용시각</th><th></th></tr></thead>
      <tbody>${(pool.applications || []).length ? pool.applications.map(a => `<tr class="${a.doc_type === '세금취소' ? 'cancel' : ''}">
        <td>${esc(a.doc_id)}</td><td>${esc(a.doc_type)}</td><td class="number">${num(a.supply_cost)}</td><td class="number">${num(a.tax)}</td><td class="number">${num(a.total)}</td>
        <td>${esc((a.created_at || '').replace('T', ' '))}</td>
        <td>${a.doc_type === '세금계산서' ? `<button class="del unapply" type="button" data-row="${a.id}" title="적용 해제">해제</button>` : ''}</td></tr>`).join('')
        : '<tr><td colspan="7" class="tb-hint">아직 적용된 감정서가 없습니다.</td></tr>'}</tbody></table>
      ${pool.balance > 0 ? `<div class="pool-manual"><span>수동 적용</span><input class="m-doc" placeholder="감정서번호" style="width:140px"><input class="m-amt" placeholder="합계(부가세 포함)" style="width:130px;text-align:right"><button class="apply-manual" type="button">적용</button></div>` : ''}
    </div>`).join('');
    $('poolList').querySelectorAll('.apply-one').forEach(b => b.addEventListener('click', () => applyOne(Number(b.closest('.pool-card').dataset.id))));
    $('poolList').querySelectorAll('.apply-manual').forEach(b => b.addEventListener('click', () => applyManual(b.closest('.pool-card'))));
    $('poolList').querySelectorAll('.unapply').forEach(b => b.addEventListener('click', () => unapply(Number(b.dataset.row))));
  }

  async function applyOne(poolId) {
    try { const p = await post('/api/taxinvoice/pool/apply', { pool_id: poolId }); toast(p.message); await load(); }
    catch (e) { toast(e.message, true); }
  }

  async function applyAll() {
    const button = $('poolApplyAll'); button.disabled = true; button.textContent = '적용 중...';
    try { const p = await post('/api/taxinvoice/pool/apply', {}); toast(`${p.message} · ${num(p.data.amount)}원`); await load(); }
    catch (e) { toast(e.message, true); }
    finally { button.disabled = false; button.textContent = '지금 적용'; }
  }

  async function applyManual(card) {
    const doc = card.querySelector('.m-doc').value.trim(); const amount = digits(card.querySelector('.m-amt').value);
    if (!doc || !amount) { toast('감정서번호와 금액을 적으세요.', true); return; }
    if (!confirm(`${doc} 에 ${num(amount)}원을 적용합니다. 거래처가 같은지는 확인하지 않습니다. 진행할까요?`)) return;
    try { const p = await post('/api/taxinvoice/pool/apply-manual', { pool_id: Number(card.dataset.id), doc_id: doc, amount }); toast(`${p.message} · 잔액 ${num(p.data.balance)}원`); await load(); }
    catch (e) { toast(e.message, true); }
  }

  async function unapply(rowId) {
    if (!confirm('이 적용을 해제합니다. 그 감정서는 다시 미발행으로 보입니다. 진행할까요?')) return;
    try { const p = await post('/api/taxinvoice/pool/unapply', { row_id: rowId }); toast(`${p.message} · 잔액 ${num(p.data.balance)}원`); await load(); }
    catch (e) { toast(e.message, true); }
  }

  $('poolApplyAll').addEventListener('click', applyAll);
  $('poolIncludeDone').addEventListener('change', load);
  window.A10_POOL_LOAD = load;
})();
