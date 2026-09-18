"""권한 배선이 상류 병합에서 유실되지 않게 잠근다.

왜 필요한가
  이 브랜치는 화면 메뉴 숨김을 `hq-only` 클래스에서 `menuKeyForUrl` 매핑 방식으로
  바꿨다. 매핑을 빠뜨리면 그 메뉴는 **전원에게 노출된다**(실측: /desktop/fee-basis 가
  지사 일반직원까지 보였고, 메뉴 0개 사용자는 그 화면으로 튕겼다).
  상류(main)가 새 화면을 추가하면 side-nav 링크만 늘고 매핑은 안 늘어난다.
  그래서 병합할 때마다 사람이 확인해야 하는데, 그건 언젠가 빠뜨린다 — 테스트로 잡는다.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.access_policy import MENU_KEYS

UI = Path(__file__).resolve().parent.parent / "desktop" / "ui"
ROUTERS = Path(__file__).resolve().parent.parent / "app" / "routers"
CONTEXT_JS = (UI / "context.js").read_text(encoding="utf-8")


def _menu_key_block() -> str:
    match = re.search(r"const menuKeyForUrl[\s\S]*?\n  \};", CONTEXT_JS)
    assert match, "context.js 에서 menuKeyForUrl 을 찾지 못했다"
    return match.group(0)


def _mapped_paths() -> "set[str]":
    block = _menu_key_block()
    paths = set(re.findall(r"'(/desktop[^']*)'\s*:\s*'\w+'", block))
    # url.pathname === '...' 형태로 따로 처리하는 화면(감정서 LIST, 입금/미수금)
    paths |= set(re.findall(r"url\.pathname === '(/desktop[^']*)'", block))
    return paths


def _nav_links() -> "set[str]":
    """메뉴 링크 전부. 두 곳을 함께 본다.

    2026-08-08 메뉴 통합 전에는 16개 화면 HTML 이 저마다 side-nav 를 품었다.
    지금은 context.js 의 A10_MENU 한 곳에서 그린다. HTML 만 읽으면 이 테스트가
    **아무것도 안 보고 조용히 통과한다** — 그래서 둘 다 읽는다. 남은 HTML 링크가
    있다면 그것도 여전히 사람에게 보이므로 함께 검사해야 한다.
    """
    links: "set[str]" = set()
    for html in UI.glob("*.html"):
        text = html.read_text(encoding="utf-8")
        for match in re.finditer(r'<a\s[^>]*href="(/desktop[^"]*)"', text):
            links.add(match.group(1).split("?")[0])
    menu = CONTEXT_JS[
        CONTEXT_JS.index("const A10_MENU"):CONTEXT_JS.index("function a10MenuActive")
    ]
    for href in re.findall(r"href: '(/desktop[^']*)'", menu):
        links.add(href.split("?")[0])
    assert links, "메뉴 링크를 한 개도 못 찾았다 — 이 테스트가 헛돌고 있다"
    return links


def test_every_desktop_menu_link_has_a_menu_key():
    """side-nav 링크가 늘면 매핑도 같이 늘어야 한다.

    상류가 화면을 추가하면 여기서 먼저 깨진다 — 그때 context.js 매핑과
    access_policy.MENU_KEYS 를 함께 채워라.
    """
    unmapped = sorted(_nav_links() - _mapped_paths())

    assert not unmapped, (
        "메뉴 링크에 대응하는 menuKeyForUrl 매핑이 없다. 매핑이 없으면 그 메뉴는 "
        f"권한과 무관하게 노출된다: {unmapped}"
    )


def test_menu_hiding_is_fail_closed():
    """매핑이 없으면 숨겨야 한다. `if(key && ...)` 로 되돌리면 안 된다."""
    assert "if(!key || !window.A10_CAN(key))" in CONTEXT_JS, (
        "메뉴 숨김이 fail-open 으로 되돌아갔다. 매핑을 빠뜨린 메뉴가 전원에게 보인다."
    )
    assert "if(!currentMenuKey || !window.A10_CAN(currentMenuKey))" in CONTEXT_JS, (
        "화면 진입 차단이 fail-open 으로 되돌아갔다."
    )


def test_client_menu_keys_exist_on_the_server():
    """서버에 없는 키를 쓰면 A10_CAN 이 늘 false 라 모두에게 숨는다."""
    block = _menu_key_block()
    used = set(re.findall(r":\s*'(\w+)'", block)) | set(
        re.findall(r"return '(\w+)'", block)
    )
    unknown = sorted(used - set(MENU_KEYS))

    assert not unknown, f"context.js 가 서버 MENU_KEYS 에 없는 키를 쓴다: {unknown}"


@pytest.mark.parametrize(
    "router, needle",
    [
        # 상류가 이 라우터들을 고치면서 가드를 지우면 여기서 깨진다.
        ("payment_sms.py", 'require_menu_access(access, "paymentSms")'),
        ("payment_sms.py", "resolve_office_scope(access, office_code)"),
        ("card_vouchers.py", '.get("cardVouchers", False)'),
        ("fee_basis.py", "FEE_BASIS_MENU_KEY"),
        ("fee_basis.py", "_scoped_office(_access, office_code)"),
        ("my_sales.py", "require_menu_access(user, MENU_KEY)"),
    ],
)
def test_router_guard_survives(router: str, needle: str):
    source = (ROUTERS / router).read_text(encoding="utf-8")

    assert needle in source, f"{router} 의 권한 가드가 사라졌다: {needle}"


def test_our_menu_keys_are_registered():
    """이 브랜치가 추가한 메뉴 키. 상류 병합에서 빠지면 화면이 통째로 숨는다."""
    for key in ("paymentSms", "cardVouchers", "feeBasis", "mySales",
                "depositMatch"):
        assert key in MENU_KEYS, f"MENU_KEYS 에서 {key} 가 사라졌다"


def test_target_parameter_does_not_shadow_the_auth_query():
    """조회 대상 파라미터가 `usr_seq` 면 인증용 쿼리와 겹쳐 호출자 신원이 바뀐다.

    실측: 평가사가 남의 실적을 200 으로 받았다.
    """
    source = (ROUTERS / "my_sales.py").read_text(encoding="utf-8")

    assert not re.search(r"^\s*usr_seq:\s*Annotated", source, re.M), (
        "my_sales 가 usr_seq 를 쿼리 파라미터로 받으면 인증 파라미터와 충돌한다"
    )
    # 2026-08-08: 조회 대상을 `emp_name` 으로 받는 구현으로 합쳤다. 이름은 인증
    # 파라미터와 겹치지 않아 신원이 바뀔 수 없다. 대신 서버가 요청 이름을 그대로
    # 믿으면 안 되므로, 권한 없는 사람은 세션 값으로 덮어쓰는지를 본다.
    scope = source[source.index("def _resolve_scope("):source.index("@router.get(")]
    assert "if not allowed:" in scope and 'user["emp_name"]' in scope, (
        "남을 볼 권한이 없으면 요청 이름을 세션 이름으로 덮어써야 한다"
    )

# ── 2026-08-07 전수 점검에서 찾은 구멍들 ──────────────────────────────


def test_work_report_notes_read_is_guarded_too():
    """저장(PATCH)만 막고 읽기(GET)를 열어 두면 반쪽이다.

    점검 시점에 GET /notes 는 가드가 아예 없어 usr_seq 없이도 office_code 만
    바꿔 남의 지사 기재사항을 읽을 수 있었다.
    """
    source = (ROUTERS / "work_report.py").read_text(encoding="utf-8")
    block = source[source.index('@router.get("/notes"'):source.index('@router.patch("/notes"')]
    assert 'require_menu("workReport")' in block, "읽기도 막아야 한다"
    assert "resolve_office_scope(access, office_code)" in block, (
        "office_code 를 그대로 믿으면 남의 지사를 읽는다")


def test_work_report_import_needs_a_user():
    """인증 없는 파일 업로드는 열어 둘 이유가 없다."""
    source = (ROUTERS / "work_report.py").read_text(encoding="utf-8")
    block = source[source.index('@router.post("/import"'):source.index("@router.get(")]
    assert 'require_menu("workReport")' in block


def test_deposit_match_api_checks_the_menu_key():
    """화면은 메뉴를 숨기지만 주소를 아는 사람은 API 를 그냥 부를 수 있었다.

    데이터를 내려주는 엔드포인트가 모두 _office_of 를 거치므로 거기 한 곳에서
    막는다. /health 는 준비 상태만 알려주므로 거치지 않는다.
    """
    source = (ROUTERS / "gamjun_chat.py").read_text(encoding="utf-8")
    assert 'MENU_KEY = "depositMatch"' in source
    block = source[source.index("async def _office_of("):source.index('@router.get("/health"')]
    assert "can_menu(usr_seq, MENU_KEY)" in block, "_office_of 에서 메뉴를 봐야 한다"
    assert "return None" in block, "권한이 없으면 조회를 거부한다"
    # 화면 매핑과 같은 키여야 한다
    assert "'/desktop/gamjun-chat': 'depositMatch'" in CONTEXT_JS


def test_the_last_permission_manager_cannot_be_removed():
    """permissionManage 는 어느 기본값에도 없다(fail-closed 라 옳다).

    그래서 이 권한은 DB 예외로만 존재하고, 점검 시점 보유자는 한 명뿐이었다.
    그 한 행을 끄면 권한관리 화면에 들어갈 사람이 0명이 되어 SQL 을 직접
    고치는 수밖에 없다. 그 자물쇠를 막는다.
    """
    source = (Path(__file__).resolve().parent.parent
              / "app" / "services" / "permissions.py").read_text(encoding="utf-8")
    assert "def _guard_last_permission_manager(" in source
    assert "_guard_last_permission_manager(" in source.split(
        "def save_access_policy(")[1], "저장 경로에서 반드시 불러야 한다"
    assert "마지막 권한관리자입니다" in source

    # 코드 기본값 상수(APPRAISER_DEFAULT·HEAD_OFFICE_EXECUTIVE)는 2026-08-18 제거됐다.
    # 남은 건 available_menu_keys 가 쓰는 **상한** 상수뿐 — 여기에도 권한관리가 없어야
    # 한다(available_menu_keys 가 permissionManage 를 따로 붙이지, 상수엔 없다).
    from app.services.access_policy import (
        HEAD_OFFICE_FINANCE_MENU_KEYS, HEAD_OFFICE_MENU_KEYS,
        HEAD_OFFICE_PRIVILEGED_MENU_KEYS, SHARED_MENU_KEYS,
    )
    everywhere = (SHARED_MENU_KEYS | HEAD_OFFICE_MENU_KEYS
                  | HEAD_OFFICE_PRIVILEGED_MENU_KEYS | HEAD_OFFICE_FINANCE_MENU_KEYS)
    assert "permissionManage" not in everywhere, (
        "권한관리를 상한 상수에 두면 안 된다 — available_menu_keys 가 따로 붙인다")


def test_api_docs_are_off_unless_explicitly_enabled():
    """운영에서 /docs·/redoc·/openapi.json 은 닫혀 있어야 한다.

    사용자는 exe 로 열어서 주소창을 볼 일이 없지만, 사내망에서 주소를 직접 치면
    서버는 그대로 응답한다. 그때 API 문서가 열려 있으면 전체 엔드포인트와
    파라미터를 통째로 보여 주는 셈이라, 남은 위험을 정확히 키운다.
    """
    from app.config import Settings

    assert Settings().enable_api_docs is False

    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_a_user_with_no_menus_is_refused_at_launch():
    """메뉴가 하나도 없으면 빈 화면이 아니라 분명한 거절이어야 한다.

    종전 허용명단 방식은 실행 시점에 ACCESS_DENIED 를 냈다. 메뉴 권한 방식으로
    바꾸면서 그 관문이 사라지면, 권한 없는 사람이 아무것도 없는 화면을 받는다.
    빈 화면은 고장으로 읽혀서 문의가 전산으로 온다.
    """
    source = Path("app/services/users.py").read_text(encoding="utf-8")
    guard = source[source.index('if not policy["menu_keys"]:'):]
    assert "ACCESS_DENIED" in guard[:600]
    assert "이 프로그램 사용 권한이 없습니다" in guard[:600]


def test_세금계산서_라우터에_관문_없는_구멍이_없다():
    """2026-08-13 병합에서 실제로 세 개가 뚫려 있었다.

    · POST /cancel · POST /cashbill/cancel — main 이 새로 가져온 라우트다. 그쪽
      브랜치엔 권한 체계가 없으니 관문 없이 들어왔고, 그대로 두면 **되돌릴 수 없는
      발급 취소를 감정서번호만 알면 누구나** 부를 수 있었다.
    · POST /register-customer — 병합과 무관하게 처음부터 없었다. 거래처를 만드는
      쓰기인데 짝인 update-customer 는 이미 관문을 쓰고 있었다.

    이 라우터는 **예외 없이 전부** appraisals 메뉴를 요구한다. 상류가 라우트를
    더할 때마다 이 시험이 먼저 깨지게 해서, 사람이 눈으로 세지 않아도 되게 한다.
    """
    import ast

    source = (ROUTERS / "taxinvoice.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    holes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = None
        for deco in node.decorator_list:
            if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ("get", "post", "put", "delete", "patch")):
                route = f"{deco.func.attr.upper()} {deco.args[0].value if deco.args else ''}"
        if route is None:
            continue
        defaults = [d for d in (*node.args.defaults, *node.args.kw_defaults) if d]
        segments = [ast.get_source_segment(source, d) or "" for d in defaults]
        if not any("require_menu" in s for s in segments):
            holes.append(route)
    assert holes == [], f"관문이 없는 엔드포인트: {holes}"

    # 취소 두 개는 '그 감정서를 볼 수 있는가'까지 본다 — 발급(issue)과 같은 잣대다.
    for name in ("def tax_cancel(", "def cashbill_cancel("):
        body = source[source.index(name):]
        body = body[: body.index("\n@router")] if "\n@router" in body else body
        assert "assert_document_access(db, request.doc_id, access)" in body, name

    # 인쇄·팩스도 doc_id 를 받는다 — 메뉴 관문(appraisals)은 지사도 가지므로, 소속
    # 문서인지까지 봐야 지사가 본사 세금계산서를 열람/팩스하지 못한다(2026-08-19 감사).
    for name, needle in (
        ("def print_url(", "assert_document_access(db, doc_id, access)"),
        ("def send_fax(", "assert_document_access(db, request.doc_id.strip(), access)"),
    ):
        body = source[source.index(name):]
        body = body[: body.index("\n@router")] if "\n@router" in body else body
        assert needle in body, f"{name} 에 문서 소속 검사(assert_document_access)가 없다"


def test_업무실적_기재저장은_읽기와_같은_소속강제를_쓴다():
    """PATCH /notes 가 클라 office_code(기본 '10'=본사)를 그대로 넘기면, 지사 사용자가
    본사 기재사항을 삭제/덮어쓴다(2026-08-19 감사 CRITICAL). 읽기(get_notes)와 똑같이
    resolve_office_scope 로 소속을 강제해야 한다."""
    src = (ROUTERS / "work_report.py").read_text(encoding="utf-8")
    body = src[src.index("def patch_notes("):]
    body = body[: body.index("\n@router")] if "\n@router" in body else body
    assert "resolve_office_scope(access, office_code)" in body, \
        "patch_notes 가 office_code 를 소속강제 없이 그대로 저장한다(지사→본사 쓰기 구멍)"


def test_기본전표_존재조회에도_관문이_있다():
    """GET /{doc_id}/vouchers/default/status 는 형제와 달리 무인증이었다 — doc_id 만
    알면 누구나 전표 존재여부를 캤다(2026-08-19 감사). 본사재무+문서 관문을 요구한다."""
    src = (ROUTERS / "appraisals.py").read_text(encoding="utf-8")
    body = src[src.index("def default_voucher_status("):]
    body = body[: body.index("\n@router")] if "\n@router" in body else body
    assert 'require_menu("appraisals")' in body, "전표 존재조회에 메뉴 관문이 없다"
    assert "assert_document_access(db, doc_id, access)" in body, "전표 존재조회에 문서 관문이 없다"


# ── 메뉴 키 ↔ 서버 문지기 전수 대조 (2026-08-13 검수) ─────────────────────────
# 화면 체크박스는 **서버가 막아 줄 때만** 권한이다. 체크를 꺼도 API 가 열려 있으면
# 주소만 아는 사람은 그대로 들어간다. 그래서 키마다 문지기가 있는지 전부 센다.

# 관용구가 넷이다 — 하나만 보면 멀쩡한 화면을 '무방비'로 오독한다.
# (검수 첫 판에 require_menu 만 세어 9개를 잘못 지목했다.)
_GATE_CALLS = ("require_menu(", "require_menu_access(", "can_menu(", "menus.get(")

# 이 빌드에 화면이 없는 자리표. 화면이 들어오는 순간 문지기도 같이 와야 하므로
# 여기 남겨 두면 그때 아래 시험이 깨져서 알려 준다.
_NO_SCREEN_YET = {"feeReview"}          # 수수료 검토 — feature/fee-review 쪽


def _gated_menu_keys():
    import pathlib
    import re

    from app.services.access_policy import MENU_KEYS

    const_re = re.compile(r"^(\w*MENU_KEY\w*)\s*=\s*[\"'](\w+)[\"']", re.M)
    found = set()
    for path in sorted(pathlib.Path("app/routers").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        consts = dict(const_re.findall(src))
        # 키를 함수로 고르는 곳이 있다(banje._menu_key) — 그 함수 본문의 리터럴도 센다.
        for m in re.finditer(r"def _menu_key\(", src):
            frag = src[m.start(): m.start() + 300]
            found |= {k for k in re.findall(r"[\"'](\w+)[\"']", frag) if k in MENU_KEYS}
        for call in _GATE_CALLS:
            for m in re.finditer(re.escape(call), src):
                frag = src[m.start(): m.start() + 200].split(")")[0]
                found |= {k for k in re.findall(r"[\"'](\w+)[\"']", frag) if k in MENU_KEYS}
                found |= {consts[n] for n in re.findall(r"\b(\w*MENU_KEY\w*)\b", frag)
                          if n in consts}
    return found


def test_모든_메뉴_키에_서버_문지기가_있다():
    from app.services.access_policy import MENU_KEYS

    ungated = set(MENU_KEYS) - _gated_menu_keys() - _NO_SCREEN_YET
    assert not ungated, (
        f"서버 문지기가 없는 메뉴 키: {sorted(ungated)} — "
        "화면에서 체크를 꺼도 API 는 그대로 열려 있습니다."
    )


def test_화면이_없다고_적어_둔_키는_정말_화면이_없다():
    """자리표가 실제로 비어 있는지 확인한다.

    화면이 생겼는데 _NO_SCREEN_YET 에 그대로 남아 있으면, 문지기 없이 열린 화면을
    이 목록이 덮어 준다 — 면제가 아니라 부채다.
    """
    import pathlib

    ctx = pathlib.Path("desktop/ui/context.js").read_text(encoding="utf-8")
    for key in _NO_SCREEN_YET:
        assert f"'{key}'" not in ctx, (
            f"{key} 화면이 생겼습니다. 서버 문지기를 붙이고 _NO_SCREEN_YET 에서 빼세요."
        )


# ── 부서 권한 (2026-08-16 요청) ────────────────────────────────────────────
# 부서명을 누르면 **사람 이름을 누른 것과 같은 화면**이 열린다. 부서 하나를
# 바꾸면 그 부서 사람 전부가 한 번에 바뀌므로, 확인 장치가 붙어 있는지 지킨다.

def _preview_sources():
    import pathlib

    ui = pathlib.Path("desktop/ui")
    return (
        (ui / "permissions-preview.js").read_text(encoding="utf-8"),
        (ui / "permissions-preview.html").read_text(encoding="utf-8"),
    )


def test_부서명을_누르면_권한_화면이_열린다():
    """따로 선 버튼이 아니라 부서명 자체가 연다 — 사람 이름과 같은 방식."""
    js, html = _preview_sources()
    assert "'.tree-row.department'" in js, "부서명 줄에 클릭이 안 걸려 있다"
    assert "openDepartment(" in js
    assert 'id="departmentPanel"' in html and 'id="employeePanel"' in html
    # 옛 '부서 권한' 버튼과 트리 셀렉트는 걷어냈다.
    assert "dept-open" not in js
    assert "departmentRoleSelect" not in js


def test_부서_화면이_사람_화면과_같은_모양이다():
    """다른 모양이 나오면 같은 일을 하는 화면으로 안 읽힌다.

    사람 화면의 클래스를 그대로 써야 토글·요약·저장줄이 같은 것으로 보인다.
    """
    js, html = _preview_sources()
    for needle in ("menu-permission-group", "menu-permission-row", "inline-switch",
                   "menu-group-heading"):
        assert needle in js, f"부서 화면이 사람 화면의 {needle} 을 안 쓴다"
    panel = html[html.index('id="departmentPanel"'):html.index('id="employeePanel"')]
    for needle in ("selected-user", "permission-summary", "menu-access-section",
                   "permission-actions"):
        assert needle in panel, f"부서 패널에 {needle} 이 없다"


def test_캐럿과_부서명이_다른_일을_한다():
    """한 버튼이 접기와 열기를 겸하면, 권한을 보려다 부서가 접힌다."""
    js, _ = _preview_sources()
    assert "tree-caret-button" in js
    assert "toggleNode(" in js


def test_스코프_토글은_개인_편집기에서_본사_전지사_지사_개인내역만():
    """2026-08-18 최종: 조회 범위 토글을 권한관리 **개인 편집기**에 둔다.

    일괄권한은 메뉴만 정하고, 조회 넓이(스코프)는 사람별로 여기서 정한다. 규칙:
      · 전지사조회: 본사만 준다 — 지사 사람에겐 아예 숨긴다(코드가 강제로 막는다).
      · 개인내역(남의실적)조회: 본사·지사 모두 — 지사 재무 담당도 켠다.
    기본값(server.defaults)과 다르게 켠 것만 개인 예외로 저장된다.

    되돌려 전지사조회를 지사에도 노출하면 옛 버그가 살아난다 — 이 시험이 막는다.
    """
    js, html = _preview_sources()
    # 개인 편집기에 두 스코프 섹션·토글이 있다.
    assert 'id="viewAllSection"' in html and 'id="viewAllToggle"' in html
    assert 'people-scope-section' in html and 'id="viewOtherUsersToggle"' in html
    # 전지사조회는 본사만 — 지사면 섹션을 숨긴다(!isHeadOffice → hidden).
    render = js[js.index("function renderSelectedEmployee"):js.index("function updatePreviewPermission")]
    assert "$('viewAllSection').classList.toggle('hidden', !isHeadOffice)" in render, \
        "전지사조회가 지사에도 뜬다"
    assert "isHeadOffice && effectiveViewAll()" in render
    # 개인내역은 모든 직원 — 평가사 전용 제한(isAppraiserDataScopeEmployee)이 없다.
    upd = js[js.index("function updatePeopleScopePermission"):js.index("function resetPreviewPermission")]
    assert "isAppraiserDataScopeEmployee" not in upd, "개인내역이 평가사에게만 열린다"
    assert "viewOtherUsersOverrides" in upd
    # 부서 패널에는 스코프 토글을 두지 않는다(메뉴만) — 스코프는 사람별로.
    panel = html[html.index('id="departmentPanel"'):html.index('id="employeePanel"')]
    assert 'data-flag="viewAll"' not in panel and 'data-flag="viewOther"' not in panel
    assert 'id="viewAllToggle"' not in panel
    # 저장: 토글값이 기본값과 다를 때만 개인 예외로 보낸다(늘 null 이 아니다).
    save = js[js.index("async function savePermission"):]
    assert "viewAllValue !== viewAllDefault" in save, "전지사 예외를 안 만든다"
    assert "viewOtherValue !== viewOtherDefault" in save, "개인내역 예외를 안 만든다"
    # 리스너가 토글 변경을 듣는다.
    assert "$('viewAllToggle').addEventListener('change', updatePreviewPermission)" in js
    assert "$('viewOtherUsersToggle').addEventListener('change', updatePeopleScopePermission)" in js


def test_부서_저장에_잠금_확인이_붙어_있다():
    """메뉴 0개는 빈 화면이 아니라 로그인 거절이다.

    서버가 409 로 되묻는데 화면이 그걸 안 받으면 확인 없이 부서 전원이 잠긴다.
    """
    js, _ = _preview_sources()
    assert "ROLE_LOCKOUT_CONFIRM" in js
    assert "confirm_lockout" in js
    assert "로그인 자체가 거절" in js


def test_부서에_세트를_걸면_참조하지_않고_복사한다():
    """2026-08-18 사용자 결정: "부서도 개인처럼 그냥 복사로 가게 해서 일괄권한
    삭제가 되게끔." 종전엔 조합이 같은 이름 붙은 일괄권한을 찾아 재사용(참조)했다 —
    그래서 그 세트가 '쓰는 곳'에 걸려 삭제가 막혔다. 이제 부서 저장은 늘 그 부서
    전용 자동일괄권한으로 복사하므로, 이름 붙은 세트는 아무도 참조하지 않아 지울 수 있다.
    대신 세트를 고쳐도 이미 적용한 부서는 안 따라온다(공유가 아니라 복사)."""
    js, _ = _preview_sources()
    assert "resolveDraftRole" in js
    # ①단계(조합 일치 → 이름 붙은 일괄권한 재사용)를 걷어냈다.
    assert "if (match) return match.role_id;" not in js, \
        "부서가 이름 붙은 일괄권한을 재사용(참조)하면 그 세트가 삭제에 걸린다"
    # 부서 저장은 늘 자동일괄권한(복사본)을 쓴다.
    assert "memo: AUTO_ROLE_MEMO" in js


def test_부서_기본값_빠른설정_버튼은_없앴다():
    """사람마다 코드에서 계산되는 값이라 담당자가 손댈 수 없는 것이었는데,
    버튼으로 서 있으니 '부서 권한을 여기서 정한다' 는 오해를 샀다."""
    js, html = _preview_sources()
    assert 'id="restoreDepartmentDefaults"' not in html
    assert "restoreDepartmentDefaults" not in js


# ── 2026-08-16 감사 반영 ──────────────────────────────────────────────────


def test_같은_부서_두번째_저장이_제자리_갱신으로_돈다():
    """resolveDraftRole 이 조합이 다를 때마다 같은 이름으로 새 일괄권한을 만들면
    두 번째 저장이 중복 이름 거절에 걸린다 — 담당자가 두 번째 사용에서 반드시
    만나는 막다른길이었다. 이 부서 1곳만 쓰는 자동 일괄권한은 제자리에서 고친다."""
    js, _ = _preview_sources()
    assert "AUTO_ROLE_MEMO" in js
    assert "role_id: current.role_id" in js, "제자리 갱신 경로가 없다"
    assert "used.departments === 1 && !used.users" in js,         "다른 부서·사람이 쓰는 일괄권한까지 고치면 그쪽도 바뀐다"


def test_서버_정책_없이는_개인_저장을_막는다():
    """서버 정책 없이 저장하면 diff 기준이 JS 폴백으로 떨어져, 일괄권한이 준 메뉴가
    통째로 개인 예외로 굳는다 — 이후 일괄권한을 고쳐도 그 사람만 안 따라온다."""
    js, _ = _preview_sources()
    assert "불러오지 못해 저장할 수 없습니다" in js


def _preset_render_block(js: str) -> str:
    """세트 목록을 그리는 쪽(생산자). 종전 시험은 여기를 한 줄도 안 봤다."""
    return js[js.index("function presetRow("):js.index("function closePresetMenus")]


def test_프리셋은_토글만_채우고_저장은_담당자가_누른다():
    """2026-08-18 사용자 지적: "세트를 누르면 바로 저장하지 말고 밑에 토글을
    바꿔라. 무엇이 바뀌는지 보고 적용해야 하니까."

    세트 클릭은 아래 메뉴 토글만 채우고, 담당자가 '부서에 저장'/'변경사항 저장'을
    눌러야 반영된다 — '전체 허용/해제' 버튼과 같은 두 단계다. 되돌려 클릭 즉시
    applyDepartment/savePermission 을 부르면 검토 없이 부서 전원이 바뀐다.
    (2026-08-16 엔 확인창 한 번으로 즉시 적용이었다 — 이 결정을 뒤집은 것이다.)
    """
    js, html = _preview_sources()
    assert "namedPresets" in js
    assert "role.memo !== AUTO_ROLE_MEMO" in js, "자동 일괄권한까지 목록에 쌓인다"
    assert 'id="deptPresets"' in html and 'id="personPresets"' in html
    i = js.index("$('deptPresets').addEventListener")
    j = js.index("});", js.index("$('personPresets').addEventListener")) + 3
    block = js[i:j]
    # 세트 클릭은 채우기만 — 즉시 저장/적용을 부르지 않는다.
    assert "applyDepartment()" not in block, "세트 클릭이 즉시 부서에 적용한다"
    assert "savePermission()" not in block, "세트 클릭이 즉시 저장한다"
    assert "window.confirm" not in block, "즉시 적용용 확인창이 남아 있다"
    # 대신 토글을 채우고 화면을 다시 그린다.
    assert "deptDraft.menus = new Set(keys)" in block, "부서 세트가 메뉴를 안 채운다"
    assert "saveMenuOverride(new Set(keys))" in block, "사람 세트가 메뉴를 안 채운다"
    assert "renderDepartmentPanel()" in block and "renderSelectedEmployee()" in block
    # 채웠다는 안내 — 저장을 눌러야 함을 알린다.
    assert "부서에 저장" in block and "변경사항 저장" in block
    # 드롭다운 라벨은 '일괄권한 적용'이고, 고른 일괄권한 이름이 요약에 뜬다(2026-08-18).
    assert "세트 적용" not in html, "옛 '세트 적용' 라벨이 남았다"
    assert html.count("일괄권한 적용") >= 2, "부서·개인 드롭다운 라벨이 안 바뀌었다"
    assert 'id="deptPresetPick"' in html and 'id="personPresetPick"' in html
    assert "$('deptPresetPick').textContent = role.name" in block, "부서 세트 이름이 요약에 안 뜬다"
    assert "$('personPresetPick').textContent = role.name" in block, "개인 세트 이름이 요약에 안 뜬다"


def test_세트_목록이_실제로_그려진다():
    """종전 시험은 id 존재만 봐서, 목록을 영구히 비우거나 렌더 호출을 지워도
    통과했다 — 누를 것이 화면에 있는지는 아무도 안 봤다(2026-08-17 적대 검증)."""
    js, html = _preview_sources()
    render = _preset_render_block(js)
    # 행이 data-preset 을 실제로 낸다 — 이게 없으면 클릭 위임이 통째로 끊긴다.
    assert "data-preset=\"' + role.role_id" in render, "행이 data-preset 을 안 낸다"
    # 세트 이름은 반드시 이스케이프한다(이름은 60자 자유 입력이라 <, ' 가 들어온다).
    assert "escapeHtml(role.name)" in render
    # 목록을 채우는 자리
    assert "sets.map(role => presetRow(" in js
    # 렌더 호출이 **두 화면 모두**에 있어야 한다.
    dept = js[js.index("function renderDepartmentPanel"):js.index("function deptAllowAll")]
    person = js[js.index("function renderMenuPermissions"):
                js.index("function renderSelectedEmployee")]
    # 주석 처리해도 문자열은 남는다 — 실제 '호출'인지 줄 단위로 가린다.
    def calls(block: str) -> bool:
        return any(line.lstrip().startswith("paintPresetMenu(")
                   for line in block.splitlines())

    assert calls(dept), "부서 화면에 세트 목록이 안 그려진다"
    assert calls(person), "사람 화면에 세트 목록이 안 그려진다"
    # 마크업이 드롭다운이어야 한다 — 맨 div 로 되돌리면 칸이 다시 모자란다. 2026-08-18
    # 부터 'hidden' 을 뗐다: 세트 0개여도 드롭다운이 열려 '일괄권한 만들기·관리' 로
    # 이어져야 한다(관리는 일괄권한 화면으로 가는 유일한 문).
    assert '<details class="preset-menu" id="deptPresetMenu">' in html
    assert '<details class="preset-menu" id="personPresetMenu">' in html


def test_세트_개수는_이_대상에_실제로_열릴_것으로_센다():
    """본사 전용만 든 세트가 지사 대상에게 '메뉴 8개'라고 초록으로 말해 놓고
    적용하면 0개 = 로그인 거절이 됐다 — 경고색이 정확히 필요한 자리에서 반대로
    말한 것이다(2026-08-17 적대 검증)."""
    js, _ = _preview_sources()
    render = _preset_render_block(js)
    assert "all.filter(key => available.has(key))" in render, "대상 필터를 안 거친다"
    # 호출부 둘 다 대상 집합을 넘겨야 한다.
    assert "new Set(deptAvailableKeys()), 'dept'" in js
    assert "available, 'person'" in js
    # 부서/사람의 결정적 차이가 행에도 남아야 한다(확인창에만 두지 않는다).
    assert "값만 복사" in render


def test_열린_목록이_다음_대상까지_따라가지_않는다():
    """대상이 바뀐 뒤에도 열려 있으면 그건 남의 대상에서 연 팝오버다 —
    사용자가 열지 않은 목록이 새 대상 위에 펼쳐져 '열고' 단계가 사라진다."""
    js, _ = _preview_sources()
    paint = js[js.index("function paintPresetMenu"):js.index("function closePresetMenus")]
    assert "menu.open = false" in paint, "매 렌더마다 닫지 않는다"
    # menu.hidden=!sets.length 는 2026-08-18 걷어냈다 — 아래 전용 시험이 그 부재를 지킨다.


def test_세트가_0개여도_일괄권한관리로_가는_문이_남는다():
    """'일괄권한 만들기·관리' 는 일괄권한 화면으로 가는 **유일한 문**이다(사이드바에서
    내렸다). 세트를 다 지운 담당자가 새로 만들 수 있어야 하므로 — 세트 0개여도
    드롭다운을 숨기면 안 된다. 종전 menu.hidden=!sets.length 가 담당자를 가뒀다
    (2026-08-18 이 화면에 링크를 드롭다운 안으로 옮기며 함께 고쳤다). 링크는
    팝오버(.preset-list) 안에 있고, 목록이 비면 안내를 띄운다."""
    js, html = _preview_sources()
    # 세트 수로 드롭다운을 숨기지 않는다.
    assert "menu.hidden = !sets.length" not in js, \
        "세트 0개면 드롭다운이 사라져 '일괄권한 관리' 로 갈 문이 막힌다"
    # 관리 링크가 두 화면 모두 팝오버 안에 있다.
    assert html.count('class="preset-manage"') >= 2, "관리 링크가 두 화면에 다 없다"
    assert html.count("일괄권한 만들기·관리") >= 2
    # 관리 링크는 preset-list(팝오버) 안에 있어야 한다 — 밖(bulk-actions 줄)으로
    # 되돌리면 다시 붐비고, '적용'과 '관리'가 남남처럼 나뉜다.
    for menu_id in ("deptPresetMenu", "personPresetMenu"):
        block = html[html.index(f'id="{menu_id}"'):]
        block = block[:block.index("</details>")]
        assert "preset-manage" in block, f"{menu_id} 드롭다운 안에 관리 링크가 없다"
    # 빈 목록 안내가 있다.
    assert "preset-empty" in js and "아직 만든 일괄권한이 없습니다" in js


def test_바깥_클릭과_Esc_로_닫힌다():
    """<details> 는 스스로 안 닫힌다. 열린 판이 메뉴 토글 ~5행을 덮어(z-index:20),
    토글을 누르려다 프리셋 행을 누르면 그 한 번이 부서 전원 적용이 된다."""
    js, _ = _preview_sources()
    assert "closePresetMenus" in js
    assert "pointerdown" in js and "closest('.preset-menu')" in js
    assert "event.key === 'Escape'" in js


def test_전역_button_규칙에_호버가_눌리지_않는다():
    """dashboard.css 의 button:hover:not(:disabled) 는 (0,2,1) 이라
    .preset-row:hover (0,2,0) 을 이긴다 — 흰 팝오버 위의 흰 호버가 되어
    '지금 이 줄을 누르면 부서 전원이 바뀐다'를 알려 줄 표시가 사라졌다.
    칩 시절 (0,3,0) 이라 멀쩡했던 부분이라 이건 회귀였다."""
    import pathlib

    css = pathlib.Path("desktop/ui/permissions-preview.css").read_text(encoding="utf-8")
    assert ".preset-list .preset-row:hover:not(:disabled)" in css, "특정도가 전역에 진다"
    assert ".preset-list .preset-row" in css
    # 미지원 엔진에서 팝오버가 '항상 열린' 채 아래를 덮지 않게.
    assert ".preset-menu:not([open]) .preset-list" in css


def test_출처_배지는_걷어냈다():
    """일괄권한이 붙은 사람에게 '부서 기본값'이라 적어 이름이 거짓말을 하던 출처 배지
    (menuSourceBadge)는 2026-08-18 아예 걷어냈다(사용자 요청 — 자잘한 표시 정리).
    권한 값은 토글이 그대로 보여 주므로 출처 문구는 없어도 된다."""
    js, html = _preview_sources()
    assert "$('menuSourceBadge')" not in js, "출처 배지를 다시 채우면 안 된다"
    assert 'id="menuSourceBadge"' not in html


def test_내부_어휘가_화면에_없다():
    """담당자에게 a10_access_policy·Seat_userinfo·'화면 시안'은 소음이고
    불안 요인이다 — 테이블 이름이 보이면 뭔가 잘못 만진 기분이 든다."""
    js, html = _preview_sources()
    assert "a10_access_policy에" not in html
    assert "a10_access_policy에" not in js
    assert "화면 시안" not in js
    assert "Seat_userinfo" not in html.split("<body")[1], "화면 본문에 테이블 이름"


def test_부서_저장_후_옛_시드를_비운다():
    """부서 권한이 바뀌었는데 옛 기준으로 계산해 둔 화면 시드가 남으면,
    재클릭 시 fetch 가 실패했을 때 옛 값이 사실처럼 보인다."""
    js, _ = _preview_sources()
    assert "menuPermissionOverrides.delete(staleKey)" in js


def test_저장_응답도_일괄권한_기준으로_계산한다():
    """PUT /users/{seq} 응답의 effective 가 grant 없이 계산되면, 일괄권한으로 메뉴를
    받는 사람의 저장 응답에 메뉴가 전부 꺼진 것으로 나온다 — 지금 화면은
    재조회해서 안 보이지만, 응답을 그대로 그리는 소비자가 생기면 사고다."""
    import pathlib

    src = pathlib.Path("app/services/permissions.py").read_text(encoding="utf-8")
    i = src.index("def save_access_policy")
    block = src[i:i + 6000]
    assert '"effective": build_access_policy(identity, row, grant=' in block


def test_권한_일괄권한은_사이드바가_아니라_권한관리_안에서_연다():
    """부서 저장이 일괄권한을 자동 처리하면서 그 화면의 남은 일은 '세트에 이름
    붙이기'뿐이다(2026-08-16 UX 판정). 1급 메뉴로 두면 담당자가 두 화면 중
    어디서 일해야 하는지부터 헷갈린다. 주소·키 매핑은 남긴다 — 화면은 살아
    있고 permissionManage 가 지킨다."""
    import pathlib
    import re

    ctx = pathlib.Path("desktop/ui/context.js").read_text(encoding="utf-8")
    menu = ctx[ctx.index("const A10_MENU"): ctx.index("// 지금 보고 있는 화면인가")]
    assert "href: '/desktop/permission-roles'" not in menu, "사이드바에 아직 있다"
    # fail-closed 매핑은 반드시 남아야 한다 — 빠지면 화면이 통째로 숨는다.
    assert re.search(r"'/desktop/permission-roles':\s*'permissionManage'", ctx)
    _js, html = _preview_sources()
    assert 'href="/desktop/permission-roles"' in html, "들어갈 문이 없다"


def test_전표_카드는_하단에_접혀_있다():
    """전표 캐시 동기화는 권한과 무관한 관리 작업인데 첫 화면 최상단을 차지하고
    있었다. 매일 여는 화면의 첫 줄은 본업(권한)이 차지해야 한다."""
    _js, html = _preview_sources()
    assert '<details id="cacheSyncSection"' in html
    # 권한 레이아웃보다 뒤에 있어야 한다.
    assert html.index('class="permission-layout"') < html.index('id="cacheSyncSection"')


# ── 일괄권한관리 화면 계약 ───────────────────────────────────────────────


def _roles_sources():
    import pathlib

    ui = pathlib.Path("desktop/ui")
    return (
        (ui / "permission-roles.js").read_text(encoding="utf-8"),
        (ui / "permission-roles.html").read_text(encoding="utf-8"),
    )


def test_부서를_안_따라가는_사람이_트리에_표시된다():
    """사용자 질문(2026-08-17): "부서가 바뀌면 자동으로 권한이 따라가려나?"

    부서 일괄권한은 따라간다(실측: 권혜민 0→19종). 그러나 개인 일괄권한·개인 예외가 붙은
    사람은 그게 부서를 이겨 **안 따라간다**(지인자는 본사로 옮긴 뒤에도 옛 8종).
    그 사실이 화면에 없으면 담당자는 '20명에게 적용했습니다'를 믿는데 실제로는
    17명만 바뀐다 — 인사이동이 잦은 조직에서 조용히 쌓이는 오차다.
    """
    js, _ = _preview_sources()
    assert "function personalSettingOf" in js
    # 두 갈래를 **모두** 본다 — 개인 일괄권한만 보면 개인 예외가 조용히 빠진다.
    fn = js[js.index("function personalSettingOf"):js.index("// 부서 일괄권한 지정은 이제 부서 패널")]
    assert "userRoleMap.get(seq)" in fn, "개인 일괄권한을 안 본다"
    assert "personalOverrides.has(seq)" in fn, "개인 예외를 안 본다"
    # 서버에서 실제로 받아 온다 — 빈 Map 이면 표가 영원히 안 뜬다.
    load = js[js.index("async function loadPersonalSettings"):js.index("/** 이 사람은 부서")]
    assert "/api/permissions/roles/user-assignments" in load
    assert "data.personal_overrides" in load
    assert "userRoleMap.set(" in load
    # 이름 옆 '개인' 딱지(personal-mark)는 2026-08-18 뺐다(사용자 요청) — 대신 부서 패널이
    # '개인 설정 N명' 을 세어 저장 버튼과 안내에 쓴다.
    assert 'class="personal-mark"' not in js, "이름 옆 개인 딱지는 뺐다(사용자 요청)"
    panel = js[js.index("function renderDepartmentPanel"):js.index("function deptAllowAll")]
    assert "department.employees.filter(personalSettingOf)" in panel, "부서 패널이 개인설정을 안 센다"


def test_부서_저장은_개인설정을_되돌리고_일괄권한이_같아도_막히지_않는다():
    """2026-08-19 신고: '3명만 개인적으로 바꿨는데 헷갈려 그냥 부서로 초기화' 하려는데
    막혔다. 부서 저장 = 복사/덮어쓰기라 개인 설정을 부서값으로 되돌린다 — (1) 일괄권한이
    그대로여도(!dirty) 되돌릴 사람이 있으면 저장 버튼이 열리고, (2) 확인 문구는 서버가
    실제로 되돌린 수(reset_count)를 사실대로 말한다. '안 바뀐 사람을 빼고 센다'는 옛
    계약은 폐기했다 — 개인은 이제 부서값으로 되돌아간다."""
    js, _ = _preview_sources()
    panel = js[js.index("function renderDepartmentPanel"):js.index("function deptAllowAll")]
    # 일괄권한이 그대로(!dirty)여도 되돌릴 개인 설정(held)이 있으면 버튼을 연다.
    assert "!dirty && held === 0" in panel, "되돌릴 사람이 있어도 저장 버튼이 잠겨 있다"
    apply_fn = js[js.index("async function applyDepartment"):js.index("function renderDepartment(")]
    # 되돌린 수는 서버 값(reset_count)으로 말한다 — 더는 개인을 빼고 세지 않는다.
    assert "data.reset_count" in apply_fn, "되돌린 수를 서버에서 안 읽는다"
    assert "(department.employees.length - held)" not in apply_fn, "개인을 빼고 세는 옛 문구가 남았다"
    # 진짜 no-op(skipped)은 '적용했습니다'가 아니라 '변경 없음'으로 사실대로 알린다.
    assert "data.skipped" in apply_fn, "no-op 을 사실대로 안 알린다"
    # 되돌린 사람의 개인 설정 표식을 즉시 비운다 — 안 그러면 이미 초기화됐는데 버튼이 계속 열린다.
    assert "userRoleMap.delete(seq)" in apply_fn
    # finally 가 버튼을 강제로 여는 대신 다시 그려, 초기화가 끝나면 스스로 잠기게 한다.
    assert "button.disabled = false" not in apply_fn, "finally 가 버튼을 강제로 열면 초기화 후에도 열려 있다"


def test_저장_증표_없으면_로그인_모달로_재발급하고_재시도한다():
    """2026-08-17 사용자 지적: "저장하면 로그인하라구 하는데" — ?usr= 나 EXE 로
    들어와 증표가 없으면 서버가 401(AUTH_TOKEN_REQUIRED)로 되돌리는데, 종전에는
    화면이 그 메시지만 보여 주고 끝나 **로그인할 창이 없는 막다른 길**이었다.

    이제 fetch 래퍼가 그 401 을 잡아 로그인 모달을 띄우고, 증표를 받은 뒤 원래
    저장을 한 번 다시 시도한다. 증표의 usr_seq 는 세션과 같아야 서버가 받으므로
    (require_menu_write 의 AUTH_TOKEN_MISMATCH) 같은 계정으로만 받는다."""
    import pathlib

    ctx = pathlib.Path("desktop/ui/context.js").read_text(encoding="utf-8")
    wrap = ctx[ctx.index("window.fetch = async function"):]
    # 401 을 실제로 처리한다 — 두 코드 모두.
    assert "response.status === 401" in wrap, "401 을 아예 안 본다"
    assert "AUTH_TOKEN_REQUIRED" in wrap and "AUTH_TOKEN_MISMATCH" in wrap
    # 재발급 모달을 부르고, 성공하면 한 번 다시 시도한다.
    assert "reauthForToken()" in wrap, "로그인 모달을 안 띄운다"
    assert "__moaReauthRetried" in wrap, "무한 루프 방지 표식이 없다 — 재시도 폭주"
    # 재발급 함수: 로그인 POST + 같은 계정 확인 + 증표 저장.
    reauth = ctx[ctx.index("function reauthForToken"):ctx.index("window.fetch = async")]
    assert "/api/auth/login" in reauth, "비밀번호로 증표를 받지 않는다"
    assert "String(payload.data.usr_seq) !== String(ctx.usr_seq)" in reauth, \
        "다른 계정으로 받으면 서버가 어차피 거절하는데 먼저 안 막는다"
    assert "localStorage.setItem(AUTH_TOKEN_KEY" in reauth, "받은 증표를 저장하지 않는다"
    # 권한 테스트(읽기 전용)에서는 재시도하지 않는다.
    assert "!window.A10_PERMISSION_PREVIEW" in wrap


def test_사람_클릭시_서버값_전엔_메뉴토글을_폴백으로_안_그린다():
    """2026-08-18 사용자 지적: "사람 딱 누르면 몇 개 토글이 왔다갔다한다." 클릭 즉시
    폴백(부서 휴리스틱)값으로 토글을 그렸다가 loadServerPolicy 가 서버값으로 다시
    그려서다. account_linked 사람은 서버값이 오기 전엔 메뉴 토글을 로딩으로 두고, 값이
    온 뒤 한 번에 그린다. 조회 실패해도 로딩에 멈추지 않게 폴백을 그린다."""
    js, _ = _preview_sources()
    menu = js[js.index("function renderMenuPermissions"):
              js.index("function renderSelectedEmployee")]
    assert ("!selectedEmployee.serverPolicy && !selectedEmployee.serverPolicyFailed"
            in menu), "서버값 전에 로딩 가드가 없다"
    assert "불러오는 중" in menu
    # 실패(403·네트워크)해도 로딩에 멈추지 않게 폴백을 그린다.
    assert js.count("serverPolicyFailed = true") >= 2


def test_일괄권한_편집기_전체지사조회는_본사만_개인내역조회는_모두():
    """2026-08-18 사용자 요청: 일괄권한 편집기에 **전체지사조회는 본사 로그인일 때만** 뜬다
    (지사는 전지사조회를 못 가짐 — JS 가 로그인 소속으로 roleViewAllSection 을 숨김).
    개인내역조회는 본사·지사 모두. 소속은 로그인 계정으로 정해진다(드롭다운 없음).

    · 적용 대상(부서·사람 일괄 체크리스트)은 여전히 없다 — 붙이는 일은 권한관리에서.
    """
    js, html = _roles_sources()
    # 두 스코프 토글이 카드/스위치로 있다. 전체지사조회 섹션은 기본 hidden(JS가 본사에서 폄).
    assert 'id="roleViewOther"' in html and 'id="roleViewAll"' in html
    assert 'id="roleViewAllSection"' in html
    assert 'scope-policy-card' in html and 'inline-switch' in html
    # 지사는 전체지사조회를 숨긴다 — 로그인 소속이 본사(10)일 때만 편다.
    assert "secAll.hidden = !headLogin" in js
    assert "office_id || '10') === '10'" in js, "로그인 소속을 본사로 판정"
    # 옛 select/체크박스 방식은 없다.
    assert 'id="flagAllOffices"' not in html and 'id="flagOtherUsers"' not in html
    # 적용 대상은 여전히 없다.
    for gone in ('id="targetsSection"', 'id="deptTargets"', 'id="userTargets"',
                 'id="applyTargets"', 'id="userSearch"'):
        assert gone not in html, f"{gone} 가 아직 남았다"
    assert "async function applyTargets" not in js
    collect = js[js.index("function collect()"):js.index("async function post(")]
    # 저장: 개인내역조회는 토글, 전체지사조회는 본사면 토글·지사면 null.
    assert "view_other_users: $('roleViewOther').checked" in collect
    assert "$('roleViewAll').checked" in collect
    assert 'id="roleName"' in html and 'id="menuChecks"' in html


def test_일괄권한_소속은_로그인_계정으로_정해진다():
    """공용 없는 지사별 일괄권한(2026-08-18): **소속 선택칸을 뺐다** — 소속은 로그인 계정으로
    서버가 강제한다(본사 계정=본사 일괄권한, 21지사 계정=21지사 일괄권한). 저장이 office_id 를
    안 보내고, 편집기에 드롭다운·채우기 코드가 없다."""
    js, html = _roles_sources()
    assert 'id="roleOffice"' not in html, "소속 드롭다운은 뺐다(로그인으로 정해짐)"
    assert "paintOfficeOptions" not in js
    collect = js[js.index("function collect()"):js.index("async function post(")]
    assert "roleOffice" not in collect, "저장이 소속 드롭다운을 읽으면 안 된다(뺐다)"


def test_권한일괄적용은_대상_소속의_일괄권한만_보인다():
    """권한일괄적용(preset 드롭다운)은 대상(사람/부서)의 소속과 같은 office_id 일괄권한만
    보여 준다 — 타지사 건은 안 뜬다(공용 없는 지사별 일괄권한)."""
    js, _ = _preview_sources()
    assert "String(role.office_id) === String(officeId)" in js, "소속으로 안 거른다"
    assert "'dept', selectedDepartment.office.id" in js, "부서 소속을 안 넘긴다"
    assert "'person', selectedEmployee.office.id" in js, "사람 소속을 안 넘긴다"

