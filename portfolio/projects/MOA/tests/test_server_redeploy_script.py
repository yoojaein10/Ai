"""서버 재배포 스크립트가 배치를 조용히 건너뛰지 않는지 (2026-08-21).

거래처 캐시가 서버에 안 걸려 있던 이유가 이거였다. `$hasPartnerCache` 를
어디에도 정의하지 않아 PowerShell 이 $null 로 보고 `if ($hasPartnerCache)` 를
그냥 지나쳤다. 오류도 안 나고 "[7/7] 배포 성공" 이 찍혀서, 스크립트를 돌려도
아무 일이 안 일어난다는 걸 알 방법이 없었다.

PowerShell 은 없는 변수를 오류로 안 본다(StrictMode 를 안 켰다). 그래서
변수 이름을 눈으로 맞추는 대신 시험으로 잠근다.
"""

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "server_redeploy.ps1"
BODY = SCRIPT.read_text(encoding="utf-8")


def _assigned(prefix: str) -> "set[str]":
    return set(re.findall(rf"\$({prefix}\w+)\s*=", BODY))


def test_배치_존재여부_변수는_모두_정의돼_있다():
    """정의 안 된 변수는 $null 이라 그 배치가 통째로 안 걸린다."""
    used = set(re.findall(r"if \(\$(has\w+)\)", BODY))
    missing = used - _assigned("has")

    assert not missing, (
        f"정의되지 않은 조건 변수: {sorted(missing)} — "
        "PowerShell 이 $null 로 보고 해당 배치를 조용히 건너뛴다"
    )


def test_실행_래퍼_경로_변수도_모두_정의돼_있다():
    """$run... 이 비면 Set-Content 가 빈 경로로 터지거나 엉뚱한 곳에 쓴다."""
    used = set(re.findall(r"\$(run\w+)\b", BODY))
    missing = used - _assigned("run")

    assert not missing, f"정의되지 않은 경로 변수: {sorted(missing)}"


def test_거래처_캐시가_실제로_등록된다():
    """카드전표 가맹점 조회가 이 캐시에 걸려 있다 — 없으면 불러오기가 2초에서 2분이 된다."""
    assert '$hasPartnerCache = Test-Path (Join-Path $InstallDir "app\\batch\\partner_cache_sync.py")' in BODY
    assert '$runPartnerCache = Join-Path $InstallDir "scripts\\run_partner_cache.cmd"' in BODY
    assert 'schtasks /create /f /tn "A10Bridge_PartnerCache"' in BODY
    assert "app.batch.partner_cache_sync" in BODY


def test_거래처_캐시를_배포_직후_한_번_돌린다():
    """다음 04:20 까지 기다리면 그 사이 캐시가 36시간을 넘겨 화면이 느려진다."""
    tail = BODY[BODY.index("[7/7] 배포 성공"):]
    assert 'schtasks /run /tn "A10Bridge_PartnerCache"' in tail


def test_배치는_배포_중에_멈춰_둔다():
    """배포 도중 배치가 뜨면 반쯤 갈아끼운 코드로 돈다."""
    head = BODY[:BODY.index("# 2. zip 반영")]
    for task in ("A10Bridge_PartnerCache", "A10Bridge_DepositVoucher",
                 "A10Bridge_FeeBasisPrepare", "A10Bridge_CacheSync"):
        assert f'Disable-A10TaskIfExists "{task}"' in head, f"{task} 를 안 멈춘다"


def test_등록한_배치는_반드시_다시_켠다():
    """1단계에서 끈 작업을 6단계에서 안 켜면 그날부터 조용히 안 돈다."""
    disabled = set(re.findall(r'Disable-A10TaskIfExists "(A10Bridge_\w+)"', BODY))
    enabled = set(re.findall(r'schtasks /change /tn "(A10Bridge_\w+)" /enable', BODY))
    # /create 는 활성 상태로 만들어지므로 create 만 있는 것도 켜진 것으로 본다
    created = set(re.findall(r'schtasks /create /f /tn "?\$?(\w+)"?', BODY))
    removed = set(re.findall(r'Remove-A10TaskIfExists "(A10Bridge_\w+)"', BODY))
    # 변수로 이름을 넘기는 두 개는 별도로 확인한다
    created |= {"A10Bridge_CacheSync", "A10Bridge_CacheSyncYear"}

    stuck = disabled - enabled - created - removed
    assert not stuck, f"껐다가 다시 안 켜는 작업: {sorted(stuck)}"
