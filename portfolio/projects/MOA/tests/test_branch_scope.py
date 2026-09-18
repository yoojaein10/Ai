"""지사에 무엇이 열리고 무엇이 닫히나 — 2026-08-17 메뉴 19개 전수조사의 결론.

왜 있나
    사용자 요구: "본사 데이터만 취급하는 것들은 지사는 권한관리쪽에서 아예
    제외해줘." 19개를 라우터·서비스·SQL·화면까지 읽고, '본사 전용' 판정에는
    반증 단계를 따로 붙여(지사 자료가 실제로 있는지 운영 DB SELECT 로 확인)
    확정했다. 결과: **새로 뺄 것은 0건이었다** — 8개는 이미 지사 미노출이었다.

    그래서 이 시험의 일은 '고친 것을 지키는' 게 아니라 **확정된 경계를 못박는**
    것이다. 다음 사람이 무심코 SHARED 에 하나를 더하거나 빼면 여기서 깨진다.

판정의 근거는 '집계냐'가 아니라 '지사에 자료가 있느냐'다
    낡은 주석들이 "집계·통계는 본사 전용" 이라 적어 두었지만 사실이 아니다 —
    업무실적 보고는 지사마다 자기 MEMBERID 로 협회에 따로 제출하는 보고이고,
    기간별 매출실적은 division_code 로 갈려 18개 지사에 전부 자료가 있다.
    그 문장에 기대어 메뉴를 자르면 지사 직원의 정당한 접근이 끊긴다.

반제 2종·품질점검·엑셀대사가 본사 전용인 이유도 데이터가 아니다
    SQL 은 지사 파라미터화돼 있고 지사 전표도 실재한다. 본사 전용인 이유는
    **업무 소관이 본사 재무**이고 화면이 그렇게 막혀 있어서다. 훗날 열자는
    요구가 오면 서비스는 손댈 게 없다 — 그때 이 시험을 고치면 된다.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.services.access_policy import (
    BRANCH_FINANCE_MENU_KEYS,
    MENU_KEYS,
    PolicyIdentity,
    available_menu_keys,
)

# 2026-08-17 확정 — 지사에 열지 않는 8종.
HEAD_OFFICE_ONLY = {
    "salesInput",           # 배분 초안이 '01-'(본사) 감정서만 적재 — 실측 3,105/3,105
    "bonus",                # SQL 에 office 축이 없다. '01-%'·division 1000·본사 좌석표
    "cardVouchers",         # 본사 재무의 카드 전표 생성·전송
    "receivableReconcile",  # 업무 소관이 본사 재무(데이터는 지사에도 있다)
    "advanceReconcile",     # 〃
    "dataQuality",          # 〃
    "reconcile",            # 지사가 열면 403 OFFICE_SCOPE_DENIED
    "depositMatch",         # 통장 원장(CB2_ACCT_HIS)에 지사 열이 없다
}

# 지사 일반 직원에게 열리는 것. 전부 SQL 에 지사 축이 있고 실측으로 자료가 나온다.
BRANCH_SHARED = {
    "appraisals", "payments", "receivables", "allocation",
    "salesStats", "workReport", "permissionManage",
}

# 개인 지정된 지사 재무담당에게만 더 열리는 것.
BRANCH_FINANCE_EXTRA = {"feeBasis", "paymentSms"}

UNDECIDED = set()   # feeReview 는 2026-08-18 제거(화면 없는 유령 메뉴였다)

# 지사에는 안 열지만 '본사 데이터 전용'이라 부르면 안 되는 것.
# 실제 사유는 배정자 폴백 미구현이라 지사에서 실적이 0으로 나오는 것이다.
NOT_HQ_ONLY_BUT_CLOSED = {"mySales"}


def _identity(office_id: str, usr_seq: int = 999_999) -> PolicyIdentity:
    return PolicyIdentity(
        usr_seq=usr_seq, usr_id="x", emp_name="아무개", office_id=office_id,
        department_code=None, department_name="업무팀",
        employee_type="일반직원", is_appraiser=False,
    )


def test_분류가_메뉴_전체를_빠짐없이_덮는다():
    """새 메뉴가 생기면 여기서 걸린다 — 분류 없이 슬쩍 들어오지 못하게."""
    covered = (HEAD_OFFICE_ONLY | BRANCH_SHARED | BRANCH_FINANCE_EXTRA
               | UNDECIDED | NOT_HQ_ONLY_BUT_CLOSED)
    assert covered == set(MENU_KEYS), (
        f"분류 안 된 메뉴: {sorted(set(MENU_KEYS) - covered)} / "
        f"없는 메뉴를 분류함: {sorted(covered - set(MENU_KEYS))}"
    )


@pytest.mark.parametrize("key", sorted(HEAD_OFFICE_ONLY))
def test_본사_전용은_지사에_열리지_않는다(key):
    """열리면 지사 직원이 그 메뉴를 받을 수 있다 — 전수조사 결론이 무너진다."""
    assert key not in available_menu_keys(_identity("21"))


@pytest.mark.parametrize("key", sorted(BRANCH_SHARED))
def test_공통은_지사_일반직원에게도_열린다(key):
    """빼면 지사 직원의 정당한 접근이 끊긴다 — 실측으로 지사 자료를 확인한 것들."""
    assert key in available_menu_keys(_identity("21"))


def test_지사_재무_2종은_열려_있되_기본으로_켜지지_않는다():
    """2026-08-17 담당자 하드코딩(BRANCH_FINANCE_HOLDERS 18명)을 걷어내며 바뀐 계약.

    available 은 '구조적으로 가능한가'만 말한다 — 둘 다 전수조사에서 '본·지사
    공통'으로 확정됐으므로 지사 전원에게 연다(=붙일 수 있다). 실제로 누가 받을지는
    화면에서 '지사 재무담당' 묶음으로 정하고, 기본값은 꺼져 있다.
    이래야 담당자 교체가 배포 없이 화면에서 끝난다.
    """
    from app.services.access_policy import build_access_policy

    assert BRANCH_FINANCE_EXTRA <= set(BRANCH_FINANCE_MENU_KEYS)
    plain = _identity("21")
    assert BRANCH_FINANCE_EXTRA <= available_menu_keys(plain), "붙일 수조차 없다"
    # 클린 모델: 코드 기본값이 없어 묶음 없으면 0개 — 전 지사가 재무 화면을 받지 않는다.
    assert build_access_policy(plain, None)["menu_keys"] == [], "묶음 없으면 0개"


def test_본사에는_모두_열린다():
    """본사는 전 메뉴가 available 이고, 실제 on/off 는 기본값·묶음이 정한다."""
    assert set(MENU_KEYS) == available_menu_keys(_identity("10"))


# ── 화면이 서버와 같은 말을 하는가 ───────────────────────────────────────


def _preview_js() -> str:
    return (pathlib.Path("desktop/ui/permissions-preview.js")
            .read_text(encoding="utf-8"))


def test_화면이_지사_재무담당의_토글을_감추지_않는다():
    """서버는 주는데 화면이 감추면, 권한 담당자가 그 18명의 이 메뉴를 끄고 켤
    수가 없다 — 2026-08-17 전수조사가 잡은 실제 어긋남이다."""
    js = _preview_js()
    labels = dict(re.findall(r"\{key: '(\w+)'.*?access: '(\w+)'", js))
    for key in BRANCH_FINANCE_EXTRA:
        assert labels.get(key) == "financeOrBranchFinance", (
            f"{key} 가 {labels.get(key)} 로 분류돼 지사에서 토글이 사라진다")
    # 그 갈래는 지사에서도 available 이어야 한다.
    branch = js[js.index("if (item.access === 'financeOrBranchFinance')"):]
    branch = branch[:branch.index("}")]
    assert "available: true" in branch


@pytest.mark.parametrize("key", sorted(HEAD_OFFICE_ONLY))
def test_화면_분류도_본사_전용을_지사에_안_보여준다(key):
    """menuPolicy 는 서버 응답 전 fallback 이지만, 그 짧은 순간에도 본사 전용이
    지사 화면에 뜨면 안 된다."""
    js = _preview_js()
    labels = dict(re.findall(r"\{key: '(\w+)'.*?access: '(\w+)'", js))
    assert labels.get(key) in {
        "headOffice", "headOfficePrivileged", "headOfficeOperations", "financeOnly",
    }, f"{key} 가 {labels.get(key)} — 지사에 보인다"


def test_전사_기능은_본사만_실행한다():
    """permissionManage 는 지사에게도 열린다. 그런데 그 키로 열리는 것 중에는
    **전 지사 전표를 갈아엎는 배치**가 있었다 — 화면만 본사로 막고 API 는
    안 막아, 주소를 아는 사람에게 그대로 열려 있었다(2026-08-17 전수조사)."""
    src = pathlib.Path("app/routers/cache_admin.py").read_text(encoding="utf-8")
    assert src.count("_head_office_only(_access)") == 2, "캐시 동기화 두 곳이 본사로 안 막혔다"


def test_권한_조회도_자기_지사만_본다():
    """부여·회수는 지사 경계로 막혀 있는데 조회만 전사였다 — 잣대를 맞춘다."""
    src = pathlib.Path("app/routers/permissions.py").read_text(encoding="utf-8")
    head = src[src.index("def get_permissions"):src.index("def get_organization")]
    assert "_branch_member_usr_ids" in head
    emp = src[src.index("def get_employees"):src.index("def get_organization")]
    assert 'row.get("office_id")' in emp


def test_낡은_주석이_되살아나지_않는다():
    """'집계·통계·보수기준검토는 본사 전용, 재무 특례 없음' — 바로 아래 코드가
    스스로 부정하는 문장이었다. 이 말에 기대어 메뉴를 자르면 지사가 막힌다."""
    policy = pathlib.Path("app/services/access_policy.py").read_text(encoding="utf-8")
    assert "집계·통계·보수기준검토는 본사 전용" not in policy
    js = _preview_js()
    assert "집계·통계·보수기준검토는 본사 전용" not in js
