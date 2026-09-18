"""열려 있는 뱅크온라인 폼 값 ↔ 우리가 만든 매핑 값 대조 (검증 전용).

실제 `.gam` 을 FTP 로 받아 파싱하고, 은행별 매핑을 돌려 나온 값을
**이미 사람이 작성해 둔 화면 값**과 비교한다. 자동입력을 켜기 전에
"우리가 넣을 값이 사람이 넣은 값과 같은가" 를 확인하는 용도다.

화면에는 아무것도 쓰지 않는다 — 읽기만 한다.

    python tools/verify_form.py 01-2608-3-2529 [--env D:\\AI\\GamJun\\.env]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.config import load_config  # noqa: E402
from bankon.db import connect  # noqa: E402
from bankon.downloader import download_to, ftp_session  # noqa: E402
from bankon.gam_bridge import process_gam  # noqa: E402
from bankon.mapping import kookmin, shinhan  # noqa: E402
from bankon.model import DocumentContext, Fee, Parties, SiteInfo  # noqa: E402
from bankon.parse import (  # noqa: E402
    machines, units,
    buildings,
    characteristics, cost, detail, kb, mullist, outline, rental, sections, standard_land,
)
from bankon.parse import address as _address, round as round_parse  # noqa: E402  (농협 이식 2026-09-07)
from bankon.parse.account import primary_account  # noqa: E402
from bankon.resolver import resolve_document  # noqa: E402
from bankon.sources import apw, scan  # noqa: E402
from bankon.ui import driver, navigate  # noqa: E402
from inspect_bankon import _connect, walk  # noqa: E402
from map_fields import collect  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

BANK_FORMS = {"TBNKSHG24DAMB": "신한", "TBNKKBB24DAMB": "국민", "TBNKKIB24DAMB": "기업", "TBNKNHB24DAMB": "농협",
              "TBNKSSB24DAMB": "수협", "TBNKHNB24DAMB": "하나", "TBNKWRB24DAMB": "우리", "TBNKMGB24DAMB": "새마을"}


def load_combos(path: Path) -> dict[str, frozenset[str]]:
    if not path.exists():
        return {}
    combos: dict[str, frozenset[str]] = {}
    for block in path.read_text(encoding="utf-8").split("## ")[1:]:
        name = block.split("\n")[0].split("  (")[0]
        combos[name] = frozenset(
            line[2:].strip() for line in block.split("\n")[1:] if line.startswith("- ")
        )
    return combos


def fetch_gam(cfg, doc_id: str):
    """문서번호 → .gam 다운로드 → gamexport 실행 → (테이블, 의견서)."""
    work = Path(cfg.work_dir) / doc_id
    out = Path(cfg.output_dir) / doc_id
    with connect(cfg.source_sql, readonly=True) as source, ftp_session(cfg.ftp) as ftp:
        paths = resolve_document(source, doc_id)
        remote = paths.remote("gam")
        if not remote:
            raise SystemExit(f"{doc_id}: .gam 원격경로가 없습니다.")
        local = download_to(ftp, remote, work / f"{doc_id}.gam")
        return process_gam(cfg.gamexport_exe, str(local), str(out)), work, out


def _body_of(opinion):
    """의견서 한 장 → 섹션 조회 함수."""
    secs = sections.split(opinion.document.paragraphs)

    def body(title: str) -> str | None:
        found = sections.find(secs, title)
        return found.body if found else None
    return body


def sections_from_gam(gam):
    """gamexport 결과의 의견서 → 섹션 조회 함수(**가장 긴 의견서** — 종전 그대로).

    ★의견서가 여러 장인 문서가 많다(로컬 표본 610건 중 136건). 대개는 RTI(적정성 검토)·요약보고서 같은
    첨부라 대표 한 장만 보면 되지만, 그중 18건은 감정평가표가 **현장별로** 갈린 다현장 문서다
    (2818 = 옹정리 토지건물 + 삼성동 구분건물). 그런 건은 준공일자·용도지역·소재지가 물건마다 달라서
    대표 한 장만 보면 다른 현장 물건에 엉뚱한 값이 들어간다(2818 실화면 대조에서 7칸 불일치).

    그래서 돌려주는 함수에 **의견서 전부**를 `.opinions`(이름, 섹션함수) 로 붙여 둔다 —
    `build_context` 가 이것으로 `DocumentContext.sites` 를 만든다. 기존 호출부는 손댈 것이 없다.
    """
    ordered = sorted(gam.opinions, key=lambda o: len(o.document.text), reverse=True)
    bodies = [(getattr(o, "source_name", None), _body_of(o)) for o in ordered]
    body = bodies[0][1] if bodies else (lambda title: None)
    body.opinions = tuple(bodies)
    return body


def load_from_dw(cfg, doc_id: str):
    """FTP 대신 GamJun DW 에 적재된 내용을 쓴다(검증용).

    FTP 가 막혔거나 이미 백필된 건이면 이쪽이 빠르고 부담이 없다.
    의견서는 섹션별로 적재돼 있어 재파싱이 필요 없다.
    """
    with connect(cfg.dw_sql, readonly=True) as target:
        cursor = target.cursor()
        cursor.execute(
            "SELECT TOP 1 payload FROM dbo.gam_raw WHERE doc_id=? AND source='gam'", doc_id)
        row = cursor.fetchone()
        if row is None:
            raise SystemExit(f"{doc_id}: DW(gam_raw)에 없습니다. --live 로 받으세요.")
        tables = json.loads(row[0])
        cursor.execute("SELECT section, content FROM dbo.gam_opinion WHERE doc_id=?", doc_id)
        stored = {section: content for section, content in cursor.fetchall()}
    return tables, (lambda title: stored.get(title))


def _sites_from(section_body) -> tuple[SiteInfo, ...]:
    """의견서마다 현장 하나 — `대상물건 개요` 소재지가 있는 것만(RTI·요약보고서 첨부는 뺀다).

    첫째가 대표(가장 긴 의견서)다. 현장이 하나뿐인 보통 문서는 종전과 값이 같다.
    """
    found: list[SiteInfo] = []
    for name, body in getattr(section_body, "opinions", None) or ((None, section_body),):
        overview = body("대상물건 개요")
        parsed = outline.parse(overview)
        if not found or parsed.address:      # 대표는 무조건 넣고, 나머지는 소재지가 있어야 현장으로 본다
            found.append(SiteInfo(
                name=name, outline=parsed,
                legal_text=outline.parse_legal(body("감정평가액 결정")),
                buildings=buildings.parse(overview), units=units.parse(overview),
                machines=machines.parse(overview)))
    return tuple(found)


def _legal_codes(cursor, sites, doc_site, gongbu) -> tuple[tuple[str, str], ...]:
    """다현장 문서에서 **대표 현장이 아닌 소재지**의 법정동코드 — (소재지, 코드) 짝.

    보통 문서(현장 1개)는 APW 가 준 문서 코드 하나로 충분하므로 조회하지 않는다(빈 값).
    후보 주소는 현장 개요 소재지 + 공부스캔 주소(등기 주소라 시도·시군구까지 온전하다 — 개요 소재지는
    `옹정리 197-50` 처럼 앞이 잘려 있기도 하다). 시군구가 없는 주소는 코드를 못 믿으므로 건너뛴다.
    """
    if len(sites) < 2:
        return ()
    head = _address.dong_tail(doc_site.address) or _address.dong_tail(sites[0].outline.address)
    wanted = {_address.dong_part(s.outline.address) for s in sites[1:]}
    wanted |= {_address.dong_part(g.address) for g in gongbu}
    found: list[tuple[str, str]] = []
    for addr in sorted(x for x in wanted if x):
        if _address.dong_tail(addr) == head or len(addr.split()) < 3:
            continue
        code = apw.fetch_legal_code(cursor, addr)
        if code:
            found.append((addr, code))
    return tuple(found)


def build_context(cfg, doc_id: str, tables: dict, section_body) -> DocumentContext:
    info = (tables.get("gam_info") or [{}])[0]
    sites = _sites_from(section_body)

    gongbu = ()
    if cfg.scan_sql is not None:
        with connect(cfg.scan_sql, readonly=True) as scan_conn:
            gongbu = scan.fetch_rows(scan_conn.cursor(), doc_id)

    with connect(cfg.source_sql, readonly=True) as source:
        cursor = source.cursor()
        master_id = apw.fetch_master_id(cursor, doc_id)
        jibun = apw.fetch_jibun(cursor, doc_id)
        site = apw.fetch_site(cursor, doc_id)
        appraisers = apw.fetch_appraisers(cursor, doc_id)
        sender = apw.fetch_sender(cursor, doc_id)
        reviewer = apw.fetch_reviewer(cursor, master_id) if master_id else None
        account = apw.fetch_account(cursor, master_id) if master_id else None
        legal_codes = _legal_codes(cursor, sites, site, gongbu)

    def money(key: str):
        value = info.get(key)
        return outline.to_decimal(str(value)) if value not in (None, "") else None

    layers = cost.parse(
        (section_body("감정평가액 산출 과정") or "") + (section_body("감정평가 개요") or "")
    )
    boss = (info.get("President") or "").replace(" ", "") or None
    writer = info.get("writer_name")
    parsed_outline = sites[0].outline if sites else outline.parse(section_body("대상물건 개요"))
    details = detail.parse(tables)
    # 화면 소재지는 시도·시군구까지 필요하다. **DB `apw_masterex.ADDR` 이 바로 그 값**이라
    # 그걸 먼저 쓰고(농협 13/14·기업 실측 일치), 비어 있을 때만 의견서 본문에서 찾는다.
    site_address = site.address or _address.full_address(
        (section_body("감정평가 개요") or "") + (section_body("대상물건 개요") or ""),
        parsed_outline.address,
        *(row.location for row in details if row.location),
    )
    return DocumentContext(
        doc_id=doc_id,
        business_number=cfg.business_number,
        parties=Parties(
            boss=boss,
            appraisers=appraisers or tuple(x for x in (writer,) if x),
            reviewer=reviewer or kb.reviewer_from_round(tables),
            sender=sender,
        ),
        fee=Fee(net=money("SUSU"), vat=money("TAX"), subtotal=money("SUSUSUM"),
                total=money("TOTAL"), expense_base=money("SILBISUM"),
                expense_extra=money("SILBI"),
                expense_parts=tuple(
                    x for x in (money("GONGBU"), money("YEBI"), money("MULJOSABI"),
                                money("TOJOSABI")) if x)),
        account=account,
        jibun=jibun,
        outline=parsed_outline,
        site_address=site_address,
        site_full=site.full,
        client_doc_no=(str(info.get("cuctdocid")).strip() or None
                       if info.get("cuctdocid") not in (None, "") else None),
        rounds=round_parse.parse(tables),
        buildings=buildings.parse(section_body("대상물건 개요")),
        units=units.parse(section_body("대상물건 개요")),
        machines=machines.parse(section_body("대상물건 개요")),
        # 비교표준지 표는 '감정평가 개요' 뿐 아니라 '산출 근거/과정' 섹션에도 온다
        # (토지 공시지가기준 건 — 실측 0668). 세 섹션을 이어 붙여 넘긴다.
        standard_land=standard_land.parse(
            (section_body("감정평가 개요") or "")
            + (section_body("감정평가액 산출 근거") or "")
            + (section_body("감정평가액 산출 과정") or "")),
        characteristics=characteristics.parse(section_body("그 밖의 사항")),
        cost_layers=layers,
        # gamexport 는 날짜를 **추출한 PC 의 로캘**로 찍는다(ISO 인 PC 도, `8/12/2026` 인 PC 도 있다) —
        # 화면에 그대로 넣으면 안 되므로 여기서 ISO 로 못 박는다(농협 인계본 표본 4건 실측, 2026-09-07).
        price_point_date=outline.to_iso_date(info.get("PricePointDate")),
        survey_date=outline.to_iso_date(info.get("SearchStartDate")),
        total_amount=money("price"),
        properties=mullist.parse(tables),
        gongbu=gongbu,
        kb_summary=kb.parse_summary(tables),
        kb_checks=kb.parse_checks(tables),
        con=kb.parse_con(tables),
        details=details,
        excluded_parts=detail.excluded_parts(tables),
        legal_text=outline.parse_legal(section_body("감정평가액 결정")),
        expense_note=(tables.get("bill30") or [{}])[0].get("area6") or None,
        gam_category=(str(info.get("category")).strip() or None) if info.get("category") not in (None, "") else None,
        sites=sites,
        legal_codes=legal_codes,
        lease_hint=rental.lease_hint(tables),
        spec_extras=detail.spec_extras(tables),
    )


def screen_values(form: driver.WindowRef) -> dict[str, str]:
    """화면에서 비교 대상 값만 뽑는다.

    라디오 그룹/버튼은 제외한다 — 그룹은 캡션(`평가방법`)이, 버튼은 자기 이름이
    값으로 읽혀서 비교하면 전부 잡음이 된다. 선택 상태는 별도로 봐야 한다.
    """
    values: dict[str, str] = {}
    for field in collect(walk(_connect(driver.BACKEND, title_re=None, pid=None,
                                       handle=form.handle))):
        if "RadioGroup" in field["class_name"]:
            continue
        if field["label"] and field["db_bound"] and field["value"]:
            values.setdefault(field["label"], field["value"])
    return values


_CODE_SUFFIX = re.compile(r"\((\d+)\)\s*$")


def normalize_value(text: str) -> str:
    """비교용 정규화.

    콤보는 사람 이름 뒤에 내부 코드를 붙여 보여준다(`박용준(3056)`). 우리는
    이름으로 고르므로 코드는 떼고 비교한다. 콤마도 표시 서식이라 뗀다.
    """
    return _CODE_SUFFIX.sub("", text.replace(",", "")).strip()


def compare(mine: dict[str, str | None], screen: dict[str, str]) -> tuple[int, int, int]:
    same = differ = only_screen = 0
    rows = []
    for label in sorted(set(mine) | set(screen)):
        ours = normalize_value(mine.get(label) or "")
        theirs = normalize_value(screen.get(label) or "")
        if not ours and not theirs:
            continue
        if ours and theirs:
            mark = "일치" if ours == theirs else "불일치"
            same, differ = (same + 1, differ) if mark == "일치" else (same, differ + 1)
        elif theirs:
            mark = "화면만"
            only_screen += 1
        else:
            mark = "우리만"
        rows.append((mark, label, ours or "-", theirs or "-"))

    order = {"불일치": 0, "화면만": 1, "우리만": 2, "일치": 3}
    for mark, label, ours, theirs in sorted(rows, key=lambda r: (order[r[0]], r[1])):
        print(f"  [{mark:4}] {label[:22]:24} 우리={ours[:26]:28} 화면={theirs[:26]}")
    return same, differ, only_screen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_form")
    parser.add_argument("doc_id", nargs="+")
    parser.add_argument("--env", default=None)
    parser.add_argument("--keep", action="store_true", help="받은 .gam 을 지우지 않는다")
    parser.add_argument("--live", action="store_true",
                        help="DW 대신 FTP 로 .gam 을 직접 받는다(기본은 DW)")
    args = parser.parse_args(argv)

    cfg = load_config(args.env)
    mains = driver.find_windows(driver.MAIN_CLASS)
    if not mains:
        print("BANK24 가 실행돼 있지 않습니다.", file=sys.stderr)
        return 1
    session = navigate.Session(mains[0])

    totals = [0, 0, 0]
    for doc_id in args.doc_id:
        print(os.linesep + "=" * 18 + " " + doc_id)
        form = session_open(session, doc_id)
        bank = BANK_FORMS.get(form.class_name)
        print(f"폼: {form.class_name} ({bank or '미지원'})")
        if bank is None:
            continue
        result = verify_one(cfg, args, doc_id, form, bank)
        totals = [t + r for t, r in zip(totals, result)]
    print(f"{os.linesep}[합계] 일치 {totals[0]} / 불일치 {totals[1]} / 화면에만 있음 {totals[2]}")
    return 0


def session_open(session, doc_id: str) -> driver.WindowRef:
    """같은 프로세스 안에서 문서를 열어 준다(앞 문서 폼은 닫는다)."""
    return navigate.open_document(session, doc_id)


def verify_one(cfg, args, doc_id: str, form, bank) -> tuple[int, int, int]:
    """문서 한 건: 자료 적재 → 매핑 → 화면과 대조."""
    work = out = None
    if args.live:
        gam, work, out = fetch_gam(cfg, doc_id)
        tables, section_body = gam.tables, sections_from_gam(gam)
        source_label = "FTP 실시간"
    else:
        tables, section_body = load_from_dw(cfg, doc_id)
        source_label = "GamJun DW"
    try:
        context = build_context(cfg, doc_id, tables, section_body)
        print(f"자료 출처: {source_label} / mullist 물건행: {len(context.properties)}개")
        if bank == "신한":
            combos = load_combos(__import__("bankon.paths", fromlist=["RECON_DIR"]).RECON_DIR / "combo_shinhan.md")
            mine = shinhan.build(context, combos)[0]
        else:
            mine = kookmin.build(context)
        same, differ, only_screen = compare(mine, screen_values(form))
        print(f"일치 {same} / 불일치 {differ} / 화면에만 있음 {only_screen}")
        return same, differ, only_screen
    finally:
        if not args.keep and work is not None:
            shutil.rmtree(work, ignore_errors=True)
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
