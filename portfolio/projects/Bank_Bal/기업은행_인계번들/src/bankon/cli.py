"""명령행 진입점.

  python -m bankon.cli open <감정서번호>
      BANK24 실행 → 로그인 → 문서 검색 → '작 성(열람)' 폼 열기까지.
      폼을 열어 두기만 하고 값은 건드리지 않는다.

  python -m bankon.cli dump <감정서번호>
      위와 같되, 열린 폼의 현재 필드 값을 표로 출력한다(읽기 전용).

자격증명·실행 명령은 `.env` 에서 읽는다(소스에 두지 않는다).
종료코드: 0=정상, 1=설정/화면 오류.
"""
from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
from .ui import driver, navigate


def _open(cfg, doc_id: str) -> driver.WindowRef:
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"메인 화면: {session.main.title}")
    form = navigate.open_document(session, doc_id)
    print(f"작성 폼: {form.class_name} — {form.title}")
    return form


def _dump(form: driver.WindowRef) -> None:
    """열린 폼의 값 있는 필드를 훑어 보여준다(진단용)."""
    values = []
    for control in driver.descendants(form.handle):
        try:
            name = control.element_info.class_name or ""
        except Exception:
            continue
        if not name.startswith("TcxDB") or "Inner" in name:
            continue
        value = driver.read(control)
        if value:
            rect = driver._rect(control)
            values.append((rect.top if rect else 0, rect.left if rect else 0, name, value))
    for top, left, name, value in sorted(values):
        print(f"  @{left},{top:<5} {name:24} {value[:48]}")
    print(f"값이 있는 필드: {len(values)}개")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bankon")
    parser.add_argument("--env", default=None, help=".env 경로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, help_text in (("open", "작성 폼까지 열기"), ("dump", "열고 현재 값 출력")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("doc_id", help="감정서번호 (예: 01-2608-3-2529)")

    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.env)
    except ConfigError as error:
        print(f"[설정 오류] {error}", file=sys.stderr)
        return 1

    try:
        form = _open(cfg, args.doc_id)
        if args.cmd == "dump":
            _dump(form)
    except (navigate.NavigationError, driver.UiTimeout, driver.ValueRejected) as error:
        print(f"[화면 오류] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
