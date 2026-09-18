# -*- coding: utf-8 -*-
"""감정평가 워크북의 (토지이용)/(건축대장) 탭에 KRAS 조회 결과를 기입한다.

- 원본은 절대 수정하지 않고 복사본을 만들어 기입한다.
- 사진·도형·수식 보존을 위해 Excel COM(실제 엑셀)을 사용한다.
- 수식 셀(제한1~3, 목록, 비교 행)은 건드리지 않는다.
"""
import re
import shutil
from pathlib import Path

# (토지이용) 필지 블록 시작행: 1~4번째 필지 = 4, 19, 34, 49 (15행 간격, 최대 10블록)
LANDUSE_BLOCK_BASE = 4
LANDUSE_BLOCK_STEP = 15

# (건축대장) 양식 병합 범위 — 병합 없는 원본 워크북에 수작업 관례대로 만들어준다
BLD_MERGES = ["C8:E8", "B10:B11", "C10:C11", "E10:E11", "F10:F11", "G10:G11",
              "B13:B14", "C13:C14", "D13:D14", "E13:E14", "F13:F14",
              "C16:C17", "D16:D17", "E16:G17"]


def landuse_merges(base):
    """필지 블록 1개의 병합 범위 (국토계획/다른법령/시행령 세로 + 좌측 라벨 가로)"""
    return [f"C{base + 5}:C{base + 8}", f"C{base + 9}:C{base + 11}",
            f"C{base + 12}:C{base + 14}",
            f"A{base + 12}:B{base + 12}", f"A{base + 13}:B{base + 13}",
            f"A{base + 14}:B{base + 14}"]


def _annex(bld):
    """'부속건축물' '0동 0㎡' -> ('0동', '0㎡'). 없으면 ('', '')"""
    parts = (bld.get("부속건축물") or "").split()
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return re.sub(r"\s+", " ", str(v)).strip()


class ExcelFiller:
    def __init__(self):
        import win32com.client
        self.excel = win32com.client.DispatchEx("Excel.Application")
        self.excel.Visible = False
        self.excel.DisplayAlerts = False

    def close(self):
        try:
            self.excel.Quit()
        except Exception:
            pass

    def fill(self, src_path, out_path, landuse_list, bld, dry_run=False):
        """
        landuse_list: [dict] parse_landuse 결과, 필지 순서대로
        bld: parse_bld_title 결과 + {'명칭','지번텍스트'} 보강 (None이면 건축대장 생략)
        out_path: None이면 원본에 바로 기입, 지정하면 복사본을 만들어 기입
        Returns: diffs = [(시트, 셀, 기존값, 새값)]
        """
        # Excel COM은 상대경로를 자기 작업폴더 기준으로 해석하므로 절대경로 필수
        src_path = str(Path(src_path).resolve())
        if out_path is None:
            target = src_path
        else:
            out_path = str(Path(out_path).resolve())
            if not dry_run:
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, out_path)
            target = src_path if dry_run else out_path

        wb = self.excel.Workbooks.Open(target, UpdateLinks=0,
                                       ReadOnly=dry_run, IgnoreReadOnlyRecommended=True)
        if not dry_run and wb.ReadOnly:
            # 다른 엑셀에서 열려 있으면 읽기전용으로 붙어 저장이 원본에 반영되지 않는다
            wb.Close(SaveChanges=False)
            raise RuntimeError("파일이 다른 곳(엑셀)에서 열려 있어 기입할 수 없음 — 닫고 다시 실행")
        diffs = []
        try:
            ws = wb.Worksheets("(토지이용)")
            for i, lu in enumerate(landuse_list):
                if not lu:  # 조회 실패 필지: 블록 위치만 유지하고 건드리지 않음
                    continue
                base = LANDUSE_BLOCK_BASE + LANDUSE_BLOCK_STEP * i
                area = lu.get("면적", "")
                try:
                    area = float(area.replace(",", ""))
                    if area == int(area):
                        area = int(area)
                except (ValueError, AttributeError):
                    pass
                writes = []
                if lu.get("_공시지가"):
                    writes.append((f"B{base}", lu["_공시지가"]))
                writes += [
                    (f"A{base + 4}", lu.get("소재지", "")),
                    (f"B{base + 4}", lu.get("지번", "")),
                    (f"C{base + 4}", lu.get("지목", "")),
                    (f"D{base + 4}", area),
                    (f"C{base + 5}", lu.get("국토계획", "")),
                    (f"C{base + 9}", lu.get("다른법령", "")),
                    (f"C{base + 12}", lu.get("시행령사항", "")),
                ]
                self._apply(ws, "(토지이용)", writes, diffs, dry_run)
                for addr in landuse_merges(base):
                    self._ensure_merge(ws, "(토지이용)", addr, diffs, dry_run)
                if not dry_run:
                    # 근거 텍스트(국토계획/다른법령/시행령)는 수작업 관례 서체: 돋움 9pt
                    for off in (5, 9, 12):
                        font = ws.Range(f"C{base + off}").Font
                        font.Name = "돋움"
                        font.Size = 9

            if bld:
                ws = wb.Worksheets("(건축대장)")
                writes = [
                    ("C8", bld.get("대지위치", "")),
                    ("G8", bld.get("지번", "")),
                    ("C9", bld.get("대지면적", "")),
                    ("E9", bld.get("연면적", "")),
                    ("G9", bld.get("명칭", "") or bld.get("명칭 및 번호", "")),
                    ("I9", bld.get("_최고층") or ""),
                    ("C10", bld.get("건축면적", "")),
                    ("E10", bld.get("용적률 산정용 연면적", "")),
                    ("G10", bld.get("건축물수", "")),
                    ("C12", bld.get("_건폐율값")),
                    ("E12", bld.get("_용적률값")),
                    ("G12", bld.get("총호수", "")),
                    ("C13", bld.get("주용도", "")),
                    ("E13", bld.get("주구조", "")),
                    ("G13", _annex(bld)[0]),  # 부속건축물 '0동 0㎡' -> 동
                    ("G14", _annex(bld)[1]),  #                     -> ㎡
                    ("C15", bld.get("허가일자", "")),
                    ("E15", bld.get("착공일자", "")),
                    ("G15", bld.get("사용승인일자", "")),
                    ("C16", bld.get("위반건축물여부", "") or bld.get("위반건축물 여부", "")),
                ]
                writes = [(c, v) for c, v in writes if v not in (None, "")]
                self._apply(ws, "(건축대장)", writes, diffs, dry_run)
                for addr in BLD_MERGES:
                    self._ensure_merge(ws, "(건축대장)", addr, diffs, dry_run)

            if not dry_run:
                wb.Save()
        finally:
            wb.Close(SaveChanges=False)
        return diffs

    @staticmethod
    def _ensure_merge(ws, sheet_name, addr, diffs, dry_run):
        """addr 범위가 병합돼 있지 않으면 병합한다(수작업 양식 관례).

        좌상단 외 셀에 값이 있으면 병합 시 그 값이 지워지므로 건드리지 않는다.
        """
        rng = ws.Range(addr)
        if rng.MergeCells is True:  # 전체가 이미 한 병합이면 그대로
            return
        n = rng.Cells.Count
        if any(_norm(rng.Cells(i).Value) for i in range(2, n + 1)):
            print(f"  [경고] {sheet_name}!{addr} 병합 생략 — 좌상단 외 셀에 값 있음")
            return
        diffs.append((sheet_name, addr, "", "[병합]"))
        if not dry_run:
            rng.Merge()

    @staticmethod
    def _apply(ws, sheet_name, writes, diffs, dry_run):
        for cell, new in writes:
            old = ws.Range(cell).Value
            if _norm(old) != _norm(new):
                diffs.append((sheet_name, cell, _norm(old), _norm(new)))
            if not dry_run:
                ws.Range(cell).Value = new
