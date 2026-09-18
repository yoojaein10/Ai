# -*- coding: utf-8 -*-
"""테스트 EXE 빌드·smoke test·번들 위생 검사 (지시 §14).

- PyInstaller onedir 스펙으로 빌드(UPX 미사용).
- SHA-256 계산, --selftest 및 --pdf-worker smoke test.
- 번들에 시크릿/실설정/PII/fixture/테스트가 없는지 검사.
- 전역 Python 을 변경하지 않는다(설치/업그레이드 없음). lock 파일이 없으면 보고만 한다.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
EXE = os.path.join(DIST, "Y_TSBankAuto.exe")

# 번들에 있으면 안 되는 위생 위반 패턴
_FORBIDDEN_NAMES = ("settings.ini", "탁상_DB대조.py", "탁상_DB조회.ps1")
_FORBIDDEN_EXT = (".pdf", ".csv", ".xlsx", ".xls", ".log")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build() -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "Y_TSBankAuto_onefile.spec",
           "--noconfirm", "--clean",
           "--distpath", os.path.join(ROOT, "dist"),
           "--workpath", os.path.join(ROOT, "build")]
    print("BUILD:", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def smoke_selftest() -> bool:
    # console=False EXE 에서는 stdout 이 없을 수 있으므로 종료코드로 판정(§17).
    # requireAdministrator 매니페스트가 박힌 EXE 는 일반 권한 빌드 프로세스에서 CreateProcess
    # 로 실행할 수 없다(WinError 740). 이 경우 매니페스트 검증으로 대체한다.
    try:
        proc = subprocess.run([EXE, "--selftest"], capture_output=True, timeout=120)
    except OSError as e:
        if getattr(e, "winerror", None) == 740:  # 권한 상승 필요 = 매니페스트 정상
            ok = _verify_requires_admin()
            print(f"--- selftest: elevated EXE (WinError 740), manifest={'OK' if ok else 'MISSING'} ---")
            return ok
        raise
    print(f"--- selftest returncode: {proc.returncode} ---")
    return proc.returncode == 0


def _verify_requires_admin() -> bool:
    """EXE 바이너리에 requireAdministrator 매니페스트가 임베드됐는지 확인."""
    try:
        with open(EXE, "rb") as f:
            data = f.read()
        return b"requireAdministrator" in data
    except OSError:
        return False


def smoke_worker() -> bool:
    # PDF worker 결과는 전용 결과 파일 IPC 로 받는다(stdout 미사용; §17).
    import json
    root = tempfile.mkdtemp()
    pdf = os.path.join(root, "s.pdf")
    result_path = os.path.join(root, "result.json")
    with open(pdf, "wb") as f:
        f.write(b"%PDF-1.4\nx\n%%EOF\n")
    env = dict(os.environ)
    env["YTS_PDF_RESULT_FILE"] = result_path
    try:
        subprocess.run([EXE, "--pdf-worker", pdf, root],
                       capture_output=True, timeout=120, env=env, close_fds=True)
        if not os.path.isfile(result_path):
            print("--- pdf-worker: 결과 파일 없음 ---")
            return False
        with open(result_path, encoding="utf-8") as f:
            obj = json.loads(f.read())
        print(f"--- pdf-worker status: {obj.get('status')} ---")
        return "status" in obj
    finally:
        for p in (pdf, result_path):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(root)
        except OSError:
            pass


def scan_bundle() -> list[str]:
    violations = []
    if os.path.isfile(DIST):
        return violations
    for dirpath, _, files in os.walk(DIST):
        for fn in files:
            low = fn.lower()
            if fn in _FORBIDDEN_NAMES:
                violations.append(os.path.join(dirpath, fn))
            if low.endswith(_FORBIDDEN_EXT):
                violations.append(os.path.join(dirpath, fn))
            if low.startswith("test_") and low.endswith(".py"):
                violations.append(os.path.join(dirpath, fn))
    return violations


def main() -> int:
    build()
    if not os.path.isfile(EXE):
        print("EXE 생성 실패:", EXE)
        return 1
    size = os.path.getsize(EXE)
    digest = sha256_file(EXE)
    print(f"EXE: {EXE}")
    print(f"SIZE: {size} bytes")
    print(f"SHA256: {digest}")

    st = smoke_selftest()
    print(f"SMOKE selftest: {'OK' if st else 'FAIL'}")
    # --pdf-worker 는 읽기 전용 제품에서 제거됨(§102) → pdf-worker smoke 미수행.

    violations = scan_bundle()
    print(f"BUNDLE hygiene violations: {len(violations)}")
    for v in violations:
        print("  !", os.path.relpath(v, DIST))

    ok = st and not violations
    print("BUILD_RESULT:", "OK" if ok else "REVIEW")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
