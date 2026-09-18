"""세금계산서 추가 발행 — 착수금 계산서 뒤 잔금 계산서 (2026-08-31 사용자 요청).

감정서당 1장을 전제로 잠겨 있던 발급 팝업에 '추가 발행' 단계를 연다.
문서번호는 기존 -R{차수} 인프라(next_issue_mgt_key)를 그대로 쓰므로
서버 발행 경로는 안 바뀌고, 초안에 기발행 합계만 실어 확인창에 쓴다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "desktop" / "ui" / "taxinvoice-dialog.js").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "popbill_tax.py").read_text(encoding="utf-8")


def test_초안에_기발행_합계가_실린다():
    block = SERVICE[SERVICE.index("def appraisal_tax_draft"):]
    block = block[: block.index("def issue_for_appraisal")]
    assert '"issued_totals"' in block
    # 취소 행은 음수 금액으로 쌓이므로(save_issued의 세금취소) 단순 합이 곧 유효 발행 합계다
    assert "N'세금계산서', N'세금취소'" in block


def test_추가_발행_버튼이_있다():
    assert 'id="taxMoreBtn"' in JS
    assert "$('taxMoreBtn').addEventListener('click', startAdditional);" in JS


def test_추가_발행_모드에서만_발급이_풀린다():
    # 발행된 건이라도 세금계산서 탭에서 추가 발행 모드를 켰으면 발급 버튼이 산다.
    # 같은 조건식을 validate 와 renderModeState 가 함께 써야 상태가 안 엇갈린다.
    assert JS.count("issued && !(mode === 'tax' && current.additional)") >= 2


def test_추가_발행은_남은_금액을_미리_채운다():
    block = JS[JS.index("function startAdditional"):]
    block = block[: block.index("\n  }") + 4]
    assert "fullSupply" in block
    assert "issuedTotals" in block
    assert "confirm(" in block  # 켜기 전에 기발행 합계를 보여주고 묻는다


def test_발행_합계_초과시_경고한다():
    assert "발행 합계가 감정서 수수료" in JS


def test_화면_버전을_올렸다():
    for page in ("dashboard.html", "receivables.html"):
        html = (ROOT / "desktop" / "ui" / page).read_text(encoding="utf-8")
        assert "taxinvoice-dialog.js?v=20260831-1" in html, page
