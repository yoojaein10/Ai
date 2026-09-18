"""BANK24 조회 그리드를 행 단위로 훑으며 담보 전건 자동 검증(신한·국민).

전제: BANK24 로그인 + 감정서조회 조회화면(업무구분 '담보', 원하는 기간 조회) 상태.
동작: 그리드 포커스 → 맨 위 행 → [Shift+F10 우클릭메뉴 → 'a'(작성/열람) → 폼 읽기 →
      문서 식별(본번지·부번지·평가사로 DB 역조회) → 원본 대조 → '닫 기' → 아래 행] 반복.
      같은 건이 연속으로 열리면(맨 끝 도달) 종료.

화면엔 안 쓴다(작성/열람=읽기, 값 변경 없음). 관리자 권한 필요(입력 주입).
국민(--bank kb)은 다물건이면 화면 감정평가액으로 물건을 정합해 검증한다.

    (관리자) python tools/verify_grid_loop.py --bank kb --log out.txt [--max 600]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.ui import driver, navigate         # noqa: E402
from inspect_bankon import _connect, walk      # noqa: E402
from map_fields import collect                 # noqa: E402
from pywinauto.keyboard import send_keys       # noqa: E402
import verify_live as V                        # noqa: E402
import verify_fill as VF                        # noqa: E402
import verify_fill_kb as VF_KB                  # noqa: E402

# 은행별 폼 클래스·의뢰처(CustName 접두)·표시명.
BANKS = {
    "shg": {"cls": "TBNKSHG24DAMB", "cust": "신한은행", "name": "신한"},
    "kb": {"cls": "TBNKKBB24DAMB", "cust": "국민은행", "name": "국민"},
}


def _strip0(s: str | None) -> str:
    return re.sub(r"\D", "", (s or "")).lstrip("0")


def _bun_from_rows(rows) -> tuple[str | None, str | None]:
    """대조행에서 본번지 (화면, 우리) 값을 뽑는다 — 국민 식별검증용."""
    for mark, lab, ours, theirs in rows:
        if lab == "본번지":
            return theirs, ours
    return None, None


def read_form_id(form) -> dict:
    """폼에서 식별·표시용 값 추출."""
    fid = {"cls": form.class_name, "bun1": None, "bun2": None,
           "manager": None, "amount": None, "addr": None}
    for f in collect(walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle))):
        lab, val = f["label"], (f["value"] or "").strip()
        if lab == "본번지":
            fid["bun1"] = val
        elif lab == "부번지":
            fid["bun2"] = val
        elif lab == "평가사명1" and val:
            fid["manager"] = re.sub(r"\((\d+)\)\s*$", "", val).strip()
        elif lab == "감정평가액" and val:
            fid["amount"] = re.sub(r"\D", "", val)
        elif not lab and len(val) > 6 and re.search(r"[가-힣]", val) and not fid["addr"]:
            fid["addr"] = val
    return fid


def identify(cfg, fid: dict, cust: str) -> tuple[str | None, str]:
    """본번지·부번지·평가사로 담보 문서번호 역조회.

    반환: (doc_id, 상태). 상태: 'ok' | 'ambig' | 'none'
    """
    bun1, bun2, mgr = _strip0(fid["bun1"]), _strip0(fid["bun2"]), fid["manager"]
    with connect(cfg.source_sql, readonly=True) as s:
        c = s.cursor()
        # 접수일 기준 그리드라 doc_id 연월이 섞일 수 있어 2024~2026 폭넓게 조회.
        c.execute(
            """SELECT DocID, BUN1, BUN2, manager FROM apw_masterex
               WHERE DocID LIKE '01-2[456]%-3-%' AND CustName LIKE ? AND LWorkinfo=N'담보'""",
            f"{cust}%")
        cands = []
        for doc, b1, b2, mg in c.fetchall():
            if _strip0(b1) == bun1 and _strip0(b2) == bun2 and mgr and mgr in (mg or ""):
                cands.append(doc)
    if len(cands) == 1:
        return cands[0], "ok"
    if not cands:
        return None, "none"
    # 자매호(같은 본번·평가사) → 화면 감정평가액을 각 .gam 에서 찾아 판별
    amt = fid["amount"]
    if amt:
        for doc in cands:
            try:
                ev = V.GamEvidence(V.fetch_gam(cfg, doc), doc)
                if int(amt) in ev.numbers or ev.has_text(f"{int(amt):,}"):
                    return doc, "ok"
            except Exception:
                continue
    return None, "ambig"


def close_form(form) -> None:
    btn = driver.by_text(form.handle, "닫 기", "TcxButton")
    if btn:
        driver.click(btn)
    else:
        send_keys("%{F4}")  # 최후수단
    time.sleep(1.2)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_grid_loop")
    p.add_argument("--bank", choices=("shg", "kb"), default="shg", help="shg=신한 kb=국민")
    p.add_argument("--log", default=None)
    p.add_argument("--max", type=int, default=600)
    p.add_argument("--ym", default="260", help="문서번호 연월 접두(예 260=2026년)")
    p.add_argument("--cleanup", action="store_true", help="검증 후 .gam 삭제(디스크 절약)")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    bank = BANKS[args.bank]
    if args.log:
        sys.stdout = open(args.log, "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout

    cfg = load_config(args.env)
    mains = driver.find_windows(driver.MAIN_CLASS)
    if not mains:
        print("BANK24 메인창 없음"); return 1
    # 그리드(TcxGridSite)를 가진 메인창을 고른다(TfrmMain 이 여러 개일 수 있다).
    session = None
    for m in mains:
        if driver.by_class(m.handle, "TcxGridSite"):
            session = navigate.Session(m); break
    if session is None:
        print("그리드 있는 메인창 없음 — 조회화면 확인 필요"); return 1
    print(f"메인창 {hex(session.main.handle)} 사용")

    def focus_grid():
        send_keys("{ESC}"); time.sleep(0.15)             # 열린 메뉴 닫기
        try:
            session.main.set_focus()                     # 메인창 포그라운드로(닫기 후 포커스 유실 방지)
        except Exception:
            pass
        time.sleep(0.2)
        navigate._grid(session).set_focus(); time.sleep(0.35)

    def open_current(retries=1):
        """현재 선택 행의 작성폼을 연다(재시도)."""
        for _ in range(retries + 1):
            send_keys("+{F10}"); time.sleep(0.8); send_keys("a")
            try:
                return driver.wait_for_window(driver.FORM_CLASS_PREFIX, pid=session.pid, timeout=12)
            except Exception:
                send_keys("{ESC}"); time.sleep(0.3); focus_grid()
        return None

    def advance():
        focus_grid(); send_keys("{DOWN}"); time.sleep(0.3)

    def process(form, fid) -> tuple[str, str | None]:
        """폼 하나 검증 → (카테고리, doc). 카테고리: clean|flag|skip."""
        head = f"[{i}] {(fid['addr'] or '?')[:16]:16} 본번{(fid['bun1'] or '-'):5} {(fid['manager'] or '?'):4}"
        if fid["cls"] != bank["cls"]:
            print(f"{head}  ⏭ {fid['cls']}({bank['name']}담보 아님)"); return "skip", None
        doc, st = identify(cfg, fid, bank["cust"])
        if doc is None:
            print(f"{head}  ⚠ 식별실패({st})"); return "skip", None
        try:
            if args.bank == "kb":                        # 국민: 다물건이면 화면 금액으로 물건 정합
                rows = VF_KB.build_fill_kb(cfg, doc, form)
                sb, mb = _bun_from_rows(rows)
            else:
                meta, rows = VF.build_fill(cfg, doc, form)   # 정품추출→매핑→"채울값 ↔ 화면"
                sb, mb = meta["screen_bun"], meta["mine_bun"]
        except (Exception, SystemExit) as e:   # SystemExit: fetch_gam 의 '.gam 없음' 등
            print(f"{head}  {doc}  ⛔ 검증불가 {str(e)[:45]}"); return "skip", doc
        if sb and mb and _strip0(sb) != _strip0(mb):   # 0패딩 무시하고도 본번 다르면 다른문서
            print(f"{head}  {doc}  ⚠ 식별불일치"); return "skip", doc
        probs = [r for r in rows if r[0].startswith("❌")]
        same = sum(1 for r in rows if r[0].startswith("✅"))
        fill = sum(1 for r in rows if r[0].startswith("🖊"))
        if probs:
            print(f"{head}  {doc}  ✅{same} ❌{len(probs)} 🖊{fill} → 불일치")
            for m, lab, ours, theirs in probs:
                print(f"        {lab}: 우리={ours[:20]} / 화면={theirs[:20]}")
            return "flag", doc
        print(f"{head}  {doc}  ✅{same} 🖊{fill} 이상없음"); return "clean", doc

    cnt = {"clean": 0, "flag": 0, "skip": 0}
    prev_sig = None
    stall = 0
    seen = set()                                            # 위치 미끄러짐 대비 중복 방지
    focus_grid(); send_keys("^{HOME}"); time.sleep(0.4)     # 첫 행
    for i in range(args.max):
        form = open_current()
        if form is None:
            stall += 1
            print(f"[{i}] 폼 안열림(stall {stall}/3)")
            if stall >= 5:
                print("끝 도달로 판단, 종료"); break
            advance(); continue
        try:
            fid = read_form_id(form)
            sig = (fid["cls"], fid["addr"], fid["bun1"], fid["manager"], fid["amount"])
            if sig == prev_sig:                # 행이 안 넘어감(또는 그리드 끝)
                close_form(form); stall += 1
                if stall >= 5:
                    print(f"[{i}] 직전과 동일 반복({fid['addr']}) — 끝 도달, 종료"); break
                advance(); continue
            stall = 0; prev_sig = sig
            if sig in seen:                    # 이미 처리한 행(위치 미끄러짐) — 재검증 안 함
                print(f"[{i}] 중복행({fid['addr']}) — 건너뜀")
                close_form(form); advance(); continue
            seen.add(sig)
            cat, doc = process(form, fid)
            cnt[cat] += 1
            close_form(form)
            if args.cleanup and doc:
                shutil.rmtree(Path("work") / doc, ignore_errors=True)
        except (Exception, SystemExit) as e:   # 어떤 오류든 이 건만 건너뛰고 계속
            print(f"[{i}] ⛔ 처리오류 {str(e)[:60]} — 건너뜀"); cnt["skip"] += 1
            try:
                close_form(form)
            except Exception:
                pass
        advance()

    print(f"\n[종료] 이상없음 {cnt['clean']} / 확인필요 {cnt['flag']} / 스킵 {cnt['skip']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
