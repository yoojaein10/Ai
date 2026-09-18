"""화면 HTML 은 캐시되면 안 된다 (2026-08-21).

HTML 이 캐시되면 그 안에 적힌 `?v=` 도 옛 값이라 새 JS·CSS 를 영영 안 받는다.
화면을 배포해도 사용자에겐 옛 화면이 그대로 보이고, "안 올라간 것 같다"가 된다.

실제로 두 번 겪었다.
- 2026-08-20 보수기준 점검: 그 화면만 ?v 없이 걸려 있어 옛 CSS 를 쓰고 있었다.
- 2026-08-21 입금발송내역: 새 검색 조건(입금상태)·매출총액 열이 안 보인다는 제보.
  헤더를 화면마다 손으로 달다 보니 21개 중 13개가 빠져 있었다.

그래서 헤더를 한 곳(_screen)에서만 만들고, 새 화면이 그 길을 안 지나가면
여기서 걸리게 한다.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

MAIN = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text(
    encoding="utf-8"
)

# @app.get("/desktop...") 로 등록된 화면 주소 전부
SCREEN_PATHS = re.findall(r'@app\.get\("(/desktop[^"]*)"', MAIN)


def test_화면_주소를_하나도_못_찾으면_시험이_헛돈다():
    assert len(SCREEN_PATHS) >= 20, f"화면을 {len(SCREEN_PATHS)}개밖에 못 찾았다"


@pytest.mark.parametrize("path", SCREEN_PATHS)
def test_모든_화면이_캐시되지_않는다(path):
    response = TestClient(app).get(path)

    assert response.status_code == 200, f"{path} 가 안 열린다"
    cache = response.headers.get("cache-control", "")
    assert "no-cache" in cache, (
        f"{path} 에 캐시 방지가 없다 — 배포해도 옛 화면이 그대로 보인다"
    )


def test_화면_응답은_한_곳에서만_만든다():
    """FileResponse 를 직접 쓰면 헤더를 또 빠뜨린다."""
    assert MAIN.count("def _screen(") == 1
    assert "FileResponse(DESKTOP_UI_DIR" not in MAIN.replace(
        'FileResponse(\n        DESKTOP_UI_DIR / name,', ""
    ), "화면은 _screen() 을 거쳐야 한다"


def test_입금발송내역도_새로_받는다():
    """2026-08-21 제보 화면 — 회귀 방지로 이름을 박아 둔다."""
    response = TestClient(app).get("/desktop/payment-sms")

    assert "no-cache" in response.headers.get("cache-control", "")
    assert 'id="payStatusFilter"' in response.text, "새 검색 조건이 응답에 있어야 한다"
    assert "매출총액" in response.text
