"""열린 신한 담보 화면 ↔ 원본(.gam+APW DB) 대조 — gamexport 없이 동작.

이 PC엔 gamexport.exe 가 없고 최신 건은 DW 에도 없어서(→ [[bankon-this-pc-no-gamexport]]),
정품 파서 대신 **증거 기반 대조**를 한다:

  DB 필드(지번·평가사·심사자·대표)  : APW DB 로 정확 계산 → 화면과 정확 비교(✅/❌)
  .gam 필드(담보종류·면적·금액·날짜) : .gam 원본에 그 값이 있는지(포함검사) + gam_info
                                     숫자(float64) 디코딩으로 대조(✅있음/⚠️확인)
  물건특성 8종                      : 기본값(아니오/해당없음)이라 원본에 없어도 정상(ℹ️)

화면엔 쓰지 않는다. 읽기 전용.

    python tools/verify_live.py 01-2608-3-2545
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config          # noqa: E402
from bankon.db import connect                  # noqa: E402
from bankon.downloader import download_to, ftp_session  # noqa: E402
from bankon.resolver import resolve_document   # noqa: E402
from bankon.sources import apw                 # noqa: E402
from bankon.ui import driver                   # noqa: E402
from inspect_bankon import _connect, walk      # noqa: E402
from map_fields import collect                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

FORM_CLASS = "TBNKSHG24DAMB"
# 대상 아님 — 참고용 안내 문구
OTHER_FORMS = {
    "TBNKSHG24YAKS": "신한 공동주택자문(제외)",
    "TBNKSHG24TABS": "신한 탁상(제외)",
    "TBNKKBB24DAMB": "국민 담보(이 도구는 신한 전용)",
}

# 화면 라벨 분류 --------------------------------------------------------------
DB_EXACT = {          # APW DB 로 정확히 계산되는 필드
    "번지구분", "본번지", "부번지",
    "평가사명1", "평가사명2", "평가사명3", "심사자", "대표,지사장",
}
DEFAULTS = {          # 의견서 표 없으면 기본값 → 원본에 없어도 정상
    "매매/분양", "임대", "튼상가", "오픈상가", "공부/현황 불일치",
    "제시외건물,종물/부합물", "미등기 부동산", "별도 등기 존재",
}
DATE_LABELS = {"기준시점", "현장답사일", "사용승인일"}
IGNORE_LABELS = {"사업등록번호", "물건순번"}
# 계산값 — gam_info 원값이 아니라 파생 계산이라 원문에 그대로 없다(대조 보류).
COMPUTED_LABELS = {"실   비", "실비"}
# 은행 콤보 라벨로 코드매핑되는 값 — 원문 텍스트와 달라 포함검사로 대조 불가(보류).
MAPPED_LABELS = {"담보용도"}
# 콤보 어휘 필드 — 화면값이 원문과 괄호·수식어(집합·(일반)·구조)만 다를 수 있어 부분대조.
CONTROLLED_LABELS = {"담보종류", "담보세부종류", "지목", "용도지역구분(신)", "용도지역구분(구)",
                     "건물구조(신)", "건물구조(구)", "이용상황구분", "도시계획구역구분"}
_CODE_SUFFIX = re.compile(r"\((\d+)\)\s*$")
_EPOCH = date(1899, 12, 30)


def norm(text: str | None) -> str:
    return _CODE_SUFFIX.sub("", (text or "").replace(",", "")).strip()


# .gam 증거 수집 -------------------------------------------------------------
_NORM = re.compile(r"[\s,\-]")


def _norm_txt(text: str) -> str:
    """대조용 정규화 — 공백·콤마·하이픈 제거(표기 차이 무시)."""
    return _NORM.sub("", text)


class GamEvidence:
    def __init__(self, raw: bytes, doc_id: str):
        self.raw = raw
        self.dates = self._collect_dates(raw)
        self.comma_nums = {m.group().decode() for m in re.finditer(rb"\d{1,3}(?:,\d{3})+", raw)}
        self.numbers = self._decode_numbers(doc_id)
        # 공백·콤마·하이픈 제거한 텍스트 뭉치(주소 띄어쓰기·등기번호 하이픈 차이 흡수)
        self.text_blob = _norm_txt(raw.decode("cp949", "ignore"))

    @staticmethod
    def _collect_dates(raw: bytes) -> list[str]:
        """구분자(- . /) 무관하게 날짜를 모아 ISO(yyyy-mm-dd)로 정규화.

        의견서는 `2024.02.22`, mullist 는 `2018-12-26` 처럼 표기가 달라서
        구분자를 흡수한다. 월/일 범위로 가짜 8자리 숫자를 걸러낸다.
        """
        found: set[str] = set()
        for m in re.finditer(rb"(?:19|20)\d\d[-./]?[01]\d[-./]?[0-3]\d", raw):
            d = re.sub(rb"[-./]", b"", m.group()).decode()
            yy, mm, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
            if 1950 <= yy <= 2027 and 1 <= mm <= 12 and 1 <= dd <= 31:
                found.add(f"{d[:4]}-{d[4:6]}-{d[6:8]}")
        return sorted(found)

    def _decode_numbers(self, doc_id: str) -> set[int]:
        """gam_info 블록 주변의 float64(금액)를 정수로 디코딩."""
        nums: set[int] = set()
        anchor = self.raw.find(doc_id.encode("ascii"))
        if anchor < 0:
            return nums
        region = self.raw[anchor: anchor + 4000]
        for off in range(0, len(region) - 8):
            v = struct.unpack_from("<d", region, off)[0]
            if v == v and 1 <= abs(v) < 5e11 and abs(v - round(v)) < 1e-6:
                nums.add(int(round(v)))
        return nums

    def has_text(self, value: str) -> bool:
        key = _norm_txt(value)
        if key and key in self.text_blob:
            return True
        # 주소류: 시/도 약칭 차이(경기 vs 경기도, 서울 vs 서울특별시) 흡수 —
        # 첫 토큰(시/도)을 떼고 나머지(시·군·구·동·번지·건물명)로 재대조.
        parts = value.split(None, 1)
        if len(parts) == 2:
            tail = _norm_txt(parts[1])
            if len(tail) >= 6 and tail in self.text_blob:
                return True
        # 조합 주소(번지+건물명+층/호)는 통짜로 안 맞으니 토큰별 대조.
        # 층/호 토큰은 제외하고, 의미있는 토큰(≥2자)이 2개 이상이면서 전부
        # 원본에 있으면 인정(번지·건물명이 실제로 틀리면 여전히 걸린다).
        toks = [_norm_txt(t) for t in value.split()
                if len(_norm_txt(t)) >= 2 and not re.search(r"\d+\s*[층호]|제\d", t)]
        return len(toks) >= 2 and all(t in self.text_blob for t in toks)

    def has_core(self, value: str) -> bool:
        """콤보 어휘값: 괄호·수식어 표기차 흡수. 핵심어(4자+) 부분일치면 인정.

        예) 창고시설(일반)→창고시설, 집합업무시설→업무시설, 철근콘크리트구조→철근콘크리트.
        """
        if self.has_text(value):
            return True
        core = _norm_txt(re.sub(r"\(.*?\)", "", value))   # (일반) 등 제거
        if len(core) >= 2 and core in self.text_blob:
            return True
        for length in range(len(core), 3, -1):            # 4자 이상 최장 부분일치
            for start in range(len(core) - length + 1):
                if core[start:start + length] in self.text_blob:
                    return True
        return False

    def has_amount(self, value: str) -> bool:
        digits = re.sub(r"[^\d]", "", value)
        if digits and int(digits) in self.numbers:      # gam_info 바이너리 금액
            return True
        if self.has_text(value):                          # mullist 텍스트 금액
            return True
        return self.has_text(value.split(".")[0])         # 1,339.00 → 1339


def read_screen(form) -> list[dict]:
    fields = collect(walk(_connect(driver.BACKEND, title_re=None, pid=None, handle=form.handle)))
    out = []
    seen = set()
    for f in fields:
        if "RadioGroup" in f["class_name"]:
            continue
        lab = (f["label"] or "").strip()
        val = (f["value"] or "").strip()
        if not val or not f["db_bound"]:
            continue
        if val in ("0", "1") and "ComboBox" in f["class_name"] and not f["db_bound"]:
            continue
        box = f["box"]
        key = (lab, val, box.left, box.top)
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": lab, "value": val, "class": f["class_name"],
                    "left": box.left, "top": box.top})
    return out


def db_values(cfg, doc_id: str) -> dict:
    with connect(cfg.source_sql, readonly=True) as s:
        cur = s.cursor()
        mid = apw.fetch_master_id(cur, doc_id)
        jibun = apw.fetch_jibun(cur, doc_id)
        appr = apw.fetch_appraisers(cur, doc_id)
        rev = apw.fetch_reviewer(cur, mid) if mid else None
        boss = apw.fetch_office_boss(cur)
    vals = {
        "번지구분": jibun.jibun_kind if jibun else None,
        "본번지": jibun.bun1 if jibun else None,
        "부번지": jibun.bun2 if jibun else None,
        "평가사명1": appr[0] if len(appr) > 0 else None,
        "평가사명2": appr[1] if len(appr) > 1 else None,
        "평가사명3": appr[2] if len(appr) > 2 else None,
        "심사자": rev,
        "대표,지사장": boss,
    }
    return {"mid": mid, "jibun": jibun, "vals": vals}


def fetch_gam(cfg, doc_id: str) -> bytes:
    dest = Path("work") / doc_id / f"{doc_id}.gam"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest.read_bytes()
    with connect(cfg.source_sql, readonly=True) as s, ftp_session(cfg.ftp) as ftp:
        remote = resolve_document(s, doc_id).remote("gam")
        if not remote:
            raise SystemExit(f"{doc_id}: .gam 원격경로 없음")
        return download_to(ftp, remote, dest).read_bytes()


def open_form():
    """열린 신한 담보 폼(있으면) 반환. 없으면 (None, 안내문)."""
    all_forms = driver.find_windows(driver.FORM_CLASS_PREFIX)
    forms = [f for f in all_forms if f.class_name == FORM_CLASS]
    if forms:
        return forms[0], None
    if all_forms:
        names = ", ".join(f"{f.class_name}({OTHER_FORMS.get(f.class_name, '미지원')})"
                          for f in all_forms)
        return None, (f"열린 폼: {names} — 신한 담보(TBNKSHG24DAMB) 아님(제외 업무)")
    return None, "신한 담보 화면이 열려 있지 않습니다."


def build_rows(cfg, doc_id: str, form) -> tuple[dict, list]:
    """폼 ↔ 원본 대조 결과를 (메타, rows)로 반환(출력 안 함)."""
    screen = read_screen(form)
    db = db_values(cfg, doc_id)
    ev = GamEvidence(fetch_gam(cfg, doc_id), doc_id)
    jib = db["jibun"]
    screen_bun = next((s["value"] for s in screen if s["label"] == "본번지"), None)

    def _digs0(x):  # 숫자만 + 앞의 0 제거(화면 0569 vs DB 569 오판 방지)
        return re.sub(r"\D", "", x or "").lstrip("0")
    mismatch_doc = bool(jib and jib.bun1 and screen_bun
                        and _digs0(screen_bun) != _digs0(jib.bun1))
    addr = next((s["value"] for s in screen
                 if not s["label"] and len(s["value"]) > 6 and re.search(r"[가-힣]", s["value"])), "")
    meta = {"mid": db["mid"], "gam": len(ev.raw), "dates": ev.dates,
            "mismatch_doc": mismatch_doc, "screen_bun": screen_bun, "addr": addr,
            "appraiser": (db["vals"].get("평가사명1") or "")}
    rows = []
    for item in screen:
        lab, val = item["label"], item["value"]
        if lab in IGNORE_LABELS:
            continue
        if lab in DB_EXACT:
            ours = norm(db["vals"].get(lab))
            theirs = norm(val)
            if ours and theirs:
                mark = "✅일치" if ours == theirs else "❌불일치"
            elif theirs and not ours:
                mark = "⚠️우리없음"
            else:
                mark = "—"
            rows.append((mark, lab, val, ours or "-"))
        elif lab in DEFAULTS:
            rows.append(("ℹ️기본값", lab, val, "(표없으면 기본값)"))
        elif lab in COMPUTED_LABELS:
            rows.append(("🧮계산값", lab, val, "파생계산(원문無 정상)"))
        elif lab in MAPPED_LABELS:
            rows.append(("🔤매핑값", lab, val, "코드매핑(콤보라벨)"))
        elif lab in CONTROLLED_LABELS:
            mark = "✅있음" if ev.has_core(val) else "⚠️원본에없음"
            rows.append((mark, lab, val, "콤보값 부분대조"))
        elif lab in DATE_LABELS:
            mark = "✅있음" if val in ev.dates else "⚠️원본에없음"
            rows.append((mark, lab, val, "/".join(ev.dates[-3:]) if ev.dates else "-"))
        elif "동미만 주소" in lab and re.search(r"[가-힣]", val):
            # 주소 조합칸(시·구·동·지번·건물명). 지번·동은 본번지/소재지로 별도 검증되고
            # 건물명은 따옴표·영문·'번지' 접미사 등 표기차가 커서 통짜 대조가 무의미.
            # → 지번만 원본에 있으면 ✅, 아니면 보류(⚠️로 잡음 만들지 않음).
            m = re.search(r"산?\s*\d+(?:-\d+)?", val)
            if m and ev.has_text(m.group().replace(" ", "")):
                rows.append(("✅있음", "소재지(동미만)", val, "지번확인"))
            else:
                rows.append(("📮보류", "소재지(동미만)", val, "주소조합 대조보류"))
        elif not lab and re.fullmatch(r"\d{5}", val):
            # 라벨 없는 5자리 = 법정동코드(REG/EUB) 또는 우편번호
            if jib and val in (jib.reg, jib.eub):
                rows.append(("✅일치", "법정동코드", val, f"REG/EUB={jib.reg}/{jib.eub}"))
            else:
                rows.append(("📮보류", "우편번호?", val, "감정서엔 없음(대조보류)"))
        elif re.search(r"\d", val) and re.match(r"^[\d,]+(\.\d+)?$", val):
            mark = "✅있음" if ev.has_amount(val) else "⚠️원본에없음"
            rows.append((mark, lab or "(라벨없음)", val, "원본대조"))
        else:
            mark = "✅있음" if ev.has_text(val) else "⚠️원본에없음"
            rows.append((mark, lab or "(라벨없음)", val, "원본포함"))
    return meta, rows


_ORDER = {"❌불일치": 0, "⚠️원본에없음": 1, "⚠️우리없음": 1, "⚠️": 1,
          "✅일치": 3, "✅있음": 3, "🧮계산값": 4, "📮보류": 4, "🔤매핑값": 4,
          "ℹ️기본값": 5, "—": 6}


def counts(rows) -> tuple[int, int, int, int]:
    ok = sum(1 for r in rows if r[0].startswith("✅"))
    warn = sum(1 for r in rows if r[0].startswith("⚠️") or r[0].startswith("❌"))
    hold = sum(1 for r in rows if r[0][0] in "🧮📮🔤")
    base = sum(1 for r in rows if r[0].startswith("ℹ️"))
    return ok, warn, hold, base


def verify(cfg, doc_id: str) -> int:
    form, msg = open_form()
    if form is None:
        print(msg, file=sys.stderr)
        return 1
    meta, rows = build_rows(cfg, doc_id, form)
    if meta["mismatch_doc"]:
        print(f"⚠️  화면 본번지({meta['screen_bun']}) ≠ 문서 {doc_id} — 화면이 다른 문서일 수 있습니다.\n")
    print(f"===== {doc_id} =====")
    print(f"masterid={meta['mid']}  .gam={meta['gam']:,}B  원본날짜={meta['dates']}\n")
    for mark, lab, val, src in sorted(rows, key=lambda r: _ORDER.get(r[0], 2)):
        print(f"  [{mark:7}] {lab[:20]:22} 화면={val[:24]:26} 원본={src[:24]}")
    ok, warn, hold, base = counts(rows)
    print(f"\n일치/확인됨 {ok} · 확인필요 {warn} · 보류(계산값·우편번호) {hold} · 기본값 {base}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="verify_live")
    p.add_argument("doc_id", nargs="+")
    p.add_argument("--env", default=None)
    args = p.parse_args(argv)
    cfg = load_config(args.env)
    rc = 0
    for doc_id in args.doc_id:
        rc |= verify(cfg, doc_id)
        print()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
