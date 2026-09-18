"""처리 로그 파싱 — 대시보드 숫자가 여기서 나온다.

로그 줄에 **날짜가 없다**(시각만). 파일명이 시작일로 고정돼 자정을 넘겨도 같은 파일에
쌓이므로, 시각이 거꾸로 가면 다음 날로 넘겨야 한다. 그 판정이 이 파일의 핵심이다.
"""
from __future__ import annotations

from datetime import date, datetime

from bankon import runlog


def write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


SEND = ("[{time}] Send#{seq} {doc} [{bank}] 의뢰 2026-08-26 요청 08-31 15:47 "
        "(왕성진) APW=완료처리(발송)/10 → {result}")


def line(time, result, seq=12290, doc="01-2608-3-2711", bank="국민"):
    return SEND.format(time=time, seq=seq, doc=doc, bank=bank, result=result)


class TestClassify:
    def test_아는_표현(self):
        assert runlog.classify("실패 exit=1 reports/full_20260831_161345.log") == "실패"
        assert runlog.classify("제외(이미 완료)") == "제외"
        assert runlog.classify("보류(담보 아님, 기록 안 함)") == "보류"

    def test_실행표시는_결과가_아니다(self):
        # `→ 실행 LIVE` 는 시작 표시다. 결과로 세면 건수가 두 배가 된다.
        assert runlog.classify("실행 LIVE") is None

    def test_모르는_표현은_기타로_남긴다(self):
        # 성공 줄의 실물을 아직 못 봤다 — 못 알아보면 버리지 말고 드러내야 한다.
        assert runlog.classify("이상한새표현") == "기타"


class TestParse:
    def test_한_줄에서_필드를_다_뽑는다(self, tmp_path):
        write(tmp_path, "gui_20260831.log", line("16:13:45", "제외(이미 완료)"))
        run = runlog.parse_gui_log(tmp_path / "gui_20260831.log")[0]
        assert run.doc_id == "01-2608-3-2711"
        assert run.bank == "국민"
        assert run.result == "제외"
        assert run.send_seq == 12290
        assert run.apw_status == "완료처리(발송)/10"
        assert run.requester == "왕성진"
        assert run.order_date == date(2026, 8, 26)
        assert run.at == datetime(2026, 8, 31, 16, 13, 45)

    def test_실패줄은_full로그_시각을_쓴다(self, tmp_path):
        # 줄 시각이 어긋나 있어도 full 로그 이름이 정확한 시각을 준다.
        write(tmp_path, "gui_20260831.log",
              line("16:13:45", "실패 exit=1 reports/full_20260831_161345.log"))
        run = runlog.parse_gui_log(tmp_path / "gui_20260831.log")[0]
        assert run.at == datetime(2026, 8, 31, 16, 13, 45)
        assert run.key == "full_20260831_161345.log"

    def test_자정을_넘기면_다음날로(self, tmp_path):
        write(tmp_path, "gui_20260901.log", "\n".join([
            line("23:50:00", "제외(이미 완료)"),
            line("00:10:00", "제외(이미 완료)"),
            line("01:20:00", "제외(이미 완료)"),
        ]))
        runs = runlog.parse_gui_log(tmp_path / "gui_20260901.log")
        assert [r.at.date() for r in runs] == [
            date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 2)]

    def test_실행표시줄은_내역이_안된다(self, tmp_path):
        write(tmp_path, "gui_20260831.log", "\n".join([
            line("16:13:40", "실행 LIVE"),
            line("16:13:45", "실패 exit=1 reports/full_20260831_161345.log"),
        ]))
        runs = runlog.parse_gui_log(tmp_path / "gui_20260831.log")
        assert len(runs) == 1 and runs[0].result == "실패"

    def test_실패사유와_모드를_full로그에서_가져온다(self, tmp_path):
        write(tmp_path, "full_20260831_161345.log", "\n".join([
            "[runner] start 20260831_161345 대상=01-2608-3-2711 "
            "기간=2026-08-26~2026-08-26 모드=★LIVE+저장+PDF등록 옵션=[]",
            "Traceback (most recent call last):",
            "bankon.sources.archive.ArchiveError: 수수료 PDF 를 못 찾았습니다: X",
            "[runner] 실패 ArchiveError('수수료 PDF 를 못 찾았습니다: X')",
            "[runner] exit=1",
        ]))
        write(tmp_path, "gui_20260831.log",
              line("16:13:45", "실패 exit=1 reports/full_20260831_161345.log"))
        run = runlog.parse_gui_log(tmp_path / "gui_20260831.log", tmp_path)[0]
        assert run.mode == "★LIVE+저장+PDF등록"
        assert run.error and "수수료 PDF" in run.error

    def test_같은_줄을_두_번_읽어도_한_건(self, tmp_path):
        write(tmp_path, "gui_20260831.log",
              line("16:13:45", "실패 exit=1 reports/full_20260831_161345.log"))
        assert len(runlog.collect(tmp_path, tmp_path)) == 1


class TestSummary:
    """**작성건수 = 성공한 문서 수**(중복 제거). 같은 건을 10분마다 재시도하므로
    실행 횟수를 그대로 쓰면 부풀어 보인다 — 실측에서 보류 100건이 한 문서였다."""

    def _runs(self, tmp_path):
        write(tmp_path, "gui_20260831.log", "\n".join([
            line("10:00:00", "성공", seq=1, doc="01-2608-3-0001"),
            line("10:10:00", "성공", seq=1, doc="01-2608-3-0001"),   # 같은 문서 재처리
            line("10:20:00", "성공", seq=2, doc="01-2608-3-0002", bank="신한"),
            line("10:30:00", "실패 exit=1", seq=3, doc="01-2608-3-0003"),
            line("10:40:00", "보류(담보 아님, 기록 안 함)", seq=4, doc="01-2608-3-0004"),
        ]))
        return runlog.collect(tmp_path)

    def test_작성건수는_문서_기준(self, tmp_path):
        stats = runlog.summary(self._runs(tmp_path), today=date(2026, 8, 31))
        assert stats["총작성건수"] == 2          # 0001·0002 (0001 두 번 처리해도 1)
        assert stats["총성공"] == 3              # 실행 횟수는 3
        assert stats["총실패"] == 1
        assert stats["총스킵"] == 1
        assert stats["총문서수"] == 4

    def test_금일은_그날만(self, tmp_path):
        stats = runlog.summary(self._runs(tmp_path), today=date(2026, 9, 2))
        assert stats["총작성건수"] == 2 and stats["금일작성건수"] == 0

    def test_은행별(self, tmp_path):
        rows = {r["은행"]: r for r in runlog.by_bank(self._runs(tmp_path),
                                                    today=date(2026, 8, 31))}
        assert rows["국민"]["총작성건수"] == 1
        assert rows["신한"]["총작성건수"] == 1
        assert rows["국민"]["총실패"] == 1
