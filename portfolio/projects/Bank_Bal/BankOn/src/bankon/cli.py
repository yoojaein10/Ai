"""명령행 진입점.

  python -m bankon.cli open <감정서번호>
      BANK24 실행 → 로그인 → 문서 검색 → '작 성(열람)' 폼 열기까지.
      폼을 열어 두기만 하고 값은 건드리지 않는다.

  python -m bankon.cli dump <감정서번호>
      위와 같되, 열린 폼의 현재 필드 값을 표로 출력한다(읽기 전용).

  python -m bankon.cli query
      작성 탭에서 담보·2026-08-18 하루 조건으로 목록만 조회한다.

  python -m bankon.cli rows [--from --to --work-type]
      감정서번호 없이 조회 목록을 행 단위로 훑어 출력한다(읽기 전용).

  python -m bankon.cli open --row 1 [--from --to --work-type]
      감정서번호 없이 조회 목록의 N번째 행을 열어 둔다(dump 도 같음).

자격증명·실행 명령은 `.env` 에서 읽는다(소스에 두지 않는다).
종료코드: 0=정상, 1=설정/화면 오류.
"""
from __future__ import annotations

import argparse
import sys

from .config import ConfigError, load_config
from .ui import driver, navigate


def _open(cfg, doc_id: str | None, *, write_tab: bool = False,
          date_from: str | None = None, scan: bool = False,
          row: int | None = None, date_to: str | None = None,
          work_type: str = "담보") -> driver.WindowRef:
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"메인 화면: {session.main.title}")
    if row is not None:
        # 감정서번호 없이: 작성 탭 → 조건 조회 → N번째 행 → 작성 폼(읽기 전용으로 열기만).
        if not navigate.select_tab(session, "작성"):
            raise navigate.NavigationError("작성 탭을 선택하지 못했습니다.")
        navigate.query_documents(
            session, start=date_from or "2026-08-18",
            end=date_to or date_from or "2026-08-18", work_type=work_type)
        navigate.close_forms(session)
        text = navigate.focus_row(session, row - 1)
        print(f"{row}번째 행 포커스: {text.strip().splitlines()[-1][:120]}")
        form = navigate.open_write_form(session, home=False)
        print(f"작성 폼: {form.class_name} — {form.title}")
        return form
    if not doc_id:
        raise navigate.NavigationError("감정서번호 또는 --row 중 하나는 있어야 합니다.")
    if write_tab:
        ok = navigate.select_tab(session, "작성")
        print(f"작성 탭 선택: {'OK' if ok else '실패(현재 탭으로 진행)'}")
    if date_from:
        navigate.set_date_range(session, date_from)
        print(f"조회시작일: {date_from}")
    if scan:
        # '찾 기'(전 기간 검색, 수 분) 대신 조회된 목록에서 행을 훑어 찾는다.
        navigate.close_forms(session)
        if not navigate.find_row_by_doc(session, doc_id):
            raise navigate.NavigationError(f"{doc_id} 행을 목록에서 찾지 못했습니다.")
        print("목록에서 대상 행 포커스 완료")
        form = navigate.open_write_form(session, home=False)
    else:
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


def _query(cfg, *, date_from: str, date_to: str, work_type: str,
           list_rows: bool = False) -> None:
    """대상 문서를 지정하지 않고 조건에 맞는 목록만 조회한다(옵션: 행 나열)."""
    session = navigate.open_app(cfg.loader_cmd, cfg.bankon_user, cfg.bankon_password)
    print(f"메인 화면: {session.main.title}")
    if not navigate.select_tab(session, "작성"):
        raise navigate.NavigationError("작성 탭을 선택하지 못했습니다.")
    navigate.query_documents(
        session, start=date_from, end=date_to, work_type=work_type)
    print(f"목록 조회 완료: 업무구분={work_type}, 기간={date_from}~{date_to}, 대상문서=없음")
    if list_rows:
        navigate.close_forms(session)
        rows = navigate.list_rows(session)
        for i, text in enumerate(rows, 1):
            data = [ln for ln in text.splitlines() if ln.strip()]
            cells = [c.strip() for c in data[-1].split(chr(9))] if data else []
            print(f"  [{i:3}] 셀 {len(cells):2}개 | " + " | ".join(cells)[:160])
        print(f"행 순회 결과: {len(rows)}행")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bankon")
    parser.add_argument("--env", default=None, help=".env 경로")
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, help_text in (("open", "작성 폼까지 열기"), ("dump", "열고 현재 값 출력")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("doc_id", nargs="?", default=None,
                       help="감정서번호 (예: 01-2608-3-2529). --row 를 쓰면 생략")
        p.add_argument("--row", type=int, default=None,
                       help="감정서번호 없이 조회 목록의 N번째 행(1부터)을 연다")
        p.add_argument("--to", dest="date_to", default=None,
                       help="--row 조회종료일 YYYY-MM-DD (기본: 조회시작일)")
        p.add_argument("--work-type", default="담보",
                       help="--row 업무구분 (기본: 담보)")
        p.add_argument("--write-tab", action="store_true",
                       help="검색 전에 작성 탭을 먼저 선택(미접수 탭에 남아 있을 때)")
        p.add_argument("--from", dest="date_from", default=None,
                       help="조회시작일 YYYY-MM-DD (오래된 건이 목록에 없을 때)")
        p.add_argument("--scan", action="store_true",
                       help="'찾 기' 대신 조회 목록을 행 단위로 훑어 문서를 찾는다")

    query = sub.add_parser("query", help="문서번호 없이 조건으로 목록만 조회")
    query.add_argument("--from", dest="date_from", default="2026-08-18",
                       help="조회시작일 YYYY-MM-DD (기본: 2026-08-18)")
    query.add_argument("--to", dest="date_to", default="2026-08-18",
                       help="조회종료일 YYYY-MM-DD (기본: 2026-08-18)")
    query.add_argument("--work-type", default="담보",
                       help="업무구분 (기본: 담보)")

    rows = sub.add_parser("rows", help="문서번호 없이 조회 목록을 행 단위로 나열")
    rows.add_argument("--from", dest="date_from", default="2026-08-18")
    rows.add_argument("--to", dest="date_to", default="2026-08-18")
    rows.add_argument("--work-type", default="담보")

    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.env)
    except ConfigError as error:
        print(f"[설정 오류] {error}", file=sys.stderr)
        return 1

    try:
        if args.cmd in ("query", "rows"):
            _query(cfg, date_from=args.date_from, date_to=args.date_to,
                   work_type=args.work_type, list_rows=args.cmd == "rows")
        else:
            form = _open(cfg, args.doc_id, write_tab=args.write_tab,
                         date_from=args.date_from, scan=args.scan,
                         row=args.row, date_to=args.date_to,
                         work_type=args.work_type)
            if args.cmd == "dump":
                _dump(form)
    except (navigate.NavigationError, driver.UiTimeout, driver.ValueRejected) as error:
        print(f"[화면 오류] {error}", file=sys.stderr)
        return 1
    except RuntimeError as error:
        if "Not enough rights" in str(error):
            print("[권한 오류] BANK24 화면 제어에는 관리자 권한이 필요합니다.",
                  file=sys.stderr)
            return 1
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
