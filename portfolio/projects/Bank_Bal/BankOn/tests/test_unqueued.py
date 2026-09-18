"""큐에 없는 감정서를 번호로 콕 집어 '1회 처리' — 시연·수동 실행 경로(2026-09-17).

후보 SQL 은 Apw_YJI_Send JOIN apw_masterex 라, 발송 요청이 없는 옛 건은 only_doc 을 줘도 0건이었다
(01-2608-3-2513: 큐 행 없음, APW 72/22 조사후반려). 사람이 번호를 적어 누른 경우에 한해
apw_masterex 만으로 후보 1건을 만들고, Send_Seq 가 없으니 이력(Apw_YJI_BankAuto)은 남기지 않는다.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import run_queue_worker as W  # noqa: E402

DOC = "01-2608-3-2513"
ROW = ("01-2608-3-2513", "국민은행 증권타운지점장", dt.datetime(2026, 8, 10), "완료처리(조사후반려)", "22")


class FakeCursor:
    """apw_masterex 한 행만 돌려주는 커서."""

    description = [("DocID",), ("CustName",), ("RequestDate",), ("LStatus",), ("Result",)]

    def __init__(self, row):
        self._row = row
        self.sql = ""

    def execute(self, sql, *params):
        self.sql = sql
        return self

    def fetchone(self):
        return self._row


class FakeConn:
    def __init__(self, row):
        self._cur = FakeCursor(row)

    def cursor(self):
        return self._cur


class TestUnqueuedCandidate:
    def test_큐에_없어도_후보_1건을_만든다(self):
        rows = W.unqueued_candidate(FakeConn(ROW), DOC)
        assert len(rows) == 1
        assert rows[0]["Docid"] == DOC
        assert rows[0]["CustName"] == "국민은행 증권타운지점장"
        assert rows[0]["RequestDate"] == dt.datetime(2026, 8, 10)

    def test_Send_행이_없으니_Seq_는_None(self):
        # one_round 가 이걸 보고 record()/send_status() 를 건너뛴다 — 이력 오염 방지
        assert W.unqueued_candidate(FakeConn(ROW), DOC)[0]["Seq"] is None

    def test_APW_에도_없는_번호는_빈_목록(self):
        assert W.unqueued_candidate(FakeConn(None), "01-2699-3-9999") == []

    def test_후보_모양은_큐_후보와_같은_키를_갖는다(self):
        # one_round 가 r["LStatus"]·r["Emp_Regi"] 등을 그대로 포맷한다
        row = W.unqueued_candidate(FakeConn(ROW), DOC)[0]
        assert set(row) == {"Seq", "Docid", "Insert_Date", "Emp_Regi", "CustName",
                            "RequestDate", "LStatus", "Result"}

    def test_큐_없는_건은_은행_담보_가드를_그대로_탄다(self):
        row = W.unqueued_candidate(FakeConn(ROW), DOC)[0]
        assert W.bank_of(row["CustName"]) == "국민"
        assert W.DAMBO_DOC.match(row["Docid"])
