"""카드전표 업무 흐름: 엑셀 업로드 → 검증 → 분개 확정(초안) → 아마란스 전송.

전송 취소는 아마란스에서 직접 삭제한다(MOA에는 삭제 기능을 두지 않는다).
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.config import get_settings
from app.models.card_voucher import CardVoucher, CardVoucherItem
from app.services import card_source, card_vehicles, partner_cache
from app.services import card_vouchers as cv

DIVISION_CODE = "1000"  # 본사 (재무팀 확인)
MAX_ITEMS = 500         # 한 전표에 담을 수 있는 건수 상한
SYNC_MAX_DATES = 5      # 아마란스 삭제 동기화가 한 번에 검사할 전표일자 수 (하루 ~1초)

# 아마란스는 (전표일자, 작성번호)를 전표 한 장의 이름표로 본다 — 남이 쓰는 번호를
# 잡으면 새 전표가 아니라 그 전표에 줄을 덧붙이려 하고, 상대가 승인된 전표면
# "이미 발행되어 추가입력할 수 없습니다"로 막힌다.
#
# MOA 안에서 번호를 잡는 곳이 셋인데 각자 자기 테이블 id로 정한다. 기본전표가
# 10000+id 라 카드전표(옛 10000+id)와 정면으로 겹쳤다 — 2026-08-14 실제 발생:
# 카드전표 57번과 기본전표 57번이 둘 다 10057, 전표일자도 같은 날이었다.
# 그래서 카드전표는 8만번대를 전용으로 쓴다(입금전표 50000+id 와도 떨어져 있다).
MENU_SQ_BASE = 80000
MENU_SQ_SPAN = 10000


PARTNER_PAGE = 1000          # 거래처 조회 한 페이지 크기
MERCHANT_CACHE_TTL = 900     # 가맹점 조회 결과 보관 시간(초)
MERCHANT_CACHE_MAX = 20000   # 보관 상한 — 넘으면 통째로 비운다

# 사업자번호 → 거래처(또는 미등록이면 None). 프로세스 메모리라 재기동하면 사라진다.
_MERCHANT_CACHE: "dict[str, tuple[float, dict[str, str] | None]]" = {}


# 이력이 갈려 스스로 못 정하는 업종에 재무팀이 값을 준다 (2026-08-20 사용자 지시).
# 골프는 이력이 체력단련비 63건 / 복리후생비 22건으로 갈려 자동 판정이 안 됐다.
# 업종 표기가 여섯 갈래라(골프장·골프경기장·실외/실내골프장·스크린골프·골프장(6004))
# '골프'가 든 것을 묶되, 물건을 사는 '골프 용품'은 뺀다(이력도 복리후생비다).
def _rule_purpose(industry: str) -> str:
    text_ = str(industry or "")
    if "골프" in text_ and "용품" not in text_:
        return "체력단련비"
    return ""


class CardVoucherError(ValueError):
    pass


def mask_card(card_no: str) -> str:
    """카드번호는 뒤 4자리만 남긴다(화면·저장·응답 공통)."""
    digits = cv._digits(card_no)
    return f"****{digits[-4:]}" if len(digits) >= 4 else ""


def _amaranth_detail(exc: Exception) -> str:
    """아마란스는 실제 원인을 resultData의 라인별 errorMsg에 담아 보낸다.

    상위 메시지("데이터 전송 중 문제가 발생하였습니다")만으로는 원인을 알 수 없어
    라인별 사유를 꺼내 보여준다.
    """
    rows = getattr(exc, "data", None)
    if isinstance(rows, dict):
        rows = [rows]
    if isinstance(rows, list):
        reasons = [
            str(r.get("errorMsg")).strip()
            for r in rows
            if isinstance(r, dict) and r.get("errorMsg")
        ]
        if reasons:
            return " / ".join(reasons[:3])
    return str(exc)


def _masked(item: dict[str, Any]) -> dict[str, Any]:
    """감사 추적용 원본 보관 시 카드번호는 마스킹한다."""
    safe = dict(item)
    if safe.get("card_no"):
        safe["card_no"] = mask_card(str(safe["card_no"]))
    return safe


class CardVoucherService:
    def __init__(self, db: Session, client: AmaranthClient | None = None) -> None:
        self.db = db
        self.client = client or AmaranthClient(db)
        self._company_code: str | None = None

    # ── 기초 정보 ────────────────────────────────────────────────
    @property
    def company_code(self) -> str:
        if self._company_code is None:
            from scripts.find_management_numbers import _company_code

            self._company_code = _company_code(self.db, self.client)
        return self._company_code

    def _rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        from scripts.find_management_numbers import _result_rows

        return _result_rows(payload)

    def card_partners(self) -> dict[str, dict[str, str]]:
        """카드번호 → 아마란스 신용카드 거래처(trFg=9). 중복이면 최근 등록분을 쓴다.

        한 번에 1000건씩 받는다 — 카드 거래처가 770건이라 100건씩이면 왕복만
        8번이다(2026-08-20 실측 0.93초/회 → 1회 0.58초).
        """
        found: dict[str, dict[str, str]] = {}
        for offset in range(0, 20000, PARTNER_PAGE):
            payload = self.client.post(
                "/apiproxy/api16S11",
                json_body={"coCd": self.company_code, "trFg": "9", "usePagination": True,
                           "pagingOffset": offset, "pagingCount": PARTNER_PAGE},
            )
            rows = self._rows(payload)
            for row in rows:
                key = cv._digits(row.get("baNb"))
                if not key:
                    continue
                code = str(row.get("trCd") or "")
                # 같은 카드번호가 여러 거래처에 걸리면 코드가 큰 쪽 = 최근 등록분
                if key not in found or code > found[key]["code"]:
                    found[key] = {"code": code, "name": str(row.get("trNm") or "").strip()}
            if len(rows) < PARTNER_PAGE:
                break
        return found

    def find_merchant(self, biz_no: str) -> dict[str, str] | None:
        """가맹점 사업자번호로 아마란스 거래처를 찾는다.

        한 번 물어본 사업자번호는 잠시 기억한다 — 조회 한 번에 한 왕복(0.22초)이라
        가맹점이 500곳이면 그것만으로 2분이 걸린다(2026-08-20 실측). 거래처가
        새로 등록되는 것을 놓치지 않도록 보관 시간은 짧게 둔다.
        """
        if len(biz_no) != 10:
            return None
        now = time.monotonic()
        hit = _MERCHANT_CACHE.get(biz_no)
        if hit is not None and now - hit[0] < MERCHANT_CACHE_TTL:
            return hit[1]
        payload = self.client.post(
            "/apiproxy/api16S11", json_body={"coCd": self.company_code, "regNb": biz_no}
        )
        found: dict[str, str] | None = None
        for row in self._rows(payload):
            if cv._digits(row.get("regNb")) == biz_no:
                found = {"code": str(row.get("trCd") or ""),
                         "name": str(row.get("trNm") or "").strip()}
                break
        if len(_MERCHANT_CACHE) > MERCHANT_CACHE_MAX:
            _MERCHANT_CACHE.clear()
        _MERCHANT_CACHE[biz_no] = (now, found)
        return found

    def register_merchant(self, *, biz_no: str, name: str) -> dict[str, str]:
        """미등록 가맹점을 일반 거래처(trFg=1)로 등록하고 거래처코드를 돌려준다."""
        short = (name or biz_no)[:60]
        body = {
            "list": [{
                "coCd": self.company_code, "trNm": short, "attrNm": short[:30],
                "trFg": "1", "regNb": biz_no,
            }],
            "dupCheck": False,
        }
        payload = self.client.post("/apiproxy/api16S12", json_body=body)
        rows = self._rows(payload)
        code = str(rows[0].get("trCd")) if rows else ""
        if not code:
            found = self.find_merchant(biz_no)
            if found:
                return found
            raise CardVoucherError(f"가맹점 거래처 등록에 실패했습니다: {name}")
        return {"code": code, "name": short}

    # ── 업로드/불러오기 → 검증 ───────────────────────────────────
    def analyze(self, path: str, *, auto_register: bool = True) -> dict[str, Any]:
        """엑셀을 읽어 검증하고, 거래처를 붙여 화면에 보여줄 목록을 만든다."""
        return self.analyze_usages(cv.parse_excel(path), auto_register=auto_register)

    def analyze_from_db(self, date_from: str, date_to: str, *,
                        auto_register: bool = False) -> dict[str, Any]:
        """카드내역 DB(CB2_APPR)를 기간 조회해 엑셀 업로드와 같은 목록을 만든다."""
        usages = card_source.fetch_usages(date_from, date_to)
        return self.analyze_usages(usages, auto_register=auto_register)

    def analyze_usages(self, usages: list[cv.CardUsage], *,
                       auto_register: bool) -> dict[str, Any]:
        # 이미 처리한 건은 dedup_key로 걸러낸다. 전표 상태까지 같이 읽어 화면이
        # 전송완료 건만 숨기고 미전송 초안·실패 건은 계속 보여줄 수 있게 한다.
        cv.assign_split_numbers(usages)  # dedup_key가 분할 순번을 포함한다
        keys = {u.dedup_key for u in usages}
        known: dict[str, str] = {}
        stored: dict[str, CardVoucherItem] = {}
        key_list = list(keys)
        for start in range(0, len(key_list), 500):
            rows = self.db.execute(
                select(CardVoucherItem, CardVoucher.status)
                .join(CardVoucher, CardVoucher.id == CardVoucherItem.voucher_id)
                .where(CardVoucherItem.dedup_key.in_(key_list[start:start + 500]))
            ).all()
            for item, status in rows:
                known[item.dedup_key] = status
                stored[item.dedup_key] = item
        # 처리된 건은 확정 당시 저장한 값으로 보여준다 — 원천 공제 플래그·자동
        # 추천으로 다시 그리면 확정 값이 되돌아간 것처럼 보인다 (2026-08-31).
        cv.apply_confirmed(usages, stored)
        # 계정을 먼저 채운 뒤에 검증한다 — 반대로 하면 '계정 미매핑' 보류가
        # 남아, 자동으로 채운 줄까지 보류로 뜬다.
        self._suggest_accounts(usages)
        cv.validate(usages, known_keys=known)
        self._fill_card_owners(usages)

        cards = self.card_partners()
        # 가맹점은 아마란스에 한 건씩 물어야 해서(왕복 0.22초) 미리 아는 것부터
        # 채운다 — 거래처 캐시(하루 1회 적재) → 우리 전표 이력 순.
        wanted = {u.merchant_biz_no for u in usages if len(u.merchant_biz_no) == 10}
        merchants = self._known_merchants(wanted)
        merchants.update(partner_cache.find_partners_by_reg_no(self.db, wanted))
        # 캐시는 거래처 전체를 담으므로, 최근 것이면 '여기 없다'를 '아마란스에 없다'로
        # 믿고 확인 왕복을 건너뛴다 — 2026-08-20 실측, 19일치에서 못 찾은 117곳이
        # 전부 진짜 미등록이었고 그걸 확인하는 데만 26초를 썼다.
        # 자동 등록을 켠 회차에는 믿지 않는다: 캐시가 낡은 사이에 남이 등록해 둔
        # 가맹점을 또 등록하면 거래처가 둘로 갈린다.
        trust_absence = not auto_register and partner_cache.is_fresh(self.db)
        items = []
        for u in usages:
            card = cards.get(u.card_no)
            if not card and not u.on_hold:
                u.holds.append("아마란스에 등록되지 않은 카드")
            merchant = None
            if len(u.merchant_biz_no) == 10:
                if u.merchant_biz_no not in merchants:
                    hit = None if trust_absence else self.find_merchant(u.merchant_biz_no)
                    if hit is None and auto_register and not u.on_hold:
                        hit = self.register_merchant(biz_no=u.merchant_biz_no, name=u.merchant)
                    if hit:
                        merchants[u.merchant_biz_no] = hit
                merchant = merchants.get(u.merchant_biz_no)
            # 가맹점 미등록 안내는 2026-08-31 뺐다 — 분개 세 줄을 카드사 거래처로
            # 통일(2026-08-19)한 뒤로 전표에 안 쓰이는데 매달 130건쯤 노란 줄만
            # 만들었다. 조회는 가맹점명 풍선말·자동 등록용으로 유지한다.
            items.append(self._to_dict(u, card, merchant))
        return {"summary": cv.summarize(usages), "items": items}

    def _suggest_accounts(self, usages: list[cv.CardUsage]) -> None:
        """비어 있는 계정(사용용도)을 우리 전표 이력에서 채운다.

        카드내역 DB에는 엑셀의 '사용용도' 칸이 없어 계정이 전부 비어 온다 —
        담당자가 1,000줄을 손으로 골라야 했다. 대신 우리가 이미 만든 전표가
        답을 갖고 있다 (2026-08-20 실측):

          가맹점별 계정이 한 종류뿐인 곳 1,064/1,076 (98%), 최빈값 일치율 99.6%
          업종별로도 뚜렷 — 택시·주유소·커피전문점은 100%

        가맹점으로 먼저 맞추고, 없으면 한쪽으로 90% 이상 쏠린 업종만 쓴다.
        갈리는 업종(PG일반 61%, 인터넷P/G 42%)은 손대지 않는다.
        채운 줄은 auto_purpose 로 표시해 화면이 '자동'을 붙인다 — 담당자가
        훑어보고 고칠 수 있어야 한다.
        """
        blanks = [u for u in usages if not u.purpose]
        if not blanks:
            return
        by_merchant = self._history_purposes(
            CardVoucherItem.merchant_biz_no,
            {u.merchant_biz_no for u in blanks if u.merchant_biz_no},
        )
        industries = {u.industry for u in blanks if u.industry}
        by_industry = (
            self._industry_purposes(industries) if industries else {}
        )
        for u in blanks:
            purpose = (_rule_purpose(u.industry)
                       or by_merchant.get(u.merchant_biz_no)
                       or by_industry.get(u.industry))
            if not purpose or purpose not in cv.ACCOUNT_MAP:
                continue
            u.purpose = purpose
            u.account_code = cv.ACCOUNT_MAP[purpose]
            u.auto_purpose = True
            u.remark = u.auto_remark   # 적요 꼬리말이 계정에 따라 달라진다

    def _history_purposes(self, column, keys: set[str]) -> dict[str, str]:
        """이력에서 열쇠별 최빈 계정. 값이 갈리면 많이 쓴 쪽을 쓴다."""
        wanted = sorted(k for k in keys if k)
        if not wanted:
            return {}
        tally: dict[str, dict[str, int]] = {}
        for start in range(0, len(wanted), 500):
            rows = self.db.execute(
                select(column, CardVoucherItem.purpose, func.count())
                .where(column.in_(wanted[start:start + 500]))
                .where(CardVoucherItem.purpose != "")
                .group_by(column, CardVoucherItem.purpose)
            ).all()
            for key, purpose, count in rows:
                tally.setdefault(key, {})[purpose] = int(count)
        return {k: max(v, key=v.get) for k, v in tally.items() if v}

    # 업종은 이력 표에 열이 없어 원본(origin_json)에 담긴 값을 쓴다.
    # 한쪽으로 이만큼 쏠린 업종만 믿는다 — 백화점·골프장처럼 갈리는 곳은 사람이 본다.
    INDUSTRY_MIN_SHARE = 0.90
    INDUSTRY_MIN_ROWS = 5

    def _industry_purposes(self, industries: set[str]) -> dict[str, str]:
        rows = self.db.execute(text("""
            SELECT j.industry, i.purpose, COUNT(*) AS cnt
            FROM dbo.a10_card_voucher_item i
            CROSS APPLY (SELECT JSON_VALUE(i.origin_json, '$.industry') AS industry) j
            WHERE ISNULL(RTRIM(i.purpose), '') <> ''
              AND j.industry IS NOT NULL AND j.industry <> ''
            GROUP BY j.industry, i.purpose
        """)).all()
        tally: dict[str, dict[str, int]] = {}
        for industry, purpose, count in rows:
            tally.setdefault(industry, {})[purpose] = int(count)
        best: dict[str, str] = {}
        for industry, counts in tally.items():
            if industry not in industries:
                continue
            total = sum(counts.values())
            top = max(counts, key=counts.get)
            if total >= self.INDUSTRY_MIN_ROWS and counts[top] / total >= self.INDUSTRY_MIN_SHARE:
                best[industry] = top
        return best

    def _known_merchants(self, biz_nos: set[str]) -> dict[str, dict[str, str]]:
        """전에 전표로 만든 가맹점의 거래처코드를 우리 이력에서 되짚는다.

        가맹점 하나를 아마란스에 묻는 데 한 왕복(0.22초)이라, 한 달치를 부르면
        가맹점만 500곳이 넘어 그것만으로 2분이 걸린다 (2026-08-20 실측).
        이력 적중률은 이틀치 59%, 19일치 76%였다.

        거래처코드는 분개에 안 쓴다 — 세 줄 모두 카드사 거래처를 쓰기 때문에
        (2026-08-19 재무팀 요청) 이 값은 '아마란스에 등록된 가맹점'이라는 표시와
        기록용이다. 그래서 이력 값을 써도 전표가 틀어지지 않는다.
        """
        wanted = sorted(b for b in biz_nos if len(b) == 10)
        if not wanted:
            return {}
        found: dict[str, dict[str, str]] = {}
        for start in range(0, len(wanted), 500):
            rows = self.db.execute(
                select(CardVoucherItem.merchant_biz_no,
                       CardVoucherItem.merchant_partner_code,
                       CardVoucherItem.merchant)
                .where(CardVoucherItem.merchant_biz_no.in_(wanted[start:start + 500]))
                .where(CardVoucherItem.merchant_partner_code != "")
                .order_by(CardVoucherItem.id)   # 뒤 행이 덮으므로 최근 값이 남는다
            ).all()
            for biz_no, code, name in rows:
                if (code or "").strip():
                    found[biz_no] = {"code": code.strip(), "name": (name or "").strip()}
        return found

    def _fill_card_owners(self, usages: list[cv.CardUsage]) -> None:
        """카드 마스터에서도 비어 있는 사용자·카드별칭을 기존 이력으로 보완한다.

        기본 사용자명은 card_source가 CB2_CARD.USER_NM을 (은행, 카드번호)로
        연결해 채운다. 예외적으로 마스터 이름이 비어 있을 때만 재무팀 엑셀로 만든
        우리 전표 이력을 카드번호로 되짚는다(최근 값 우선).

        화면 표시·기록용이고 분개에는 쓰이지 않는다 (거래처는 카드사, 적요는
        카드끝4자리+가맹점). 이력에 없는 카드는 그대로 빈칸으로 둔다.
        """
        wanted = sorted({u.card_no for u in usages if u.card_no and not u.user_name})
        if not wanted:
            return
        owners: dict[str, dict[str, str]] = {}
        for start in range(0, len(wanted), 500):
            rows = self.db.execute(
                select(CardVoucherItem.card_no, CardVoucherItem.user_name,
                       CardVoucherItem.card_alias)
                .where(CardVoucherItem.card_no.in_(wanted[start:start + 500]))
                .order_by(CardVoucherItem.id)   # 뒤 행이 덮으므로 최근 값이 남는다
            ).all()
            for card_no, user_name, alias in rows:
                entry = owners.setdefault(card_no, {"user_name": "", "card_alias": ""})
                if (user_name or "").strip():
                    entry["user_name"] = user_name.strip()
                if (alias or "").strip():
                    entry["card_alias"] = alias.strip()
        for u in usages:
            found = owners.get(u.card_no)
            if not found:
                continue
            if not u.user_name:
                u.user_name = found["user_name"]
            if not u.card_alias:
                u.card_alias = found["card_alias"]

        # 카드 마스터·우리 전표 모두 비어 있는 카드만 원천의 과거 결제에서 되짚는다.
        # 사이버브랜치 수기 업로드분(Bank_Cd='Excel')에 명의자가 100% 들어 있어
        # 우리 이력(71장)보다 넓다(160장). 실패하면 빈칸으로 남을 뿐이다.
        still_blank = [u for u in usages if u.card_no and not u.user_name]
        if still_blank:
            from_source = card_source.fetch_card_owners()
            for u in still_blank:
                u.user_name = from_source.get(u.card_no, "")

    def _to_dict(self, u: cv.CardUsage, card: dict | None, merchant: dict | None) -> dict[str, Any]:
        return {
            "dedup_key": u.dedup_key,
            "row_no": u.row_no,
            "card_no": u.card_no,          # 확정 요청에 되돌려받아야 하므로 유지
            "card_no_masked": mask_card(u.card_no),
            "card_alias": u.card_alias,
            "card_partner_code": (card or {}).get("code", ""),
            "card_partner_name": (card or {}).get("name", ""),
            "user_name": u.user_name,
            "use_date": u.use_date,
            "appr_no": u.appr_no,
            "merchant": u.merchant,
            "merchant_biz_no": u.merchant_biz_no,
            "merchant_partner_code": (merchant or {}).get("code", ""),
            "merchant_partner_name": (merchant or {}).get("name", ""),
            "purpose": u.purpose,
            "account_code": u.account_code,
            "deductible": u.deductible,
            "total": float(u.total),
            "supply": float(u.supply),
            "vat": float(u.vat),
            "industry": u.industry,
            "auto_purpose": u.auto_purpose,
            "appr_time": u.appr_time,
            "tax_info": u.tax_info,
            "canceled": u.canceled,
            # 적요는 파서가 만든 값(카드끝4자리.MM.DD. 가맹점)을 그대로 쓴다.
            # 여기서 다시 조립하면 오늘 바꾼 재무팀 적요 관행이 화면에 반영되지 않는다.
            "remark": u.remark or u.auto_remark,
            "holds": list(u.holds),
            # status 는 화면 색·배지용(안내도 노란 줄), blocked 는 확정 가능 여부다
            "status": "hold" if u.on_hold else "ready",
            "blocked": u.blocked,
            "processed_status": u.processed_status,
        }

    # ── 분개 확정 (우리 DB 저장, 아마란스 전송 없음) ─────────────
    def _check_item(self, i: dict[str, Any]) -> None:
        """클라이언트가 보낸 값을 서버에서 다시 확인한다(화면 검증만 믿지 않는다)."""
        appr = str(i.get("appr_no") or "?")
        purpose = str(i.get("purpose") or "").strip()
        account = str(i.get("account_code") or "").strip()
        if account not in cv.ACCOUNT_MAP.values():
            raise CardVoucherError(f"승인번호 {appr}: 허용되지 않은 계정과목입니다.")
        if purpose and cv.ACCOUNT_MAP.get(purpose) != account:
            raise CardVoucherError(f"승인번호 {appr}: 사용용도와 계정과목이 맞지 않습니다.")
        total = Decimal(str(i.get("total") or 0))
        supply = Decimal(str(i.get("supply") or 0))
        vat = Decimal(str(i.get("vat") or 0))
        if total <= 0:
            raise CardVoucherError(f"승인번호 {appr}: 승인금액이 올바르지 않습니다.")
        if bool(i.get("deductible")) and supply + vat != total:
            raise CardVoucherError(f"승인번호 {appr}: 공급가액+부가세가 승인금액과 다릅니다.")
        if supply < 0 or vat < 0:
            raise CardVoucherError(f"승인번호 {appr}: 금액은 음수일 수 없습니다.")
        if not str(i.get("card_partner_code") or "").strip():
            raise CardVoucherError(f"승인번호 {appr}: 카드 거래처가 없습니다.")
        # 가맹점 거래처는 더 이상 분개에 쓰지 않는다(세 줄 모두 카드사 거래처).
        # 없다고 막지 않는다 — 2026-08-20 사용자 결정.
        if not str(i.get("dedup_key") or "").strip():
            raise CardVoucherError(f"승인번호 {appr}: 식별키가 없습니다.")

    def create_draft(self, items: list[dict[str, Any]], *, voucher_date: date | None = None,
                     source_file: str = "", created_by: str = "") -> dict[str, Any]:
        """선택 건을 전표 1장으로 확정한다.

        전표일자는 사용일자가 아니라 **작업일**이다 (2026-08-04 재무팀 확인 —
        아마란스에 등록된 재무팀 전표도 7/25~27 승인분을 7/27 전표 한 장으로
        묶고 있었다). 사용일자는 건별로 보관하고 적요에 남는다.
        """
        if not items:
            raise CardVoucherError("전표로 만들 건을 선택하세요.")
        if len(items) > MAX_ITEMS:
            raise CardVoucherError(f"한 전표에 담을 수 있는 건수는 {MAX_ITEMS}건까지입니다.")
        for i in items:
            self._check_item(i)
        self._require_vehicles([
            (str(i.get("user_name") or ""), i.get("account_code") or cv.ACCOUNT_MAP.get(i.get("purpose", ""), ""))
            for i in items
        ])
        for i in items:
            used = str(i.get("use_date") or "")[:8]
            if len(used) != 8 or not used.isdigit():
                raise CardVoucherError(
                    f"승인번호 {i.get('appr_no') or '?'}: 사용일자가 올바르지 않습니다."
                )
        vdate = voucher_date or date.today()
        today = date.today()
        if vdate > today:
            raise CardVoucherError("전표일자는 미래로 지정할 수 없습니다.")
        if (today - vdate).days > 400:
            raise CardVoucherError("전표일자가 너무 오래됐습니다(1년 이내로 지정하세요).")

        dup = self.db.scalars(
            select(CardVoucherItem.appr_no).where(
                CardVoucherItem.dedup_key.in_([str(i["dedup_key"]) for i in items])
            )
        ).all()
        if dup:
            # 카드번호가 든 dedup_key 대신 승인번호로 알린다.
            raise CardVoucherError(f"이미 전표로 만든 건이 있습니다(승인번호 {', '.join(dup[:3])}).")

        total = sum(Decimal(str(i.get("total") or 0)) for i in items)
        voucher = CardVoucher(
            voucher_date=vdate,
            division_code=DIVISION_CODE, menu_sq=0, item_count=len(items),
            total_amount=total, status="D", source_file=source_file[:260] or None,
            created_by=created_by or None,
        )
        self.db.add(voucher)
        self.db.flush()
        voucher.menu_sq = MENU_SQ_BASE + (int(voucher.id) % MENU_SQ_SPAN)

        for i in items:
            self.db.add(CardVoucherItem(
                voucher_id=voucher.id, dedup_key=i["dedup_key"],
                card_no=i["card_no"], card_alias=i.get("card_alias"),
                card_partner_code=i.get("card_partner_code"),
                user_name=i.get("user_name"), use_date=str(i.get("use_date") or "")[:8],
                appr_no=i.get("appr_no"),
                total=Decimal(str(i.get("total") or 0)),
                merchant=i.get("merchant"), merchant_biz_no=i.get("merchant_biz_no"),
                merchant_partner_code=i.get("merchant_partner_code"),
                purpose=i.get("purpose"),
                account_code=i.get("account_code") or cv.ACCOUNT_MAP.get(i.get("purpose", ""), ""),
                deductible=bool(i.get("deductible")),
                supply=Decimal(str(i.get("supply") or 0)),
                vat=Decimal(str(i.get("vat") or 0)),
                remark=(i.get("remark") or "")[:100],
                origin_json=json.dumps(_masked(i), ensure_ascii=False, default=str),
                edited_by=created_by or None,
                edited_at=datetime.now() if i.get("edited") else None,
            ))
        try:
            self.db.commit()
        except IntegrityError as exc:  # 동시 요청이 같은 건을 통과한 경우
            self.db.rollback()
            raise CardVoucherError("이미 전표로 만든 건이 있습니다.") from exc
        return self.draft_detail(voucher.id)

    def _require_vehicles(self, pairs: "list[tuple[str, str]]") -> None:
        """차량유지비(8220000) 건은 카드 사용자의 업무용승용차 코드가 있어야 한다 — 없으면 확정·전송을 막는다."""
        wanted = {name.strip() or "(사용자 없음)" for name, account in pairs if account == cv.ACCOUNT_VEHICLE}
        if not wanted:
            return
        vehicles = card_vehicles.vehicle_map(self.db)
        missing = sorted(n for n in wanted if not vehicles.get(n, {}).get("car_cd"))
        if missing:
            raise CardVoucherError(
                f"차량유지비 건인데 업무용승용차가 등록되지 않은 사용자: {', '.join(missing)} — 차량 표(a10_card_vehicle)에 넣거나 계정을 바꾸세요."
            )

    def list_drafts(self, *, date_from: date | None = None,
                    date_to: date | None = None, limit: int = 300
                    ) -> dict[str, Any]:
        """확정된 전표 — 전표일자 기준 기간 조회. 기본은 당일치.

        2026-08-27 사용자 결정: 화면 라벨('전표일')대로 전표일자로 자른다. (그전엔 확정일로
        잘랐다 — 소급 확정한 전표가 안 보이는 문제는 화면이 확정 직후 기간을 그 전표일자까지
        넓혀서 푼다.)

        기간 밖에 남아 있는 미전송(D)·실패(F) 건수도 같이 돌려준다 — 손이 필요한
        전표가 기간 밖으로 밀려 잊히면 안 된다 (2026-08-14 고아 전표 재발 방지).
        """
        today = date.today()
        start = date_from or today
        end = date_to or today
        if start > end:
            start, end = end, start

        rows = self.db.scalars(
            select(CardVoucher)
            .where(CardVoucher.voucher_date >= start, CardVoucher.voucher_date <= end)
            .order_by(CardVoucher.id.desc()).limit(limit)
        ).all()
        outside = dict(self.db.execute(
            select(CardVoucher.status, func.count())
            .where(CardVoucher.status.in_(("D", "F")))
            .where(or_(CardVoucher.voucher_date < start, CardVoucher.voucher_date > end))
            .group_by(CardVoucher.status)
        ).all())
        return {
            "items": [{
                "id": v.id, "voucher_date": v.voucher_date.isoformat(),
                "item_count": v.item_count, "total_amount": float(v.total_amount),
                "status": v.status, "menu_sq": v.menu_sq,
                "a10_voucher_no": v.a10_voucher_no, "error_msg": v.error_msg,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "sent_at": v.sent_at.isoformat() if v.sent_at else None,
            } for v in rows],
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "outside": {"draft": int(outside.get("D", 0)), "failed": int(outside.get("F", 0))},
        }

    # ── 아마란스 삭제 동기화 ─────────────────────────────────────
    def _amaranth_menu_sqs(self, day: date) -> "set[str]":
        """그 전표일자의 아마란스 자동전표 작성번호(menuSq) 집합."""
        day_str = day.strftime("%Y%m%d")
        found: "set[str]" = set()
        for page in range(1, 200):
            payload = self.client.post(
                "/apiproxy/api11A16",
                json_body={
                    "coCd": self.company_code,
                    "groupSeq": get_settings().a10_group_seq,
                    "divCd": DIVISION_CODE,
                    "frDt": day_str, "toDt": day_str,
                    "viewPage": page, "viewCount": 500,
                },
                timeout=60.0,
            )
            rows = self._rows(payload)
            for row in rows:
                menu_sq = str(row.get("menuSq") or "").strip()
                if menu_sq:
                    found.add(menu_sq)
            if len(rows) < 500:
                break
        return found

    def sync_amaranth_deleted(self) -> dict[str, Any]:
        """전송완료(S) 전표가 아마란스에 아직 있는지 대조해 지워진 것을 X로 닫는다.

        아마란스에서 전표를 삭제해도 MOA로 오는 신호가 없어(2026-08-14, 6·7번
        고아 발견) 화면 로드 때마다 오래 안 본 전표일자부터 돌아가며 검사한다.
        승인(발행)된 자동전표도 api11A16에 남는 것을 실측 확인(6/29 승인 건
        잔존)했으므로 '조회 결과에 없음 = 삭제'로 판정한다. 조회가 실패한
        날짜는 판정하지 않는다(fail-safe).

        삭제 확인 전표는 행을 지우지 않고 상태 X로 남겨 이력을 보존하되,
        담긴 건들은 지워 dedup_key를 풀어준다 — 같은 사용내역을 다시 확정할
        수 있다 (분개 원문은 request_body에 남아 있다).
        """
        sent = self.db.scalars(
            select(CardVoucher).where(CardVoucher.status == "S")
            # MSSQL·sqlite 모두 ASC에서 NULL(미검사)이 먼저 온다
            .order_by(CardVoucher.amaranth_checked_at.asc(), CardVoucher.id.asc())
        ).all()
        dates: "list[date]" = []
        for voucher in sent:
            if voucher.voucher_date not in dates:
                if len(dates) >= SYNC_MAX_DATES:
                    break
                dates.append(voucher.voucher_date)
        checked = 0
        deleted: "list[dict[str, Any]]" = []
        for day in dates:
            try:
                present = self._amaranth_menu_sqs(day)
            except Exception:
                continue  # 아마란스 조회 실패 — 이번 회차에는 판정하지 않는다
            for voucher in sent:
                if voucher.voucher_date != day:
                    continue
                voucher.amaranth_checked_at = datetime.now()
                checked += 1
                if str(voucher.menu_sq) in present:
                    continue
                voucher.status = "X"
                voucher.error_msg = "아마란스에서 삭제 확인(자동 동기화)"
                self.db.execute(
                    delete(CardVoucherItem).where(
                        CardVoucherItem.voucher_id == voucher.id
                    )
                )
                deleted.append({
                    "id": voucher.id,
                    "voucher_date": voucher.voucher_date.isoformat(),
                    "item_count": voucher.item_count,
                    "total_amount": float(voucher.total_amount),
                })
        self.db.commit()
        return {"checked": checked, "deleted": deleted}

    def delete_draft(self, voucher_id: int) -> dict[str, Any]:
        """아직 아마란스로 보내지 않은 전표를 취소한다.

        담긴 건들의 중복키도 같이 지워져 다시 확정할 수 있게 된다. 전송된 전표는
        아마란스에 이미 남아 있으므로 여기서 지우지 않는다(아마란스에서 직접 삭제).
        """
        voucher = self.db.scalars(
            select(CardVoucher).where(CardVoucher.id == voucher_id).with_for_update()
        ).first()
        if voucher is None:
            raise CardVoucherError("전표를 찾을 수 없습니다.")
        if voucher.status == "S":
            raise CardVoucherError(
                "이미 아마란스로 전송된 전표는 취소할 수 없습니다. 아마란스에서 직접 삭제하세요."
            )
        items = self.db.scalars(
            select(CardVoucherItem).where(CardVoucherItem.voucher_id == voucher_id)
        ).all()
        count = len(items)
        for item in items:
            self.db.delete(item)
        self.db.delete(voucher)
        self.db.commit()
        return {"id": voucher_id, "item_count": count}

    def draft_detail(self, voucher_id: int) -> dict[str, Any]:
        voucher = self.db.get(CardVoucher, voucher_id)
        if voucher is None:
            raise CardVoucherError("전표를 찾을 수 없습니다.")
        items = self.db.scalars(
            select(CardVoucherItem).where(CardVoucherItem.voucher_id == voucher_id)
            .order_by(CardVoucherItem.id)
        ).all()
        return {
            "id": voucher.id, "voucher_date": voucher.voucher_date.isoformat(),
            "status": voucher.status, "menu_sq": voucher.menu_sq,
            "item_count": voucher.item_count, "total_amount": float(voucher.total_amount),
            "a10_voucher_no": voucher.a10_voucher_no, "error_msg": voucher.error_msg,
            "items": [{
                "id": it.id, "card_alias": it.card_alias,
                "card_no_masked": mask_card(it.card_no),
                "card_partner_code": it.card_partner_code, "user_name": it.user_name,
                "appr_no": it.appr_no, "merchant": it.merchant,
                "merchant_partner_code": it.merchant_partner_code,
                "purpose": it.purpose, "account_code": it.account_code,
                "deductible": it.deductible, "total": float(it.total),
                "supply": float(it.supply), "vat": float(it.vat), "remark": it.remark,
            } for it in items],
            "lines": self._lines(voucher, items),
        }

    def _emp_of(self, usr_seq: "str | int | None") -> "tuple[str, str]":
        """전송자 usr_seq → 아마란스 (사원코드, 부서코드). 매핑 없으면 빈 값(미전송)."""
        try:
            seq = int(usr_seq or 0)
        except (TypeError, ValueError):
            return "", ""
        if not seq:
            return "", ""
        from app.models.user_emp_map import UserEmpMap

        row = self.db.scalars(
            select(UserEmpMap).where(
                UserEmpMap.usr_seq == seq, UserEmpMap.active == "Y"
            )
        ).first()
        return (row.emp_cd, row.dept_cd) if row else ("", "")

    def _lines(
        self,
        voucher: CardVoucher,
        items: list[CardVoucherItem],
        *,
        emp_cd: str = "",
        dept_cd: str = "",
    ) -> list[dict[str, Any]]:
        """저장된 확정값 그대로 분개를 만든다(계정·적요를 다시 매핑하지 않는다)."""
        usages = [cv.CardUsage(
            row_no=0, card_no=it.card_no, card_alias=it.card_alias or "",
            user_name=it.user_name or "", use_date=it.use_date, appr_no=it.appr_no or "",
            merchant=it.merchant or "", merchant_biz_no=it.merchant_biz_no or "",
            total=it.total, supply=it.supply, vat=it.vat, purpose=it.purpose or "",
            deductible=it.deductible, canceled=False,
            account_code=it.account_code or "", remark=it.remark or "",
        ) for it in items]
        vehicles = {name: v["car_cd"] for name, v in card_vehicles.vehicle_map(self.db).items()}
        missing = cv.missing_vehicles(usages, vehicles)
        if missing:
            raise CardVoucherError(f"차량유지비 건인데 업무용승용차가 등록되지 않은 사용자: {', '.join(missing)}")
        return cv.build_lines(
            usages,
            division_code=voucher.division_code,
            voucher_date=voucher.voucher_date.strftime("%Y%m%d"),
            menu_sq=voucher.menu_sq,
            vehicles=vehicles,
            card_partners={it.card_no: (it.card_partner_code or "") for it in items},
            merchant_partners={
                (it.merchant_biz_no or ""): (it.merchant_partner_code or "") for it in items
            },
            emp_cd=emp_cd,
            dept_cd=dept_cd,
        )

    # ── 아마란스 전송 ────────────────────────────────────────────
    def send(self, voucher_id: int, *, sent_by: str = "") -> dict[str, Any]:
        # 같은 전표를 두 번 보내지 않도록 행을 잠그고 상태를 확인한다.
        voucher = self.db.scalars(
            select(CardVoucher).where(CardVoucher.id == voucher_id).with_for_update()
        ).first()
        if voucher is None:
            raise CardVoucherError("전표를 찾을 수 없습니다.")
        if voucher.status == "S":
            raise CardVoucherError("이미 아마란스로 전송된 전표입니다.")
        if sent_by:
            voucher.created_by = voucher.created_by or sent_by

        items = self.db.scalars(
            select(CardVoucherItem).where(CardVoucherItem.voucher_id == voucher_id)
            .order_by(CardVoucherItem.id)
        ).all()
        # 작성자·작성부서: 전송자 기준(없으면 확정자)으로 아마란스 사원 매핑을 찾는다
        emp_cd, dept_cd = self._emp_of(sent_by or voucher.created_by)
        lines = self._lines(voucher, items, emp_cd=emp_cd, dept_cd=dept_cd)
        if not lines:
            raise CardVoucherError("전송할 분개가 없습니다.")
        debit = sum(l["acctAm"] for l in lines if l["drcrFg"] == "3")
        credit = sum(l["acctAm"] for l in lines if l["drcrFg"] == "4")
        if round(debit - credit, 2) != 0:
            raise CardVoucherError(f"차대가 맞지 않습니다 (차변 {debit:,.0f} / 대변 {credit:,.0f}).")

        body = {"coCd": self.company_code, "data": lines}
        voucher.request_body = json.dumps(body, ensure_ascii=False, default=str)
        try:
            response = self.client.post("/apiproxy/api11A10", json_body=body)
            voucher.response_body = json.dumps(response, ensure_ascii=False, default=str)
            rows = response.get("resultData") or []
            if isinstance(rows, dict):
                rows = [rows]
            errors = [r.get("errorMsg") for r in rows if isinstance(r, dict) and r.get("errorMsg")]
            if errors:
                raise CardVoucherError("; ".join(str(e) for e in errors[:3]))
            voucher.status = "S"
            voucher.sent_at = datetime.now()
            if rows and isinstance(rows[0], dict):
                voucher.a10_voucher_no = str(
                    rows[0].get("isuSq") or rows[0].get("menuSq") or voucher.menu_sq
                )
            voucher.error_msg = None
            self.db.commit()
        except Exception as exc:
            detail = _amaranth_detail(exc)
            voucher.status = "F"
            voucher.error_msg = detail[:2000]
            if voucher.response_body is None:
                voucher.response_body = json.dumps(
                    getattr(exc, "data", None), ensure_ascii=False, default=str
                )
            self.db.commit()
            raise CardVoucherError(f"아마란스 전송에 실패했습니다: {detail}") from exc
        detail_out = self.draft_detail(voucher.id)
        detail_out["vehicle_lines"] = sum(1 for line in lines if line.get("carCd"))   # 첫 실전 확인용 (2026-08-27)
        return detail_out
