"""문서를 열어 그 은행 담보 폼의 **항목표**를 뜬다(정찰 1+2단계 자동화).

`inspect_bankon list` → `map_fields --handle …` 를 손으로 잇던 걸 한 번에 한다.
BANK24 에 로그인해 조회 화면이 떠 있으면, 문서번호로 찾아 '작 성(열람)' 으로 폼을
열고 라벨↔입력칸 표를 `recon/` 에 쓴 뒤 폼을 닫는다.

화면에 **쓰지 않는다** — 조회칸에 문서번호를 넣는 것 말고는 읽기만 한다. 다만 키보드
주입(컨텍스트 메뉴)을 쓰므로 도는 동안 BANK24 를 건드리면 안 된다.

    python tools/recon_form.py 01-2608-3-2526                    # recon/fields_<클래스>.md
    python tools/recon_form.py 01-2608-3-2526 --out recon/x.md
    python tools/recon_form.py 2526 2586 2656 --keep-open        # 여러 건 연달아
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.ui import driver, navigate         # noqa: E402
from inspect_bankon import _connect, walk      # noqa: E402
from map_fields import collect, render         # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent

BANK_NAMES = {"TBNKSHG24DAMB": "신한", "TBNKKBB24DAMB": "국민", "TBNKKIB24DAMB": "기업"}


def session_with_grid() -> navigate.Session:
    """그리드를 가진 메인창을 고른다(TfrmMain 이 여러 개일 수 있다)."""
    mains = driver.find_windows(driver.MAIN_CLASS)
    if not mains:
        raise SystemExit("BANK24 메인창이 없습니다 — 실행·로그인 후 다시 시도하세요.")
    for main in mains:
        if driver.by_class(main.handle, "TcxGridSite"):
            return navigate.Session(main)
    raise SystemExit("그리드 있는 메인창이 없습니다 — 감정서조회 화면을 띄우세요.")


def dump(form: driver.WindowRef, out: Path) -> list[dict]:
    nodes = walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle))
    if not nodes:
        raise SystemExit(f"{form.class_name}: 컨트롤을 읽지 못했습니다.")
    fields = collect(nodes)
    bank = BANK_NAMES.get(form.class_name, "미지원")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(fields, f"{bank}은행 담보 ({form.class_name})"), encoding="utf-8")
    return fields


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="recon_form")
    p.add_argument("doc_id", nargs="+")
    p.add_argument("--out", default=None, help="기본 recon/fields_<폼클래스>.md")
    p.add_argument("--keep-open", action="store_true", help="끝나고 폼을 닫지 않는다")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    load_config(args.env or str(ROOT / ".env"))

    session = session_with_grid()
    print(f"메인창 {hex(session.main.handle)} 사용")
    for doc_id in args.doc_id:
        print(f"\n=== {doc_id} 여는 중 …")
        try:
            form = navigate.open_document(session, doc_id)
        except Exception as error:
            print(f"    ⛔ 열기 실패: {type(error).__name__}: {str(error)[:90]}")
            continue
        out = Path(args.out) if args.out else ROOT / "recon" / f"fields_{form.class_name}.md"
        fields = dump(form, out)
        labels = [f["label"] for f in fields if f["label"]]
        print(f"    폼 {form.class_name} ({BANK_NAMES.get(form.class_name, '미지원')}) "
              f"· 입력칸 {len(fields)} · 라벨 {len(labels)} → {out}")
        print("    라벨: " + " · ".join(dict.fromkeys(labels)))
        if not args.keep_open:
            navigate.close_forms(session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
