"""카드전표 임시저장 — 분류·체크 작업이 실수로 날아가지 않게 (2026-08-31 사용자 요청).

수정할 때마다 브라우저 저장소에 자동 저장하고, 화면을 열면 마지막 작업을
복원하며, 목록을 다시 불러와도 같은 건(dedup_key)에 하던 작업을 다시 입힌다.
눈에 보이는 '임시저장' 버튼도 있다. 서버 변경 없음 — 화면 파일만 검사한다.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "desktop" / "ui" / "card-vouchers.js").read_text(encoding="utf-8")
HTML = (ROOT / "desktop" / "ui" / "card-vouchers.html").read_text(encoding="utf-8")


def test_자동저장과_복원이_있다():
    assert "const SAVE_KEY = 'a10.cardVouchers.worksheet'" in JS
    assert "function saveWork(" in JS
    assert "function restoreWork(" in JS
    # 화면을 열 때 복원부터 한다 (조회 전에 목록이 보여야 한다)
    assert "restoreWork();" in JS


def test_수정하면_자동저장이_걸린다():
    # 계정·공제·금액·일괄변경·확정은 전부 renderRows 를 거친다 — 거기서 한 번에 건다.
    assert "if (items.length) queueSave();" in JS
    # renderRows 를 거치지 않는 적요 수정·체크에도 따로 걸어야 한다.
    assert JS.count("queueSave();") >= 3


def test_다시_불러와도_하던_작업을_입힌다():
    # 업로드·검증과 카드내역 불러오기가 목록을 통째로 바꾸면서 작업이 날아갔다
    # — 새 목록에 이전 작업을 다시 입힌 뒤에 교체한다.
    assert "function mergeSavedEdits(" in JS
    assert JS.count("mergeSavedEdits(") >= 3  # 정의 + 업로드 + 카드내역 불러오기


def test_처리된_건은_병합하지_않는다():
    # 이미 확정·전송된 건은 서버 상태가 진실이다 — 이전 작업을 덮어씌우면 안 된다.
    block = JS[JS.index("function mergeSavedEdits") :]
    block = block[: block.index("\n}") + 2]
    assert "it.processed_status || old.processed_status" in block


def test_임시저장_버튼과_저장_표시가_있다():
    assert 'id="cvSaveWork"' in HTML
    assert 'id="cvSaveNote"' in HTML
    assert "$('cvSaveWork').addEventListener('click'" in JS
    assert "card-vouchers.js?v=20260831-4" in HTML
