"""유치실적 승인 취소 (2026-08-21 사용자 요청).

승인은 아마란스 원장(Apw_Mae_GaPrice)에 INSERT 하고, 그 행 번호를
a10_gaprice_outbox.applied_ga_seq 에 적어 둔다. 취소는 그 행을 지우고 초안을
승인 대기로 되돌린다 — 상쇄 행을 넣지 않고 실제로 지운다(사용자 결정).

원장 삭제는 되돌릴 수 없다. 그래서 지울 행을 Seq 하나로만 찾지 않고 감정서번호
까지 맞을 때만 지운다 — 그 번호가 다른 감정서 행으로 바뀌어 있으면 남의 실적이
사라진다. 권한은 승인과 같다(본사 재무팀·집행부).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVICE = (ROOT / "app" / "services" / "gaprice_outbox.py").read_text(encoding="utf-8")
ROUTER = (ROOT / "app" / "routers" / "gaprice.py").read_text(encoding="utf-8")
UI = (ROOT / "desktop" / "ui" / "allocation.js").read_text(encoding="utf-8")


def test_감정서번호까지_맞을_때만_지운다():
    """Seq 하나만 믿으면 그 번호가 재사용됐을 때 남의 실적을 지운다."""
    block = SERVICE[SERVICE.index("def cancel_approval("):]

    assert "DELETE FROM [{database}].dbo.Apw_Mae_GaPrice" in block
    assert "WHERE Seq = :seq AND Docid = :doc_id" in block, (
        "감정서번호 조건이 빠지면 엉뚱한 행을 지울 수 있다"
    )


def test_승인된_것만_취소한다():
    block = SERVICE[SERVICE.index("def cancel_approval("):]

    assert 'GapriceOutbox.status == "APPROVED"' in block
    assert '"승인된 배분이 없습니다."' in block


def test_초안을_승인_대기로_되돌린다():
    """다시 승인할 수 있어야 한다. 승인 흔적도 지운다."""
    block = SERVICE[SERVICE.index("def cancel_approval("):]

    for line in ('row.status = "PENDING"', "row.applied_ga_seq = None",
                 "row.approved_by = None", "row.approved_at = None"):
        assert line in block, f"{line} 이 없다"


def test_권한은_승인과_같다():
    block = ROUTER[ROUTER.index("def cancel_outbox("):]

    assert 'require_menu("salesInput")' in block
    assert "require_same_requester(access, request.approver_usr_seq)" in block
    assert "require_operations_user(" in block, "본사 재무팀·집행부만"


def test_화면이_되돌릴_수_없음을_알리고_확인받는다():
    """원장에서 지우는 일이라 실수로 눌리면 안 된다."""
    block = UI[UI.index("if(approved){"):]
    block = block[:block.index("if(!approved){")]

    assert "confirm(" in block
    assert "되돌릴 수 없습니다" in block
    assert "submit(docId,'cancel')" in block


def test_승인_취소는_승인_완료_화면에만_있다():
    """승인 대기 화면에 취소 버튼이 있으면 지울 것이 없는데 눌리게 된다."""
    start = UI.index("${approved?`${approval}")
    cell = UI[start:UI.index("+ 담당자", start)]

    # 삼항의 참(approved) 가지 안에 있어야 한다 — ':' 뒤(승인 대기)면 안 된다.
    assert "cancel-button" in cell
    assert cell.index("cancel-button") < cell.index("`:`"), (
        "승인 대기 가지에 있으면 지울 것이 없는데 버튼이 뜬다"
    )
    assert UI.count("cancel-button") == 2, "만드는 곳 1 + 연결하는 곳 1"


def test_원장에_이미_없는_행은_막지_않는다():
    """손으로 먼저 지웠어도 '원장에 없다'는 목표는 이뤄진 것이다."""
    block = SERVICE[SERVICE.index("def cancel_approval("):]

    assert "deleted += int(result.rowcount or 0)" in block
    assert '"deleted": deleted' in block
    assert "원장에 이미 없던" in ROUTER, "몇 행이 그랬는지 알려 줘야 한다"


def test_취소가_원장_삭제와_상태_되돌리기를_함께_한다():
    from app.models.gaprice_outbox import GapriceOutbox
    from app.services.gaprice_outbox import cancel_approval

    row = GapriceOutbox(
        doc_id="01-2607-3-2229", manager="유승민", status="APPROVED",
        applied_ga_seq=55198, approved_by=813,
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = [row]
    db.execute.return_value.rowcount = 1

    result = cancel_approval(db, "01-2607-3-2229", 813)

    assert result == {"rows": 1, "deleted": 1}
    assert row.status == "PENDING"
    assert row.applied_ga_seq is None and row.approved_at is None
    params = db.execute.call_args.args[1]
    assert params == {"seq": 55198, "doc_id": "01-2607-3-2229"}
    db.commit.assert_called_once()


def test_승인된_것이_없으면_원장을_건드리지_않는다():
    from app.services.gaprice_outbox import GapriceApprovalError, cancel_approval

    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    with pytest.raises(GapriceApprovalError):
        cancel_approval(db, "01-2607-3-2229", 813)
    db.execute.assert_not_called()
    db.commit.assert_not_called()
