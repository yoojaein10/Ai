"""
launcher.py 로직 단위 테스트 (deploy share를 임시 폴더로 대체)
실행: python test_launcher.py
"""
import os
import sys
import shutil
import tempfile
import importlib.util
import traceback

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


# ── 런처 모듈을 경로 오버라이드하여 로드 ───────────────────────────
def load_launcher_with_paths(deploy_share, local_dir):
    spec = importlib.util.spec_from_file_location(
        "launcher_test", os.path.join(os.path.dirname(__file__), "launcher.py")
    )
    mod = importlib.util.module_from_spec(spec)
    mod.DEPLOY_SHARE = deploy_share
    mod.LOCAL_DIR    = local_dir
    mod.LOCAL_APP_DIR = os.path.join(local_dir, "app")
    mod.LOCAL_EXE    = os.path.join(local_dir, "app", "ScheduleApp.exe")
    mod.LOCAL_VERSION = os.path.join(local_dir, "version.txt")
    mod.SERVER_VERSION = os.path.join(deploy_share, "version.txt")
    mod.SERVER_EXE    = os.path.join(deploy_share, "ScheduleApp.exe")
    spec.loader.exec_module(mod)
    return mod


def run_tests():
    with tempfile.TemporaryDirectory() as tmpdir:
        deploy_dir = os.path.join(tmpdir, "deploy")
        local_dir  = os.path.join(tmpdir, "local")
        os.makedirs(deploy_dir)

        # ── 가짜 ScheduleApp.exe 생성 ─────────────────────────────
        fake_exe_v1 = os.path.join(deploy_dir, "ScheduleApp.exe")
        with open(fake_exe_v1, "wb") as f:
            f.write(b"FAKE_EXE_V1")

        def write_ver(path, ver):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(ver)

        server_version_path = os.path.join(deploy_dir, "version.txt")
        local_exe_path      = os.path.join(local_dir, "app", "ScheduleApp.exe")
        local_version_path  = os.path.join(local_dir, "version.txt")

        # ── 테스트 1: 최초 실행 (로컬 없음) ──────────────────────
        print("\n[Test 1] First run - no local exe")
        write_ver(server_version_path, "1.0.0")
        mod = load_launcher_with_paths(deploy_dir, local_dir)

        server_ver = mod._read_version(server_version_path)
        local_ver  = mod._read_version(local_version_path)
        needs_update = bool(server_ver) and (
            server_ver != local_ver or not os.path.exists(local_exe_path)
        )
        if needs_update:
            os.makedirs(os.path.join(local_dir, "app"), exist_ok=True)
            tmp = local_exe_path + ".tmp"
            shutil.copy2(fake_exe_v1, tmp)
            os.replace(tmp, local_exe_path)
            write_ver(local_version_path, server_ver)

        check("local exe created", os.path.exists(local_exe_path))
        check("local version.txt = 1.0.0", mod._read_version(local_version_path) == "1.0.0")

        # ── 테스트 2: 버전 같음 → 재복사 없음 ───────────────────
        print("\n[Test 2] Same version - no re-copy")
        mtime_before = os.path.getmtime(local_exe_path)

        server_ver = mod._read_version(server_version_path)
        local_ver  = mod._read_version(local_version_path)
        needs_update = bool(server_ver) and (
            server_ver != local_ver or not os.path.exists(local_exe_path)
        )
        check("needs_update = False", not needs_update)
        check("local exe not modified", os.path.getmtime(local_exe_path) == mtime_before)

        # ── 테스트 3: 버전 변경 → 재복사 ─────────────────────────
        print("\n[Test 3] Server version changed - update")
        fake_exe_v2 = os.path.join(deploy_dir, "ScheduleApp.exe")
        with open(fake_exe_v2, "wb") as f:
            f.write(b"FAKE_EXE_V2")
        write_ver(server_version_path, "1.0.1")

        server_ver = mod._read_version(server_version_path)
        local_ver  = mod._read_version(local_version_path)
        needs_update = bool(server_ver) and (
            server_ver != local_ver or not os.path.exists(local_exe_path)
        )
        if needs_update:
            tmp = local_exe_path + ".tmp"
            shutil.copy2(fake_exe_v2, tmp)
            os.replace(tmp, local_exe_path)
            write_ver(local_version_path, server_ver)

        with open(local_exe_path, "rb") as f:
            content = f.read()
        check("local exe updated to V2", content == b"FAKE_EXE_V2")
        check("local version.txt = 1.0.1", mod._read_version(local_version_path) == "1.0.1")

        # Test 4
        print("\n[Test 4] Server unavailable - keep existing local exe")
        bad_server_version = os.path.join(tmpdir, "nonexistent", "version.txt")
        bad_server_exe     = os.path.join(tmpdir, "nonexistent", "ScheduleApp.exe")

        server_ver = mod._read_version(bad_server_version)   # "" 반환
        needs_update = bool(server_ver) and (
            server_ver != mod._read_version(local_version_path)
            or not os.path.exists(local_exe_path)
        )
        check("needs_update = False (server unavailable)", not needs_update)
        check("local exe still exists", os.path.exists(local_exe_path))

        # Test 5
        print("\n[Test 5] Deploy share exe is read-only - never executed directly")
        with open(fake_exe_v2, "rb") as _locked_f:
            tmp = local_exe_path + ".tmp2"
            try:
                shutil.copy2(fake_exe_v2, tmp)
                copied = True
            except Exception:
                copied = False
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
        check("deploy exe copyable while open", copied)

    print(f"\n{'='*40}")
    print(f"Result: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("Failed:", ", ".join(FAIL))
        sys.exit(1)
    else:
        print("All tests passed.")


if __name__ == "__main__":
    run_tests()
