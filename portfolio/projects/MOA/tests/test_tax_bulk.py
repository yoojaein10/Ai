'세금계산서 일괄 발급 (2026-08-27) — 순수 규칙·발급 오케스트레이션(가짜 팝빌)·관문·화면 배선.\n\n사용자 확정: 입금된 건(부분입금·완납, 조회조건 전체/완납/부분입금), 작성일자 = 입금일,\n담당자 이메일 없으면 contact@example.com, 대주단은 거래처마다 한 장.\n'

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import tax_bulk
from app.services.access_policy import HEAD_OFFICE_FINANCE_MENU_KEYS, MENU_KEYS
from app.services.tax_bulk import (
    DEFAULT_EMAIL, MAX_ISSUE, TaxBulkError, default_amount, issue_bulk, item_name_for,
    pay_status_of, split_vat, syndicate_mgt_key, vat_of,
)

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "desktop" / "ui"
ROUTER = (ROOT / "app" / "routers" / "tax_bulk.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "app" / "services" / "tax_bulk.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
CONTEXT = (UI / "context.js").read_text(encoding="utf-8")
HTML = (UI / "tax-bulk.html").read_text(encoding="utf-8")
JS = (UI / "tax-bulk.js").read_text(encoding="utf-8")


# ── 순수 규칙 ──────────────────────────────────────────────────────────────


def test_부가세_역산과_세액은_단건_팝업과_같다():
    assert split_vat(88_000) == (80_000, 8_000)
    assert split_vat(2_574_100) == (2_340_091, 234_009)       # 대주단 새마을금고 한 장 (TAMS 실적)
    assert vat_of(2_340_091) == 234_009
    assert split_vat(0) == (0, 0)


def test_입금상태와_기본_금액():
    assert pay_status_of(1_100_000, 1_100_000, 0) == "완납"
    assert pay_status_of(2_323_200, 1_100_000, 1_223_200) == "부분입금"
    assert default_amount("완납", 1_100_000, 1_100_000) == 1_100_000
    assert default_amount("부분입금", 2_323_200, 1_100_000) == 1_100_000   # 영수 계산서 — 받은 만큼


def test_대주단_관리번호와_품목():
    assert syndicate_mgt_key("01-2607-2-0092", 3) == "01-2607-2-0092-L3"
    assert len(syndicate_mgt_key("01-2607-2-0092", 23)) <= 24                 # 팝빌 관리번호 24자 제한
    assert item_name_for("kb", "400577158") == "약식평가수수료 400577158"
    assert item_name_for("general", "01-2608-3-2601") == "감정평가수수료 01-2608-3-2601"


def test_후보_SQL은_발행_이력_두_원천과_거래처_캐시를_본다():
    issued = tax_bulk.issued_sql(":a")
    assert "a10_tams_tax_cache" in issued and "a10_issued_taxinvoice" in issued
    assert "is_test = 0" in issued and "N'세금계산서', N'현금영수증'" in issued
    assert "REPLACE(ISNULL(reg_nb, ''), '-', '')" in issued                   # TAMS 는 하이픈, 캐시는 10자리
    lines = tax_bulk.partner_lines_sql(":a")
    assert "GROUP BY v.management_no, RTRIM(v.partner_code)" in lines and "LIKE '401%'" in lines
    kb = tax_bulk.candidate_docs_sql("kb", division_code="1000", prefix_sql="1 = 1")
    assert "b.doc_id LIKE '400%'" in kb and "v.division_code = :division" in kb
    general = tax_bulk.candidate_docs_sql("general", division_code=None, prefix_sql="b.doc_id LIKE '01_%'")
    assert "b.doc_id LIKE '01_%'" in general and "b.received_amount > 0" in general


# ── 발급 오케스트레이션 (팝빌·DB 는 전부 가짜) ─────────────────────────────


class Fake:
    def __init__(self, *, lookup=None, already=None, register_ok=True, fail_docs=()):
        self.saved = []
        self.registered = []
        self._lookup = lookup or {}
        self._already = already or {}
        self._ok = register_ok
        self._fail = set(fail_docs)

    def lookup(self, db, tr_cd):
        return dict(self._lookup.get(tr_cd, {}))

    def already(self, db, kind, doc_id, corp_num, name):
        return self._already.get((doc_id, corp_num))

    def next_key(self, db, kind, doc_id):
        return f"{doc_id}-L1" if kind == "syndicate" else doc_id

    def register(self, inv, mgt_key, memo=""):
        self.registered.append((mgt_key, inv.invoiceeCorpNum, inv.invoiceeEmail1, inv.supplyCostTotal, inv.taxTotal, inv.detailList[0].itemName))
        if mgt_key.split("-L")[0] in self._fail:
            return {"success": False, "code": -99, "message": "테스트 실패"}
        return {"success": self._ok, "code": 1, "message": "발행 완료"}

    def info(self, mgt_key):
        return {"nts_confirm": f"NTS-{mgt_key}", "issue_dt": "20260827120000"}

    def save(self, db, **kw):
        self.saved.append(kw)

    def run(self, items):
        return issue_bulk(
            None, items, lookup=self.lookup, already=self.already, next_key=self.next_key,
            register=self.register, info=self.info, save=self.save,
            supplier={"corp_num": "2148746436", "corp_name": "(주)대화감정평가법인"},
        )


def _item(doc, tr_cd="0000023166", kind="general", supply=80_000, tax=8_000, **extra):
    return {"kind": kind, "doc_id": doc, "tr_cd": tr_cd, "corp_num": "", "partner_name": "어느 금고",
            "supply_cost": supply, "tax": tax, "write_date": "2026-08-25", "email": "", **extra}


def test_한_건씩_발행하고_원장에_남기며_이메일이_없으면_기본_주소를_쓴다():
    fake = Fake(lookup={"0000023166": {"corp_num": "128-82-01282", "corp_name": "고양동부새마을금고", "email": ""}})
    result = fake.run([_item("01-2608-3-2601")])
    assert result["issued"] == 1 and result["failed"] == 0
    mgt_key, corp, email, supply, tax, name = fake.registered[0]
    assert (mgt_key, corp, email, supply, tax) == ("01-2608-3-2601", "1288201282", DEFAULT_EMAIL, "80000", "8000")
    assert name == "감정평가수수료 01-2608-3-2601"
    saved = fake.saved[0]
    assert saved["doc_type"] == "세금계산서" and saved["receiver_corp_num"] == "1288201282"
    assert saved["account_code"] == "4010001" and saved["info"]["nts_confirm"] == "NTS-01-2608-3-2601"
    assert result["results"][0]["key"] == "general|01-2608-3-2601|0000023166"


def test_대주단은_거래처마다_L번호로_국민약식은_기타수수료_계정으로():
    fake = Fake(lookup={"A": {"corp_num": "1288201282", "corp_name": "금고A", "email": 'contact@example.com'},
                        "B": {"corp_num": "1198200391", "corp_name": "금고B", "email": 'contact@example.com'},
                        "K": {"corp_num": "5068513145", "corp_name": "국민은행 포항종합금융센터", "email": ""}})
    result = fake.run([
        _item("01-2607-2-0092", "A", kind="syndicate", supply=2_340_091, tax=234_009),
        _item("01-2607-2-0092", "B", kind="syndicate", supply=1_170_000, tax=117_000),
        _item("400577158", "K", kind="kb"),
    ])
    assert result["issued"] == 3
    assert [r[0] for r in fake.registered] == ["01-2607-2-0092-L1", "01-2607-2-0092-L1", "400577158"]
    assert fake.registered[2][5] == "약식평가수수료 400577158"
    assert [s["account_code"] for s in fake.saved] == ["4010001", "4010001", "4010002"]
    assert fake.registered[0][2] == 'contact@example.com'                                   # 담당자 이메일이 있으면 그것


def test_실패_건너뜀_사업자번호_없음은_각각_행_결과로_남고_나머지는_계속_간다():
    fake = Fake(
        lookup={"A": {"corp_num": "1288201282", "corp_name": "금고A"}, "N": {"corp_num": "", "corp_name": "사업자번호 없는 곳"}},
        already={("01-2607-3-0002", "1288201282"): "이미 발행됨(TAMS)"},
        fail_docs={"01-2607-3-0003"},
    )
    result = fake.run([
        _item("01-2607-3-0001", "A"), _item("01-2607-3-0002", "A"), _item("01-2607-3-0003", "A"),
        _item("01-2607-3-0004", "N"), _item("01-2607-3-0005", "A", supply=0, tax=0),
    ])
    by_doc = {r["doc_id"]: r for r in result["results"]}
    assert by_doc["01-2607-3-0001"]["success"]
    assert by_doc["01-2607-3-0002"]["skipped"] and "이미 발행" in by_doc["01-2607-3-0002"]["message"]
    assert not by_doc["01-2607-3-0003"]["success"] and by_doc["01-2607-3-0003"]["message"] == "테스트 실패"
    assert "사업자번호" in by_doc["01-2607-3-0004"]["message"]
    assert "공급가가 0" in by_doc["01-2607-3-0005"]["message"]
    assert (result["issued"], result["skipped"], result["failed"]) == (1, 1, 3)
    assert len(fake.saved) == 1                                                # 실패한 건은 원장에 안 남는다


def test_한_번에_50건_넘으면_거부():
    with pytest.raises(TaxBulkError):
        Fake().run([_item(f"01-2607-3-{i:04d}") for i in range(MAX_ISSUE + 1)])


# ── 관문·배선 ──────────────────────────────────────────────────────────────


def test_메뉴_키와_화면_배선():
    assert "taxBulk" in MENU_KEYS and "taxBulk" in HEAD_OFFICE_FINANCE_MENU_KEYS
    assert "{ label: '계산서 일괄발급', href: '/desktop/tax-bulk' }" in CONTEXT
    assert "'/desktop/tax-bulk': 'taxBulk'" in CONTEXT
    assert '@app.get("/desktop/tax-bulk", include_in_schema=False)' in MAIN and '_screen("tax-bulk.html")' in MAIN
    assert "app.include_router(tax_bulk_router)" in MAIN
    assert re.search(r'/ui/tax-bulk\.js\?v=\d{8}-\d+', HTML)


def test_라우터는_taxBulk_메뉴와_집행부_본인요청을_요구한다():
    assert ROUTER.count('require_menu("taxBulk")') == 1 and ROUTER.count('require_menu_write("taxBulk")') == 1
    assert ROUTER.count("require_operations_user(access, _MESSAGE)") == 2
    assert "require_same_requester(access, request.requester_usr_seq)" in ROUTER
    assert "resolve_office_scope(access, office_code)" in ROUTER
    assert "max_length=tax_bulk.MAX_ISSUE" in ROUTER
    client = TestClient(app)
    assert client.get("/api/taxinvoice/bulk/candidates?kind=general&date_from=2026-08-01&date_to=2026-08-25").status_code in (401, 403)
    assert client.post("/api/taxinvoice/bulk/issue", json={"requester_usr_seq": 1, "items": [
        {"kind": "general", "doc_id": "01-2608-3-2601", "supply_cost": 1, "tax": 0, "write_date": "20260825"}]}).status_code in (401, 403)
    assert client.get("/desktop/tax-bulk").status_code == 200


def test_화면은_탭_셋과_확인창_본사_집행부_게이트가_있다():
    for kind in ("general", "syndicate", "kb"):
        assert f'data-kind="{kind}"' in HTML
    for field in ("dateFrom", "dateTo", "payStatus", "onlyUnissued", "checkAll", "issueButton"):
        assert f'id="{field}"' in HTML
    assert "/api/taxinvoice/bulk/candidates?" in JS and "'/api/taxinvoice/bulk/issue'" in JS
    assert "되돌리기 어렵습니다" in JS and "confirm(" in JS                     # 실발급 확인창
    assert "ctx.office_id !== '10' || !ctx.is_operations" in JS
    assert DEFAULT_EMAIL in HTML
    assert "window.prompt" not in JS
