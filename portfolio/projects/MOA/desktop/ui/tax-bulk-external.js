// 계산서 등록 화면 (2026-09-09 외부 발행 등록 → 2026-09-11 '계산서Excel등록' 하나만) — 국세청 매출 자료나
// 우리 양식 엑셀을 올려 발급 원장에 넣는다. 한 건씩 입력은 없앴다(사용자: 무조건 엑셀로만).
// 서버 검증(/api/taxinvoice/external/validate)을 거쳐 통과한 행만 등록(/register)한다.
// 전역 이름이 새지 않게 함수 안에 가둔다.
(function () {
  const $ = id => document.getElementById(id);
  const money = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 });
  const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c]));
  const num = v => money.format(Math.round(Number(v || 0)));
  const requester = () => Number((window.A10_CTX || {}).usr_seq || 0);

  let rows = [];   // 화면 목록 — 서버가 검증해 준 행(problems·warnings·ok·registered)

  function toast(msg, err) {
    const t = $('toast');
    t.textContent = msg; t.classList.toggle('error', !!err); t.classList.remove('hidden');
    clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 7000);
  }

  async function post(url, body) {
    const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ requester_usr_seq: requester(), ...body }) });
    const p = await res.json();
    if (!p.success) throw new Error(p.message);
    return p.data;
  }

  const payloadOf = r => ({
    doc_id: r.doc_id, source: r.source, doc_type: r.doc_type, write_date: r.write_date, nts_confirm: r.nts_confirm,
    receiver_corp_num: r.receiver_corp_num, receiver_name: r.receiver_name, supply_cost: r.supply_cost, tax: r.tax,
    nts: r.nts || null,   // 국세청 자료 원래 칸 값 — 다시 검증해도 목록 모양이 유지되게
  });
  const biz = v => { const d = String(v || '').replace(/[^0-9]/g, ''); return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d; };

  function render() {
    const pending = rows.filter(r => r.ok && !r.registered);
    $('extRegister').disabled = pending.length === 0;
    $('extRegister').textContent = pending.length ? `등록 (${pending.length}건)` : '등록';
    const known = rows.filter(r => r.known && !r.registered).length;
    const bad = rows.filter(r => !r.ok && !r.registered && !r.known).length;
    const done = rows.filter(r => r.registered).length;
    $('extSummary').textContent = rows.length
      ? `${rows.length}건 · 등록 가능 ${pending.length}건${bad ? ` · 확인 필요 ${bad}건` : ''}${known ? ` · 이미 있음 ${known}건` : ''}${done ? ` · 등록됨 ${done}건` : ''}`
      : '국세청 매출 자료나 양식 엑셀을 올려 발급 원장에 등록합니다.';
    if (!rows.length) {
      $('extRows').innerHTML = '<tr><td colspan="16" class="tb-hint">엑셀 파일을 고르면 등록할 목록이 여기 나옵니다.</td></tr>';
      return;
    }
    // 국세청 자료는 우리 매출 전부라 대부분이 '이미 있음'이다 — 기본은 접어 둔다
    const hideKnown = $('extHideKnown').checked;
    const shown = rows.map((r, i) => [r, i]).filter(([r]) => !(hideKnown && r.known && !r.registered));
    if (!shown.length) {
      $('extRows').innerHTML = `<tr><td colspan="16" class="tb-hint">등록할 외부 발행분이 없습니다 (이미 있는 건 ${known}건 숨김).</td></tr>`;
      return;
    }
    $('extRows').innerHTML = shown.map(([r, i]) => {
      // 등록 전 모든 행에서 감정서번호를 고친다 — 현금영수증은 자료에 번호가 없고, 세금계산서도 품목에서 뽑은
      // 번호가 틀릴 수 있다 (재무팀 요청 2026-09-11)
      const needDoc = !r.registered;
      // 국세청 자료 칸 그대로 — 우리 양식 행은 nts 가 없어 정규화 값으로 채운다. 취소분은 자료처럼 음수로
      const n = r.nts || {};
      const sign = (r.doc_type === '세금취소' || r.doc_type === '현금취소') ? -1 : 1;
      const docCell = needDoc ? `<input class="doc-edit" value="${esc(r.doc_id)}" placeholder="감정서번호" style="width:120px">` : esc(r.doc_id);
      const state = r.registered ? '<span class="badge ok">등록 완료</span>'
        : r.ok ? '<span class="badge ok">등록 가능</span>' : r.problems.map(p => `<span class="badge bad">${esc(p)}</span>`).join(' ');
      const warn = (r.warnings || []).map(w => ` <span class="badge warn">${esc(w)}</span>`).join('');
      return `<tr data-i="${i}" class="${r.registered ? 'done' : r.ok ? '' : 'bad'}">
        <td class="center">${i + 1}</td>
        <td>${esc(n['작성일시'] || r.write_date)}</td>
        <td>${esc(biz(r.receiver_corp_num))}</td><td>${esc(r.receiver_name)}</td>
        <td class="number">${num(sign * (r.supply_cost + r.tax))}</td><td class="number">${num(sign * r.supply_cost)}</td><td class="number">${num(sign * r.tax)}</td>
        <td>${esc(n['분류'] || r.doc_type)}</td><td>${esc(n['종류'] || '')}</td><td>${esc(n['발급유형'] || r.source)}</td>
        <td class="clip" title="${esc(n['품목명'] || '')}">${esc(n['품목명'] || '')}</td><td class="clip" title="${esc(n['비고'] || '')}">${esc(n['비고'] || '')}</td>
        <td>${docCell}</td><td>${esc(r.customer_name || '-')}</td>
        <td>${state}${warn}</td>
        <td>${r.registered ? '' : '<button class="del" type="button" title="목록에서 빼기">×</button>'}</td>
      </tr>`;
    }).join('');
    $('extRows').querySelectorAll('.doc-edit').forEach(input => input.addEventListener('change', () => {
      const i = Number(input.closest('tr').dataset.i);
      rows = rows.map((x, k) => (k === i ? { ...x, doc_id: input.value.trim() } : x));
      revalidate().catch(e => toast(e.message, true));
    }));
    $('extRows').querySelectorAll('.del').forEach(b => b.addEventListener('click', () => {
      const i = Number(b.closest('tr').dataset.i);
      rows = rows.filter((_, k) => k !== i);
      revalidate().catch(e => toast(e.message, true));
    }));
  }

  // 목록이 바뀔 때마다 미등록 행 전체를 다시 검증한다 — 목록 안 승인번호 중복도 서버가 본다
  async function revalidate() {
    const keep = rows.filter(r => r.registered);
    const open = rows.filter(r => !r.registered);
    if (!open.length) { rows = keep; render(); return; }
    const data = await post('/api/taxinvoice/external/validate', { rows: open.map(payloadOf) });
    rows = keep.concat(data.rows || []);
    render();
  }

  // 파일을 고르면 바로 읽는다 — [엑셀 읽기] 버튼은 없앴다 (2026-09-11 사용자). 다른 파일을 고르면 그 파일로 바꾼다.
  async function uploadExcel() {
    const file = $('exFile').files[0];
    if (!file) return;
    rows = [];
    $('extRows').innerHTML = '<tr><td colspan="16" class="tb-hint">읽는 중...</td></tr>';
    $('exFile').disabled = true;
    try {
      const form = new FormData();
      form.append('file', file); form.append('requester_usr_seq', String(requester()));
      const res = await fetch('/api/taxinvoice/external/parse-excel', { method: 'POST', body: form });
      const p = await res.json();
      if (!p.success) throw new Error(p.message);
      const fresh = (p.data.rows || []);
      rows = rows.concat(fresh);
      await revalidate();
      toast(`${file.name} — ${fresh.length}행을 읽었습니다.`);
    } catch (e) {
      toast(e.message, true);
      render();
    } finally {
      $('exFile').disabled = false;
      $('exFile').value = '';   // 같은 파일을 다시 골라도 change 가 나게
    }
  }

  // 팝업을 닫을 때(tax-register-list.js) 올린 목록을 비운다
  window.A10_EXT_RESET = () => { rows = []; $('exFile').value = ''; render(); };

  async function registerRows() {
    const pending = rows.filter(r => r.ok && !r.registered);
    if (!pending.length) return;
    const total = pending.reduce((s, r) => s + r.supply_cost + r.tax, 0);
    if (!confirm(`${pending.length}건(합계 ${num(total)}원)을 발급 원장에 등록합니다.\n입금현황·감정서 LIST 의 발행 여부에 바로 반영됩니다. 진행할까요?`)) return;
    const button = $('extRegister');
    button.disabled = true; button.textContent = '등록 중...';
    try {
      const data = await post('/api/taxinvoice/external/register', { rows: pending.map(payloadOf) });
      const byConfirm = Object.fromEntries((data.results || []).map(r => [r.nts_confirm, r]));
      rows = rows.map(r => {
        const res = byConfirm[r.nts_confirm];
        return res && !r.registered ? { ...r, ...res } : r;
      });
      render();
      toast(`${data.registered}건 등록${data.skipped ? ` · ${data.skipped}건 건너뜀 — 행의 사유를 보세요` : ''}`, data.skipped > 0);
      if (data.registered && window.A10_TAX_LIST_RELOAD) window.A10_TAX_LIST_RELOAD();   // 팝업 뒤 원장 목록도 새로
    } catch (e) {
      toast(e.message, true);
      render();
    }
  }

  $('exFile').addEventListener('change', uploadExcel);
  $('extRegister').addEventListener('click', registerRows);
  $('extHideKnown').addEventListener('change', render);
  window.A10_READY.then(ctx => {
    $('exTemplate').href = `/api/taxinvoice/external/template.xlsx?usr_seq=${encodeURIComponent(ctx.usr_seq || '')}`;
    // 본사 재무팀·집행부만 (예전 tax-bulk.js 에 있던 관문 — 서버 API 도 같은 조건으로 막는다)
    if (ctx.office_id !== '10' || !ctx.is_operations) {
      $('exFile').disabled = true;
      $('extSummary').textContent = '계산서 등록은 본사 재무팀·집행부만 사용할 수 있습니다.';
    }
  });
})();
