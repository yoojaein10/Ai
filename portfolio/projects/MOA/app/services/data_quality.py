"""데이터 품질 점검 — 회계 입력 실수를 자동 감지 (본사 전용 관리 화면).

재무팀이 월마감 때 '정정할 목록'을 클릭 한 번으로 확보하는 용도. 오늘(2026-07-24)
매출 대사에서 반복적으로 손으로 찾던 문제들을 상시 쿼리로 만든 것.

검사 항목:
  A. 비표준 관리번호 매출 — 매출(401) 전표인데 관리번호가 감정서번호 형식이 아님
     (약식 400*은 정상이라 제외). '4'·'01'·자유텍스트·전각 등 감정서 attribution을 깬다.
  B. 청구만 있고 매출 없는 감정서 — 외상매출금(1080000)은 있는데 그 번호로 매출(401) 없음.
  C. 마스터 미매칭 감정서번호 — 표준 번호로 매출 계상됐는데 apw_masterex에 없는 번호(오타).
  D. 매출입력 비율 이상 — Apw_Mae_GaPrice 입력액이 순수수료 대비 원칙에서 벗어남.
  E. 입금 전표 중복 — 배치가 발행한 입금인데 같은 감정서·날짜·금액 전표가 2장 이상.
  F. 근거가 사라진 반제 — 배치가 반제 전표를 만든 뒤 청구가 없어져 잔액이 음수.
"""

import re
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.office_lookup import get_office
from app.services.sales_ratio import expected_ratio, ratio_basis

_STD = "[0-9][0-9]-[0-9][0-9][0-9][0-9]-%"  # 표준 감정서번호 접두 패턴
# 하이픈 있는 유사 번호(012601-1-0001-1 등) — 정규화만 하면 표준으로 복원 가능
_NEAR = re.compile(r"^\d{6}-\w-\d{4}(-\d+)?$")
_BUNDLE_KW = ("합산", "배분", "정산", "분기", "든든", "보금자리", "국세청", "공시", "주택금융")


def _reason_nonstandard(mgmt: str, remark: str) -> str:
    """비표준 관리번호 매출 한 건이 '왜' 문제인지 판정."""
    m = (mgmt or "").strip()
    rmk = remark or ""
    if _NEAR.match(m):
        return "번호 형식 오류(앞 '01-' 없음·접미사 붙음) — 정규화하면 복원 가능"
    if m.isdigit() or len(m) <= 3:
        return f"감정서번호 자리에 숫자만('{m}') 입력됨 — 정번호로 정정 필요"
    if any(k in rmk for k in _BUNDLE_KW):
        return "합산청구/정산 전표(여러 건 묶음) — 정상일 수 있음"
    return "자유 텍스트 — 감정서번호가 아님"


# 매출입력 인정비율 규칙은 app/services/sales_ratio.py 참조.
# 절사·반올림 오차가 1% 남짓이라 2%까지는 눈감는다.
_RATIO_TOLERANCE = 0.02


def _ratio_fields(row: Any) -> dict:
    return {
        "manager": row["manager"], "customer": row["customer"],
        "work": row["work"], "purpose": row["purpose"], "charge": row["charge"],
        "input_date": row["last_in"],  # 인정비율표 시행일 판정용
    }


def _ratio_gap(row: Any) -> float:
    """입력액 − 기대액."""
    return float(row["entered"]) - float(row["net"]) * expected_ratio(**_ratio_fields(row))


def _ratio_reason(row: Any) -> str:
    """이 건이 왜 걸렸는지 한 줄로 설명한다."""
    entered, net = float(row["entered"]), float(row["net"])
    expected = expected_ratio(**_ratio_fields(row))
    ratio = entered / net if net else 0.0
    return (f"{ratio_basis(**_ratio_fields(row))} 기준 {net * expected:,.0f}원이어야 하는데 "
            f"{entered:,.0f}원 입력 ({ratio:.2f}배)")


def _source_db() -> str:
    db_name = get_settings().mssql_source_db
    if not db_name.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return db_name


def run_checks(
    db: Session, date_from: date, date_to: date, office_code: str = "10"
) -> "dict[str, Any]":
    office = get_office(db, office_code)
    division = office.division_code if office else "1000"
    params = {
        "div": division, "f": date_from, "t": date_to,
        "office": office_code, "tol": _RATIO_TOLERANCE,
    }

    # A. 비표준 관리번호 매출 (약식 400* 제외)
    a_rows = db.execute(
        text(
            f"""
            SELECT LTRIM(RTRIM(management_no)) AS mgmt,
                   SUM(CASE WHEN debit_credit='4' THEN amount
                            WHEN debit_credit='3' THEN -amount ELSE 0 END) AS amount,
                   COUNT(*) AS lines,
                   MAX(remark) AS remark
            FROM dbo.a10_voucher_cache
            WHERE division_code = CAST(:div AS varchar(10))
              AND account_code LIKE '401%'
              AND voucher_date BETWEEN :f AND :t
              AND LTRIM(RTRIM(management_no)) NOT LIKE '{_STD}'
              AND LTRIM(RTRIM(management_no)) NOT LIKE '400%'
            GROUP BY LTRIM(RTRIM(management_no))
            ORDER BY ABS(SUM(CASE WHEN debit_credit='4' THEN amount
                                  WHEN debit_credit='3' THEN -amount ELSE 0 END)) DESC
            """
        ),
        params,
    ).mappings().all()

    # B. 외상매출금(청구)만 있고 그 번호로 매출(401) 없음
    b_rows = db.execute(
        text(
            f"""
            WITH sales AS (
                -- 매출이 잡힌 관리번호를 한 번만 모은다. 예전에는 청구 건마다
                -- NOT EXISTS 를 돌렸는데, LTRIM(RTRIM(management_no)) 이 인덱스를
                -- 못 쓰게 만들어 청구 건 수만큼 전량 스캔이 났다 (연초~오늘 49초).
                -- 한 번만 훑어 맞대면 0.2초다 (2026-08-21, 결과는 동일).
                -- 기간은 걸지 않는다 — 매출이 청구와 다른 날 잡혀도 누락은 아니다.
                SELECT DISTINCT LTRIM(RTRIM(management_no)) AS mgmt
                FROM dbo.a10_voucher_cache
                WHERE division_code = CAST(:div AS varchar(10))
                  AND account_code LIKE '401%' AND debit_credit = '4'
            ), ar AS (
                SELECT LTRIM(RTRIM(management_no)) AS mgmt,
                       SUM(CASE WHEN debit_credit='3' THEN amount ELSE 0 END) AS billed
                FROM dbo.a10_voucher_cache
                WHERE division_code = CAST(:div AS varchar(10))
                  AND account_code = '1080000'
                  AND voucher_date BETWEEN :f AND :t
                  AND LTRIM(RTRIM(management_no)) LIKE '{_STD}'
                GROUP BY LTRIM(RTRIM(management_no))
            )
            SELECT ar.mgmt, ar.billed
            FROM ar
            LEFT JOIN sales s ON s.mgmt = ar.mgmt
            WHERE ar.billed > 0 AND s.mgmt IS NULL
            ORDER BY ar.billed DESC
            """
        ),
        params,
    ).mappings().all()

    # C. 표준번호 매출인데 apw_masterex 미매칭 (오타 감정서번호)
    src = _source_db()
    c_rows = db.execute(
        text(
            f"""
            SELECT v.mgmt, v.amount FROM (
                SELECT LTRIM(RTRIM(management_no)) AS mgmt,
                       SUM(CASE WHEN debit_credit='4' THEN amount
                                WHEN debit_credit='3' THEN -amount ELSE 0 END) AS amount
                FROM dbo.a10_voucher_cache
                WHERE division_code = CAST(:div AS varchar(10))
                  AND account_code LIKE '401%'
                  AND voucher_date BETWEEN :f AND :t
                  AND LTRIM(RTRIM(management_no)) LIKE '{_STD}'
                GROUP BY LTRIM(RTRIM(management_no))
            ) v
            WHERE NOT EXISTS (
                SELECT 1 FROM [{src}].dbo.apw_masterex m WHERE m.DocID = v.mgmt)
            ORDER BY ABS(v.amount) DESC
            """
        ),
        params,
    ).mappings().all()

    # D. 매출입력 비율 이상 (기간은 '마지막 입력일' 기준 — 중복 입력은 나중에 덧붙으므로
    #    최초 입력일로 잡으면 정작 잡아야 할 중복 건이 기간 밖으로 빠진다).
    #    입력액은 감정서 전체 행 합계로 본다 — 여러 담당자로 나눠 여러 행이 들어가기 때문.
    d_rows = db.execute(
        text(
            f"""
            SELECT g.Docid AS doc,
                   CAST(g.susu AS float) AS entered,
                   CAST(m.[기초수수료] - m.[절사금액] AS float) AS net,
                   RTRIM(m.Manager) AS manager, RTRIM(m.CustName) AS customer,
                   RTRIM(m.LWorkinfo) AS work, RTRIM(m.LPurpose) AS purpose,
                   RTRIM(m.Charge) AS charge, g.last_in
            FROM (
                SELECT Docid, SUM(Basic_Susu) AS susu, MAX(In_Date) AS last_in
                FROM [{src}].dbo.Apw_Mae_GaPrice
                GROUP BY Docid
            ) g
            JOIN [{src}].dbo.apw_masterex m ON m.DocID = g.Docid
            WHERE g.last_in >= :f AND g.last_in < DATEADD(day, 1, :t)
              AND m.Office = CAST(:office AS varchar(10))
              AND m.[기초수수료] - m.[절사금액] > 0
            """
        ),
        params,
    ).mappings().all()
    # 인정비율 판정은 업무 종류·조사자까지 봐야 해서 SQL CASE로는 다 담기 어렵다.
    d_rows = sorted(
        (r for r in d_rows
         if abs(float(r["entered"]) / float(r["net"]) - expected_ratio(**_ratio_fields(r)))
         > _RATIO_TOLERANCE),
        key=lambda r: abs(_ratio_gap(r)),
        reverse=True,
    )

    # E. 입금 전표 중복 — 우리 배치가 발행한 뒤 사람이 또 넣었거나, 사람이 먼저
    #    넣은 걸 배치가 못 보고 또 만든 경우. 둘 다 전표가 두 장으로 남는다.
    #    (2026-08-21 조사: 알림 큐가 입금액을 두 배로 적은 21건의 주된 원인.
    #     전표가 두 벌이던 순간을 10분 배치가 사진 찍어 큐에 박아 둔다.)
    #    반제 전표는 (차)보통예금/(대)외상매출금 한 장이라 UNION 으로 전표 장수를 센다 —
    #    계정별로 세면 한 장을 두 번 세어 전부 중복으로 보인다.
    #    지사 본지점(BRANCH)·약식 묶음(YAK)은 감정서 단위가 아니라 뺀다.
    #    관리번호는 LTRIM(RTRIM()) 없이 직접 비교한다 — 계산식 조인은 인덱스 탐색을
    #    막아, 캐시가 자라자 옵티마이저가 174만 행 전체 스풀 계획으로 뒤집혀 이 항목
    #    하나가 10초를 먹었다(2026-08-28 실측, 논리 읽기 529만). 캐시에 앞공백
    #    관리번호는 0건이고 꼬리 공백은 SQL Server 가 비교 시 무시하므로 결과는 같다
    #    (입금전표 배치 _voucher_kind 도 같은 직접 비교를 쓴다).
    e_rows = db.execute(
        text(
            """
            SELECT o.doc_id AS doc, o.tx_day, o.tx_amount, o.voucher_kind,
                   o.sent_at, v.cnt AS vouchers
            FROM dbo.a10_deposit_outbox o
            CROSS APPLY (
                SELECT COUNT(*) AS cnt FROM (
                    SELECT a.voucher_date, a.voucher_no, a.division_code
                    FROM dbo.a10_voucher_cache a
                    WHERE a.division_code = CAST(:div AS varchar(10))
                      AND a.account_code = '1080000' AND a.debit_credit = '4'
                      AND a.management_no = o.doc_id
                      AND a.voucher_date = o.tx_day AND a.amount = o.tx_amount
                    UNION
                    SELECT d.voucher_date, d.voucher_no, d.division_code
                    FROM dbo.a10_voucher_cache d
                    JOIN dbo.a10_voucher_cache s
                      ON s.voucher_date = d.voucher_date AND s.voucher_no = d.voucher_no
                     AND s.division_code = d.division_code
                     AND s.management_no = o.doc_id
                    WHERE d.division_code = CAST(:div AS varchar(10))
                      AND d.account_code = '1030000' AND d.debit_credit = '3'
                      AND d.voucher_date = o.tx_day AND d.amount = o.tx_amount
                ) u
            ) v
            WHERE o.status = 'S' AND o.voucher_kind IN ('BANJE','GENERAL')
              AND o.doc_id IS NOT NULL
              AND o.tx_day BETWEEN :f AND :t
              AND v.cnt > 1
            ORDER BY o.tx_amount DESC
            """
        ),
        params,
    ).mappings().all()

    # F. 근거가 사라진 반제 전표 — 배치는 발행 직전에 '같은 금액의 외상매출금 차변이
    #    있나'를 다시 확인하고 만든다(deposit_vouchers._voucher_kind). 그런데 그 뒤
    #    재무팀이 청구 전표를 지우고 직접입금 전표로 바꾸면, 반제만 남아 외상매출금이
    #    음수가 된다 (2026-08-14 발행 3건 실측). 발행 시점 조건으로는 원리상 못 막으니
    #    사후에 잡아 정리하게 한다.
    #    '잔액 음수'만 보면 안 된다 — 묶음 관리번호·지사·옛 데이터까지 2,750건 178억이
    #    걸려 목록을 못 쓴다. 우리가 발행한 반제로 좁히면 딱 문제 건만 남는다.
    f_rows = db.execute(
        text(
            """
            SELECT o.doc_id AS doc, o.tx_day, o.tx_amount, o.sent_at, v.bal
            FROM dbo.a10_deposit_outbox o
            OUTER APPLY (
                SELECT SUM(CASE WHEN c.debit_credit = '3' THEN c.amount
                                ELSE -c.amount END) AS bal
                FROM dbo.a10_voucher_cache c
                WHERE c.division_code = CAST(:div AS varchar(10))
                  AND c.account_code = '1080000'
                  AND c.management_no = o.doc_id
            ) v
            WHERE o.status = 'S' AND o.voucher_kind = 'BANJE'
              AND o.doc_id IS NOT NULL
              AND o.tx_day BETWEEN :f AND :t
              AND ISNULL(v.bal, 0) < -0.5
            ORDER BY v.bal
            """
        ),
        params,
    ).mappings().all()

    checks = [
        {
            "key": "nonstandard_mgmt", "title": "비표준 관리번호 매출",
            "desc": "매출 전표인데 관리번호가 감정서번호 형식이 아님 (약식 400 제외). 감정서별 집계가 어긋납니다. 올바른 감정서번호로 정정하세요.",
            "count": len(a_rows), "amount": sum(float(r["amount"] or 0) for r in a_rows),
            "items": [
                {"doc": r["mgmt"], "amount": float(r["amount"] or 0),
                 "lines": int(r["lines"]), "remark": r["remark"],
                 "reason": _reason_nonstandard(r["mgmt"], r["remark"])}
                for r in a_rows
            ],
        },
        {
            "key": "billed_no_sales", "title": "청구만 있고 매출 없는 감정서",
            "desc": "외상매출금(청구)은 잡혔는데 그 감정서번호로 매출 전표가 없습니다. 매출 계상 누락이거나 매출 라인 관리번호 오입력일 수 있습니다.",
            "count": len(b_rows), "amount": sum(float(r["billed"] or 0) for r in b_rows),
            "items": [{"doc": r["mgmt"], "amount": float(r["billed"] or 0),
                       "reason": "청구(외상매출금)는 있으나 매출 전표 없음 — 매출 계상 누락 또는 관리번호 오입력"}
                      for r in b_rows],
        },
        {
            "key": "no_master", "title": "마스터에 없는 감정서번호",
            "desc": "매출은 계상됐는데 감정서 마스터(apw_masterex)에 없는 번호입니다. 감정서번호 오타일 가능성이 큽니다.",
            "count": len(c_rows), "amount": sum(float(r["amount"] or 0) for r in c_rows),
            "items": [{"doc": r["mgmt"], "amount": float(r["amount"] or 0),
                       "reason": "감정서 마스터에 없는 번호 — 오타 의심"}
                      for r in c_rows],
        },
        {
            "key": "sales_input_ratio", "title": "매출입력 비율 이상",
            "desc": "매출입력 금액이 인정비율 규정에서 벗어났습니다. 유치자가 '공(이름)'인 건은 현재 실적 미인정(0원)이 기준이며, 거래처가 우리은행이면 무조건 절반입니다. 공(이름)이 아닌 건은 전액이 기준입니다. 인정비율표가 시행되면 그 날 이후 입력분부터 업무 종류별 표(조사자가 본인뿐이면 단독처리)로 바뀝니다. 절사·반올림을 감안해 2% 넘게 어긋난 건만 표시합니다.",
            "count": len(d_rows),
            "amount": sum(_ratio_gap(r) for r in d_rows),
            "items": [
                {
                    "doc": r["doc"],
                    "amount": _ratio_gap(r),
                    "remark": f"{r['manager']} · {r['work']} · {r['customer']}",
                    "reason": _ratio_reason(r),
                }
                for r in d_rows
            ],
        },
        {
            "key": "duplicate_payment_voucher", "title": "입금 전표 중복",
            "desc": "자동 전표 배치가 발행한 입금인데 같은 감정서·같은 날짜·같은 금액의 전표가 두 장 이상입니다. 재무팀 수기 입력과 겹친 것으로, 한 장을 지워야 입금액이 두 배로 잡히지 않습니다. 배치의 이중계상 가드는 10분 주기 캐시를 보므로 수기 입력 직후나 배치 발행 뒤에 넣은 건은 못 막습니다.",
            "count": len(e_rows),
            "amount": sum(float(r["tx_amount"] or 0) for r in e_rows),
            "items": [
                {
                    "doc": r["doc"],
                    "amount": float(r["tx_amount"] or 0),
                    "lines": int(r["vouchers"]),
                    "remark": f"{r['tx_day']} · {r['voucher_kind']}",
                    "reason": (
                        f"{r['tx_day']} 입금 {float(r['tx_amount'] or 0):,.0f}원에 "
                        f"전표 {int(r['vouchers'])}장 — 배치 발행 "
                        f"{r['sent_at']:%m-%d %H:%M}. 한 장을 삭제하세요."
                        if r["sent_at"] else
                        f"{r['tx_day']} 입금에 전표 {int(r['vouchers'])}장 — 한 장을 삭제하세요."
                    ),
                }
                for r in e_rows
            ],
        },
        {
            "key": "orphan_banje", "title": "근거가 사라진 반제 전표",
            "desc": "자동 전표 배치가 반제 전표를 만든 뒤 그 감정서의 청구(외상매출금 차변)가 없어졌습니다. 반제만 남아 외상매출금이 음수입니다. 재무팀이 청구를 지우고 직접입금 전표로 바꾼 경우로, 배치가 만든 반제 라인을 지우면 정리됩니다. 발행 시점에는 청구가 있었으므로 배치가 막을 수 있는 건이 아닙니다.",
            "count": len(f_rows),
            "amount": sum(float(r["bal"] or 0) for r in f_rows),
            "items": [
                {
                    "doc": r["doc"],
                    "amount": float(r["bal"] or 0),
                    "remark": f"{r['tx_day']} 입금 {float(r['tx_amount'] or 0):,.0f}원",
                    "reason": (
                        f"외상매출금 잔액 {float(r['bal'] or 0):,.0f}원 — 청구 없이 반제만 있음. "
                        f"배치 발행 {r['sent_at']:%m-%d %H:%M}. 반제 라인을 지우세요."
                        if r["sent_at"] else
                        f"외상매출금 잔액 {float(r['bal'] or 0):,.0f}원 — 반제 라인을 지우세요."
                    ),
                }
                for r in f_rows
            ],
        },
    ]
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "total_issues": sum(c["count"] for c in checks),
        "checks": checks,
    }
