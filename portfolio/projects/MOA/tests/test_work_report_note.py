"""업무실적 기재사항 저장·복원.

fee_basis 의견 저장에서 실제로 터졌던 사고(빈 값 부활 / 목록 밖 doc 거부로 저장 전체 실패)가
이 구조에서는 재현되지 않는지 고정한다.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.work_report_note import WorkReportNote
from app.services.work_report_note import (
    apply_notes_to_rows,
    amount_fingerprint,
    load_notes,
    save_notes,
)

KEY = dict(office_code="10", year=2026, month=5, half="상반")


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    WorkReportNote.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def test_saved_note_restores_in_a_new_session(sessions):
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0001": {"excluded": True, "reason": "중복보고"},
        }, **KEY)
    with sessions() as db:
        notes = load_notes(db, **KEY)
    assert notes["01-2605-3-0001"]["excluded"] is True
    assert notes["01-2605-3-0001"]["reason"] == "중복보고"


def test_blank_reason_is_kept_not_dropped(sessions):
    """사유를 비운 것도 결정이다. 빈 문자열로 복원돼야 한다(None 이 아니라)."""
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0002": {"excluded": True, "reason": ""},
        }, **KEY)
    with sessions() as db:
        notes = load_notes(db, **KEY)
    assert "01-2605-3-0002" in notes
    assert notes["01-2605-3-0002"]["reason"] == ""


def test_explicit_include_without_reason_survives(sessions):
    """'실비만 건을 일부러 포함(N, 사유 없음)'이 자동 정리로 사라지면 안 된다.

    사라지면 다음 조회에서 NO_FEE 기본값(제외)으로 부활한다 — 빈 의견 부활 그 자체.
    """
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0003": {"excluded": False, "reason": ""},
        }, **KEY)
    with sessions() as db:
        notes = load_notes(db, **KEY)
    assert notes["01-2605-3-0003"]["excluded"] is False

    rows = [{"ID_NUM": "01-2605-3-0003", "NO_FEE": True, "GAMGA": 1, "SUSU": 2}]
    apply_notes_to_rows(rows, notes)
    # 저장값이 자동기본값(NO_FEE=제외)을 이겨야 한다.
    assert rows[0]["NOTE_EXCLUDED"] is False


def test_untouched_doc_gets_none_not_false(sessions):
    """손대지 않은 감정서는 None 이어야 한다 — False 로 내리면 자동기본값이 죽는다."""
    rows = [{"ID_NUM": "01-2605-3-0099", "NO_FEE": True, "GAMGA": 1, "SUSU": 2}]
    apply_notes_to_rows(rows, {})
    assert rows[0]["NOTE_EXCLUDED"] is None


def test_resave_keeps_single_row(sessions):
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0004": {"excluded": True, "reason": "처음"},
        }, **KEY)
        save_notes(db, basis="접수", notes={
            "01-2605-3-0004": {"excluded": False, "reason": "고침"},
        }, **KEY)
    with sessions() as db:
        rows = db.execute(select(WorkReportNote)).scalars().all()
    assert len(rows) == 1
    assert rows[0].reason == "고침"
    assert rows[0].excluded == "N"


def test_only_explicit_null_deletes(sessions):
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0005": {"excluded": True, "reason": "뺌"},
        }, **KEY)
        result = save_notes(db, basis="매출", notes={"01-2605-3-0005": None}, **KEY)
    assert result["deleted_count"] == 1
    with sessions() as db:
        assert load_notes(db, **KEY) == {}


def test_doc_outside_current_list_is_accepted(sessions):
    """수기 추가(extra_doc_ids)로 자동목록 밖 감정서를 넣는 것이 정상 동작이다."""
    with sessions() as db:
        result = save_notes(db, basis="매출", notes={
            "01-2509-B-0048": {"excluded": True, "reason": "과월 발송"},
        }, **KEY)
    assert result["saved_count"] == 1
    assert result["rejected"] == []


def test_bad_doc_is_rejected_alone_and_others_still_save(sessions):
    """한 건이 잘못됐다고 나머지를 버리지 않는다 — fee_basis 는 전체를 거부했다."""
    with sessions() as db:
        result = save_notes(db, basis="매출", notes={
            "01-2605-3-0006": {"excluded": True, "reason": "정상"},
            "나쁜/번호": {"excluded": True, "reason": "형식 오류"},
            "01-2605-3-0007": {"excluded": True, "reason": "가" * 300},
        }, **KEY)
    assert result["saved_count"] == 1
    codes = {r["code"] for r in result["rejected"]}
    assert codes == {"BAD_DOC_ID", "TOO_LONG"}
    with sessions() as db:
        assert set(load_notes(db, **KEY)) == {"01-2605-3-0006"}


def test_half_is_part_of_the_key(sessions):
    """상·하반은 별개 제출 배치다. 상반 저장이 하반 조회에 뜨면 안 된다."""
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0008": {"excluded": True, "reason": "상반만"},
        }, **KEY)
    with sessions() as db:
        other = load_notes(db, office_code="10", year=2026, month=5, half="하반")
    assert other == {}


def test_basis_is_not_part_of_the_key(sessions):
    """기준을 바꿔도 같은 기재사항이 보여야 한다 — 키에 basis 를 넣으면 화면 40~51%가 빈다."""
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0009": {"excluded": True, "reason": "기준 무관"},
        }, **KEY)
    with sessions() as db:
        notes = load_notes(db, **KEY)   # load 에는 basis 인자가 없다
    assert notes["01-2605-3-0009"]["reason"] == "기준 무관"
    assert notes["01-2605-3-0009"]["last_basis"] == "매출"


def test_amount_change_is_flagged_not_blocked(sessions):
    """금액이 바뀌면 표시만 한다. 저장·전송을 막지 않는다(409 막다른길 방지)."""
    row = {"ID_NUM": "01-2605-3-0010", "GAMGA": 100, "SUSU": 50, "NO_FEE": False}
    with sessions() as db:
        save_notes(db, basis="매출", notes={row["ID_NUM"]: {"excluded": True, "reason": "x"}},
                   rows_by_doc={row["ID_NUM"]: row}, **KEY)
    with sessions() as db:
        notes = load_notes(db, **KEY)

    same = [dict(row)]
    apply_notes_to_rows(same, notes)
    assert same[0]["NOTE_STALE"] is False

    changed = [dict(row, SUSU=999)]
    apply_notes_to_rows(changed, notes)
    assert changed[0]["NOTE_STALE"] is True
    assert amount_fingerprint(changed[0]) != notes[row["ID_NUM"]]["amount_fingerprint"]


def test_model_is_registered_for_create_all():
    """app/models/__init__.py 등록이 곧 테이블 생성이다(scripts/create_tables.py)."""
    import app.models as models

    assert "WorkReportNote" in models.__all__
    assert models.WorkReportNote is WorkReportNote


def test_updated_by_name_uses_emp_name(sessions):
    """작성자 이름은 UserContextService._resolve 의 emp_name 키에서 온다.

    usr_nm/name 으로 찾으면 항상 비어서 '누가 적었는지'가 안 남는다(운영에서 실제로 겪음).
    """
    access = {"usr_seq": 2012, "usr_id": "wondongha", "emp_name": "원동하", "office_id": "10"}
    with sessions() as db:
        save_notes(db, basis="매출", notes={
            "01-2605-3-0011": {"excluded": True, "reason": "이름 기록"},
        }, user=access, **KEY)
    with sessions() as db:
        note = load_notes(db, **KEY)["01-2605-3-0011"]
    assert note["updated_by"] == 2012
    assert note["updated_by_name"] == "원동하"
