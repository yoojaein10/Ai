# -*- coding: utf-8 -*-
"""격리 PDF 파싱 worker (지시 §6, §11, §11-a).

- 자격증명을 제거한 별도 프로세스에서 파싱한다(DB/Bank24 자격증명·실자동화 스위치 미상속).
- Windows Job Object 로 프로세스·Job 메모리, CPU 시간, KILL_ON_JOB_CLOSE 를 제한한다.
  CREATE_SUSPENDED 로 생성 → Job 할당 성공 후에만 resume. 실패 시 resume 없이 종료.
- 핸들 비상속(close_fds), shell 미사용, 명시적 실행체 경로 검증.
- 실행 timeout, 페이지 수·추출 문자 수 상한 적용(추출 계층).
- PDF 내용으로 eval/스크립트/외부 프로그램을 실행하지 않는다.
- 결과는 stdout JSON 대신 길이 제한·schema 검증된 전용 결과 파일로 받는다(가능 시).
- 출력은 마스킹된 요약 JSON 만(원문 PII 미포함).
- Job Object 가 네트워크를 차단한다고 주장하지 않는다. worker 코드에서 네트워크 API 를
  호출하지 않도록 고정하고 테스트로 확인한다.

이 모듈은 CLI 로도(`python pdf_worker.py <path>`) 실행되며, 오케스트레이터가 스크럽된
환경·timeout 으로 subprocess 호출한다. 프로즌 EXE 에서는 main_app 이 --pdf-worker 로 위임한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import config
import ro_config

# 격리 worker 에서 제거할 시크릿/스위치 환경변수
_SCRUB_ENV = (
    config.ENV_BANK24_ID, config.ENV_BANK24_PASSWORD,
    "YTS_ENABLE_BANK24_AUTOMATION",
)

# 결과 파일 IPC (경로만; 시크릿 아님)
ENV_RESULT_FILE = "YTS_PDF_RESULT_FILE"
MAX_RESULT_BYTES = 64 * 1024               # 결과 길이 상한
# Job Object 자원 상한
WORKER_MEM_LIMIT = 512 * 1024 * 1024       # 프로세스/Job 메모리 512MB
WORKER_CPU_SECONDS = 30                     # 프로세스 CPU 시간 상한

_ALLOWED_RESULT_KEYS = {
    "status", "bank", "eligible", "reasons", "unit_count", "multi_unit",
    "model", "field_presence", "error", "code",
}


def validate_result_obj(obj) -> dict:
    """worker 결과 schema 검증: dict + status(str) 필수, 알려진 키만 허용."""
    if not isinstance(obj, dict):
        return {"status": "worker_output_invalid"}
    status = obj.get("status")
    if not isinstance(status, str) or not status:
        return {"status": "worker_output_invalid"}
    if not set(obj.keys()).issubset(_ALLOWED_RESULT_KEYS):
        return {"status": "worker_output_invalid"}
    return obj


def scrubbed_child_env(environ: dict | None = None) -> dict:
    """DB 자격증명·통합스위치·Bank24 자격증명·자동화 스위치를 제거한 자식 환경 사본."""
    env = ro_config.child_env_without_db_secrets(environ)
    for name in _SCRUB_ENV:
        env.pop(name, None)
    return env


def parse_to_masked(path: str, allowed_roots: list[str],
                    *, extractor=None, preparer=None) -> dict:
    """PDF → 마스킹 요약 dict. 원문 PII 미포함. 실패는 상태로 반환한다."""
    import security
    try:
        security.validate_pdf_file(path, allowed_roots=allowed_roots)
    except Exception as e:
        return {"status": "pdf_invalid", "error": type(e).__name__}

    if extractor is None:
        from parsers import base
        extractor = lambda p: base.extract_lines(p, allowed_roots=allowed_roots)
    if preparer is None:
        import pipeline
        preparer = pipeline.prepare

    try:
        lines = extractor(path)
    except Exception as e:
        return {"status": "extract_failed", "error": type(e).__name__}

    try:
        pr = preparer(lines)
    except Exception as e:
        return {"status": "parse_failed", "error": type(e).__name__}

    return {
        "status": "parsed",
        "bank": pr.model.bank,
        "eligible": pr.eligible,
        "reasons": pr.reasons,
        "unit_count": len(pr.model.addresses),
        "multi_unit": len(pr.model.addresses) > 1,      # 대표 물건 정책 GUI 표시용
        "model": pr.model.safe_log_dict(),               # 마스킹
        "field_presence": pr.model.field_presence(),     # PII 제외 존재여부
    }


def _read_result_file(result_path: str) -> dict | None:
    """결과 파일을 길이 상한·schema 검증하며 읽는다. 없거나 위반이면 None."""
    try:
        if os.path.getsize(result_path) > MAX_RESULT_BYTES:
            return {"status": "worker_output_invalid"}
        with open(result_path, "r", encoding="utf-8") as f:
            data = f.read(MAX_RESULT_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_RESULT_BYTES:
        return {"status": "worker_output_invalid"}
    try:
        return validate_result_obj(json.loads(data))
    except Exception:
        return {"status": "worker_output_invalid"}


def _run_jobbed(exe: str, cmd: list[str], env: dict, timeout: float) -> int:
    """CREATE_SUSPENDED 로 생성 → Job Object 자원 제한 할당 성공 후 resume.

    반환: 종료코드. 실패/미가용이면 NotImplementedError 로 상위가 fallback 하게 한다.
    할당 실패 시 resume 하지 않고 프로세스를 종료한다.
    """
    try:
        import win32event
        import win32job
        import win32process
        import winerror  # noqa: F401
    except Exception as e:
        raise NotImplementedError("pywin32 미가용") from e

    flags = (win32process.CREATE_SUSPENDED |
             getattr(win32process, "CREATE_NO_WINDOW", 0) |
             getattr(win32process, "CREATE_UNICODE_ENVIRONMENT", 0x400))
    si = win32process.STARTUPINFO()
    cmdline = subprocess.list2cmdline(cmd)
    hProcess = hThread = None
    job = None
    try:
        # bInheritHandles=False → 핸들 비상속
        hProcess, hThread, _pid, _tid = win32process.CreateProcess(
            exe, cmdline, None, None, False, flags, env, None, si)

        job = win32job.CreateJobObject(None, "")   # 익명 Job
        info = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation)
        basic = info["BasicLimitInformation"]
        basic["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY |
            win32job.JOB_OBJECT_LIMIT_JOB_MEMORY |
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
            win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS |
            win32job.JOB_OBJECT_LIMIT_PROCESS_TIME)
        basic["ActiveProcessLimit"] = 1
        # PerProcessUserTimeLimit: 100ns 단위
        basic["PerProcessUserTimeLimit"] = int(WORKER_CPU_SECONDS * 10_000_000)
        info["BasicLimitInformation"] = basic
        info["ProcessMemoryLimit"] = WORKER_MEM_LIMIT
        info["JobMemoryLimit"] = WORKER_MEM_LIMIT
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, info)

        # 반드시 할당 성공 후에만 resume
        win32job.AssignProcessToJobObject(job, hProcess)
        win32process.ResumeThread(hThread)

        wait = win32event.WaitForSingleObject(hProcess, int(timeout * 1000))
        if wait != win32event.WAIT_OBJECT_0:
            win32process.TerminateProcess(hProcess, 1)   # timeout → 강제 종료
            return 1
        return win32process.GetExitCodeProcess(hProcess)
    finally:
        # Job 핸들 close → KILL_ON_JOB_CLOSE 로 잔여 프로세스 정리
        for h in (hThread, hProcess, job):
            try:
                if h is not None:
                    import win32api
                    win32api.CloseHandle(h)
            except Exception:
                pass


def run_isolated(path: str, allowed_roots: list[str], *,
                 timeout: float = 30.0, environ: dict | None = None,
                 python_exe: str | None = None) -> dict:
    """스크럽 환경·timeout·Job Object 로 worker subprocess 실행. DB/Bank24 시크릿 미상속.

    결과는 전용 결과 파일(길이·schema 검증)로 받고, 없으면 stdout 최종 라인으로 보완한다.
    """
    import tempfile

    env = scrubbed_child_env(environ)
    exe = python_exe or sys.executable
    if not exe or not os.path.isfile(exe):
        return {"status": "worker_exe_invalid"}   # 실행체 경로 검증

    result_dir = tempfile.mkdtemp(prefix="yts_pw_")
    result_path = os.path.join(result_dir, "result.json")
    env[ENV_RESULT_FILE] = result_path

    if getattr(sys, "frozen", False):
        cmd = [exe, "--pdf-worker", path, *allowed_roots]
    else:
        cmd = [exe, os.path.abspath(__file__), path, *allowed_roots]

    stdout_text = ""
    try:
        # 1) Job Object 경로 우선(Windows/pywin32). 실패 시 subprocess fallback.
        try:
            rc = _run_jobbed(exe, cmd, env, timeout)
            code = rc
        except NotImplementedError:
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, env=env,
                    timeout=timeout, check=False, shell=False, close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired:
                return {"status": "timeout"}
            code = proc.returncode
            stdout_text = proc.stdout or ""

        # 2) 결과 파일 우선
        res = _read_result_file(result_path)
        if res is not None:
            return res
        # 3) stdout 보완(fallback 경로에서만 값이 있음)
        if stdout_text.strip():
            try:
                return validate_result_obj(
                    json.loads(stdout_text.strip().splitlines()[-1]))
            except Exception:
                return {"status": "worker_output_invalid"}
        if code != 0:
            return {"status": "worker_error", "code": code}
        return {"status": "worker_output_invalid"}
    finally:
        try:
            if os.path.isfile(result_path):
                os.remove(result_path)
            os.rmdir(result_dir)
        except OSError:
            pass


def _write_result_file(result_path: str, payload: str) -> None:
    """결과를 전용 파일에 exclusive-create 로 기록(길이 상한 준수)."""
    if len(payload) > MAX_RESULT_BYTES:
        payload = json.dumps({"status": "worker_output_invalid"})
    fd = os.open(result_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({"status": "usage_error"}))
        return 2
    path = argv[1]
    allowed_roots = list(argv[2:])
    result = parse_to_masked(path, allowed_roots)
    payload = json.dumps(result, ensure_ascii=True)
    # 전용 결과 파일 IPC (설정된 경우). stdout 은 하위호환·smoke 용으로 유지.
    result_path = os.environ.get(ENV_RESULT_FILE)
    if result_path:
        try:
            _write_result_file(result_path, payload)
        except OSError:
            pass
    print(payload)
    return 0 if result.get("status") == "parsed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
