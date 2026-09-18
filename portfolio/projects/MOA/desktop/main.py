"""A10 Bridge thin 데스크톱 클라이언트.

중앙 서버가 UI/API/DB를 전부 담당하고, 이 EXE는 pywebview 창만 띄운다.
- 설정: exe 옆 A10BridgeDesktop.ini ([server] url = http://서버:8010)
- 인자: --usr-seq "APWorks 로그인 사용자 USR_SEQ" (APWorks가 ShellExecute로 전달)
  값은 TMWCMN_USR_BAC_INFO.USR_SEQ(숫자, 유일). --usr-id는 과거 호환용 별칭.
  APWorks 연동 전 테스트용으로 ini의 [user] default_usr_seq를 대신 쓸 수 있다.
- 단일 실행: named mutex — 이미 실행 중이면 기존 창을 앞으로 가져오고 종료
"""

import argparse
import configparser
import ctypes
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

# WINDOW_TITLE은 단일 실행 시 FindWindowW로 기존 창을 찾는 유일한 식별자다.
# 창 제목을 바꾸면 기존 창 활성화가 깨지므로 반드시 함께 관리할 것.
WINDOW_TITLE = "MOA"
MUTEX_NAME = "A10BridgeDesktop_SingleInstance"
INI_NAME = "A10BridgeDesktop.ini"
USR_SEQ_PATTERN = re.compile(r"^[0-9]{1,10}$")
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
DOWNLOAD_DIR_NAME = "MOA"   # %TEMP%\MOA — 엑셀 내보내기를 여는 임시 폴더
DOWNLOAD_KEEP_DAYS = 7


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def fatal(message: str) -> None:
    """GUI 빌드(console=False)에서는 stderr가 보이지 않으므로 메시지박스로 알린다."""
    ctypes.windll.user32.MessageBoxW(None, message, WINDOW_TITLE, 0x10)
    sys.exit(1)


def parse_usr_seq(default_usr_seq: str) -> str:
    parser = argparse.ArgumentParser(add_help=False)
    # --usr-id는 초기 연동안의 이름이라 별칭으로 계속 받아준다.
    parser.add_argument("--usr-seq", "--usr-id", dest="usr_seq", default="")
    args, _unknown = parser.parse_known_args()
    usr_seq = args.usr_seq.strip() or default_usr_seq
    if not usr_seq:
        return ""  # usr 없이 열면 웹 로그인창(MOA 로그인)이 뜬다
    if not USR_SEQ_PATTERN.fullmatch(usr_seq):
        fatal(f"사용자 번호(USR_SEQ) 형식이 올바르지 않습니다: {usr_seq}")
    return usr_seq


def load_config() -> tuple[str, str]:
    """ini에서 서버 주소와 기본 사용자 번호(USR_SEQ)를 읽는다."""
    ini_path = base_dir() / INI_NAME
    if not ini_path.exists():
        fatal(
            f"설정 파일을 찾을 수 없습니다.\n\n"
            f"실행 파일과 같은 폴더에 {INI_NAME}을 만들어 주세요:\n{base_dir()}\n\n"
            '내용 예시:\n[server]\nurl = http://192.0.2.10:8010'
        )
    parser = configparser.ConfigParser()
    # 메모장이 UTF-8 저장 시 BOM을 붙이므로 utf-8-sig로 읽는다.
    parser.read(ini_path, encoding="utf-8-sig")
    url = parser.get("server", "url", fallback="").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        fatal(
            f"{INI_NAME}의 서버 주소가 올바르지 않습니다.\n\n"
            '내용 예시:\n[server]\nurl = http://192.0.2.10:8010'
        )
    default_usr_seq = (
        parser.get("user", "default_usr_seq", fallback="").strip()
        or parser.get("user", "default_usr_id", fallback="").strip()  # 구버전 ini 호환
    )
    return url, default_usr_seq


def ensure_single_instance() -> int:
    """중복 실행이면 기존 창을 활성화하고 종료. mutex 핸들은 프로세스 생존 동안 유지."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
        sys.exit(0)
    return handle


def content_filename(header: "str | None") -> str:
    """Content-Disposition에서 파일명을 뽑는다 (RFC 5987 한글 파일명 우선)."""
    header = header or ""
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", header, re.IGNORECASE)
    if encoded:
        return urllib.parse.unquote(encoded.group(1).strip())
    plain = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    return plain.group(1).strip() if plain else "export.xlsx"


def download_dir() -> Path:
    """엑셀 내보내기를 여는 임시 폴더 — 보관은 사용자가 엑셀에서 '다른 이름으로 저장'으로 한다."""
    return Path(tempfile.gettempdir()) / DOWNLOAD_DIR_NAME


def unique_path(directory: Path, filename: str) -> Path:
    """같은 이름이 있으면 (2), (3)… 을 붙인다 — 엑셀이 열어 둔 파일은 덮어쓸 수 없다."""
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = directory / filename
    number = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def prune_old(directory: Path, *, keep_days: int = DOWNLOAD_KEEP_DAYS, now: "float | None" = None) -> int:
    """keep_days 보다 오래된 임시 파일을 지운다. 열려 있어 못 지우는 파일은 건너뛴다."""
    if not directory.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - keep_days * 86400
    removed = 0
    for file in directory.iterdir():
        try:
            if file.is_file() and file.stat().st_mtime < cutoff:
                file.unlink()
                removed += 1
        except OSError:
            continue
    return removed


class DesktopApi:
    """화면(JS)에서 부르는 브리지.

    pywebview 창은 브라우저처럼 파일 다운로드를 처리하지 못해 엑셀 내보내기가
    아무 반응 없이 끝난다. 그래서 파이썬이 직접 받아 임시 폴더에 두고 바로 엑셀로 연다
    (2026-08-27: 저장 대화상자 → 저장 → 직접 열던 흐름을 "열고, 원하면 저장"으로).
    """

    def __init__(self, server_url: str) -> None:
        self._server_url = server_url

    def download(self, path: str) -> str:
        if not path.startswith("/"):
            return "잘못된 내려받기 요청입니다."
        try:
            with urllib.request.urlopen(self._server_url + path, timeout=180) as response:
                data = response.read()
                filename = content_filename(response.headers.get("Content-Disposition"))
        except OSError as error:
            return f"내려받지 못했습니다: {error}"
        directory = download_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            prune_old(directory)
            target = unique_path(directory, filename)
            target.write_bytes(data)
            os.startfile(str(target))  # 연결 프로그램(엑셀)으로 연다
        except OSError as error:
            return f"열지 못했습니다: {error}"
        return f"열었습니다: {target.name} — 보관하려면 엑셀에서 '다른 이름으로 저장'"


def wait_server(server_url: str, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"{server_url}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def main() -> None:
    server_url, default_usr_seq = load_config()
    usr_seq = parse_usr_seq(default_usr_seq)
    _mutex = ensure_single_instance()

    if not wait_server(server_url):
        fatal(
            f"서버({server_url})에 연결할 수 없습니다.\n\n"
            "사내망 연결 상태를 확인하고, 계속되면 전산팀에 문의해 주세요."
        )

    import webview

    url = f"{server_url}/desktop"
    if usr_seq:
        url += f"?usr={urllib.parse.quote(usr_seq)}"
    webview.create_window(
        WINDOW_TITLE,
        url,
        js_api=DesktopApi(server_url),
        width=1480,
        height=900,
        min_size=(1100, 700),
    )
    webview.start()


if __name__ == "__main__":
    main()
