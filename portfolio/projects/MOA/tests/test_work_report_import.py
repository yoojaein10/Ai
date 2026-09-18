from io import BytesIO

import pytest
from openpyxl import Workbook

from app.services.work_report_import import extract_work_report_doc_ids


def _xlsx_bytes(rows_by_sheet):
    workbook = Workbook()
    first = workbook.active
    for index, rows in enumerate(rows_by_sheet):
        sheet = first if index == 0 else workbook.create_sheet()
        for row in rows:
            sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_extracts_docs_from_all_xlsx_sheets_and_removes_duplicates():
    data = _xlsx_bytes([
        [["감정서번호"], ["01-2503-5-0042"], ["중복 01-2503-5-0042"]],
        [["비고", "01-2608-b-0001 외 01-2608-3-0002"]],
    ])

    assert extract_work_report_doc_ids(data, "report.xlsx") == [
        "01-2503-5-0042", "01-2608-B-0001", "01-2608-3-0002",
    ]


def test_returns_empty_when_xlsx_has_no_doc_ids():
    data = _xlsx_bytes([[["감정서번호"], ["해당 없음"]]])
    assert extract_work_report_doc_ids(data, "empty.xlsx") == []


def test_rejects_non_excel_extension():
    with pytest.raises(ValueError, match="엑셀 파일"):
        extract_work_report_doc_ids(b"not excel", "report.csv")
