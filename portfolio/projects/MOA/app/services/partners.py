"""거래처 조회/등록 비즈니스 로직."""

import json
from collections.abc import Iterable
from typing import Any

from sqlalchemy.orm import Session

from app.amaranth.client import AmaranthClient
from app.models.partner_sync import PartnerSync
from app.schemas.partner import PartnerCreate


# 고객사담당자(api16S14) 등록에 쓰는 그룹코드. 재무팀 확인값 100 고정(2026-08-11).
CONTACT_GROUP_CD = "100"


class PartnerNotFoundError(LookupError):
    pass


class DuplicatePartnerError(ValueError):
    def __init__(self, partner: dict[str, Any]) -> None:
        self.partner = partner
        super().__init__("이미 등록된 사업자번호입니다.")


class PartnerService:
    def __init__(self, db: Session, client: AmaranthClient | None = None) -> None:
        self.db = db
        self.client = client or AmaranthClient(db)

    def list(
        self,
        company_code: str,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
        include_unused: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "coCd": company_code,
            "usePagination": True,
            "pagingOffset": (page - 1) * page_size,
            "pagingCount": page_size,
        }
        if not include_unused:
            # 공식 스펙에 없는 값이지만 실측으로 동작한다(2026-08-05).
            # '국민은행' 검색 200건 중 41건이 미사용이라 그냥 두면 폐지 지점이
            # 후보에 섞인다. useYn='Y'는 무시되고 '1'만 먹는다.
            body["useYn"] = "1"
        if search:
            keyword = search.strip()
            digits = keyword.replace("-", "")
            if digits.isdigit() and len(digits) <= 5:
                # 거래처코드는 10자리(앞자리 0 채움)라 끝 5자리만 입력해도 조회한다.
                body["trCd"] = digits.zfill(10)
            elif digits.isdigit():
                body["regNb"] = digits
            else:
                body["trNm"] = keyword
        payload = self.client.post("/apiproxy/api16S11", json_body=body)
        partners = _result_list(payload)
        items = _dedupe_by_code(_flatten_partner(partner) for partner in partners)
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "count": len(items),
        }

    # 거래처 마스터에서 채울 대상 필드 (팝업 키 → api16S11/S12 필드)
    _FILL_FIELDS = {
        "corp_num": "regNb", "ceo_name": "ceoNm", "biz_type": "business",
        "biz_class": "jongmok", "addr": "divAddr1", "email": "email", "tel": "tel",
    }

    def fill_missing(
        self, company_code: str, tr_cd: str, candidates: dict[str, Any], apply: bool
    ) -> dict[str, Any]:
        """거래처의 '빈 항목만' 후보값으로 채운다. apply=False면 채울 목록만 미리보기.

        마스터를 다시 읽어 비어있는 필드만 대상으로 삼는다(기존 값은 절대 덮지 않음).
        """
        payload = self.client.post(
            "/apiproxy/api16S11",
            json_body={"coCd": company_code, "trCd": tr_cd,
                       "usePagination": True, "pagingOffset": 0, "pagingCount": 5},
        )
        master = next(
            (r for r in _result_list(payload) if str(r.get("trCd") or "").strip() == tr_cd),
            None,
        )
        if master is None:
            raise PartnerNotFoundError("거래처를 찾을 수 없습니다.")

        fillable: dict[str, str] = {}
        for pop_key, ama_key in self._FILL_FIELDS.items():
            cand = str(candidates.get(pop_key) or "").strip()
            if pop_key == "corp_num":
                cand = _digits(cand)
            if cand and not str(master.get(ama_key) or "").strip():
                fillable[ama_key] = cand

        # 담당자정보 이메일 — 아마란스 세금계산서 화면은 기본정보가 아니라
        # 고객사담당자의 이메일을 가져온다. 담당자 흔적이 전혀 없을 때만 등록
        # 대상으로 삼는다(수기 등록된 담당자 옆에 정(defYn=1)을 또 만들지 않기 위해).
        cand_email = str(candidates.get("email") or "").strip()
        contact_email = (
            cand_email if cand_email and not _has_customer_contact(master) else ""
        )
        if not apply or not (fillable or contact_email):
            return {"fillable": fillable, "contact_email": contact_email,
                    "applied": False}

        # 수정 전송: 마스터 값 유지 + 빈 칸만 채움. inputFg=1(수정), trCd 지정.
        response_ok = None
        if fillable:
            merged = {
                "coCd": company_code, "inputFg": "1", "trCd": tr_cd,
                "trNm": str(master.get("trNm") or "").strip(),
                "attrNm": str(master.get("attrNm") or master.get("trNm") or "").strip(),
                "trFg": str(master.get("trFg") or "1"),
            }
            for ama_key in ("regNb", "ceoNm", "business", "jongmok", "zip",
                            "divAddr1", "addr2", "tel", "fax", "email"):
                val = str(master.get(ama_key) or "").strip() or fillable.get(ama_key, "")
                if val:
                    merged[ama_key] = val
            result = self.client.post("/apiproxy/api16S12", json_body={"list": [merged], "dupCheck": False})
            response_ok = bool(_result_list(result))
        contact_synced = None
        if contact_email:
            contact_synced = self._register_contact_email(company_code, tr_cd, contact_email)
        return {"fillable": fillable, "contact_email": contact_email, "applied": True,
                "response_ok": response_ok, "contact_synced": contact_synced}

    def get(self, company_code: str, business_no: str) -> dict[str, Any]:
        payload = self.client.post(
            "/apiproxy/api16S11",
            json_body={"coCd": company_code, "regNb": business_no},
        )
        partners = _result_list(payload)
        exact = next(
            (
                partner
                for partner in partners
                if _digits(str(partner.get("regNb", ""))) == business_no
            ),
            None,
        )
        if exact is None:
            raise PartnerNotFoundError("거래처를 찾을 수 없습니다.")
        return _flatten_partner(exact)

    def create(self, request: PartnerCreate) -> dict[str, Any]:
        request_body = {
            "list": [request.to_amaranth_item()],
            "dupCheck": False,
        }
        if request.insert_id:
            request_body["insertId"] = request.insert_id

        try:
            existing = self._find_by_business_no(
                request.company_code, request.business_no
            )
            if existing is not None:
                raise DuplicatePartnerError(_flatten_partner(existing))

            payload = self.client.post(
                "/apiproxy/api16S12", json_body=request_body
            )
            result = _first_result(payload)
            partner_code = str(result.get("trCd") or request.partner_code or "") or None
            self._record_sync(
                request=request,
                request_body=request_body,
                response_body=payload,
                status="S",
                partner_code=partner_code,
            )
            response = {
                "business_no": request.business_no,
                "partner_code": partner_code,
                "name": request.name,
                "synced": True,
            }
            if request.email and partner_code:
                response["contact_synced"] = self._register_contact_email(
                    request.company_code, partner_code, request.email
                )
            return response
        except Exception as exc:
            self._record_sync(
                request=request,
                request_body=request_body,
                response_body=None,
                status="F",
                error=str(exc),
            )
            raise

    def _register_contact_email(self, company_code: str, tr_cd: str, email: str) -> bool:
        """고객사담당자(api16S14)에 이메일만 있는 담당자를 정(defYn=1)으로 등록한다.

        아마란스 세금계산서 화면이 담당자정보의 이메일을 가져오기 때문에 기본정보
        email과 같이 채운다. 거래처 자체는 이미 등록된 뒤라 실패해도 예외를 올리지
        않고 False만 돌려준다.
        """
        try:
            self.client.post(
                "/apiproxy/api16S14",
                json_body={"list": [{
                    "coCd": company_code, "trCd": tr_cd,
                    "empgrpCd": CONTACT_GROUP_CD,
                    "trchargeEmail": email, "defYn": "1",
                }]},
            )
            return True
        except Exception:
            return False

    def _find_by_business_no(
        self, company_code: str, business_no: str
    ) -> dict[str, Any] | None:
        payload = self.client.post(
            "/apiproxy/api16S11",
            json_body={"coCd": company_code, "regNb": business_no},
        )
        return next(
            (
                partner
                for partner in _result_list(payload)
                if _digits(str(partner.get("regNb", ""))) == business_no
            ),
            None,
        )

    def _record_sync(
        self,
        *,
        request: PartnerCreate,
        request_body: dict[str, Any],
        response_body: dict[str, Any] | None,
        status: str,
        partner_code: str | None = None,
        error: str | None = None,
    ) -> None:
        self.db.add(
            PartnerSync(
                company_code=request.company_code,
                business_no=request.business_no,
                partner_name=request.name,
                partner_code=partner_code,
                status=status,
                request_body=json.dumps(request_body, ensure_ascii=False),
                response_body=(
                    json.dumps(response_body, ensure_ascii=False, default=str)
                    if response_body is not None
                    else None
                ),
                error_msg=error,
            )
        )
        self.db.commit()


def _result_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("resultData")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "datas", "list"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _first_result(payload: dict[str, Any]) -> dict[str, Any]:
    items = _result_list(payload)
    if items:
        return items[0]
    data = payload.get("resultData")
    return data if isinstance(data, dict) else {}


def _has_customer_contact(master: dict[str, Any]) -> bool:
    """거래처조회(api16S11) 행에 고객사담당자 흔적이 있는지 본다.

    조회가 담당자 정보를 stempgrpTrcharge* 필드로 조인해 내려주므로 하나라도
    값이 있으면 담당자가 이미 있다고 본다.
    """
    return any(
        str(value or "").strip()
        for key, value in master.items()
        if key.startswith("stempgrpTrcharge")
    )


def partner_hp(value: dict[str, Any]) -> str:
    """거래처 담당자 휴대폰 후보. 마스터에 드물게만 입력돼 있어 채워진 필드부터 쓴다."""
    for key in ("stempHp", "streceiveHp", "stempgrpTrchargeHp"):
        hp = str(value.get(key) or "").strip()
        if hp:
            return hp
    return ""


def _dedupe_by_code(items: "Iterable[dict[str, Any]]") -> "list[dict[str, Any]]":
    """거래처코드가 같은 행을 하나로 접는다 (먼저 온 행을 남긴다).

    api16S11 이 거래처 하위 정보와 조인해 내려주는지, 같은 거래처가 여러 줄로
    온다 — '신한은행 영동금융센터'는 코드·상호·사업자번호가 똑같은 4줄이었다
    (2026-08-07 실측). 그대로 두면 전표·세금계산서 후보 목록에 같은 거래처가
    여러 번 떠서 담당자가 무엇이 다른지 찾느라 시간을 쓴다.

    코드가 없는 행은 접을 근거가 없으므로 그대로 둔다.
    """
    seen: "set[str]" = set()
    result: "list[dict[str, Any]]" = []
    for item in items:
        code = str(item.get("partner_code") or "").strip()
        if code:
            if code in seen:
                continue
            seen.add(code)
        result.append(item)
    return result


def _flatten_partner(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "partner_code": value.get("trCd"),
        "name": value.get("trNm"),
        "short_name": value.get("attrNm"),
        "partner_type": value.get("trFg"),
        "business_no": _digits(str(value.get("regNb") or "")),
        "representative": value.get("ceoNm"),
        "business_type": value.get("business"),
        "business_item": value.get("jongmok"),
        "postal_code": value.get("zip"),
        "address1": value.get("divAddr1"),
        "address2": value.get("addr2"),
        "telephone": value.get("tel"),
        "hp": partner_hp(value),
        "fax": value.get("fax"),
        "email": value.get("email"),
        "use_yn": value.get("useYn"),
    }


def _digits(value: str) -> str:
    return "".join(character for character in value if character.isdigit())
