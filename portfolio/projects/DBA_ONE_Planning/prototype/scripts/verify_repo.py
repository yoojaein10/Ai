"""저장소 위생 점검 — 비밀·데이터 파일이 git ignore 대상인지 확인한다.

실행: python scripts/verify_repo.py   (prototype 디렉터리 기준)
git이 없거나 저장소가 아니면(소스 압축본 등) 명확히 SKIP 하고 0으로 종료한다.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # prototype/
SECRET_FILES = ["config.json", "history.db", "audit.log", "knowledge.json",
                "history_backup_20990101_000000.db", "__pycache__/app.cpython-312.pyc"]


def main() -> int:
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("SKIP: git을 찾을 수 없음")
        return 0
    if top.returncode != 0:
        print("SKIP: git 저장소가 아님 (소스 압축본으로 실행 중?)")
        return 0
    missing = []
    for name in SECRET_FILES:
        r = subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT)
        if r.returncode != 0:
            missing.append(name)
    if missing:
        print("FAIL: 다음 파일이 git ignore 대상이 아님 — 커밋되면 비밀·데이터가 노출됩니다:")
        for name in missing:
            print("  -", name)
        return 1
    print("OK: 비밀·데이터 파일 전부 ignore 확인:", ", ".join(SECRET_FILES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
