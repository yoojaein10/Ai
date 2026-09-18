"""권한 화면의 메뉴 이름·목록이 실제 사이드바와 같은지 지킨다 (2026-08-15).

왜 있나
    권한 담당자는 **사이드바에서 본 이름**으로 권한을 찾는다. 그런데 메뉴 이름이
    세 곳에 따로 적혀 있다 — 사이드바(context.js A10_MENU), 권한관리 화면
    (permissions-preview.js menuGroups), 권한묶음 화면(permission-roles.js
    MENU_NAMES). 한 곳만 고치면 조용히 갈라진다.

    2026-08-15 대조에서 실제로 갈라져 있었다:
      · 이름 4건이 옛 이름 — '매출 입력'(→유치실적), '내 매출실적'(→개인별
        매출실적), '외상매출금 반제리스트'·'선수금 반제리스트'(→…반제)
      · 실제 있는 메뉴 셋(보수기준 점검·입금 대사·수수료 검토)이 권한관리
        화면에서 **통째로 빠져** 있었다 — 그 권한은 화면에서 켤 방법이 없었다

    빠진 쪽이 이름 틀린 쪽보다 나쁘다. 이름은 헷갈리게 하지만, 빠진 메뉴는
    담당자가 할 수 있는 일 자체를 없앤다.

원본은 사이드바다. 이름을 바꿀 일이 생기면 context.js 를 먼저 고치고 나머지를
맞춘다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.access_policy import MENU_KEYS

UI = Path("desktop/ui")
CONTEXT = (UI / "context.js").read_text(encoding="utf-8")
PREVIEW = (UI / "permissions-preview.js").read_text(encoding="utf-8")
ROLES = (UI / "permission-roles.js").read_text(encoding="utf-8")

# 서버 정책에는 있으나 붙는 화면이 아직 없는 키. 사이드바에 없는 게 정상이다.
NO_SCREEN_YET = set()   # feeReview 제거(2026-08-18). 새 무화면 키가 생기면 여기 채운다.


def _sidebar_labels() -> dict[str, str]:
    """사이드바가 쓰는 '메뉴 키 → 사람이 보는 이름'.

    A10_MENU 는 href 만 들고 있고 키는 menuKeyForUrl 이 붙이므로, 둘을 이어서 푼다.
    """
    url_to_key = dict(re.findall(r"'(/desktop[^']*)':\s*'(\w+)'", CONTEXT))
    block = CONTEXT[CONTEXT.index("const A10_MENU"): CONTEXT.index("// 지금 보고 있는 화면인가")]
    labels: dict[str, str] = {}
    for label, href in re.findall(r"label:\s*'([^']+)',\s*href:\s*'([^']+)'", block):
        key = url_to_key.get(href) or url_to_key.get(href.split("?")[0])
        # '권한 관리'와 '권한 묶음'은 같은 키를 쓴다 — 먼저 나온 이름을 원본으로 둔다.
        if key and key not in labels:
            labels[key] = label
    return labels


def _preview_names() -> dict[str, str]:
    return dict(re.findall(r"\{key:\s*'(\w+)',\s*name:\s*'([^']+)'", PREVIEW))


def _roles_names() -> dict[str, str]:
    block = ROLES[ROLES.index("const MENU_NAMES"): ROLES.index("};", ROLES.index("const MENU_NAMES"))]
    return dict(re.findall(r"(\w+):\s*'([^']+)'", block))


def test_사이드바에_있는_메뉴는_권한관리_화면에도_다_있다():
    """빠진 메뉴는 '권한을 줄 방법이 없다'는 뜻이다 — 이름 틀린 것보다 나쁘다."""
    missing = sorted(set(_sidebar_labels()) - set(_preview_names()))
    assert not missing, f"권한관리 화면에서 빠진 메뉴: {missing}"


def test_서버가_아는_메뉴는_권한관리_화면에도_다_있다():
    missing = sorted(set(MENU_KEYS) - set(_preview_names()))
    assert not missing, (
        f"서버 MENU_KEYS 에는 있는데 권한관리 화면에 없는 키: {missing} — "
        "화면에서 켤 수 없는 권한이 생깁니다."
    )


@pytest.mark.parametrize("screen", ["권한관리", "권한묶음"])
def test_메뉴_이름이_사이드바와_같다(screen):
    names = _preview_names() if screen == "권한관리" else _roles_names()
    sidebar = _sidebar_labels()
    mismatch = {
        key: (label, names[key])
        for key, label in sidebar.items()
        if key in names and names[key] != label
    }
    assert not mismatch, (
        f"{screen} 화면의 이름이 사이드바와 다릅니다 "
        f"(키: (사이드바, {screen})): {mismatch}"
    )


def test_화면이_없는_키는_사이드바에도_없다():
    """자리표가 실제로 비어 있는지 확인한다 — 화면이 생기면 이 시험이 알려 준다."""
    sidebar = _sidebar_labels()
    landed = sorted(NO_SCREEN_YET & set(sidebar))
    assert not landed, (
        f"{landed} 화면이 생겼습니다. NO_SCREEN_YET 에서 빼고, "
        "'아직 화면이 없음' 묶음에서도 옮기세요."
    )


def test_두_권한화면이_서로_같은_말을_한다():
    """권한관리와 권한묶음이 같은 키를 다르게 부르면 담당자가 다른 메뉴로 읽는다."""
    preview, roles = _preview_names(), _roles_names()
    mismatch = {
        key: (preview[key], roles[key])
        for key in set(preview) & set(roles)
        if preview[key] != roles[key]
    }
    assert not mismatch, f"두 화면의 이름이 다릅니다 (키: (권한관리, 권한묶음)): {mismatch}"


def _role_group_keys() -> list[str]:
    """권한묶음 화면이 메뉴를 나눠 담는 묶음(MENU_GROUPS)의 키 전부.

    2026-08-18 권한관리와 같은 행 구조로 바꾸면서 MENU_GROUPS 가
    keys:[...] 에서 items:[{key:'...'}] 로 바뀌었다.
    """
    block = ROLES[ROLES.index("const MENU_GROUPS"): ROLES.index("/** 서버가 준 키")]
    return re.findall(r"key:\s*'(\w+)'", block)


def test_권한묶음_화면이_메뉴를_하나도_흘리지_않는다():
    """묶음에서 빠진 키는 화면에 안 뜬다 = 그 권한을 줄 수 없다.

    JS 는 모르는 키를 '기타'로 담아 살려 두지만, 그건 안전망이지 제자리가 아니다.
    새 메뉴가 생기면 사이드바 순서에 맞는 자리에 넣어야 한다.
    """
    placed = _role_group_keys()
    missing = sorted(set(MENU_KEYS) - set(placed))
    assert not missing, (
        f"권한묶음 화면의 MENU_GROUPS 에서 빠진 키: {missing} — "
        "'기타'로 떨어져 사이드바와 다른 자리에 뜹니다."
    )


def test_같은_메뉴가_두_묶음에_들어가지_않는다():
    """두 곳에 뜨면 한쪽만 끄고 껐다고 여기게 된다."""
    placed = _role_group_keys()
    dupes = sorted({key for key in placed if placed.count(key) > 1})
    assert not dupes, f"두 묶음에 걸친 메뉴: {dupes}"


def test_권한묶음의_묶음_이름이_사이드바_그룹과_같다():
    """담당자는 사이드바에서 본 묶음 이름으로 찾는다."""
    groups = set(re.findall(r"group:\s*'([^']+)'", CONTEXT))
    block = ROLES[ROLES.index("const MENU_GROUPS"): ROLES.index("/** 서버가 준 키")]
    names = set(re.findall(r"\{name:\s*'([^']+)'", block))
    # '업무'(사이드바 최상위 감정서 LIST)와 '아직 화면이 없음'은 사이드바에 그룹이
    # 없는 자리라 예외로 둔다.
    unknown = sorted(names - groups - {"업무"})
    assert not unknown, f"사이드바에 없는 묶음 이름: {unknown}"
