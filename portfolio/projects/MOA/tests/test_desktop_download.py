"""데스크톱 EXE 엑셀 내려받기 (2026-08-27) — 저장 대화상자 없이 임시 폴더에 두고 바로 엑셀로 연다.

보관하고 싶으면 엑셀에서 '다른 이름으로 저장'. 예전엔 저장 대화상자 → 저장 → 사용자가 직접 열어야 했다.
"""

import os
import re
import time
from pathlib import Path

from desktop.main import download_dir, prune_old, unique_path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "desktop" / "main.py").read_text(encoding="utf-8")
CONTEXT = (ROOT / "desktop" / "ui" / "context.js").read_text(encoding="utf-8")


def test_같은_이름이_있으면_번호를_붙인다(tmp_path):
    """엑셀이 열어 둔 파일은 덮어쓸 수 없으니 (2), (3)… 으로 비켜 간다."""
    assert unique_path(tmp_path, "매출.xlsx") == tmp_path / "매출.xlsx"
    (tmp_path / "매출.xlsx").write_bytes(b"x")
    assert unique_path(tmp_path, "매출.xlsx") == tmp_path / "매출 (2).xlsx"
    (tmp_path / "매출 (2).xlsx").write_bytes(b"x")
    assert unique_path(tmp_path, "매출.xlsx") == tmp_path / "매출 (3).xlsx"


def test_오래된_임시파일만_지운다(tmp_path):
    old, new = tmp_path / "old.xlsx", tmp_path / "new.xlsx"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    now = time.time()
    os.utime(old, (now - 10 * 86400, now - 10 * 86400))
    assert prune_old(tmp_path, keep_days=7, now=now) == 1
    assert not old.exists() and new.exists()
    assert prune_old(tmp_path / "없는폴더") == 0


def test_임시_폴더는_시스템_temp_아래_MOA_다():
    assert download_dir().name == "MOA"


def test_저장_대화상자_대신_바로_연다():
    assert "os.startfile(" in MAIN
    assert "SAVE_DIALOG" not in MAIN and "_ask_save_path" not in MAIN
    assert "열었습니다:" in MAIN
    # 화면은 '열었습니다'도 성공으로 봐야 한다 — 아니면 빨간 토스트가 뜬다
    assert "/^(저장했습니다|열었습니다)/" in CONTEXT


def test_모든_화면이_같은_context_js_버전을_쓴다():
    """context.js 를 고치면 26개 화면의 ?v= 를 전부 올려야 새 코드가 나간다."""
    versions = set()
    for page in (ROOT / "desktop" / "ui").glob("*.html"):
        match = re.search(r"context\.js\?v=([\w-]+)", page.read_text(encoding="utf-8"))
        if match:
            versions.add(match.group(1))
    assert versions == {"20260827-1"}, versions
