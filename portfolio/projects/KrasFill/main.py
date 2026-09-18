# -*- coding: utf-8 -*-
"""일사편리(KRAS) -> 감정평가 워크북 (토지이용)/(건축대장) 자동 기입.

기본 흐름: 파일명의 감정서번호(예 01-2605-1-0265) -> apworksdw APW_MasterEx에서
법정동코드·대표필지 조회 -> 일사편리 조회 -> 탭 기입.
전체 필지 목록은 파일명 주소 > (정식) 탭 > DB 대표필지 순으로 확보한다.
감정서번호가 없거나 DB 조회 실패 시 파일명/워크북 주소 파싱으로 폴백.

사용법:
  python main.py <워크북.xlsx 또는 폴더> [...]  [--dry-run] [--out 출력폴더]
  python main.py --addr "경기 부천시 원미구 원미동148-21, 148-22"   # 조회만

- 기본은 원본 워크북에 바로 기입한다. --out 지정 시 복사본(*_KRAS.xlsx)에 기입.
- 폴더를 주면 안의 모든 .xlsx를 일괄 처리한다.
"""
import argparse
import re
import sys
import io
import traceback
from pathlib import Path

# GUI(gui.py)가 stdout을 로그 큐로 바꿔치기한 채 import하는 경우가 있어 buffer 있는 콘솔만 감싼다
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from addr import (parse_address, parse_address_from_workbook,
                  read_parcels_from_jsik, read_parcels_from_deunggi)
from kras_client import KrasClient, pct_to_ratio

DOCID_RE = re.compile(r"\d{2}-\d{4}-\d-\d{4}")
DONG_RE = re.compile(r"제?(\d{1,4})동")  # 파일명의 '제101동'/'107동' (읍면동은 숫자 앞이 아니라 불일치)

_clients = {}


def get_client(key):
    """key: 시도명('경기') 또는 법정동코드 앞 2자리('41')"""
    if key not in _clients:
        _clients[key] = KrasClient(key)
    return _clients[key]


def _num(s):
    """'1,429.3㎡' -> 1429.3 (없으면 0)"""
    m = re.search(r"[\d,.]+", s or "")
    try:
        return float(m.group().replace(",", "")) if m else 0.0
    except ValueError:
        return 0.0


def pick_title_row(blds, dong):
    """건축물대장 목록에서 대상 표제부 1건 선택.

    총괄표제부('총괄표제부'도 '표제부'를 포함하므로 명시 제외)는 상세 파싱이 안 되므로 뺀다.
    다동 건물은 파일명의 동 번호로 매칭하고, 특정 못 하면 오기입 방지를 위해 None.
    """
    rows = [b for b in blds if "표제부" in b["대장종류"] and "총괄" not in b["대장종류"]]
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    if dong:
        for b in rows:
            if re.sub(r"\D", "", b.get("동명칭") or "") == dong:
                return b
        print(f"  [경고] 파일명 동({dong}동)과 일치하는 표제부 없음 — "
              f"동 목록: {[b['동명칭'] for b in rows]} — 건축대장 미기입")
        return None
    print(f"  [경고] 표제부가 여러 동인데 파일명에 동 번호 없음 — "
          f"동 목록: {[b['동명칭'] for b in rows]} — 건축대장 미기입")
    return None


def fetch_parcels(client, umd_code, jibuns, dong=None, verbose=True):
    """법정동코드+지번 목록으로 KRAS 조회 -> (landuse_list, bld)"""
    landuse_list, bld = [], None
    price_down = False
    for idx, jibun in enumerate(jibuns):
        landcode = client.make_landcode(umd_code, jibun)
        page = client.fetch_parcel(landcode)
        lu = client.parse_landuse(page)
        if not lu or not lu.get("지번"):
            print(f"  [경고] {jibun}: 토지이용 정보 없음")
            lu = None
        else:
            price = client.parse_landprice(page)
            if price:
                lu["_공시지가"] = price
            elif client.landprice_server_down(page):
                price_down = True
            if verbose:
                p = f", 공시지가={price:,}원" if price else ""
                print(f"  {jibun}: 지목={lu['지목']}, 면적={lu['면적']}㎡, "
                      f"용도지역={lu['국토계획'][:30]}{p}")
        landuse_list.append(lu)

        # 건축물대장은 대표지번(첫 필지)에서 표제부를 찾는다
        if bld is None and lu is not None:
            blds = client.parse_bld_list(page)
            if not blds:  # 서버가 간헐적으로 건축물 목록 없는 페이지를 반환 -> 1회 재시도
                page = client.fetch_parcel(landcode)
                blds = client.parse_bld_list(page)
            row = pick_title_row(blds, dong)
            if row:
                title_html = client.fetch_bld_title(row["pk"], landcode, row["kind_cd"])
                bld = client.parse_bld_title(title_html)
                name = bld.get("명칭 및 번호") or row["명칭"]
                dong_nm = (row.get("동명칭") or "").strip()
                if dong_nm and dong_nm not in name:
                    if re.fullmatch(r"제?\d+동", dong_nm):
                        name = f"{name} {dong_nm}".strip()
                    else:
                        # 동명칭이 고유명('광백드림빌')이면 그것이 실제 건물명 (수작업 관례)
                        name = dong_nm
                bld["명칭"] = name
                # 다동 단지의 동별 표제부는 대지면적이 0으로 옴 -> 총괄표제부에서 보강
                if _num(bld.get("대지면적")) == 0:
                    recap_rows = [b for b in blds if "총괄" in b["대장종류"]]
                    if not recap_rows:  # 서버가 간헐적으로 목록 일부를 빠뜨림 -> 1회 재조회
                        blds2 = client.parse_bld_list(client.fetch_parcel(landcode))
                        recap_rows = [b for b in blds2 if "총괄" in b["대장종류"]]
                    if recap_rows:
                        rr = recap_rows[0]
                        recap = client.parse_bld_title(client.fetch_bld_title(
                            rr["pk"], landcode, rr["kind_cd"], recap=True))
                        if _num(recap.get("대지면적")) > 0:
                            bld["대지면적"] = recap["대지면적"]
                            print(f"  대지면적은 총괄표제부에서 보강: {bld['대지면적']}")
                    if _num(bld.get("대지면적")) == 0:
                        # 0㎡로 기존 값을 덮지 않도록 비운다(빈 값은 기입에서 제외됨)
                        bld["대지면적"] = ""
                        print("  [경고] 대지면적 0 — 총괄표제부 보강 실패, 셀은 기존값 유지")
                # 인천 등 일부 대장은 표제부 주구조가 비어 있음 -> 층별현황 최빈 구조로 보강
                if not bld.get("주구조"):
                    structs = [f["구조"] for f in bld.get("_층별현황", []) if f.get("구조")]
                    if structs:
                        bld["주구조"] = max(set(structs), key=structs.count)
                        print(f"  주구조는 층별현황에서 보강: {bld['주구조']}")
                bld["_건폐율값"] = pct_to_ratio(bld.get("건폐율", ""))
                bld["_용적률값"] = pct_to_ratio(bld.get("용적률", ""))
                if verbose:
                    print(f"  건축물대장(표제부): {bld['명칭']} / "
                          f"대지 {bld.get('대지면적')} / 연면적 {bld.get('연면적')} / "
                          f"승인 {bld.get('사용승인일자')} / 최고 {bld.get('_최고층')}층")
        if bld is None and idx == len(jibuns) - 1:
            print("  [경고] 건축물대장 표제부를 찾지 못함")

    if price_down:
        print("  [경고] 개별공시지가: 지자체 서버 연결 실패 — 공시지가 셀은 기존값 유지. "
              "나중에 다시 실행하면 채워짐")
    return landuse_list, bld


def combine_jibuns(file_jibuns, src):
    """파일명 지번과 (정식)/(등기) 탭 목록을 합친다 -> (jibuns, 출처).

    '외 N필지' 파일명처럼 일부만 적힌 경우 나머지 필지를 워크북에서 보충한다.
    (정식) 탭이 파일명 지번을 모두 포함하면 그 목록을 순서째 쓴다 — 토지이용
    블록의 '목록' 비교 행이 (정식) 순서를 기준으로 하기 때문.
    (정식) 탭도 일부만 적힌 경우가 있어('외 6필지'인데 2필지만 등재된 사례),
    (등기) 탭 토지 목록(등기부 표제부의 전체 필지)이 현재 목록을 모두 포함하면
    그 전체 목록을 쓴다 — 다른 건의 잔여 데이터라면 대표지번이 없어 걸러진다.
    """
    try:
        jsik = read_parcels_from_jsik(src)
    except Exception:
        jsik = []
    file_jibuns = file_jibuns or []
    m = re.search(r"외\s*(\d+)\s*필지", src.name)
    if not jsik:
        jibuns, list_src = file_jibuns, "파일명/워크북"
    elif not file_jibuns:
        jibuns, list_src = jsik, "(정식) 탭"
    # 보충은 파일명이 '외 N필지'로 일부만 적었을 때만 — (정식) 탭에는 이전 건의
    # 잔여 목록이 남아있을 수 있어 무조건 합치면 엉뚱한 필지를 기입할 위험
    elif not m:
        return file_jibuns, "파일명/워크북"
    elif set(file_jibuns) <= set(jsik):
        jibuns, list_src = jsik, "(정식) 탭(파일명 보충)"
    else:
        extra = [j for j in jsik if j not in file_jibuns]
        jibuns, list_src = file_jibuns + extra, \
            ("파일명+(정식) 탭" if extra else "파일명/워크북")

    if m and jibuns:
        try:
            deunggi = read_parcels_from_deunggi(src)
        except Exception:
            deunggi = []
        if deunggi and set(jibuns) <= set(deunggi) and len(deunggi) > len(jibuns):
            expected = int(m.group(1)) + 1
            if len(deunggi) != expected:
                print(f"  [경고] (등기) 탭 필지 {len(deunggi)}개가 파일명 "
                      f"'외 {m.group(1)}필지'({expected}개)와 다름 — (등기) 목록 사용")
            return deunggi, "(등기) 탭(전체 필지)"
    return jibuns, list_src


def resolve_target(src):
    """파일 1건의 조회 대상 결정 -> (client, umd_code, jibuns) 또는 None.

    1순위: 감정서번호 -> APW_MasterEx (법정동코드 확정)
    필지 목록: 파일명 주소 > (정식) 탭 > DB 대표필지
    폴백: 파일명/워크북 주소 파싱 -> 일사편리 콤보 API로 코드 조회
    """
    master = None
    m = DOCID_RE.search(src.name)
    if m:
        try:
            from db_lookup import fetch_master
            master = fetch_master(m.group(0))
            if not master:
                print(f"  [경고] APW_MasterEx에 감정서번호 없음: {m.group(0)}")
        except Exception as e:
            print(f"  [경고] DB 조회 실패({e.__class__.__name__}) — 주소 파싱으로 폴백")
    else:
        print("  [안내] 파일명에 감정서번호 없음 — 주소 파싱으로 폴백")

    addr_info = parse_address(src.name) or parse_address_from_workbook(src)

    if master:
        umd_code = master["umd_code"]
        client = get_client(umd_code[:2])
        jibuns, list_src = combine_jibuns(
            addr_info["jibuns"] if addr_info else [], src)
        if not jibuns:
            jibuns, list_src = [master["jibun"]], "DB 대표필지"
        if master["jibun"] not in jibuns:
            print(f"  [경고] DB 대표필지 {master['jibun']}이(가) 필지 목록{jibuns}에 없음 "
                  f"— 목록 맨 앞에 추가")
            jibuns = [master["jibun"]] + jibuns
        print(f"  대상(DB {m.group(0)}): {master['addr']} "
              f"{', '.join(jibuns)} ({len(jibuns)}필지, 목록출처: {list_src}) "
              f"/ {master['building']} {master['floor']}층 {master['ho']}호")
        return client, umd_code, jibuns

    if addr_info:
        client = get_client(addr_info["sido"])
        umd_code = client.resolve_umd_code(addr_info["sgg"], addr_info["umd"])
        jibuns, list_src = combine_jibuns(addr_info["jibuns"], src)
        print(f"  대상(주소 파싱): {addr_info['sido']} {addr_info['sgg']} "
              f"{addr_info['umd']} {', '.join(jibuns)} "
              f"({len(jibuns)}필지, 목록출처: {list_src})")
        return client, umd_code, jibuns

    print("  [오류] 감정서번호로도, 주소로도 대상을 특정할 수 없음")
    return None


def collect_files(paths):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += sorted(f for f in p.glob("*.xlsx") if not f.name.startswith("~$"))
        elif p.suffix.lower() == ".xlsx":
            files.append(p)
        else:
            print(f"[건너뜀] xlsx 아님: {p}")
    return files


def process_file(filler, src, out_dir, dry_run):
    target = resolve_target(src)
    if not target:
        return None
    client, umd_code, jibuns = target

    m = DONG_RE.search(src.name)
    dong = m.group(1) if m else None
    landuse_list, bld = fetch_parcels(client, umd_code, jibuns, dong=dong)
    if not any(landuse_list) and not bld:
        print("  [오류] 조회된 데이터 없음 — 기입 생략")
        return None

    out_path = Path(out_dir) / (src.stem + "_KRAS" + src.suffix) if out_dir else None
    diffs = filler.fill(src, out_path, landuse_list, bld, dry_run=dry_run)

    if dry_run:
        print(f"  [DRY-RUN] 기존 값과 다른 셀: {len(diffs)}건")
    elif out_path:
        print(f"  [완료] {out_path.name} / 기존 값과 다른 셀: {len(diffs)}건")
    else:
        print(f"  [완료] 원본에 기입 / 기존 값과 다른 셀: {len(diffs)}건")
    for sheet, cell, old, new in diffs:
        print(f"    {sheet}!{cell}: '{old[:50]}' -> '{new[:50]}'")
    return len(diffs)


def main():
    ap = argparse.ArgumentParser(description="일사편리 -> 감정평가 워크북 자동 기입")
    ap.add_argument("paths", nargs="*", help="워크북 .xlsx 또는 폴더 (여러 개 가능)")
    ap.add_argument("--addr", help="주소 직접 지정(조회만): '경기 부천시 원미구 원미동148-21, ...'")
    ap.add_argument("--dry-run", action="store_true", help="기입 없이 차이만 보고")
    ap.add_argument("--out", default=None,
                    help="복사본 출력 폴더 (지정 시 원본 대신 복사본에 기입; 기본: 원본에 바로 기입)")
    args = ap.parse_args()

    if args.addr:
        addr_info = parse_address(args.addr)
        if not addr_info:
            print(f"[오류] 주소를 파싱할 수 없음: {args.addr}")
            sys.exit(1)
        client = get_client(addr_info["sido"])
        umd_code = client.resolve_umd_code(addr_info["sgg"], addr_info["umd"])
        print(f"대상: {addr_info['sido']} {addr_info['sgg']} {addr_info['umd']} "
              f"{', '.join(addr_info['jibuns'])} / 법정동코드 {umd_code}")
        fetch_parcels(client, umd_code, addr_info["jibuns"])
        return

    files = collect_files(args.paths)
    if not files:
        ap.error("처리할 .xlsx가 없습니다. 파일이나 폴더를 지정하세요.")

    from fill_excel import ExcelFiller
    filler = ExcelFiller()
    ok = fail = 0
    try:
        for i, src in enumerate(files, 1):
            print(f"\n[{i}/{len(files)}] {src.name}")
            try:
                result = process_file(filler, src, args.out, args.dry_run)
                if result is None:
                    fail += 1
                else:
                    ok += 1
            except Exception as e:
                fail += 1
                print(f"  [오류] {e}")
                traceback.print_exc()
    finally:
        filler.close()

    print(f"\n===== 총 {len(files)}건: 성공 {ok}, 실패 {fail} =====")
    if not args.dry_run and ok:
        print(f"결과 폴더: {args.out}" if args.out else "원본 워크북에 직접 기입 완료")


if __name__ == "__main__":
    main()
