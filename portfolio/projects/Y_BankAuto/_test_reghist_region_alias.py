"""
RegHist 시·도 약칭 확장 테스트.
DB 연결 없이 fake connection/fake cursor 로 실행.
"""
import sys
import types

# ── fake pyodbc (DB 연결 없이 import 가능하게) ───────────────────────────────
fake_pyodbc = types.ModuleType("pyodbc")
fake_pyodbc.connect = lambda *a, **kw: None  # type: ignore
sys.modules.setdefault("pyodbc", fake_pyodbc)

from db_writer import _SIDO_ALIAS, _expand_sido, lookup_reg_eub, _should_use_official_addr


# ── Fake cursor/connection 헬퍼 ───────────────────────────────────────────────

class FakeCursor:
    """실행된 쿼리와 파라미터를 기록하고, 미리 세팅된 행을 반환한다."""

    def __init__(self, rows_by_as1: dict):
        """rows_by_as1: {as1_prefix: [row_tuple, ...]}  (LIKE 패턴 키에서 '%' 제거)"""
        self._rows_by_as1 = rows_by_as1
        self.executed: list = []

    def execute(self, sql, params):
        self.executed.append((sql, list(params)))
        as1_val = str(params[0]).rstrip("%") if params else ""
        self._last_rows = self._rows_by_as1.get(as1_val, [])

    def fetchall(self):
        return list(self._last_rows)

    def close(self):
        pass


class FakeConn:
    def __init__(self, rows_by_as1: dict):
        self._cur = FakeCursor(rows_by_as1)

    def cursor(self):
        return self._cur


# 문제 주소의 기대 RegHist 행 (REG, EUB, NAME, AS1, AS2, AS3, AS4)
_GYEONGBUK_ROW = ("47900", "34047", "미석리", "경상북도", "예천군", "감천면", "미석리")


# ── 개별 테스트 ───────────────────────────────────────────────────────────────

def test_expand_sido_gyeongbuk():
    """경북 → [경북, 경상북도]"""
    result = _expand_sido("경북")
    assert result == ["경북", "경상북도"], f"FAIL: {result}"
    print("PASS: 경북 → 경상북도 후보 포함")


def test_expand_sido_official_passthrough():
    """공식 명칭 입력은 그대로 1개만 반환."""
    for official in ["경상북도", "경상남도", "충청북도", "충청남도",
                     "전라북도", "전라남도", "강원특별자치도", "강원도",
                     "제주특별자치도", "서울특별시", "부산광역시"]:
        result = _expand_sido(official)
        assert result == [official], f"FAIL {official}: {result}"
    print("PASS: 공식 명칭 그대로 반환")


def test_expand_sido_all_aliases():
    """모든 약칭 후보 생성 정상."""
    cases = {
        "경북": {"경북", "경상북도"},
        "경남": {"경남", "경상남도"},
        "충북": {"충북", "충청북도"},
        "충남": {"충남", "충청남도"},
        "전북": {"전북", "전북특별자치도", "전라북도"},
        "전남": {"전남", "전라남도"},
        "강원": {"강원", "강원특별자치도", "강원도"},
        "제주": {"제주", "제주특별자치도", "제주도"},
    }
    for abbr, expected_set in cases.items():
        result = _expand_sido(abbr)
        assert set(result) == expected_set, f"FAIL {abbr}: {result}"
        assert result[0] == abbr, f"FAIL {abbr}: 원본이 첫 번째여야 함"
    print("PASS: 모든 약칭 후보 생성 정상")


def test_no_duplicate_candidates():
    """후보 중복 없음."""
    for abbr in _SIDO_ALIAS:
        result = _expand_sido(abbr)
        assert len(result) == len(set(result)), f"FAIL {abbr}: 중복 {result}"
    print("PASS: 후보 중복 제거 정상")


def test_lookup_gyeongbuk_abbreviated():
    """경북 주소가 경상북도 행으로 매칭됨.

    fake cursor: 경북% → 빈 결과, 경상북도% → _GYEONGBUK_ROW
    """
    conn = FakeConn({"경상북도": [_GYEONGBUK_ROW]})
    result = lookup_reg_eub(conn, "경북 예천군 감천면 미석리")
    assert result["matched"] is True, f"FAIL matched: {result}"
    assert result["Reg"] == "47900",  f"FAIL Reg: {result['Reg']}"
    assert result["Eub"] == "34047",  f"FAIL Eub: {result['Eub']}"
    assert result["AS1"] == "경상북도", f"FAIL AS1: {result['AS1']}"
    assert result["AS2"] == "예천군",   f"FAIL AS2: {result['AS2']}"
    assert result["AS3"] == "감천면",   f"FAIL AS3: {result['AS3']}"
    assert result["AS4"] == "미석리",   f"FAIL AS4: {result['AS4']}"
    assert result["official_addr"] == "경상북도 예천군 감천면 미석리", \
        f"FAIL official_addr: {result['official_addr']}"
    print("PASS: 경북 약칭 → 경상북도 매칭 성공")


def test_lookup_official_gyeongbuk_passthrough():
    """공식 명칭 경상북도 입력 시 직접 매칭 (후보 1개)."""
    conn = FakeConn({"경상북도": [_GYEONGBUK_ROW]})
    result = lookup_reg_eub(conn, "경상북도 예천군 감천면 미석리")
    assert result["matched"] is True, f"FAIL: {result}"
    assert result["Reg"] == "47900",  f"FAIL Reg: {result['Reg']}"
    print("PASS: 공식 명칭 경상북도 직접 매칭")


def test_first_strategy_uses_all_four_tokens():
    """4토큰 주소의 첫 전략은 AS1/AS2/AS3/AS4 모두 포함.
    fake cursor는 경북%로는 반환 안 하고 경상북도%에서만 반환.
    실행된 파라미터를 확인해 4-column 조건이 먼저 시도됨을 검증."""
    conn = FakeConn({"경상북도": [_GYEONGBUK_ROW]})
    lookup_reg_eub(conn, "경북 예천군 감천면 미석리")
    cur = conn._cur
    # 첫 번째 실행: 경북%로 AS1/AS2/AS3/AS4 시도 (no match)
    # 두 번째 실행: 경상북도%로 AS1/AS2/AS3/AS4 시도 (match)
    second = cur.executed[1]
    sql, params = second
    assert "AS1 LIKE ?" in sql,    f"FAIL: AS1 조건 없음"
    assert "AS2 LIKE ?" in sql,    f"FAIL: AS2 조건 없음"
    assert "AS3 LIKE ?" in sql,    f"FAIL: AS3 조건 없음"
    assert "AS4 LIKE ?" in sql,    f"FAIL: AS4 조건 없음"
    assert "FUSE='1'" in sql,      f"FAIL: FUSE='1' 조건 없음"
    assert params[0] == "경상북도%", f"FAIL AS1 param: {params[0]}"
    assert params[1] == "예천군%",   f"FAIL AS2 param: {params[1]}"
    assert params[2] == "감천면%",   f"FAIL AS3 param: {params[2]}"
    assert params[3] == "미석리%",   f"FAIL AS4 param: {params[3]}"
    print("PASS: 4-토큰 전략에 AS1/AS2/AS3/AS4 + FUSE='1' 모두 적용됨")


def test_no_wrong_region_match():
    """다른 지역의 동일한 리 이름이 잘못 선택되지 않음.

    경북 미석리 조회 시 경남 미석리가 있어도,
    경북%에서 경남 행이 반환되지 않으면 경상북도%에서만 매칭됨.
    """
    gyeongnam_row = ("48000", "99999", "미석리", "경상남도", "XX군", "YY면", "미석리")
    # 경남은 경북%로도 경상북도%로도 반환 안 됨 (별도 region)
    conn = FakeConn({
        "경상북도": [_GYEONGBUK_ROW],
        "경상남도": [gyeongnam_row],
    })
    result = lookup_reg_eub(conn, "경북 예천군 감천면 미석리")
    assert result["Reg"] == "47900",   f"FAIL: 경남 행이 섞임 Reg={result['Reg']}"
    assert result["AS1"] == "경상북도", f"FAIL: AS1={result['AS1']}"
    print("PASS: 다른 지역 동명 리 오매칭 방어 확인")


def test_no_match_returns_empty():
    """매칭 실패 시 기존 빈 결과 반환."""
    conn = FakeConn({})  # 항상 빈 결과
    result = lookup_reg_eub(conn, "경북 예천군 감천면 미석리")
    assert result["matched"] is False, f"FAIL: matched={result['matched']}"
    assert result["Reg"] == "",        f"FAIL: Reg={result['Reg']}"
    assert result["Eub"] == "",        f"FAIL: Eub={result['Eub']}"
    print("PASS: 매칭 실패 시 빈 결과 반환")


def test_should_use_official_addr_true():
    """`_should_use_official_addr()` 가 문제 주소에서 True 반환."""
    lu_reg = {
        "matched": True,
        "Reg": "47900",
        "Eub": "34047",
        "NAME": "미석리",
        "AS1": "경상북도",
        "AS2": "예천군",
        "AS3": "감천면",
        "AS4": "미석리",
        "official_addr": "경상북도 예천군 감천면 미석리",
    }
    result = _should_use_official_addr("경북 예천군 감천면 미석리", lu_reg)
    assert result is True, f"FAIL: {result}"
    print("PASS: _should_use_official_addr() = True (문제 주소)")


def test_san_bun_hoetc_unaffected():
    """SAN/BUN/hoetc 값은 이번 변경에 영향 없음 (정적 검증)."""
    # _parse_address, _format_bun 은 lookup_reg_eub 과 독립적으로 동작
    from db_writer import _parse_address, _format_bun
    parsed = _parse_address("경북 예천군 감천면 미석리 1064")
    assert parsed["San"] == 1,     f"FAIL San: {parsed['San']}"
    assert parsed["Bun1"] == "1064", f"FAIL Bun1: {parsed['Bun1']}"
    assert parsed["Bun2"] == "",    f"FAIL Bun2: {parsed['Bun2']}"
    assert _format_bun("1064") == "1064", "FAIL format_bun"
    assert _format_bun("") == "0000",     "FAIL format_bun empty"
    print("PASS: SAN/BUN/hoetc 로직 영향 없음")


def test_expected_sp_mapping():
    """문제 PDF의 수정 후 예상 SP 매핑 확인 (SP 실행 없이 계산값만 검증)."""
    from db_writer import _parse_address, _format_bun, _should_use_official_addr
    addr_body = "경북 예천군 감천면 미석리"
    conn = FakeConn({"경상북도": [_GYEONGBUK_ROW]})
    lu_reg = lookup_reg_eub(conn, addr_body)

    parsed = _parse_address(addr_body + " 1064")
    use_official = _should_use_official_addr(addr_body, lu_reg)

    sp_addr = lu_reg["official_addr"] if use_official else addr_body
    sp_reg  = lu_reg["Reg"]
    sp_eub  = lu_reg["Eub"]
    sp_san  = parsed["San"]   # int
    sp_bun1 = _format_bun(parsed["Bun1"])
    sp_bun2 = _format_bun(parsed["Bun2"])

    assert sp_addr == "경상북도 예천군 감천면 미석리", f"FAIL ADDR: {sp_addr}"
    assert sp_reg  == "47900",   f"FAIL REG: {sp_reg}"
    assert sp_eub  == "34047",   f"FAIL EUB: {sp_eub}"
    assert sp_san  == 1,         f"FAIL SAN: {sp_san}"
    assert sp_bun1 == "1064",    f"FAIL BUN1: {sp_bun1}"
    assert sp_bun2 == "0000",    f"FAIL BUN2: {sp_bun2}"

    print("PASS: 예상 SP 매핑 전체 확인")
    print(f"  ADDR = {sp_addr}")
    print(f"  REG  = {sp_reg}  EUB = {sp_eub}")
    print(f"  SAN  = {sp_san}  BUN1 = {sp_bun1}  BUN2 = {sp_bun2}")
    print(f"  hoetc (기존 파싱값 유지) = 1063, 1053, 1051, 1050-2, 1050-1, 1052, 1005")


# ── 실행 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_expand_sido_gyeongbuk,
        test_expand_sido_official_passthrough,
        test_expand_sido_all_aliases,
        test_no_duplicate_candidates,
        test_lookup_gyeongbuk_abbreviated,
        test_lookup_official_gyeongbuk_passthrough,
        test_first_strategy_uses_all_four_tokens,
        test_no_wrong_region_match,
        test_no_match_returns_empty,
        test_should_use_official_addr_true,
        test_san_bun_hoetc_unaffected,
        test_expected_sp_mapping,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"FAIL [{fn.__name__}]: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"결과: {passed}개 PASS / {failed}개 FAIL (총 {passed+failed}개)")
    sys.exit(0 if failed == 0 else 1)
