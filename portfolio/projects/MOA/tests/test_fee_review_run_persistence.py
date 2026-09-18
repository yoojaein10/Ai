from copy import deepcopy
from datetime import timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import mssql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateTable

import pytest

from app.services.fee_basis import FeeReviewRunRecord
from app.services import fee_basis as runs


@pytest.fixture
def sessions():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    FeeReviewRunRecord.__table__.create(engine)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    with runs._LOCK:
        runs._RUNS.clear()
        runs._LAST_MUTATION_AT = None
    try:
        yield factory
    finally:
        with runs._LOCK:
            runs._RUNS.clear()
            runs._LAST_MUTATION_AT = None
        engine.dispose()


def snapshot():
    return {
        "office_id": "10",
        "year": 2026,
        "month": 7,
        "half": "상반",
        "basis": "매출",
        "profile": "FINANCE_FEE_CHECK_V1",
        "summary": {"total": 1, "review_target": 1},
        "items": [{
            "source_row_number": 3,
            "doc_id": "01-2607-A-0001",
            "review_target": True,
            "existing_opinion": "",
            "suggested_opinion": "[추정] 컨설팅 업무 정황",
            "source_row_json": {"AB": ""},
        }],
    }


def two_row_snapshot():
    data = snapshot()
    second = deepcopy(data["items"][0])
    second.update({
        "source_row_number": 4,
        "doc_id": "01-2607-A-0002",
    })
    data["items"].append(second)
    data["summary"] = {"total": 2, "review_target": 2}
    return data


def test_persisted_run_survives_memory_cache_reset(sessions):
    with sessions() as db:
        run = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        assert run.persisted is True
        assert run.persistence_warning is None
        runs.update_decisions(
            run,
            opinions={"3": "담당자가 확인한 별도 계약 보수"},
            skipped={},
            accepted=[3],
            db=db,
        )
        run_id = run.run_id
        source_sha256 = run.source_sha256

    # 프로세스 재시작처럼 메모리 캐시를 비운 뒤 새 세션으로 복원한다.
    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        restored = runs.get_run(
            run_id, owner_usr_seq=901, office_code="10", db=db
        )
        assert restored.persisted is True
        assert restored.source_sha256 == source_sha256
        public = runs.public_data(restored)
        assert public["decision_state"] == {
            "opinions": {"3": "담당자가 확인한 별도 계약 보수"},
            "skipped": {},
            "accepted": [3],
        }
        assert public["decision_summary"]["pending"] == 0

        latest = runs.find_latest_run(
            owner_usr_seq=901,
            office_code="10",
            year=2026,
            month=7,
            half="상반",
            basis="매출",
            db=db,
        )
        assert latest.run_id == run_id

        exported, pending = runs.export_rows(restored, mode="final")
        assert pending == []
        assert exported[0]["source_row_json"]["AB"] == (
            "담당자가 확인한 별도 계약 보수"
        )


def test_prepared_snapshot_is_persisted_found_and_upserted(sessions):
    prepared = snapshot()
    prepared["prepared_at"] = "2026-07-29T01:00:00+00:00"

    with sessions() as db:
        first = runs.save_prepared_run(
            prepared, office_code="10", db=db
        )
        first_hash = first.source_sha256
        assert first.persisted is True
        assert first.owner_usr_seq == str(runs.PREPARED_OWNER_USR_SEQ)
        assert first.data["half"] == runs.PREPARED_HALF
        assert first.data["profile"] == runs.PREPARED_PROFILE

    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        restored = runs.find_prepared_run(
            office_code="10",
            year=2026,
            month=7,
            basis="매출",
            db=db,
        )
        assert restored.persisted is True
        assert restored.source_sha256 == first_hash
        assert restored.data["items"][0]["doc_id"] == "01-2607-A-0001"

        updated = snapshot()
        updated["prepared_at"] = "2026-07-29T02:00:00+00:00"
        updated["items"][0]["title"] = "갱신된 월 스냅숏"
        refreshed = runs.save_prepared_run(
            updated, office_code="10", db=db
        )

        count = db.scalar(select(func.count()).select_from(FeeReviewRunRecord))
        assert count == 1
        assert refreshed.run_id == restored.run_id
        assert refreshed.source_sha256 != first_hash
        assert refreshed.data["items"][0]["title"] == "갱신된 월 스냅숏"


def test_same_source_requery_restores_skipped_blank_after_restart(sessions):
    """의견 대상을 비울 때는 제외 사유가 함께 있어야 하고, 재시작 후에도 그대로 복원된다."""
    with sessions() as db:
        first = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        runs.update_decisions(
            first,
            opinions={"3": ""},
            skipped={"3": "타 지사 청구건으로 확인"},
            accepted=[],
            db=db,
        )
        first_id = first.run_id
        source_sha256 = first.source_sha256

    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        second = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        assert second.run_id != first_id
        assert second.source_sha256 == source_sha256
        assert second.opinions == {}
        assert second.skipped == {3: "타 지사 청구건으로 확인"}
        assert second.reused_from_run_id == first_id
        assert second.source_changed is False
        assert second.review_required is False

    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        restored = runs.get_run(
            second.run_id, owner_usr_seq=901, office_code="10", db=db
        )
        public = runs.public_data(restored)
        assert public["decision_state"]["opinions"] == {}
        assert public["decision_state"]["skipped"] == {
            "3": "타 지사 청구건으로 확인"
        }
        assert public["items"][0]["effective_opinion"] == ""
        # 제외 사유로 비운 행은 MANUAL이 아니라 SKIPPED로 남는다.
        assert public["items"][0]["effective_opinion_origin"] == "SKIPPED"
        assert public["items"][0]["source_row_json"]["AB"] == ""
        exported, pending = runs.export_rows(restored, mode="final")
        assert pending == []
        assert exported[0]["source_row_json"]["AB"] == ""


def test_late_save_on_older_same_source_run_is_reused(
    sessions, monkeypatch,
):
    with sessions() as db:
        first = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        second = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        assert second.created_at >= first.created_at
        assert second.opinions == {}

        # Two tabs queried the same source.  The older tab is saved after the
        # newer run was created, so updated_at—not created_at—must win.
        saved_at = second.updated_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: saved_at)
        runs.update_decisions(
            first,
            opinions={"3": "보수특약"},
            skipped={},
            accepted=[],
            db=db,
        )

        latest = runs.find_latest_run(
            owner_usr_seq=901,
            office_code="10",
            year=2026,
            month=7,
            half="상반",
            basis="매출",
            db=db,
        )
        assert latest.run_id == first.run_id

        third = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        assert third.reused_from_run_id == first.run_id
        assert third.opinions == {3: "보수특약"}
        assert runs.public_data(third)["items"][0]["source_row_json"]["AB"] == (
            "보수특약"
        )


def test_same_source_two_tab_partial_updates_are_merged(sessions):
    data = two_row_snapshot()
    with sessions() as db:
        tab_a = runs.create_run(
            data, owner_usr_seq=901, office_code="10", db=db
        )
        tab_b = runs.create_run(
            data, owner_usr_seq=901, office_code="10", db=db
        )

        runs.update_decisions(
            tab_a,
            opinions={"3": ""},
            skipped={"3": "타 지사 청구건으로 확인"},
            accepted=[],
            db=db,
        )
        runs.update_decisions(
            tab_b,
            opinions={"4": "임료감정"},
            skipped={},
            accepted=[],
            db=db,
        )

        assert tab_b.opinions == {4: "임료감정"}
        assert tab_b.skipped == {3: "타 지사 청구건으로 확인"}
        next_run = runs.create_run(
            data, owner_usr_seq=901, office_code="10", db=db
        )
        assert next_run.reused_from_run_id == tab_b.run_id
        assert next_run.opinions == {4: "임료감정"}
        assert next_run.skipped == {3: "타 지사 청구건으로 확인"}
        public = runs.public_data(next_run)
        assert [
            item["source_row_json"]["AB"] for item in public["items"]
        ] == ["", "임료감정"]


def test_mutation_timestamps_are_strict_when_clock_tick_is_equal(
    sessions, monkeypatch,
):
    fixed = runs._utcnow()
    monkeypatch.setattr(runs, "_utcnow", lambda: fixed)

    with sessions() as db:
        first = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        second = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        assert second.created_at > first.created_at

        runs.update_decisions(
            first,
            opinions={"3": "보수특약"},
            skipped={},
            accepted=[],
            db=db,
        )
        assert first.updated_at > second.updated_at
        latest = runs.find_latest_run(
            owner_usr_seq=901,
            office_code="10",
            year=2026,
            month=7,
            half="상반",
            basis="매출",
            db=db,
        )
        assert latest.run_id == first.run_id


def test_memory_fallback_uses_decision_update_time(monkeypatch):
    with runs._LOCK:
        runs._RUNS.clear()
        runs._LAST_MUTATION_AT = None
    try:
        first = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=None
        )
        second = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=None
        )
        saved_at = second.updated_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: saved_at)
        runs.update_decisions(
            first,
            opinions={"3": "보수특약"},
            skipped={},
            accepted=[],
            db=None,
        )

        third = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=None
        )

        assert third.reused_from_run_id == first.run_id
        assert third.opinions == {3: "보수특약"}
    finally:
        with runs._LOCK:
            runs._RUNS.clear()
            runs._LAST_MUTATION_AT = None


def test_changed_source_does_not_carry_decision_and_requires_review(sessions):
    with sessions() as db:
        first = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        runs.update_decisions(
            first,
            opinions={"3": "보수특약"},
            skipped={},
            accepted=[3],
            db=db,
        )
        first_sha256 = first.source_sha256

    changed = snapshot()
    changed["items"][0]["title"] = "원천에서 변경된 건명"
    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        second = runs.create_run(
            changed, owner_usr_seq=901, office_code="10", db=db
        )
        second_id = second.run_id
        assert second.source_sha256 != first_sha256
        assert second.opinions == {}
        assert second.accepted == set()
        assert second.source_changed is True
        assert second.review_required is True
        assert second.previous_source_sha256 == first_sha256
        assert second.reused_from_run_id is None
        public = runs.public_data(second)
        assert public["source_changed"] is True
        assert public["review_required"] is True
        assert public["previous_source_sha256"] == first_sha256
        assert public["items"][0]["effective_opinion"] == (
            "[추정] 컨설팅 업무 정황"
        )

    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        restored = runs.get_run(
            second_id, owner_usr_seq=901, office_code="10", db=db
        )
        assert restored.source_changed is True
        assert restored.review_required is True
        assert restored.opinions == {}
        runs.update_decisions(
            restored,
            opinions={"3": "담당자확인요청"},
            skipped={},
            accepted=[],
            db=db,
        )
        assert restored.source_changed is True
        assert restored.review_required is False

    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        reviewed = runs.get_run(
            second_id, owner_usr_seq=901, office_code="10", db=db
        )
        assert reviewed.source_changed is True
        assert reviewed.review_required is False
        assert reviewed.previous_source_sha256 == first_sha256
        assert reviewed.opinions == {3: "담당자확인요청"}


def test_stale_different_source_save_is_rejected_and_new_decision_survives(
    sessions, monkeypatch,
):
    source_v1 = snapshot()
    source_v2 = snapshot()
    source_v2["items"][0]["title"] = "변경된 최신 원천"

    with sessions() as db:
        old = runs.create_run(
            source_v1, owner_usr_seq=901, office_code="10", db=db
        )
        new_source_at = old.created_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: new_source_at)
        current = runs.create_run(
            source_v2, owner_usr_seq=901, office_code="10", db=db
        )
        assert current.source_changed is True
        assert current.review_required is True

        current_saved_at = new_source_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: current_saved_at)
        runs.update_decisions(
            current,
            opinions={"3": "임료감정"},
            skipped={},
            accepted=[],
            db=db,
        )
        assert current.review_required is False

        stale_save_at = current_saved_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: stale_save_at)
        with pytest.raises(runs.RunSourceChanged):
            runs.update_decisions(
                old,
                opinions={"3": "보수특약"},
                skipped={},
                accepted=[],
                db=db,
            )
        assert old.opinions == {}

        next_query_at = stale_save_at + timedelta(seconds=1)
        monkeypatch.setattr(runs, "_utcnow", lambda: next_query_at)
        next_run = runs.create_run(
            source_v2, owner_usr_seq=901, office_code="10", db=db
        )
        assert next_run.reused_from_run_id == current.run_id
        assert next_run.opinions == {3: "임료감정"}
        assert next_run.review_required is False
        assert runs.public_data(next_run)["items"][0]["source_row_json"]["AB"] == (
            "임료감정"
        )


def test_old_same_hash_epoch_cannot_resurrect_after_source_round_trip(
    sessions,
):
    source_a = snapshot()
    source_b = snapshot()
    source_b["items"][0]["title"] = "중간에 변경된 원천"

    with sessions() as db:
        old_epoch = runs.create_run(
            source_a, owner_usr_seq=901, office_code="10", db=db
        )
        runs.update_decisions(
            old_epoch,
            opinions={"3": "과거의견"},
            skipped={},
            accepted=[],
            db=db,
        )

        changed_epoch = runs.create_run(
            source_b, owner_usr_seq=901, office_code="10", db=db
        )
        assert changed_epoch.source_sha256 != old_epoch.source_sha256

        returned_epoch = runs.create_run(
            source_a, owner_usr_seq=901, office_code="10", db=db
        )
        assert returned_epoch.source_sha256 == old_epoch.source_sha256
        assert returned_epoch.opinions == {}
        assert returned_epoch.review_required is True

        with pytest.raises(runs.RunSourceChanged):
            runs.update_decisions(
                old_epoch,
                opinions={"3": "되살아나면 안 되는 과거의견"},
                skipped={},
                accepted=[],
                db=db,
            )

        runs.update_decisions(
            returned_epoch,
            opinions={"3": "현재 원천 재검토 의견"},
            skipped={},
            accepted=[],
            db=db,
        )
        next_run = runs.create_run(
            source_a, owner_usr_seq=901, office_code="10", db=db
        )
        assert next_run.reused_from_run_id == returned_epoch.run_id
        assert next_run.opinions == {3: "현재 원천 재검토 의견"}


def test_persisted_run_keeps_owner_and_office_scope(sessions):
    with sessions() as db:
        run = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        run_id = run.run_id
    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        with pytest.raises(runs.RunForbidden):
            runs.get_run(run_id, owner_usr_seq=902, db=db)
        with pytest.raises(runs.RunForbidden):
            runs.get_run(
                run_id, owner_usr_seq=901, office_code="11", db=db
            )


def test_corrupt_decision_json_is_reported_as_store_error(sessions):
    with sessions() as db:
        run = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        record = db.get(FeeReviewRunRecord, run.run_id)
        record.decisions_json = "[]"
        db.commit()
        run_id = run.run_id
    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        with pytest.raises(runs.RunStoreUnavailable):
            runs.get_run(run_id, owner_usr_seq=901, db=db)


def test_corrupt_snapshot_hash_is_reported_as_store_error(sessions):
    with sessions() as db:
        run = runs.create_run(
            snapshot(), owner_usr_seq=901, office_code="10", db=db
        )
        record = db.get(FeeReviewRunRecord, run.run_id)
        record.source_sha256 = "0" * 64
        db.commit()
        run_id = run.run_id
    with runs._LOCK:
        runs._RUNS.clear()

    with sessions() as db:
        with pytest.raises(runs.RunStoreUnavailable):
            runs.get_run(run_id, owner_usr_seq=901, db=db)


def test_sql_server_model_uses_max_and_datetime2_types():
    ddl = str(CreateTable(FeeReviewRunRecord.__table__).compile(
        dialect=mssql.dialect()
    )).upper()

    assert "SNAPSHOT_BLOB VARBINARY(MAX)" in ddl
    assert "DECISIONS_JSON NVARCHAR(MAX)" in ddl
    assert "EXPIRES_AT DATETIME2" in ddl
    assert "CK_A10_FEE_REVIEW_RUN_JSON" in ddl


def test_db_failure_is_fail_closed_by_default(monkeypatch):
    engine = create_engine("sqlite://")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(
        runs,
        "get_settings",
        lambda: type("Config", (), {
            "fee_review_allow_memory_fallback": False
        })(),
    )

    with factory() as db:
        with pytest.raises(runs.RunStoreUnavailable):
            runs.create_run(
                snapshot(), owner_usr_seq=901, office_code="10", db=db
            )
    engine.dispose()
