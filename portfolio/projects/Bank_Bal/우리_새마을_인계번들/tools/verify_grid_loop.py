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
import verify_fill_ibk as VF_IBK               # noqa: E402
import verify_fill_nh as VF_NH                 # noqa: E402
import verify_fill_ssb as VF_SSB               # noqa: E402
import verify_fill_hnb as VF_HNB               # noqa: E402
import verify_fill_wrb as VF_WRB               # noqa: E402
import verify_fill_mgb as VF_MGB               # noqa: E402

# 은행별 폼 클래스·의뢰처(CustName 접두)·표시명.
BANKS = {
    "shg": {"cls": "TBNKSHG24DAMB", "cust": "신한은행", "name": "신한"},
    "kb": {"cls": "TBNKKBB24DAMB", "cust": "국민은행", "name": "국민"},
    "ibk": {"cls": "TBNKKIB24DAMB", "cust": "기업은행", "name": "기업"},
    # 농협은 **농협은행(중앙회)과 지역·품목농협**(군자농협·서울축산농협 …)이 같은 폼을 쓴다.
    # 그래서 의뢰처는 '농협' 부분일치로 잡는다(`CustName LIKE '%농협%'`).
    "nh": {"cls": "TBNKNHB24DAMB", "cust": "농협", "name": "농협", "cust_like": "%농협%"},
    # 수협도 **수협은행(중앙)과 지역·업종수협**(굴수하식·통영수협 …)이 같은 폼을 쓴다.
    # CustName 이 '수협' 또는 '수산업협동조합' 둘 다라 '수…협' 부분일치로 잡는다.
    "ssb": {"cls": "TBNKSSB24DAMB", "cust": "수협", "name": "수협", "cust_like": "%수%협%"},
    "hnb": {"cls": "TBNKHNB24DAMB", "cust": "하나은행", "name": "하나", "cust_like": "%하나%"},
    "wrb": {"cls": "TBNKWRB24DAMB", "cust": "우리은행", "name": "우리", "cust_like": "%우리%"},
    "mgb": {"cls": "TBNKMGB24DAMB", "cust": "새마을금고", "name": "새마을", "cust_like": "%새마을%"},
}

# 채우기(--fill/--fill-live) 지원 은행 → 그 은행 매핑으로 채우는 함수.
# ⚠️ 여기 없는 은행은 채우면 **다른 은행 매핑값이 주입된다**(라벨이 겹치는 본번지·소재지·
#    감정평가액 등이 실제로 들어간다). 그래서 없으면 채우지 않고 스킵한다.
FILLERS = {
    "kb": VF_KB.fill_kb,
    "ibk": VF_IBK.fill_ibk,
    "nh": VF_NH.fill_nh,
    "ssb": VF_SSB.fill_ssb,
    "hnb": VF_HNB.fill_hnb,
    "wrb": VF_WRB.fill_wrb,
    "mgb": VF_MGB.fill_mgb,
}

# 검증(대조)용 — 은행별 "채울값 ↔ 화면" 행 생성기.
COMPARERS = {
    "kb": VF_KB.build_fill_kb,
    "ibk": VF_IBK.build_fill_ibk,
    "nh": VF_NH.build_fill_nh,
    "ssb": VF_SSB.build_fill_ssb,
    "hnb": VF_HNB.build_fill_hnb,
    "wrb": VF_WRB.build_fill_wrb,
    "mgb": VF_MGB.build_fill_mgb,
}


def _strip0(s: str | None) -> str:
    return re.sub(r"\D", "", (s or "")).lstrip("0")


def _bun_from_rows(rows) -> tuple[str | None, str | None]:
    """대조행에서 본번지 (화면, 우리) 값을 뽑는다 — 국민 식별검증용."""
    for mark, lab, ours, theirs in rows:
        if lab == "본번지":
            return theirs, ours
    return None, None


# 이 값들이 어긋나면 '필드가 틀린' 게 아니라 **다른 문서를 열어 놓고 비교한 것**이다.
IDENTITY_LABELS = ("본번지", "부번지", "소유자명", "담보번호")


def identity_conflict(rows) -> str | None:
    """식별이 어긋났는지 — 어긋난 항목 설명(맞으면 None).

    본번지 하나만 보면 같은 필지의 다른 문서를 잡아도 못 알아챈다(실측: 본번 815·평가사
    김기석에 두 문서가 있어 엉뚱한 건을 13칸 불일치로 보고했다).
    """
    for mark, label, ours, theirs in rows:
        if label not in IDENTITY_LABELS or not mark.startswith("❌"):
            continue
        if label in ("본번지", "부번지") and _strip0(theirs) == _strip0(ours):
            continue                       # 0패딩 차이는 같은 값
        return f"{label} 우리={ours[:14]} / 화면={theirs[:14]}"
    return None


# 화면 `소재지` 는 `apw_masterex.ADDR` 과 **글자 그대로 같다**(농협 13/14·기업 실측). 시도로
# 시작하는 값을 그 칸으로 보고 역조회 키로 쓴다 — 본번·평가사보다 훨씬 강한 키다.
_SIDO = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
         "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도",
         "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도",
         "제주특별자치도")


def read_form_id(form) -> dict:
    """폼에서 식별·표시용 값 추출."""
    fid = {"cls": form.class_name, "bun1": None, "bun2": None,
           "manager": None, "amount": None, "addr": None, "site": None, "owner": None}
    for f in collect(walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle))):
        lab, val = f["label"], (f["value"] or "").strip()
        if lab == "본번지":
            fid["bun1"] = val
        elif lab == "부번지":
            fid["bun2"] = val
        elif lab in ("평가사명1", "평가사명") and val and not fid["manager"]:
            fid["manager"] = re.sub(r"\((\d+)\)\s*$", "", val).strip()
        elif lab == "감정평가액" and val:
            fid["amount"] = re.sub(r"\D", "", val)
        elif lab == "소유자명" and val and not fid["owner"]:
            fid["owner"] = val
        elif not lab and len(val) > 6 and re.search(r"[가-힣]", val) and not fid["addr"]:
            fid["addr"] = val
        # 소재지 칸은 은행마다 라벨이 없거나 다른 라벨을 빌려 쓴다 — 값 모양으로 알아본다.
        if val.startswith(_SIDO) and not fid["site"]:
            fid["site"] = re.sub(r"\s+", " ", val).strip()
    return fid


def identify(cfg, fid: dict, cust: str) -> tuple[str | None, str]:
    """화면 값으로 담보 문서번호 역조회.

    키는 **소재지(ADDR) → 본번·부번·평가사** 순이다. 소재지는 화면값과 DB 가 글자 그대로
    같아 가장 강하다. 지번만 쓰면 같은 필지의 다른 건과 섞이고(실측: 본번 815·평가사 김기석에
    두 문서), 화면 지번이 사람 입력이라 DB 와 어긋나면 아예 못 찾는다(실측 5건 식별실패).

    반환: (doc_id, 상태). 상태: 'ok' | 'ambig' | 'none'
    """
    bun1, bun2, mgr = _strip0(fid["bun1"]), _strip0(fid["bun2"]), fid["manager"]
    site = fid.get("site")
    with connect(cfg.source_sql, readonly=True) as s:
        c = s.cursor()
        # 접수일 기준 그리드라 doc_id 연월이 섞일 수 있어 2024~2026 폭넓게 조회.
        c.execute(
            """SELECT DocID, BUN1, BUN2, manager, ADDR FROM apw_masterex
               WHERE DocID LIKE '01-2[456]%-3-%' AND CustName LIKE ? AND LWorkinfo=N'담보'""",
            cust if "%" in cust else f"{cust}%")
        found = c.fetchall()

    def squeeze(text) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    if site:
        by_site = [doc for doc, _b1, _b2, mg, addr in found
                   if squeeze(addr) == site and (not mgr or mgr in (mg or ""))]
        if len(by_site) == 1:
            return by_site[0], "ok"
        # 소재지가 같은 건이 여럿이면 지번으로 더 좁힌다.
        if len(by_site) > 1:
            narrowed = [doc for doc, b1, b2, mg, addr in found
                        if doc in by_site and _strip0(b1) == bun1 and _strip0(b2) == bun2]
            if len(narrowed) == 1:
                return narrowed[0], "ok"

    cands = [doc for doc, b1, b2, mg, _addr in found
             if _strip0(b1) == bun1 and _strip0(b2) == bun2 and mgr and mgr in (mg or "")]
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
    p.add_argument("--bank", choices=tuple(BANKS), default="shg",
                   help="shg=신한 kb=국민 ibk=기업 nh=농협")
    p.add_argument("--fill", action="store_true",
                   help="검증 대신 '채우기 계획'(드라이런) — 국민·기업")
    p.add_argument("--fill-live", action="store_true",
                   help="실제 입력(빈칸만) — 국민·기업·농협. 반드시 감독 하에!")
    p.add_argument("--select", action="store_true",
                   help="콤보도 자동선택. 목록에 없으면 ESC 로 취소하고 원래 값을 둔다")
    p.add_argument("--requery", action="store_true",
                   help="시작 전 '조 회'를 다시 눌러 목록 복원(단건 '찾 기' 뒤에 필요). "
                        "조회조건(업무구분·기간)은 화면 그대로 둔다")
    p.add_argument("--log", default=None)
    p.add_argument("--max", type=int, default=600)
    p.add_argument("--ym", default="260", help="문서번호 연월 접두(예 260=2026년)")
    p.add_argument("--cleanup", action="store_true", help="검증 후 .gam 삭제(디스크 절약)")
    p.add_argument("--i-understand-experimental", action="store_true",
                   help="실험 경로(--fill-live --select) 봉인 해제. 감사 P0-D 미해결이라 기본 봉인.")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    bank = BANKS[args.bank]
    # 감사 P0-D: 배치 순회(--fill-live)에서 --select 콤보 자동선택은 닫힌 드롭다운 ENTER→폼
    # 저장 커밋 위험이 문서마다 반복돼 폭발반경이 크다. 명시 플래그 없이는 봉인.
    if args.fill_live and args.select and not args.i_understand_experimental:
        print("⛔ --fill-live --select(배치 콤보 자동선택)는 감사 P0-D 로 봉인됨. "
              "콤보는 사람이 선택하세요. (정말 필요하면 --i-understand-experimental)",
              file=sys.stderr)
        return 2
    if args.log:
        sys.stdout = open(args.log, "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout

    cfg = load_config(args.env)
    try:
        driver.require_desktop()       # 잠긴 화면이면 여기서 분명히 멈춘다
    except driver.DesktopLocked as error:
        print(f"⛔ {error}"); return 1
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
    if args.requery:
        navigate.close_forms(session)      # 폼이 열려 있으면 그 값을 읽게 된다
        navigate.requery(session)
        print("'조 회' 재실행 — 목록 복원")

    def focus_grid():
        # 순회는 10~20분씩 걸린다 — 도중에 화면이 잠기면 키보드·마우스 주입이 통째로
        # 실패한다. 스택트레이스로 죽지 말고 여기서 분명히 멈춘다(그때까지 결과는 남는다).
        driver.require_desktop()
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
        doc, st = identify(cfg, fid, bank.get("cust_like") or bank["cust"])
        if doc is None:
            print(f"{head}  ⚠ 식별실패({st})"); return "skip", None
        if args.fill or args.fill_live:            # 채우기 모드(국민·기업)
            filler = FILLERS.get(args.bank)
            if filler is None:                     # 신한 등 미지원 은행 — 남의 매핑을 쓰면 안 된다
                print(f"{head}  {doc}  ⛔ {bank['name']}은 채우기 미지원(--fill 불가)")
                return "skip", doc
            try:
                results, align = filler(cfg, doc, form, live=args.fill_live,
                                        select=args.select)
            except (Exception, SystemExit) as e:   # 실사전 .gam 없음 등 → 스킵
                print(f"{head}  {doc}  ⛔ {str(e)[:40]}"); return "skip", doc
            done = sum(1 for r in results if r.wrote)
            # **빈 폼 수율** — 실전은 사람이 아무것도 안 넣은 폼에 우리가 채우는 것이다.
            # `수동(선택형)`·`미발견` 은 폼이 차 있든 비어 있든 같으므로, 드라이런으로
            # "우리가 실제로 쓸 수 있는 칸"을 그대로 잴 수 있다.
            #   쓸수있음 = 채움 + 덮어씀 + 일치   (이미 같은 값이면 빈 폼에선 우리가 썼을 칸)
            writable = sum(1 for r in results
                           if r.action in ("채움", "덮어씀", "일치") or r.action.startswith("고름"))
            plan = sum(1 for r in results
                       if r.action in ("채움", "덮어씀") or r.action.startswith("고름"))
            manual = sum(1 for r in results if r.action == "수동(선택형)")
            miss = sum(1 for r in results if r.action == "미발견")
            empty = sum(1 for r in results if r.action == "빈값")
            seqinfo = (f" [물건{align['resolved']}/{align['total']}·{align['by']}]"
                       if align["total"] >= 2 else "")
            if args.fill_live and not align["safe"]:
                print(f"{head}  {doc}  ⚠순번불명확{seqinfo} — 실입력 건너뜀")
            elif args.fill_live:
                print(f"{head}  {doc}  ✍입력 {done} · 수동 {manual} · 미발견 {miss}{seqinfo}")
            else:
                print(f"{head}  {doc}  📝쓸수있음 {writable} · 수동(콤보) {manual} · "
                      f"미발견 {miss} · 값없음 {empty}{seqinfo}(드라이런)")
            return "clean", doc
        try:
            comparer = COMPARERS.get(args.bank)
            if comparer is not None:                     # 국민·기업·농협: 물건 순번 정합 내장
                rows = comparer(cfg, doc, form)
                sb, mb = _bun_from_rows(rows)
            else:
                meta, rows = VF.build_fill(cfg, doc, form)   # 정품추출→매핑→"채울값 ↔ 화면"
                sb, mb = meta["screen_bun"], meta["mine_bun"]
        except (Exception, SystemExit) as e:   # SystemExit: fetch_gam 의 '.gam 없음' 등
            print(f"{head}  {doc}  ⛔ 검증불가 {str(e)[:45]}"); return "skip", doc
        if sb and mb and _strip0(sb) != _strip0(mb):   # 0패딩 무시하고도 본번 다르면 다른문서
            print(f"{head}  {doc}  ⚠ 식별불일치"); return "skip", doc
        conflict = identity_conflict(rows)
        if conflict is not None:
            print(f"{head}  {doc}  ⚠ 식별불일치 — {conflict}"); return "skip", doc
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
        except driver.DesktopLocked as e:      # 화면이 잠겼다 — 더 못 간다
            print(f"[{i}] ⛔ {e}"); break
        except (Exception, SystemExit) as e:   # 그 외 오류는 이 건만 건너뛰고 계속
            print(f"[{i}] ⛔ 처리오류 {str(e)[:60]} — 건너뜀"); cnt["skip"] += 1
            try:
                close_form(form)
            except Exception:
                pass
        try:
            advance()
        except driver.DesktopLocked as e:
            print(f"[{i}] ⛔ {e}"); break

    print(f"\n[종료] 이상없음 {cnt['clean']} / 확인필요 {cnt['flag']} / 스킵 {cnt['skip']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
