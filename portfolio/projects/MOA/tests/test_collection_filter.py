"""배분 수금 진행 — 감정서번호 검색조건 테스트."""

from datetime import date

from app.services.collection import collection_progress


class FakeResult:
    def mappings(self):
        return self

    def all(self):
        return []


class FakeDb:
    """실행된 SQL과 파라미터만 기록하는 가짜 세션."""

    def __init__(self):
        self.sql = ""
        self.params = {}

    def execute(self, statement, params):
        self.sql = str(statement)
        self.params = params
        return FakeResult()


def _run(**kwargs):
    db = FakeDb()
    collection_progress(db, date(2026, 1, 1), date(2026, 7, 29), **kwargs)
    return db


def test_without_doc_id_filters_by_send_date():
    db = _run()

    assert "m.SendDate BETWEEN :f AND :t" in db.sql
    assert "m.DocID LIKE" not in db.sql
    assert "doc" not in db.params


def test_doc_id_searches_all_periods():
    """번호로 찾을 때는 발송일 조건을 빼야 오래된 건도 나온다."""
    db = _run(doc_id="01-2607-3-2263")

    assert "m.DocID LIKE" in db.sql
    assert "m.SendDate BETWEEN" not in db.sql
    assert db.params["doc"] == "%01-2607-3-2263%"


def test_doc_id_is_cast_to_varchar():
    """varchar 컬럼에 NVARCHAR로 바인드하면 풀스캔이 된다."""
    db = _run(doc_id="01-2607")

    assert "CAST(:doc AS VARCHAR(50))" in db.sql


def test_blank_doc_id_keeps_date_filter():
    db = _run(doc_id="")

    assert "m.SendDate BETWEEN :f AND :t" in db.sql


def test_manager_filters_by_partial_name():
    """공동유치는 유치자가 '공(홍길동)'이라 이름만 넣어도 걸려야 한다."""
    db = _run(manager="조경미")

    assert "m.Manager LIKE CAST(:manager AS VARCHAR(50))" in db.sql
    assert db.params["manager"] == "%조경미%"


def test_manager_keeps_date_filter():
    """유치자는 기간을 좁혀 보는 조건이므로 발송일 조건이 남아야 한다."""
    db = _run(manager="조경미")

    assert "m.SendDate BETWEEN :f AND :t" in db.sql


def test_manager_absent_when_not_given():
    db = _run()

    assert "m.Manager LIKE" not in db.sql
    assert "manager" not in db.params


def test_doc_id_and_manager_combine():
    db = _run(doc_id="01-2607", manager="조경미")

    assert "m.DocID LIKE" in db.sql
    assert "m.Manager LIKE" in db.sql
    assert "m.SendDate BETWEEN" not in db.sql


def test_scope_person_forces_own_docs():
    """다른 직원 조회 권한이 없으면(view_other=OFF) 본인 유치/조사 건으로 고정한다."""
    db = _run(scope_person="홍길동")

    assert "(m.Manager LIKE :scope_person OR m.Charge LIKE :scope_person)" in db.sql
    assert db.params["scope_person"] == "%홍길동%"


def test_scope_person_absent_when_none():
    """조회 권한이 있으면(view_other=ON, scope_person=None) 개인범위 필터가 없다 — 전체를 본다."""
    db = _run()

    assert ":scope_person" not in db.sql
    assert "scope_person" not in db.params


def test_scope_person_combines_with_manager_search():
    """클라이언트 유치자 검색과 별개로 개인범위 AND 가 무조건 결합된다."""
    db = _run(manager="조경미", scope_person="홍길동")

    assert "m.Manager LIKE CAST(:manager AS VARCHAR(50))" in db.sql
    assert "(m.Manager LIKE :scope_person OR m.Charge LIKE :scope_person)" in db.sql
    assert db.params["manager"] == "%조경미%"
    assert db.params["scope_person"] == "%홍길동%"
