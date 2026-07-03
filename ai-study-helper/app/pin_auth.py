"""4자리 비밀번호(PIN) 기반 경량 사용자 시스템.

구글 OAuth 도입 전의 실용적 접근 통제:
- 등록: 4자리 PIN, 중복 불가 (PIN이 곧 계정이므로 두 사람이 같으면 안 됨)
- 입장: 등록된 PIN 입력 → user_id 세션 부여
- 격리: 사용자별 job 목록(users.json)으로 자기 자료만 보이게

저장: data/users.json — PIN은 해시로만 저장한다.
{"users": {"<sha256>": {"user_id": "u3f2a1c", "created": ..., "jobs": ["job_id", ...]}}}

한계(정직 표기): 4자리는 조합이 1만 개라 강한 보안은 아니다 — 지인 공유·데모
수준의 통제이며, 실서비스 전엔 OAuth(코드 준비됨)로 교체할 것.
"""

import hashlib
import json
import re
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config

USERS_PATH = config.DATA_DIR / "users.json"
WRONG_PIN_DELAY_SEC = 0.8  # 무차별 대입을 느리게 만드는 최소한의 방어


def _load() -> dict:
    if not USERS_PATH.exists():
        return {"users": {}}
    return json.loads(USERS_PATH.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERS_PATH)


def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"lecturemate:{pin}".encode()).hexdigest()


def validate_pin_format(pin: str) -> str | None:
    """형식 검사. 문제 없으면 None, 있으면 오류 메시지."""
    if not re.fullmatch(r"\d{4}", pin or ""):
        return "비밀번호는 숫자 4자리여야 합니다."
    return None


def register_pin(pin: str) -> tuple[str | None, str | None]:
    """새 PIN 등록. 반환 (user_id, 오류). 중복이면 오류.

    첫 번째 등록자는 기존(소유자 없는) 분석 자료를 모두 승계한다 —
    PIN 도입 전에 분석해둔 자료는 서비스 주인 것이기 때문.
    """
    if err := validate_pin_format(pin):
        return None, err
    data = _load()
    key = hash_pin(pin)
    if key in data["users"]:
        return None, "이미 사용 중인 비밀번호입니다. 다른 번호를 선택하세요."

    user_id = "u" + key[:8]
    jobs: list[str] = []
    if not data["users"]:  # 첫 사용자 — 기존 자료 승계
        jobs = existing_job_ids()
    data["users"][key] = {"user_id": user_id, "created": time.time(), "jobs": jobs}
    _save(data)
    return user_id, None


def verify_pin(pin: str) -> str | None:
    """PIN 확인. 맞으면 user_id, 틀리면 None (지연 포함)."""
    if validate_pin_format(pin):
        time.sleep(WRONG_PIN_DELAY_SEC)
        return None
    entry = _load()["users"].get(hash_pin(pin))
    if entry is None:
        time.sleep(WRONG_PIN_DELAY_SEC)
        return None
    return entry["user_id"]


def existing_job_ids() -> list[str]:
    if not config.JOBS_DIR.exists():
        return []
    return [p.parent.name for p in config.JOBS_DIR.glob("*/meta.json")]


def _find_user(data: dict, user_id: str) -> dict | None:
    for entry in data["users"].values():
        if entry["user_id"] == user_id:
            return entry
    return None


def get_user_jobs(user_id: str) -> list[str]:
    entry = _find_user(_load(), user_id)
    return list(entry["jobs"]) if entry else []


def add_user_job(user_id: str, job_id: str) -> None:
    """분석 완료된 job을 사용자 소유 목록에 추가 (중복 없이)."""
    data = _load()
    entry = _find_user(data, user_id)
    if entry is not None and job_id not in entry["jobs"]:
        entry["jobs"].append(job_id)
        _save(data)


def remove_user_job(user_id: str, job_id: str) -> None:
    """job을 사용자 목록에서 제거 (소유 해제)."""
    data = _load()
    entry = _find_user(data, user_id)
    if entry is not None and job_id in entry["jobs"]:
        entry["jobs"].remove(job_id)
        _save(data)


def job_owner_count(job_id: str) -> int:
    """이 job을 소유한 사용자 수 — 0이면 실제 파일을 지워도 안전하다."""
    return sum(1 for e in _load()["users"].values() if job_id in e["jobs"])


def delete_job(user_id: str, job_id: str) -> bool:
    """내 목록에서 삭제하고, 아무도 소유하지 않으면 데이터도 정리한다.

    같은 자료를 여러 사용자가 분석하면 캐시(job 폴더)를 공유하므로,
    남은 소유자가 있는 동안은 파일을 지우면 안 된다.
    반환: 실제 파일까지 삭제됐으면 True.
    """
    import shutil

    remove_user_job(user_id, job_id)
    if job_owner_count(job_id) > 0:
        return False
    for target in (config.JOBS_DIR / job_id, config.BASE_DIR / "vectorstore" / job_id):
        # Windows에서 벡터DB 파일이 열려 있으면 삭제가 실패할 수 있다 —
        # 소유 해제는 이미 됐으므로(보이지 않음) 실패해도 치명적이지 않다.
        shutil.rmtree(target, ignore_errors=True)
    return True
