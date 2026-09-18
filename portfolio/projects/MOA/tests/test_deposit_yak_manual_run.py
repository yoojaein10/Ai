"""권한 관리 화면의 '약식 입금전표 지금 실행' 버튼 (2026-08-28 사용자 요청).

약식(400*) 묶음전표는 17시 예약 회차에만 나간다 — 그 전에 필요하면 서버에
접속해 schtasks /run 을 손으로 쳤다. 그 한 줄을 화면 버튼으로 옮긴다.
배치 로직을 다시 돌리지 않고 예약 작업 자체를 즉시 실행한다(작업 스케줄러가
같은 작업의 중복 실행을 막아 주고, 로그도 한 곳에 쌓인다).
"""

from pathlib import Path

from app.routers.deposit_yak import _log_tail

ROOT = Path(__file__).resolve().parent.parent
ROUTER = (ROOT / "app" / "routers" / "deposit_yak.py").read_text(encoding="utf-8")


def test_라우터가_등록되어_있다():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "app.include_router(deposit_yak_router)" in main


def test_본사만_실행한다():
    """permissionManage 는 지사에게도 열린다 — 이 버튼은 실제 아마란스 전표를
    만드는 배치라 캐시 동기화와 같은 잣대로 본사만 허용한다(2026-08-17 전수조사
    이후 규칙)."""
    assert ROUTER.count("_head_office_only(_access)") == 2, (
        "실행·상태 두 곳이 본사로 안 막혔다"
    )
    assert 'require_menu("permissionManage")' in ROUTER


def test_배치를_다시_돌리지_않고_예약_작업을_실행한다():
    """서버 예약 작업 이름은 배포 스크립트가 등록하는 이름 그대로여야 한다."""
    assert '["schtasks", "/run", "/tn", TASK_NAME]' in ROUTER
    assert 'TASK_NAME = "A10Bridge_DepositVoucherYak"' in ROUTER
    redeploy = (ROOT / "scripts" / "server_redeploy.ps1").read_text(encoding="utf-8")
    assert 'schtasks /create /f /tn "A10Bridge_DepositVoucherYak"' in redeploy
    # 여기서 DepositVoucherService 를 직접 돌리면 17시 회차·매시간 회차와
    # 동시 실행될 수 있다 — 반드시 예약 작업 경유로 유지한다.
    assert "DepositVoucherService" not in ROUTER


def test_로그_꼬리는_마지막_줄만_돌려준다(tmp_path):
    log = tmp_path / "deposit_voucher_yak.log"
    lines = [f"오래된 줄 {n}" for n in range(20)] + [
        "입금 수집 2026-08-22~2026-08-28: 신규 3건 (전표대상 2 · 제외 1) · 기존 40건(재분류 0)",
        "전표 전송: 성공 1 · 보류 0 · 실패 0 · 약식·지사 이월 0",
    ]
    log.write_bytes(("\n".join(lines) + "\n").encode("cp949"))

    tail = _log_tail(log)
    assert tail["exists"] is True
    assert tail["updated_ts"] == log.stat().st_mtime
    assert len(tail["lines"]) == 6
    assert tail["lines"][-1].startswith("전표 전송:")


def test_로그가_없으면_없다고_답한다(tmp_path):
    tail = _log_tail(tmp_path / "없는파일.log")
    assert tail == {"exists": False, "updated_ts": None, "updated_at": None, "lines": []}


def test_화면에_버튼과_폴링이_있다():
    """권한 관리 화면은 permissions-preview 다 — 옛 permissions.html 은 라우트가
    끊긴 화면이라 거기 넣으면 아무도 못 본다(2026-08-28 실측)."""
    html = (ROOT / "desktop" / "ui" / "permissions-preview.html").read_text(
        encoding="utf-8"
    )
    assert 'id="yakRunSection"' in html
    assert 'id="yakRunButton"' in html
    assert 'id="yakStatus"' in html
    assert "permissions-preview.js?v=20260828-1" in html, (
        "JS 를 고쳤으면 ?v= 를 올려야 운영에 반영된다"
    )

    js = (ROOT / "desktop" / "ui" / "permissions-preview.js").read_text(encoding="utf-8")
    assert "/api/deposit-yak/run" in js
    assert "/api/deposit-yak/status" in js
    assert "실제 아마란스 전표가 생성됩니다" in js, "실전표를 만드는 버튼은 확인창이 있어야 한다"


def test_약식_카드는_본사_권한_블록_안에서만_열린다():
    """카드 노출은 전표 가져오기와 같은 잣대(본사 + permissionManage) — canSync
    검사를 지나야 hidden 이 벗겨져야 한다."""
    js = (ROOT / "desktop" / "ui" / "permissions-preview.js").read_text(encoding="utf-8")
    block = js[js.index("const canSync"):]
    block = block[:block.index("}).catch")]
    assert "yakRunSection" in block, "약식 카드가 권한 검사 밖에서 열린다"
    assert "$('yakRunButton').addEventListener('click', runYak)" in block
