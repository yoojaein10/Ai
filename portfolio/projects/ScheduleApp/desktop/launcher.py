import sys
import os
import shutil
import subprocess
import ctypes

DEPLOY_SHARE = r"\\server\DATA1\전산\SEAT\ScheduleAppDeploy"
LOCAL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ScheduleApp")
LOCAL_APP_DIR = os.path.join(LOCAL_DIR, "app")
LOCAL_EXE = os.path.join(LOCAL_APP_DIR, "ScheduleApp.exe")
LOCAL_VERSION = os.path.join(LOCAL_DIR, "version.txt")
SERVER_VERSION = os.path.join(DEPLOY_SHARE, "version.txt")
SERVER_EXE = os.path.join(DEPLOY_SHARE, "ScheduleApp.exe")


def _read_version(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _show_error(msg):
    ctypes.windll.user32.MessageBoxW(0, msg, "ScheduleLauncher", 0x10)


def main():
    empno = sys.argv[1] if len(sys.argv) > 1 else ""

    os.makedirs(LOCAL_APP_DIR, exist_ok=True)

    server_ver = _read_version(SERVER_VERSION)
    local_ver = _read_version(LOCAL_VERSION)

    needs_update = bool(server_ver) and (
        server_ver != local_ver or not os.path.exists(LOCAL_EXE)
    )

    if needs_update:
        tmp_exe = LOCAL_EXE + ".tmp"
        try:
            shutil.copy2(SERVER_EXE, tmp_exe)
            # PyInstaller onefile exe는 실행 후 temp로 추출되므로
            # LOCAL_EXE 자체는 잠기지 않아 replace 가능
            os.replace(tmp_exe, LOCAL_EXE)
            with open(LOCAL_VERSION, "w", encoding="utf-8") as f:
                f.write(server_ver)
        except Exception:
            # 복사/교체 실패 → 기존 버전으로 계속 실행
            if os.path.exists(tmp_exe):
                try:
                    os.remove(tmp_exe)
                except Exception:
                    pass

    if not os.path.exists(LOCAL_EXE):
        _show_error(
            "ScheduleApp을 실행할 수 없습니다.\n"
            "네트워크 연결을 확인하거나 관리자에게 문의하세요."
        )
        return

    args = [LOCAL_EXE]
    if empno:
        args.append(empno)
    subprocess.Popen(args)


if __name__ == "__main__":
    main()
