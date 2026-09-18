"""발급 팝업의 전표 생성 — 거래처를 고르는 창을 건너뛴다.

현금영수증(2026-08-20): 아마란스 거래처가 늘 '현금영수증(국세청)'(0000028605) 하나뿐이라
매번 창을 띄워 고르게 할 이유가 없다.
세금계산서(2026-08-27 재무팀 요청): 계산서의 공급받는자가 곧 전표 거래처다 — 거래처코드(tr_cd)가
있으면 창 없이 바로 아마란스로 보내고, 코드 없이 수기 입력한 거래처만 종전대로 창을 띄운다.
"""

from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"


def test_현금영수증_거래처_코드는_국세청_계정이다():
    script = (UI / "dashboard.js").read_text(encoding="utf-8")

    assert "const CASH_RECEIPT_PARTNER={code:'0000028605',name:'현금영수증(국세청)'}" in script, (
        "아마란스 거래처코드는 열 자리다 — '28605' 로 보내면 거절당한다"
    )


def test_현금영수증은_늘_세금계산서는_거래처코드가_있을_때만_창을_건너뛴다():
    """세금계산서는 계산서에 쓴 거래처(tr_cd)로만 바로 보낸다 — 코드가 없으면 엉뚱한 거래처가 되므로 창을 연다."""
    script = (UI / "taxinvoice-dialog.js").read_text(encoding="utf-8")

    block = script[script.index("function doVoucher()"):]
    block = block[:block.index("\n  }") + 4]

    assert "current.issuedType === 'cash'" in block, "발급 종류를 안 보면 둘 다 건너뛴다"
    assert "window.A10_CREATE_VOUCHER_CASH(docId)" in block
    # 세금계산서 직행 경로 — 거래처코드가 있을 때만, 계산서의 공급받는자 코드로
    assert "current.issuedType === 'tax' && trCd" in block
    assert "window.A10_CREATE_VOUCHER_TAX(docId, { code: trCd" in block
    # 호스트가 직행 경로를 안 주는 화면·코드 없는 거래처는 종전 창 흐름으로 되돌아가야 한다
    assert "window.A10_CREATE_VOUCHER(docId)" in block
    # 이미 전표가 있으면 아무것도 하지 않는다 (중복 생성 방지)
    assert "if (!current || !current.issued || current.voucherExists) return;" in block

    dashboard = (UI / "dashboard.js").read_text(encoding="utf-8")
    assert "window.A10_CREATE_VOUCHER_TAX=(docId,partner)=>createVoucherWithPartner(docId,partner)" in dashboard
    for page in ("dashboard.html", "receivables.html"):
        assert "taxinvoice-dialog.js?v=20260831-1" in (UI / page).read_text(encoding="utf-8"), page


def test_전표가_없는_화면에서는_버튼을_숨긴다():
    """입금 현황처럼 dashboard.js 가 없는 화면은 전표를 만들 수 없다."""
    script = (UI / "taxinvoice-dialog.js").read_text(encoding="utf-8")

    assert "typeof window.A10_CREATE_VOUCHER === 'function'" in script
    assert "typeof window.A10_CREATE_VOUCHER_CASH === 'function'" in script
