"""은행 공통 중간 모델.

파서들(.gam·의견서·APW DB)이 만든 값을 은행과 무관한 형태로 모아 둔다.
은행별 매핑(`mapping/*.py`)은 이 모델만 보고 화면 필드를 채운다.
그래서 은행이 늘어도 파서는 그대로고 매핑 파일만 추가하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .parse.account import BankAccount
from .parse.characteristics import Characteristics
from .parse.kb import KbConItem, KbSummary
from .parse.cost import CostLayer
from .parse.detail import DetailRow
from .parse.mullist import MullistRow
from .parse.outline import Outline
from .parse.round import RoundInfo
from .parse.standard_land import StandardLand
from .sources.apw import Jibun
from .sources.scan import GongbuRow, identify as identify_gongbu, registry_for


@dataclass(frozen=True)
class Parties:
    """작성·심사 담당자. 이름으로 콤보를 고르므로 코드는 필요 없다."""

    boss: str | None = None                     # 대표·지사장
    appraisers: tuple[str, ...] = ()            # 평가사 1~3 (manager 분리 결과)
    reviewer: str | None = None                 # 심사자 (APW_Judgment itype=2)
    sender: str | None = None                   # 발송(입력) 담당 (apw_masterex.Sendman)

    def appraiser(self, index: int) -> str | None:
        return self.appraisers[index] if index < len(self.appraisers) else None


@dataclass(frozen=True)
class Fee:
    """수수료 — `gam_info` 원시값을 그대로 담는다.

    은행마다 쓰는 조합이 달라서(신한 `감정평가료`=TOTAL, 국민 `총액`=SUSUSUM)
    여기서 계산하지 않고 은행별 매핑이 골라 쓰게 한다. 실측 대조로 확인한 관계:

        순수수료      = SUSU
        부가가치세     = TAX (= SUSUTAX)
        수수료합계     = SUSUSUM        (SUSU+실비를 1,000원 단위로 절사)
        청구총액      = TOTAL (= BILL)  = SUSUSUM + TAX
        실비(부가세포함) = (실비 구성항목 합) × 1.1

    ⚠️ `SILBISUM` 은 낡은 값이 섞여 있다 — 실측에서 두 건의 `SILBISUM` 이 같은데
    화면 실비가 달랐고, 차이는 `GONGBU`(공부발급비) 였다. 그래서 합계 필드를 믿지
    않고 **구성 항목을 더한다**. 구성이 모두 비어 있을 때만 `SILBISUM` 으로 물러선다.

        2182: GONGBU 2,000 + YEBI 40,000 + MULJOSABI 10,000 + SILBI 200 = 52,200 → 57,420 ✓
        2168: GONGBU 2,600 + YEBI 40,000 + MULJOSABI 10,000 + SILBI 200 = 52,800 → 58,080 ✓
    """

    net: Decimal | None = None            # SUSU
    vat: Decimal | None = None            # TAX
    subtotal: Decimal | None = None       # SUSUSUM
    total: Decimal | None = None          # TOTAL
    expense_base: Decimal | None = None   # SILBISUM (합계 — 낡을 수 있어 대비용)
    expense_extra: Decimal | None = None  # SILBI
    expense_parts: tuple[Decimal, ...] = ()  # GONGBU/YEBI/MULJOSABI/TOJOSABI …

    VAT_RATE = Decimal("1.1")

    @property
    def expense_net(self) -> Decimal | None:
        """부가세 전 실비 — 구성 항목 합이 우선, 없으면 합계 필드."""
        parts = sum((p for p in self.expense_parts if p), Decimal(0))
        extra = self.expense_extra or Decimal(0)
        if parts:
            return parts + extra
        if self.expense_base is None:
            return None if not extra else extra
        return self.expense_base + extra

    @property
    def expense_with_vat(self) -> Decimal | None:
        """화면의 `실 비` 칸 값 — 실비에 부가세를 더한 금액."""
        base = self.expense_net
        if base is None:
            return None
        return (base * self.VAT_RATE).quantize(Decimal(1))


@dataclass(frozen=True)
class DocumentContext:
    """문서 한 건의 헤더성 정보(물건과 무관한 값)."""

    doc_id: str
    business_number: str
    parties: Parties = field(default_factory=Parties)
    fee: Fee = field(default_factory=Fee)
    account: BankAccount | None = None
    jibun: Jibun | None = None
    outline: Outline = field(default_factory=Outline)
    standard_land: StandardLand = field(default_factory=StandardLand)
    characteristics: Characteristics = field(default_factory=Characteristics)
    cost_layers: tuple[CostLayer, ...] = ()
    site_address: str | None = None        # 시군구까지 갖춘 소재지 (apw_masterex.ADDR 우선)
    site_full: str | None = None           # 지번·건물명·층/호까지 (apw_masterex.Address)
    client_doc_no: str | None = None       # 의뢰처가 준 담보번호 (gam_info.cuctdocid)
    rounds: tuple[RoundInfo, ...] = ()     # 감정평가표 머리말(소유자명·의뢰처·표별 총액)
    price_point_date: str | None = None    # 現 기준시점 (괄호감정표 pricepointdate)
    survey_date: str | None = None         # 현장답사일
    total_amount: Decimal | None = None    # 총감정가액
    opinion_conclusion: str | None = None  # 감정평가액 결정의견
    properties: tuple[MullistRow, ...] = ()  # mullist 물건행(신한). 없으면 빈 튜플
    gongbu: tuple[GongbuRow, ...] = ()       # 공부 스캔(등기번호). 본사 건만 채워진다
    kb_summary: KbSummary = field(default_factory=KbSummary)  # KB_Summary (국민)
    kb_checks: tuple[str | None, ...] = ()   # 점검항목 20개, 화면 순서 (국민)
    con: tuple[KbConItem, ...] = ()          # KB_Con 물건별 집계값 (집계형 국민)
    details: tuple[DetailRow, ...] = ()      # 명세표 물건행 (mullist 없는 은행용)

    @property
    def has_mullist(self) -> bool:
        """신한 건의 68% 가 True. False 면 담보종류·담보용도를 비워둔다."""
        return bool(self.properties)

    def registry_no(self, *, kind: str | None = None, seq_no: str | None = None,
                    area: Decimal | None = None, location: str | None = None,
                    jibun: str | None = None) -> str | None:
        """등기번호 — `mullist` 에 있으면 그걸 쓰고, 없으면 공부 스캔에서 찾는다.

        `area`/`location`/`jibun` 은 **물건 고유값**이다. 한 문서에 등기번호가 여러 개면
        순번만으로는 못 고르므로(실측 2625·2399) 이 값들로 좁힌다.
        """
        if self.properties:
            for row in self.properties:
                if seq_no is not None and row.seq_no != seq_no:
                    continue
                if kind == "토지" and not row.is_land:
                    continue
                if kind == "건물" and not row.is_building:
                    continue
                if row.registry_no:
                    return row.registry_no
        return registry_for(self.gongbu, kind=kind, seq_no=seq_no,
                            area=area, location=location, jibun=jibun)

    def gongbu_address(self, *, area: Decimal | None = None, location: str | None = None,
                       jibun: str | None = None) -> str | None:
        """물건 고유값으로 찾은 공부 스캔 행의 **주소**.

        스캔 주소는 `… 900 에이스하이테크시티범계 제2층 제201호` 처럼 물건 단위로 적혀
        있어, 문서 대표 주소가 다른 물건을 가리키는 다물건 건에서 건물명 소스가 된다.
        """
        rows = identify_gongbu(self.gongbu, area=area, location=location, jibun=jibun)
        return next((row.address for row in rows if row.address), None)
