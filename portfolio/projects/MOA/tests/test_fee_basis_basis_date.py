"""기준시점 보강 — 소급 할증(코드 2)이 조용히 빠지던 두 원인을 고정한다.

1) JUN 이 감정서번호를 소문자로 저장한 건(실측 772건, 상속 B계열 등)에서
   본문·기준시점이 통째로 유실됐다. DB 콜레이션은 대소문자를 무시하는데
   돌려받은 표기를 그대로 dict 키로 써서 호출자가 못 찾았다.
2) extracted_data_json 의 AppraisalDate 가 비면 기준시점이 없어 판정이 빠졌다.
   산출근거 본문에는 적혀 있다.
"""

from datetime import date

import pytest

from app.services import fee_basis


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeConnection:
    """document_version / page / chunk 세 질의에만 답하는 최소 스텁."""

    def __init__(self, *, versions, pages, chunks):
        self.versions, self.pages, self.chunks = versions, pages, chunks

    def execute(self, statement, params=None):
        sql = str(statement)
        if "jun.document_version" in sql:
            wanted = {str(v).casefold() for v in (params or {}).values()}
            return _FakeResult([
                row for row in self.versions if str(row[0]).casefold() in wanted
            ])
        wanted_ids = set((params or {}).values())
        if "jun.page" in sql:
            return _FakeResult([r for r in self.pages if r[0] in wanted_ids])
        if "jun.chunk" in sql:
            return _FakeResult([r for r in self.chunks if r[0] in wanted_ids])
        raise AssertionError(f"예상치 못한 질의: {sql[:80]}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn


@pytest.fixture
def patched_engine(monkeypatch):
    def install(conn):
        monkeypatch.setattr(
            fee_basis, "get_gamjun_parse_engine", lambda: _FakeEngine(conn)
        )
    return install


def test_lowercase_appraisal_number_still_matches_the_requested_doc_id(patched_engine):
    """JUN 이 '01-2509-b-0044' 로 저장해도 호출자는 대문자로 찾는다."""
    conn = _FakeConnection(
        versions=[("01-2509-b-0044", 11821, "2024년 12월 22일")],
        pages=[(11821, 1, "본문")],
        chunks=[],
    )
    patched_engine(conn)

    signals = fee_basis._parsed_signals(["01-2509-B-0044"])

    assert "01-2509-B-0044" in signals
    assert signals["01-2509-B-0044"]["appraisal_date"] == date(2024, 12, 22)
    assert signals["01-2509-B-0044"]["pages"] == [(1, "본문")]


def test_basis_date_is_recovered_from_the_calculation_basis_text(patched_engine):
    """AppraisalDate 가 비어도 산출근거 본문에서 기준시점을 되찾는다."""
    conn = _FakeConnection(
        versions=[("01-2512-b-0064", 11929, None)],
        pages=[(11929, 1, "본문")],
        chunks=[(
            11929,
            "3. 기준시점 결정 및 그 이유 기준시점은 귀 제시일을 기준한 "
            "2024년 12월 28일임. 4. 실지조사 실시기간 및 내용 대상물건에 대한 "
            "실지조사 실시기간은 2026년 03월 25일임.",
        )],
    )
    patched_engine(conn)

    signals = fee_basis._parsed_signals(["01-2512-B-0064"])

    assert signals["01-2512-B-0064"]["appraisal_date"] == date(2024, 12, 28)


def test_recovery_does_not_run_when_the_date_was_already_read(patched_engine):
    """이미 읽은 기준시점을 본문값으로 덮으면 안 된다."""
    conn = _FakeConnection(
        versions=[("01-2512-b-0064", 11929, "2025년 1월 5일")],
        pages=[],
        chunks=[(11929, "기준시점은 2024년 12월 28일임.")],
    )
    patched_engine(conn)

    signals = fee_basis._parsed_signals(["01-2512-B-0064"])

    assert signals["01-2512-B-0064"]["appraisal_date"] == date(2025, 1, 5)


def test_investigation_period_is_not_mistaken_for_the_valuation_date():
    """기준시점 날짜가 깨져 있으면 뒤따르는 실지조사일을 주워오면 안 된다."""
    broken = (
        "3. 기준시점 결정 및 그 이유 가격조사를 완료한 날짜 20266 3월300 임, "
        "4. 실지조사 실시기간 대상물건에 대한 실지조사 실시기간은 2026년 3월 30일임."
    )

    assert fee_basis._basis_date_in_text(broken) is None


def test_valuation_date_formats_that_appear_in_real_reports():
    assert fee_basis._basis_date_in_text(
        "기준시점은 귀 제시일을 기준한 2024년 12월 22일임.(상속개시일)"
    ) == date(2024, 12, 22)
    assert fee_basis._basis_date_in_text(
        "본건의 기준시점은 「감정평가에 관한 규칙」 제9조 제2항에 의거 "
        "가격조사를 완료한 날짜인 2026.03.09 임."
    ) == date(2026, 3, 9)
    assert fee_basis._basis_date_in_text(
        "대상물건의 기준시점은 귀 측에서 제시한 2025-04-18 임"
    ) == date(2025, 4, 18)
    # 연도가 상식 밖이면 파싱 오류로 보고 버린다.
    assert fee_basis._basis_date_in_text(
        "기준시점은 귀 제시일인 1978년 5월 3일임"
    ) is None
    assert fee_basis._basis_date_in_text("기준시점을 정하지 못했다") is None
    # 문장이라는 근거가 없으면 채택하지 않는다 — 표 머리글일 수 있다.
    assert fee_basis._basis_date_in_text("기 준 시 점 2026.03.09") is None


def test_valuation_date_is_not_taken_from_a_precedent_table():
    """'기준시점'은 유사 물건 평가선례 표의 열 제목으로도 나온다 — 남의 감정 날짜다.

    실측 01-2603-3-0800: 진짜 기준시점은 2026-03-13 인데 OCR 이 '20266 3월 13일' 로
    깨뜨려 정규식이 실패했고, 17쪽 선례표의 2023-07-27 을 주워 32개월 소급이 됐다.
    """
    precedent = (
        "2.2. 유사 물건의 평가선례 소재지 전유면적 기준시점 감정평가액(원) "
        "화정동 970-2 2023.07.27 1,507,000,000 선례1"
    )

    assert fee_basis._basis_date_in_text(precedent) is None


def test_broken_ocr_falls_back_to_nothing_not_to_a_table():
    """진짜 문장이 깨졌을 때 뒤따르는 표를 대신 주워오면 안 된다."""
    blob = (
        "3. 기준시점 결정 및 그 이유 기준시점은 가격조사를 완료한 날짜인 20266 3월 13일 "
        "…… 2.2. 유사 물건의 평가선례 소재지 기준시점 감정평가액(원) "
        "화정동 970-2 2023.07.27 1,507,000,000"
    )

    assert fee_basis._basis_date_in_text(blob) is None
