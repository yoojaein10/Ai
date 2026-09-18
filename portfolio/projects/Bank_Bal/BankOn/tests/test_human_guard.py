"""사람 작성 보호 가드 — 큐 '진행' 건을 자동 처리하면서 사람이 작성한 폼은 건드리지 않는다.

지표 칸 목록은 실측 새 폼(2780 기업·2742 국민·2717 신한)과 발송완료 폼(recon/nh_screen.json)으로 고른 것이라,
여기서는 그 실측 화면값을 그대로 넣어 오판이 없는지 고정한다.
"""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import human_guard as G           # noqa: E402
import run_queue_worker as W      # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class TestIsBlank:
    def test_빈값과_0은_안채운_칸(self):
        for v in ("", None, "0", "0.00", "0,000", " 0 "):
            assert G.is_blank(v), repr(v)

    def test_값이_있으면_채운_칸(self):
        for v in ("정영배", "2,282,500", "2026-09-04", "1"):
            assert not G.is_blank(v), repr(v)


class TestWrittenFields:
    def test_기업_새폼은_헤더_물건종류만_있어도_새폼(self):
        # 2780 새 폼 실측: 접수 단계에서 물건종류 '공장' 만 들어 있고 지표 칸은 전부 빈칸
        values = {"물건종류": "공장", "감정수수료": "", "기준시점": "", "순수수료": "", "평가사명": ""}
        assert G.written_fields(values, "기업") == []

    def test_국민_새폼은_수수료_0과_할증_미적용이_있어도_새폼(self):
        # 2742 새 폼 실측: 수수료 칸이 '0', 수수료할증적용 '미적용' 으로 미리 채워져 있음
        values = {"감정평가(순)수수료": "0", "(순)수수료-부가가치세": "0", "감정평가(순)수수료 총액": "0",
                  "수수료할증적용": "미적용", "평가사명1": ""}
        assert G.written_fields(values, "국민") == []

    def test_신한_새폼은_전부_빈칸(self):
        assert G.written_fields({"본번지": "0000", "감정평가액": "", "기준시점": ""}, "신한") == []

    def test_사람이_작성한_기업폼은_잡는다(self):
        values = {"평가사명": "전영배", "감정수수료": "2,282,500", "기준시점": "2026-09-04"}
        hits = G.written_fields(values, "기업")
        assert [k for k, _ in hits] == ["평가사명", "감정수수료", "기준시점"]

    def test_농협_발송완료_실폼_화면값은_전부_잡힌다(self):
        data = json.loads((ROOT / "recon" / "nh_screen.json").read_text(encoding="utf-8"))
        for doc, rec in list(data.items())[:5]:
            values = {f["label"]: f["value"] for f in rec["fields"] if f.get("label")}
            assert G.written_fields(values, "농협"), doc

    def test_모르는_은행은_지표_없음(self):
        assert G.written_fields({"평가사명": "x"}, "씨티") == []   # 하나는 2026-09-10 이식으로 지표 생김


class FakeNavigate:
    """발송완료 확인 경로만 흉내 낸다 — 어떤 조회로 찾았는지 기록한다."""

    NavigationError = RuntimeError

    def __init__(self, *, found_by_period=False, found_by_find=False, tab_ok=True):
        self.found_by_period, self.found_by_find, self.tab_ok = found_by_period, found_by_find, tab_ok
        self.calls: list[str] = []
        self._searched = False

    def select_tab(self, session, tab="작성"):
        self.calls.append(f"tab:{tab}")
        return self.tab_ok

    def query_documents(self, session, *, start, end, work_type="담보"):
        self.calls.append(f"query:{start}~{end}:{work_type}")

    def find_document(self, session, doc, *, settle=2.5):
        self.calls.append(f"find:{doc}")
        self._searched = True

    def find_row_by_doc(self, session, doc, *, max_rows=400):
        self.calls.append("walk")
        return self.found_by_find if self._searched else self.found_by_period


class TestInSentTab:
    """2787 실측(2026-09-10): 의뢰 09-04 건을 사람이 09-10 14:34 에 발송 → 09-01~09-05 기간 조회엔 안 걸렸다.
    그 탓에 '이미 발송완료(제외)' 가 아니라 '실패' 로 남았다. 기간에서 못 찾으면 '찾 기'로 한 번 더 본다."""

    def _run(self, nav):
        import human_guard
        old, human_guard.navigate = human_guard.navigate, nav
        try:
            return human_guard.in_sent_tab(None, "01-2609-3-2787", "2026-09-01", "2026-09-05")
        finally:
            human_guard.navigate = old

    def test_기간_조회로_찾으면_거기서_끝(self):
        nav = FakeNavigate(found_by_period=True)
        assert self._run(nav) is True
        assert "find:01-2609-3-2787" not in nav.calls          # 느린 '찾 기'는 안 쓴다

    def test_기간에_없으면_찾기로_재확인(self):
        nav = FakeNavigate(found_by_period=False, found_by_find=True)
        assert self._run(nav) is True
        assert nav.calls.index("find:01-2609-3-2787") > nav.calls.index("walk")

    def test_찾기로도_없으면_발송완료가_아니다(self):
        assert self._run(FakeNavigate(found_by_period=False, found_by_find=False)) is False

    def test_탭_선택이_안_되면_확인_못_한_것으로(self):
        # 탭 클릭이 안 먹은 채 조회하면 작성 탭을 다시 훑어 '발송완료 아님'으로 오판한다 → 아예 조회하지 않는다
        nav = FakeNavigate(found_by_period=True, tab_ok=False)
        assert self._run(nav) is False
        assert not any(c.startswith("query") for c in nav.calls)


class TestHumanizeMissed:
    """라벨을 못 짚어 넘어간 칸('미발견')은 거부와 달리 exit 0 이라 '완료'로 기록되고 아무도 몰랐다
    (2804 국민 구분건물 층수 누락 제보 2026-09-10) → 비고에 남긴다."""

    OUT = ("  [미발견    ] 물건:건물 층수             넣을값=1                          현재=\n"
           "  [미발견    ] 물건:총층수/층수            넣을값=7                          현재=\n"
           "MISSED=2 / [요약] write_fill=exit=0 | write_save=OK")

    def test_칸못찾음이_비고에_남는다(self):
        msg = W.humanize(self.OUT)
        assert "칸못찾음 2개" in msg
        assert "물건:건물 층수" in msg and "물건:총층수/층수" in msg

    def test_없으면_정상_처리(self):
        assert W.humanize("[요약] write_fill=exit=0 | write_save=OK") == "정상 처리"

    def test_거부와_같이_나오면_둘_다(self):
        msg = W.humanize("[거부(콤보)] 세부:용도지역 넣을값=제1종일반주거 현재=\n" + self.OUT)
        assert "입력 거부" in msg and "칸못찾음 2개" in msg


class FakeCursor:
    def __init__(self, row):
        self.row, self.sql, self.args = row, None, None

    def cursor(self):
        return self

    def execute(self, sql, *args):
        self.sql, self.args = sql, args

    def fetchone(self):
        return self.row


class TestSentAlready:
    """이미 발송한 건(APW Status 72 · Result 10)에 다시 발송 요청이 들어오면(재전송) 자동 작성 대상이 아니다.
    Bank24 에 사람이 작성한 내용이 이미 있기 때문 — 실측 2418(8월에 세 번 발송, 09-10 재요청되어 자동 작성돼 버렸다)."""

    def test_발송완료면_제외(self):
        conn = FakeCursor(("72", "10"))
        assert W.sent_already(conn, "01-2607-3-2418") is True
        assert "apw_Master" in conn.sql and conn.args == ("01-2607-3-2418",)

    def test_발송대기는_처리대상(self):
        assert W.sent_already(FakeCursor(("69", "01")), "01-2609-3-2799") is False

    def test_72라도_결과가_다르면_다른_상태(self):
        # '완료처리(조사전반려)' 도 72 다 — Result 까지 봐야 발송 완료를 가린다
        assert W.sent_already(FakeCursor(("72", "20")), "x") is False

    def test_없는_문서(self):
        assert W.sent_already(FakeCursor(None), "없는문서") is False

    def test_공백_패딩도_맞춘다(self):
        assert W.sent_already(FakeCursor((" 72 ", " 10 ")), "x") is True


class TestWorkerStatus:
    def test_후보_SQL과_실행직전에_둘_다_거른다(self):
        import inspect
        sql = inspect.getsource(W.candidates)
        assert "AND NOT (m.Status = ? AND m.Result = ?)" in sql
        assert "SENT_STATUS, SENT_RESULT" in sql          # 바인딩 순서(TOP·statuses 다음)
        assert "sent_already" in inspect.getsource(W.one_round)
        assert (W.SENT_STATUS, W.SENT_RESULT) == ("72", "10")

    def test_실행_직전_요청상태_재확인(self):
        # 후보를 뽑은 뒤 사람이 먼저 처리해 Status 가 '완료'로 바뀌는 일이 있다(2787) → 실행 전에 다시 읽는다
        import inspect
        src = inspect.getsource(W.one_round)
        assert "send_status" in src and "사람이 처리" in src
        assert "SELECT Status FROM dbo.Apw_YJI_Send WHERE Seq = ?" in inspect.getsource(W.send_status)

    def test_exit_코드_매핑(self):
        assert W.status_for(0) == "완료"
        assert W.status_for(W.EXIT_EXCLUDED) == "제외"
        assert W.status_for(1) == "실패"
        assert W.EXIT_EXCLUDED == G.EXIT_EXCLUDED

    def test_후보_SQL에_농협은행과_제외가_들어있다(self):
        import inspect
        src = inspect.getsource(W.candidates)
        assert "농협은행" in src
        assert "N'제외'" in src


class TestGuardOrder:
    """은행(폼 클래스) 확인이 가드보다 먼저여야 한다.

    2026-09-15 오제외: 남은 우리 폼을 국민·기업 러너가 받았는데 가드가 먼저 돌아
    '사람 작성 → 제외'(exit 3, 재시도 없음)로 끝났다. 순서가 반대면 '…폼이 아닙니다' 실패로
    남아 사람이 알아채고 재처리할 수 있다.
    """

    RUNNERS = {"run_shinhan_full.py": "TBNKSHG", "run_kb_full.py": "TBNKKBB",
               "run_ibk_full.py": "TBNKKIB", "run_nh_full.py": "WRITE_CLASS",
               "bank_runner.py": "spec.write_class"}

    def test_모든_러너가_폼_클래스를_먼저_본다(self):
        for name, token in self.RUNNERS.items():
            source = (ROOT / "tools" / name).read_text(encoding="utf-8")
            guard = source.index("assert_not_written")
            checks = [i for i in range(len(source)) if source.startswith(token, i) and i < guard]
            assert checks, f"{name}: 가드 앞에 폼 클래스({token}) 확인이 없다"


class _StubVerifyForm:
    """assert_not_written 이 안에서 import 하는 verify_form 대역."""

    def __init__(self, values):
        self.values = values

    def screen_values(self, form):
        return self.values


class TestForce:
    """--force — 사람이 작성한 폼이어도 진행(시연·재작성, 사용자 요청 2026-09-17).

    2513(조사후반려 72/22)을 LIVE 로 다시 작성해 보여야 했다. 가드가 exit 3 으로 막던 걸
    사람이 번호를 콕 집었을 때만 열어준다. 감시 모드는 절대 안 켠다.
    """

    WRITTEN = {"평가사명1": "김기도(5764)", "감정평가액": "751,842,000"}
    EMPTY = {"평가사명1": "", "감정평가액": "0", "現 기준시점": ""}

    def _stub(self, monkeypatch, values):
        monkeypatch.setitem(sys.modules, "verify_form", _StubVerifyForm(values))

    def test_기본은_종전대로_제외(self, monkeypatch):
        import pytest
        self._stub(monkeypatch, self.WRITTEN)
        with pytest.raises(G.Excluded):
            G.assert_not_written(object(), "국민", {})

    def test_force_면_사람_작성_폼도_진행한다(self, monkeypatch):
        self._stub(monkeypatch, self.WRITTEN)
        summary = {}
        G.assert_not_written(object(), "국민", summary, force=True)   # 예외 없이 통과
        assert "김기도" in summary["guard_forced"]

    def test_빈_폼은_force_여도_흔적을_남기지_않는다(self, monkeypatch):
        self._stub(monkeypatch, self.EMPTY)
        summary = {}
        G.assert_not_written(object(), "국민", summary, force=True)
        assert "guard_forced" not in summary

    def test_감시_모드는_절대_안_켜진다(self):
        # only_doc 이 없으면(=감시 모드) 어떤 설정이어도 가드 그대로
        for raw in (True, "true", "01-2608-3-2513"):
            assert W.force_for(SimpleNamespace(force=raw), None) is False

    def test_번호를_적으면_그_건에만_걸린다(self):
        opt = SimpleNamespace(force="01-2608-3-2513")
        assert W.force_for(opt, "01-2608-3-2513") is True
        assert W.force_for(opt, "01-2609-3-2890") is False      # 다른 건은 종전대로 제외

    def test_여러_건은_쉼표로(self):
        opt = SimpleNamespace(force="01-2608-3-2513, 01-2609-3-2890")
        assert W.force_for(opt, "01-2609-3-2890") is True
        assert W.force_for(opt, "01-2609-3-2881") is False

    def test_true_면_적은_번호_아무거나(self):
        for raw in (True, "true", "TRUE", "1", "on"):
            assert W.force_for(SimpleNamespace(force=raw), "01-2609-3-2890") is True

    def test_비었거나_false_면_안_켜진다(self):
        for raw in (False, "", "  ", "false", "no", "off", "0"):
            assert W.force_for(SimpleNamespace(force=raw), "01-2608-3-2513") is False

    def test_설정이_아예_없어도_안전(self):
        assert W.force_for(SimpleNamespace(), "01-2608-3-2513") is False

    def test_워커는_force_for_로_판단한다(self):
        import inspect
        assert "force = force_for(opt, only_doc)" in inspect.getsource(W.one_round)

    def test_러너에_force_플래그가_전달된다(self):
        import inspect
        assert '["--force"] if force else []' in inspect.getsource(W.run_one)


class TestNoPdfDocs:
    """전례 PDF 가 없는 건은 탐색 자체를 건너뛴다(사용자 요청 2026-09-17).

    2513 실측: 감정서·수수료·공부·현장조사 4번을 네트워크 공유에서 헛찾느라 폼을 열기까지
    10:47:54 → 10:50:48, 약 3분을 썼다. no_pdf_docs 에 적힌 건은 locate() 를 아예 안 부른다.
    """

    def test_적힌_건만_건너뛴다(self):
        opt = SimpleNamespace(no_pdf_docs="01-2608-3-2513")
        assert W.no_pdf_for(opt, "01-2608-3-2513") is True
        assert W.no_pdf_for(opt, "01-2609-3-2890") is False

    def test_감시_모드는_영향_없다(self):
        assert W.no_pdf_for(SimpleNamespace(no_pdf_docs="01-2608-3-2513"), None) is False

    def test_비었으면_종전대로_PDF_탐색(self):
        for raw in ("", "  ", "false"):
            assert W.no_pdf_for(SimpleNamespace(no_pdf_docs=raw), "01-2608-3-2513") is False

    def test_force_와_같은_파서를_쓴다(self):
        import inspect
        assert "doc_switch(" in inspect.getsource(W.no_pdf_for)
        assert "doc_switch(" in inspect.getsource(W.force_for)

    def test_ini_옵션과_합쳐서_러너에_넘긴다(self):
        import inspect
        src = inspect.getsource(W.one_round)
        assert "skip_pdf = no_pdf_for(opt, only_doc)" in src
        assert "no_pdf=opt.no_pdf or skip_pdf" in src
