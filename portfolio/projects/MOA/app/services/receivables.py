"""감정서 관리번호 기준 입금 및 미수금 조회."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.services.office_lookup import docid_prefixes, get_office


# 목록 건수·합계를 페이지 조회와 동시에 계산하기 위한 전용 워커 (appraisals와 동일 구조).
_COUNT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="receivable-count")

# SQL Server 는 한 문장에 파라미터 2,100개까지만 받는다. 감정서번호 IN 절은 끊어서 넣는다.
_DOC_CHUNK = 800


def _direct_deposit_total_sql(fee: str, vat_net: str, fee_total: str) -> str:
    """직접입금 전표(외상매출금 대변 없음)의 수수료→입금 총액 환산 식.

    기본은 매출×1.1 반올림이지만, 재무팀 전표의 부가세 끊는 방식(합계÷11 절사 /
    공급가×10% 반올림)이 혼재해 1원이 어긋난다. 개별 거래처 금액은 원 단위가
    섞여도 합계 공급가가 10원 단위로 끝날 수 있다(01-2607-2-0092 — 실제 입금
    30,245,500원을 30,245,501원으로 계산). 따라서 공급가 끝자리가 아니라 같은
    전표의 실제 부가세예수금(2550000)을 쓸 수 있는지를 본다.

    전표의 매출 대변 전액이 이 감정서 것이고(fee_total 일치, 다감정서 전표는
    부가세를 나눌 수 없음) 부가세 라인이 실제로 있을 때만 실값을 더한다.
    현금영수증 자진발급 전표처럼 부가세 라인이 없으면(vat_net=0) 입금에는 부가세가
    포함돼 있으므로 기존 ROUND(매출×1.1) 식으로 떨어진다(01-2505-2-0078).
    """
    return (
        f"CASE WHEN {fee_total} = {fee} AND {vat_net} <> 0 "
        f"THEN {fee} + {vat_net} ELSE ROUND({fee} * 1.1, 0) END"
    )


def _aggregate_rows(sql: str, params: dict[str, Any]) -> "dict[str, Any]":
    """세션은 스레드 안전하지 않으므로 별도 커넥션으로 건수·합계만 계산한다."""
    with get_engine().connect() as connection:
        return dict(connection.execute(text(sql), params).mappings().one())


def _latest_day_amounts(
    db: Session, items: list[dict[str, Any]]
) -> dict[tuple[str, Any], dict[str, Any]]:
    """페이지에 표시된 감정서의 최근 입금일 당일 금액을 전표에서 집계한다.

    a10_receivable_summary는 감정서별 누계만 보관하므로, (기) 금액과 최근
    입금일 당일 금액을 나누려면 해당 날짜의 전표를 한 번 더 읽어야 한다.
    """
    targets = [
        (str(item["doc_id"]), item.get("last_received_date"))
        for item in items
        if item.get("last_received_date")
    ]
    if not targets:
        return {}

    all_doc_ids = sorted({doc_id for doc_id, _ in targets})
    dates = sorted({received_date for _, received_date in targets})
    date_binds = [f"latest_date_{index}" for index in range(len(dates))]

    # SQL Server 는 한 문장에 파라미터 2,100개까지만 받는다. 엑셀 내보내기는 페이지 없이
    # 전 건을 넘기므로 감정서번호를 한 번에 넣으면 넓은 기간에서 바로 터진다.
    result: dict[tuple[str, Any], dict[str, Any]] = {}
    for offset in range(0, len(all_doc_ids), _DOC_CHUNK):
        doc_ids = all_doc_ids[offset : offset + _DOC_CHUNK]
        doc_binds = [f"latest_doc_{index}" for index in range(len(doc_ids))]
        params: dict[str, Any] = {
            **{name: doc_ids[index] for index, name in enumerate(doc_binds)},
            **{name: dates[index] for index, name in enumerate(date_binds)},
        }
        rows = db.execute(
            text(
                f"""
                WITH tagged AS (
                    SELECT management_no AS doc_id, voucher_date, voucher_no, division_code,
                           SUM(CASE WHEN account_code = '1080000' AND debit_credit = '4'
                                    THEN amount ELSE 0 END) AS ar_credit,
                           SUM(CASE WHEN account_code LIKE '401%' AND debit_credit = '4' THEN amount
                                    WHEN account_code LIKE '401%' AND debit_credit = '3' THEN -amount
                                    ELSE 0 END) AS fee_credit,
                           SUM(CASE WHEN account_code = '2590000' AND debit_credit = '4' THEN amount
                                    WHEN account_code = '2590000' AND debit_credit = '3' THEN -amount
                                    ELSE 0 END) AS advance_net,
                           SUM(CASE WHEN account_code = '2570000' AND debit_credit = '4' THEN amount
                                    WHEN account_code = '2570000' AND debit_credit = '3' THEN -amount
                                    ELSE 0 END) AS suspense_net
                    FROM dbo.a10_voucher_cache
                    WHERE management_no IN ({','.join(':' + name for name in doc_binds)})
                      AND voucher_date IN ({','.join(':' + name for name in date_binds)})
                      AND (account_code IN ('1080000','2590000','2570000')
                           OR account_code LIKE '401%')
                    GROUP BY management_no, voucher_date, voucher_no, division_code
                ), cash AS (
                    SELECT c.voucher_date, c.voucher_no, c.division_code,
                           SUM(CASE WHEN c.account_code = '1030000' AND c.debit_credit = '3'
                                    THEN c.amount
                                    WHEN c.account_code = '1030000' AND c.debit_credit = '4'
                                    THEN -c.amount ELSE 0 END) AS bank_net,
                           SUM(CASE WHEN c.account_code = '1410001' AND c.debit_credit = '3'
                                    THEN c.amount
                                    WHEN c.account_code = '1410001' AND c.debit_credit = '4'
                                    THEN -c.amount ELSE 0 END) AS hq_net,
                           SUM(CASE WHEN c.account_code = '2550000' AND c.debit_credit = '3'
                                    THEN -c.amount
                                    WHEN c.account_code = '2550000' AND c.debit_credit = '4'
                                    THEN c.amount ELSE 0 END) AS vat_net,
                           SUM(CASE WHEN c.account_code LIKE '401%' AND c.debit_credit = '4'
                                    THEN c.amount
                                    WHEN c.account_code LIKE '401%' AND c.debit_credit = '3'
                                    THEN -c.amount ELSE 0 END) AS fee_total
                    FROM dbo.a10_voucher_cache c
                    INNER JOIN (
                        SELECT DISTINCT voucher_date, voucher_no, division_code FROM tagged
                    ) t ON t.voucher_date = c.voucher_date
                       AND t.voucher_no = c.voucher_no
                       AND t.division_code = c.division_code
                    WHERE c.account_code IN ('1030000','1410001','2550000')
                       OR c.account_code LIKE '401%'
                    GROUP BY c.voucher_date, c.voucher_no, c.division_code
                ), events AS (
                    SELECT t.doc_id, t.voucher_date, t.advance_net,
                           CASE WHEN (COALESCE(c.bank_net, 0) + COALESCE(c.hq_net, 0)) <> 0
                                THEN t.ar_credit + t.advance_net + t.suspense_net
                                   + CASE WHEN t.ar_credit = 0
                                          THEN {_direct_deposit_total_sql('t.fee_credit', 'c.vat_net', 'c.fee_total')} ELSE 0 END
                                ELSE 0 END AS received_delta
                    FROM tagged t
                    LEFT JOIN cash c
                      ON c.voucher_date = t.voucher_date
                     AND c.voucher_no = t.voucher_no
                     AND c.division_code = t.division_code
                )
                SELECT doc_id, voucher_date,
                       SUM(received_delta) AS daily_received_amount,
                       SUM(advance_net) AS daily_advance_amount
                FROM events
                GROUP BY doc_id, voucher_date
                """
            ),
            params,
        ).mappings().all()
        result.update({
            (str(row["doc_id"]), row["voucher_date"]): dict(row)
            for row in rows
        })
    return result


def _advance_history(
    db: Session, items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """감정서별 선수금 수령액·상계액 (전 기간).

    a10_receivable_summary 의 advance_amount 는 순액(대변-차변)이라 전액 상계된 건은
    0이 된다. 그러면 화면에서 '선수금이 아예 없던 건'과 구분할 수 없어, 받은 총액을
    전표에서 따로 읽는다.
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(doc_ids), _DOC_CHUNK):
        chunk = doc_ids[offset : offset + _DOC_CHUNK]
        binds = [f"adv_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        rows = db.execute(
            text(
                f"""
                SELECT management_no AS doc_id,
                       SUM(CASE WHEN debit_credit = '4' THEN amount ELSE 0 END) AS received,
                       SUM(CASE WHEN debit_credit = '3' THEN amount ELSE 0 END) AS offset_amount
                FROM dbo.a10_voucher_cache
                WHERE account_code = '2590000'
                  AND management_no IN ({','.join(':' + name for name in binds)})
                GROUP BY management_no
                """
            ),
            params,
        ).mappings().all()
        result.update({str(row["doc_id"]): dict(row) for row in rows})
    return result


# 요약 테이블은 외상매출금 라인이 없는 전표에서 부가세를 못 읽어
# ROUND(수수료 × 1.1) 로 역산한다(receivable_status_cte 의 direct_billed_delta).
# 그래서 입금액이 실제 입금보다 1~2원 커지는 건이 2026년 본사에 7건 있다
# (01-2607-A-0105 — 통장 4,700,000 인데 4,272,728 × 1.1 = 4,700,000.8 → 4,700,001).
# 전표당 최대 1원이라 2원까지는 잔돈으로 보고 완납 처리한다.
# 2026-08-04 _direct_deposit_total_sql 도입으로 반올림 케이스는 부가세예수금 실값을
# 읽어 역산 자체가 정확해졌다(재집계 후 해당 7건 소멸) — 이 허용치는 부가세 라인이
# 없거나 수동 조정된 잔여 케이스를 위한 안전망으로 유지한다.
_ROUND_NOISE = 2.0

# 정산 조회는 하위 쿼리가 많아 더 작게 끊는다.
_SETTLE_DOC_CHUNK = 300


def _advance_settlement(
    db: Session, items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """감정서별 '입금액에 안 잡힌 수금'. 미수금 산정에 더한다.

    a10_receivable_summary 의 received_amount 는 같은 전표에 현금(1030000·1410001)이
    있어야만 입금으로 센다. 그래서 두 가지가 빠진다.

    ① 현금 없이 들어온 선수금 — 가수금→선수금 대체, 타 감정서에서 이첩 등.
       나중에 매출 전표에서 상계될 때 입금액을 그만큼 깎아 '허깨비 미수'를 만든다.
       (01-2601-4-0024 50만, 01-2604-4-0163 20만, 01-2607-A-0113 10만 실측)
    ② 선수금 수령 전표의 부가세 — 부가세예수금(2550000)이 관리번호 없이 잡혀서
       현금 11,000,000 을 받았는데 선수금 대변 10,000,000 만 세어진다
       (01-2604-3-1088 실측).

    ①에서 빼야 하는 세 경우:
    - 같은 전표에 현금이 있으면 이미 received_amount 에 들어있다
    - 같은 전표에 이 감정서의 외상매출금 차변이 있으면 그 경로로 이미 회수됐다
      (01-2601-3-0149 — 안 빼면 272,727 이중가산)
    - 한 전표에 여러 감정서의 선수금 대변이 걸린 일괄 정산 전표는 제외한다.
      허그 분기정산처럼 매출 쪽에서 이미 털린 건이 섞여 있다
      (01-2512-3-4083 — 안 빼면 165만이 허위 과입금이 된다)

    ③ 가수금(2570000)을 매출로 직접 대체한 전표 — 수령 전표에 감정서번호가
       없어 ①과 같은 구조로 빠진다. 매출(401%) 대변이 같은 전표에 있고 현금이
       없는 가수금 차변만 수금으로 더한다 (01-2606-1-0388 — 2,200,000 실측,
       재무 관행 연 34~159건이라 전표 정정 대신 판정을 넓혔다, 2026-09-01).
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return {}

    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(doc_ids), _SETTLE_DOC_CHUNK):
        chunk = doc_ids[offset : offset + _SETTLE_DOC_CHUNK]
        binds = [f"set_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        placeholders = ",".join(":" + name for name in binds)
        rows = db.execute(
            text(
                f"""
                WITH grp AS (
                    SELECT v.management_no, v.voucher_date, v.voucher_no, v.division_code,
                           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE 0 END) AS cr,
                           SUM(CASE WHEN v.debit_credit = '3' THEN v.amount ELSE 0 END) AS dr
                    FROM dbo.a10_voucher_cache v
                    WHERE v.account_code = '2590000'
                      AND v.management_no IN ({placeholders})
                    GROUP BY v.management_no, v.voucher_date, v.voucher_no, v.division_code
                ), info AS (
                    SELECT g.*,
                      (SELECT ISNULL(SUM(CASE WHEN x.debit_credit = '3'
                                              THEN x.amount ELSE -x.amount END), 0)
                         FROM dbo.a10_voucher_cache x
                        WHERE x.voucher_date = g.voucher_date AND x.voucher_no = g.voucher_no
                          AND x.division_code = g.division_code
                          AND x.account_code IN ('1030000','1410001')) AS cash,
                      (SELECT COUNT(*) FROM dbo.a10_voucher_cache x
                        WHERE x.voucher_date = g.voucher_date AND x.voucher_no = g.voucher_no
                          AND x.division_code = g.division_code
                          AND x.account_code = '1080000' AND x.debit_credit = '3'
                          AND x.management_no = g.management_no) AS ar_cnt,
                      (SELECT COUNT(DISTINCT y.management_no) FROM dbo.a10_voucher_cache y
                        WHERE y.voucher_date = g.voucher_date AND y.voucher_no = g.voucher_no
                          AND y.division_code = g.division_code
                          AND y.account_code = '2590000' AND y.debit_credit = '4') AS cr_docs,
                      (SELECT ISNULL(SUM(CASE WHEN z.debit_credit = '4'
                                              THEN z.amount ELSE -z.amount END), 0)
                         FROM dbo.a10_voucher_cache z
                        WHERE z.voucher_date = g.voucher_date AND z.voucher_no = g.voucher_no
                          AND z.division_code = g.division_code
                          AND z.account_code LIKE '401%') AS fee_net,
                      (SELECT ISNULL(SUM(w.amount), 0) FROM dbo.a10_voucher_cache w
                        WHERE w.voucher_date = g.voucher_date AND w.voucher_no = g.voucher_no
                          AND w.division_code = g.division_code
                          AND w.account_code = '2550000' AND w.debit_credit = '4') AS vat
                    FROM grp g
                )
                , gasu_v AS (
                    -- 감정서번호 달린 가수금 줄이 있는 전표의 성격 (_settle_cte 와 동일).
                    SELECT k.voucher_date, k.voucher_no, k.division_code,
                           MAX(CASE WHEN c.account_code LIKE '401%' AND c.debit_credit = '4'
                                    THEN 1 ELSE 0 END) AS has_fee,
                           MAX(CASE WHEN c.account_code IN ('1030000','1410001')
                                    THEN 1 ELSE 0 END) AS has_cash
                    FROM (SELECT DISTINCT voucher_date, voucher_no, division_code
                          FROM dbo.a10_voucher_cache
                          WHERE account_code = '2570000'
                            AND management_no IN ({placeholders})) k
                    INNER JOIN dbo.a10_voucher_cache c
                       ON c.voucher_date = k.voucher_date AND c.voucher_no = k.voucher_no
                      AND c.division_code = k.division_code
                    GROUP BY k.voucher_date, k.voucher_no, k.division_code
                )
                , adv AS (
                    SELECT management_no AS doc_id,
                           -- 같은 전표에서 받고 바로 상계한 분(cr-dr)은 이미 정리된 돈이라 뺀다
                           -- (01-2512-1-0618 — 안 빼면 658만이 이중가산된다).
                           SUM(CASE WHEN cash = 0 AND ar_cnt = 0 AND cr_docs <= 1
                                         AND cr - dr > 0
                                    THEN cr - dr ELSE 0 END) AS uncounted,
                           SUM(CASE WHEN cash > 0 AND dr = 0 AND cr_docs <= 1
                                     AND ABS(fee_net) < 1 AND cash - cr > 0
                                    THEN CASE WHEN cash - cr <= vat THEN cash - cr ELSE vat END
                                    ELSE 0 END) AS vat_extra,
                           SUM(cr) AS credit_all,
                           SUM(dr) AS debit_all,
                           0.0 AS gasu_settled
                    FROM info GROUP BY management_no
                    UNION ALL
                    -- ③ 가수금→매출 직접 대체 — _settle_cte() 의 gasu 와 같은 규칙
                    -- (차변은 매출 대변 있고 현금 없는 전표만, 번호 달린 대변은 상계).
                    SELECT v.management_no, 0.0, 0.0, 0.0, 0.0,
                           SUM(CASE WHEN v.debit_credit = '3'
                                     AND w.has_fee = 1 AND w.has_cash = 0
                                    THEN v.amount
                                    WHEN v.debit_credit = '4' THEN -v.amount
                                    ELSE 0 END)
                    FROM dbo.a10_voucher_cache v
                    INNER JOIN gasu_v w
                       ON w.voucher_date = v.voucher_date AND w.voucher_no = v.voucher_no
                      AND w.division_code = v.division_code
                    WHERE v.account_code = '2570000'
                      AND v.management_no IN ({placeholders})
                    GROUP BY v.management_no
                    HAVING SUM(CASE WHEN v.debit_credit = '3'
                                     AND w.has_fee = 1 AND w.has_cash = 0
                                    THEN v.amount
                                    WHEN v.debit_credit = '4' THEN -v.amount
                                    ELSE 0 END) > 0
                )
                SELECT doc_id, SUM(uncounted) AS uncounted, SUM(vat_extra) AS vat_extra,
                       SUM(credit_all) AS credit_all, SUM(debit_all) AS debit_all,
                       SUM(gasu_settled) AS gasu_settled
                FROM adv GROUP BY doc_id
                """
            ),
            params,
        ).mappings().all()
        result.update({str(row["doc_id"]): dict(row) for row in rows})
    return result


def _variant_doc_invoice_guard(no_expr: str, total_expr: str) -> str:
    """변형 관리번호('원번호 + 꼬리표') 전표 몫의 계산서는 원 번호 매출에서 뺀다.

    사본발급비처럼 전표는 '01-2607-3-2290 사본발급' 별도 번호로 청구·정산이
    완결되는데 계산서만 원 번호로 달리는 건이 있다 — 원 감정서에 그 금액이
    허깨비 미수로 남는다(55,000 실측). 2026-09-01 사용자 결정: 사본발급류는
    감정 매출과 연동되면 안 된다. 변형 번호의 외상 발생액과 **금액까지 같을
    때만** 남의 몫으로 본다 — 우연 일치를 막는 이중 조건. 품목명으로는 못
    가른다(TAMS 대장에 품목이 안 적힌다).
    """
    return (
        "NOT EXISTS (SELECT 1 FROM dbo.a10_voucher_cache vv "
        f"WHERE vv.management_no LIKE {no_expr} + ' %' "
        "AND vv.account_code = '1080000' AND vv.debit_credit = '3' "
        f"AND vv.amount = ISNULL({total_expr}, 0))"
    )


def gasu_cte_blocks(voucher_target: str = "") -> str:
    """가수금(2570000)→매출 직접 대체 인식액 CTE (gasu_v, gasu 두 블록).

    입금현황 판정(_settle_cte)과 APWorks 입금 결과(payment_status)가 같은 식을
    쓰도록 한 곳에 둔다 — 식이 갈라지면 화면끼리 어긋난다 (2026-09-01,
    감정서 LIST 만 '일부입금'으로 남았던 사례).
    """
    return f"""gasu_v AS (
    -- 감정서번호 달린 가수금(2570000) 줄이 있는 전표의 성격 —
    -- 매출(401%) 대변이 있는지, 현금(1030000·1410001)이 있는지.
    SELECT k.voucher_date, k.voucher_no, k.division_code,
           MAX(CASE WHEN c.account_code LIKE '401%' AND c.debit_credit = '4'
                    THEN 1 ELSE 0 END) AS has_fee,
           MAX(CASE WHEN c.account_code IN ('1030000','1410001')
                    THEN 1 ELSE 0 END) AS has_cash
    FROM (SELECT DISTINCT v.voucher_date, v.voucher_no, v.division_code
          FROM dbo.a10_voucher_cache v
          {voucher_target}
          WHERE v.account_code = '2570000' AND v.management_no IS NOT NULL) k
    INNER JOIN dbo.a10_voucher_cache c
       ON c.voucher_date = k.voucher_date AND c.voucher_no = k.voucher_no
      AND c.division_code = k.division_code
    GROUP BY k.voucher_date, k.voucher_no, k.division_code
), gasu AS (
    -- 가수금을 매출로 직접 대체한 전표(차변) — 돈은 가수금 수령 때 이미
    -- 들어왔지만 그 수령 전표에는 감정서번호가 없어 received_amount 가 못 센다.
    -- 재무 관행이 연 34~159건이라 전표 정정 대신 여기서 수금으로 인식한다
    -- (01-2606-1-0388 실측 — 2,200,000 이 허깨비 미수로 남았다, 2026-09-01).
    -- 차변 인식 조건: 매출 대변이 같은 전표에 있고(순수 가수반제·착오반환 제외)
    -- 현금이 없어야 한다(있으면 received_amount 경로가 이미 센다).
    -- 감정서번호 달린 가수금 대변은 빼서 상계한다 — 수령 전표에 번호가 달려
    -- received 에 이미 잡힌 건을 또 세면 완납 182건이 허위 과입금이 된다(실측).
    SELECT v.management_no AS doc_id,
           SUM(CASE WHEN v.debit_credit = '3' AND w.has_fee = 1 AND w.has_cash = 0
                    THEN v.amount
                    WHEN v.debit_credit = '4' THEN -v.amount ELSE 0 END) AS amount
    FROM dbo.a10_voucher_cache v
    {voucher_target}
    INNER JOIN gasu_v w ON w.voucher_date = v.voucher_date AND w.voucher_no = v.voucher_no
                       AND w.division_code = v.division_code
    WHERE v.account_code = '2570000' AND v.management_no IS NOT NULL
    GROUP BY v.management_no
    HAVING SUM(CASE WHEN v.debit_credit = '3' AND w.has_fee = 1 AND w.has_cash = 0
                    THEN v.amount
                    WHEN v.debit_credit = '4' THEN -v.amount ELSE 0 END) > 0
)"""


# 합계 바에서 쓰는 정산액. _advance_settlement() 와 같은 규칙을 SQL 하나로 낸 것이다.
def _settle_cte(target_sql: "str | None" = None) -> str:
    """검색 대상을 먼저 좁힐 수 있는 선수금·계산서 합계 CTE.

    기존 쿼리는 하루치 몇 건을 조회해도 173만 전표와 20만 계산서를 모두 집계했다.
    상태/미수 조건처럼 CTE 결과가 필터 자체에 필요한 경우만 전체판을 사용한다.
    """
    target_head = f"WITH target_docs AS ({target_sql})," if target_sql else "WITH"
    voucher_target = (
        "INNER JOIN target_docs target ON target.doc_id = v.management_no"
        if target_sql else ""
    )
    tax_target = (
        "INNER JOIN target_docs target ON target.doc_id = tx.appraisal_no"
        if target_sql else ""
    )
    issued_target = (
        "INNER JOIN target_docs target ON target.doc_id = i.doc_id"
        if target_sql else ""
    )
    return f"""
{target_head} {settle_cte_blocks(voucher_target)}, tax_doc AS (
    SELECT m.doc_id, SUM(m.amount) AS tax_total, MAX(m.own_sales) AS own_sales FROM (
        -- 발급 원장 하나로 본다 (2026-09-09): MOA 팝빌 + 팝빌 동기화 + TAMS 이관분.
        -- 취소는 세금취소가 음수, 현금취소는 양수 취소금액이라 부호를 맞춘다.
        SELECT i.doc_id,
               SUM(CASE WHEN i.doc_type = N'현금취소' THEN -ABS(CAST(ISNULL(i.total, 0) AS float))
                        ELSE CAST(ISNULL(i.total, 0) AS float) END) AS amount, 0.0 AS own_sales
        FROM dbo.a10_issued_taxinvoice i
        {issued_target}
        WHERE i.doc_id IS NOT NULL AND i.doc_id <> '' AND i.is_test = 0 AND i.is_pool = 0
          AND {_variant_doc_invoice_guard("i.doc_id", "i.total")}
        GROUP BY i.doc_id
        UNION ALL
        SELECT v.management_no, 0.0,
               ROUND(SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END) * 1.1, 0)
        FROM dbo.a10_voucher_cache v
        INNER JOIN (SELECT DISTINCT i.doc_id FROM dbo.a10_issued_taxinvoice i
                    {issued_target}
                    WHERE i.doc_id IS NOT NULL AND i.doc_id <> '' AND i.is_test = 0 AND i.is_pool = 0) tt
                ON tt.doc_id = v.management_no
        WHERE v.account_code LIKE '401%'
        GROUP BY v.management_no
    ) m GROUP BY m.doc_id
)
"""


def settle_cte_blocks(voucher_target: str = "") -> str:
    """미포착 수금 보정 CTE 묶음 — 선수금(adv_v·vagg·ar·grp) + 가수금 대체 + settle.

    입금현황 판정(_settle_cte)과 APWorks 입금 결과(payment_status)가 같은 보정을
    쓰도록 한 곳에 둔다 (2026-09-01 — 무현금 선수금 정산이 payment_status 에만
    빠져 감정서 LIST 18건이 '일부입금'으로 어긋났던 사례).
    계산서 합계(tax_doc)는 여기 없다 — 판정 보정에 불필요하고 비싸다.
    """
    return f"""adv_v AS (
    SELECT DISTINCT v.voucher_date, v.voucher_no, v.division_code
    FROM dbo.a10_voucher_cache v
    {voucher_target}
    WHERE v.account_code = '2590000'
), vagg AS (
    SELECT c.voucher_date, c.voucher_no, c.division_code,
           SUM(CASE WHEN c.account_code IN ('1030000','1410001')
                    THEN CASE WHEN c.debit_credit = '3' THEN c.amount ELSE -c.amount END
                    ELSE 0 END) AS cash,
           SUM(CASE WHEN c.account_code LIKE '401%'
                    THEN CASE WHEN c.debit_credit = '4' THEN c.amount ELSE -c.amount END
                    ELSE 0 END) AS fee_net,
           SUM(CASE WHEN c.account_code = '2550000' AND c.debit_credit = '4'
                    THEN c.amount ELSE 0 END) AS vat,
           COUNT(DISTINCT CASE WHEN c.account_code = '2590000' AND c.debit_credit = '4'
                               THEN c.management_no END) AS cr_docs
    FROM dbo.a10_voucher_cache c
    INNER JOIN adv_v v ON v.voucher_date = c.voucher_date AND v.voucher_no = c.voucher_no
                      AND v.division_code = c.division_code
    GROUP BY c.voucher_date, c.voucher_no, c.division_code
), ar AS (
    SELECT DISTINCT v.voucher_date, v.voucher_no, v.division_code, v.management_no
    FROM dbo.a10_voucher_cache v
    {voucher_target}
    WHERE v.account_code = '1080000' AND v.debit_credit = '3'
), grp AS (
    SELECT v.management_no, v.voucher_date, v.voucher_no, v.division_code,
           SUM(CASE WHEN v.debit_credit = '4' THEN v.amount ELSE 0 END) AS cr,
           SUM(CASE WHEN v.debit_credit = '3' THEN v.amount ELSE 0 END) AS dr
    FROM dbo.a10_voucher_cache v
    {voucher_target}
    WHERE v.account_code = '2590000' AND v.management_no IS NOT NULL
    GROUP BY v.management_no, v.voucher_date, v.voucher_no, v.division_code
), {gasu_cte_blocks(voucher_target)}, settle AS (
    SELECT m.doc_id, SUM(m.uncounted) AS uncounted, SUM(m.vat_extra) AS vat_extra,
           SUM(m.credit_all) AS credit_all, SUM(m.debit_all) AS debit_all,
           SUM(m.gasu_settled) AS gasu_settled
    FROM (
        SELECT g.management_no AS doc_id,
               SUM(CASE WHEN a.cash = 0 AND r.management_no IS NULL AND a.cr_docs <= 1
                         AND g.cr - g.dr > 0
                        THEN g.cr - g.dr ELSE 0 END) AS uncounted,
               SUM(CASE WHEN a.cash > 0 AND g.dr = 0 AND a.cr_docs <= 1 AND ABS(a.fee_net) < 1
                         AND a.cash - g.cr > 0
                        THEN CASE WHEN a.cash - g.cr <= a.vat THEN a.cash - g.cr ELSE a.vat END
                        ELSE 0 END) AS vat_extra,
               SUM(g.cr) AS credit_all, SUM(g.dr) AS debit_all,
               0.0 AS gasu_settled
        FROM grp g
        INNER JOIN vagg a ON a.voucher_date = g.voucher_date AND a.voucher_no = g.voucher_no
                         AND a.division_code = g.division_code
        LEFT JOIN ar r ON r.voucher_date = g.voucher_date AND r.voucher_no = g.voucher_no
                      AND r.division_code = g.division_code AND r.management_no = g.management_no
        GROUP BY g.management_no
        UNION ALL
        SELECT doc_id, 0.0, 0.0, 0.0, 0.0, amount FROM gasu
    ) m GROUP BY m.doc_id
)"""


# 정산 결과 자체로 대상을 거르는 호출을 위한 기존 전체판 호환 상수.
_SETTLE_CTE = _settle_cte()

# 목록과 같은 식: 대변만 온 건도, 차변만 온 건도 받은 돈으로 본다.
# 목록과 같은 식: 대변만 온 것도 차변만 온 것도 잡되, 실제 상계액을 넘지 않는다.
_UNC = (
    "(CASE WHEN ISNULL(s.uncounted, 0) > "
    "ISNULL(s.debit_all, 0) - (ISNULL(s.credit_all, 0) - ISNULL(s.uncounted, 0)) "
    "THEN ISNULL(s.uncounted, 0) "
    "ELSE ISNULL(s.debit_all, 0) - (ISNULL(s.credit_all, 0) - ISNULL(s.uncounted, 0)) END)"
)
_SETTLED = (
    f"(CASE WHEN {_UNC} > ISNULL(s.debit_all, 0) THEN ISNULL(s.debit_all, 0) "
    f"WHEN {_UNC} > 0 THEN {_UNC} ELSE 0 END + ISNULL(s.vat_extra, 0))"
)


def settled_amount_expr(alias: str = "s") -> str:
    """미포착 선수금 정산액(_SETTLED)을 지정한 settle 별칭으로 낸다.

    payment_status 처럼 s 가 다른 테이블 별칭인 쿼리에서 쓴다 — 식 자체는
    _SETTLED 하나뿐이어야 화면끼리(입금현황 ↔ 감정서 LIST) 안 어긋난다.
    """
    return _SETTLED.replace("ISNULL(s.", f"ISNULL({alias}.")
# 기준액 = max(원장 매출총액, 세금계산서 발행액). 둘 다 0이면 전표 청구액.
# 목록(_tax_invoice_totals + invoice_total)과 같은 식이어야 합계가 맞는다.
# 계산서가 원장보다 클 때는 전표 청구액이 같은 금액을 가리킬 때만 채택한다
# (목록의 invoice_total 계산과 같은 식이어야 합계 바가 맞는다).
_TAX_OK = (
    "(ISNULL(t.tax_total, 0) > ISNULL(a.[매출총액], 0) "
    "AND ISNULL(b.billed_amount, 0) > 0 "
    "AND ABS(ISNULL(t.tax_total, 0) - b.billed_amount) <= "
    "CASE WHEN ISNULL(t.tax_total, 0) * 0.02 > 1000 "
    "THEN ISNULL(t.tax_total, 0) * 0.02 ELSE 1000 END "
    # 합산청구 계산서 제외 — 이 감정서 자신의 매출보다 크면 남의 몫이 섞인 것이다.
    "AND NOT (ISNULL(t.own_sales, 0) > 0 "
    "AND ISNULL(t.tax_total, 0) > ISNULL(t.own_sales, 0) * 1.02 + 1000))"
)
# 원장이 부가세를 한 번 더 붙인 건 (2026-08-07 01-2606-5-0095 에서 확인).
# 담당자가 수수료를 '부가세 포함' 금액으로 APW_Bill.SUSUSUM 에 넣으면 원장이
# 거기에 또 10%를 더해 TOTAL 을 만든다. 그러면 계산서·전표·입금이 모두 맞는데도
# 원장 매출총액만 부가세만큼 커서 그 차액이 영원히 미수로 남는다.
#
# 아래 네 가지가 동시에 맞을 때만 계산서 총액을 기준으로 바꾼다:
#   1) 계산서 총액 = 전표 청구액   — 청구가 계산서대로 잡혔다
#   2) 수금액 = 전표 청구액        — 그 청구를 전액 회수했다
#   3) 원장 매출총액 − 수금액 = 원장 부가세  — 남은 차이가 정확히 부가세다
#   4) 합산청구 계산서가 아니다    — 남의 몫이 섞이면 1)이 우연히 맞을 수 있다
# 3)이 핵심이다. 이 조건 없이 "계산서가 있으면 계산서 기준"으로 넓히면
# 4,628건이 바뀌고 정상 미수 146억이 통째로 사라진다(2026-08-07 실측).
# 네 조건을 다 걸면 7건·1,032만원만 바뀌고, 미수가 늘어나는 건은 없다.
_VAT_DOUBLED = (
    "(ISNULL(t.tax_total, 0) > 0 AND ISNULL(b.billed_amount, 0) > 0 "
    f"AND ABS(ISNULL(t.tax_total, 0) - b.billed_amount) <= {_ROUND_NOISE} "
    f"AND ABS(ISNULL(b.received_amount, 0) - b.billed_amount) <= {_ROUND_NOISE} "
    "AND ISNULL(a.[부가가치세], 0) > 0 "
    "AND ABS((ISNULL(a.[매출총액], 0) - ISNULL(b.received_amount, 0)) "
    f"- ISNULL(a.[부가가치세], 0)) <= {_ROUND_NOISE} "
    "AND NOT (ISNULL(t.own_sales, 0) > 0 "
    "AND ISNULL(t.tax_total, 0) > ISNULL(t.own_sales, 0) * 1.02 + 1000))"
)
_GROSS = (
    f"(CASE WHEN {_TAX_OK} THEN "
    "CASE WHEN ISNULL(b.billed_amount, 0) > ISNULL(t.tax_total, 0) "
    "THEN b.billed_amount ELSE ISNULL(t.tax_total, 0) END "
    f"WHEN {_VAT_DOUBLED} THEN ISNULL(t.tax_total, 0) "
    "WHEN ISNULL(a.[매출총액], 0) > 0 THEN a.[매출총액] "
    "WHEN ISNULL(b.billed_amount, 0) > 0 THEN b.billed_amount "
    "ELSE ISNULL(a.[청구금액], 0) END)"
)

# 실비 종결(ec = a10_expense_close 활성 행) 건은 처리 시점 수금액이 최종 매출이다
# (2026-09-01 사용자 결정 — 입금현황 우클릭 '실비 처리'). 원장 매출총액·계산서를
# 버리고 그 금액을 기준액으로 쓴다. 이후 돈이 더 들어오면 과입금으로 드러난다.
# ec 는 settle(s)·tax_doc(t)과 같은 자리에서 LEFT JOIN 된다 — _EXPENSE_CLOSE_JOIN.
_GROSS = (
    "(CASE WHEN ec.closed_amount IS NOT NULL THEN ec.closed_amount "
    f"ELSE {_GROSS} END)"
)
_EXPENSE_CLOSE_JOIN = (
    "LEFT JOIN dbo.a10_expense_close ec "
    "ON ec.doc_id = b.doc_id AND ec.released_at IS NULL "
)

# 수금액 = 입금액 + 미포착 정산(선수금) + 가수금→매출 대체분.
# 가수금 대체분(gasu_settled)은 기준액(_GROSS)까지만 채운다 — 잔여 미수를 지우는
# 보정이지 과입금의 근거가 아니다. 상한 없이 더하면 절사·몰아달기 legacy 전표에서
# 완납 11건·미수 7건이 허위 과입금으로 뒤집힌다(2026-09-01 실측). 선수금 캡
# (min(uncounted, debit_all))과 같은 정신이다.
_PAID_BASE = (
    "(ISNULL(b.received_amount, 0) + "
    f"CASE WHEN {_SETTLED} > 0 THEN {_SETTLED} ELSE 0 END)"
)
_GASU = "ISNULL(s.gasu_settled, 0)"
_PAID = (
    f"(CASE WHEN {_PAID_BASE} + {_GASU} <= {_GROSS} THEN {_PAID_BASE} + {_GASU} "
    f"WHEN {_PAID_BASE} <= {_GROSS} THEN {_GROSS} "
    f"ELSE {_PAID_BASE} END)"
)


def attach_payment_amounts(db: Session, items: "list[dict[str, Any]]") -> None:
    """감정서 목록에 입금현황과 같은 기준의 수금액·미수금·최근 입금일을 붙인다.

    (2026-09-01 감정서 LIST 개편) 화면끼리 어긋나지 않도록 _GROSS/_PAID 상수를
    스코프판 CTE 로 그대로 돌린다 — 선수금·가수금 보정, 계산서 기준액, 실비
    종결까지 전부 입금현황과 같은 값이 나온다. 요약 행이 없는 감정서(전표
    0건)는 수금 0, 미수 = 원장 매출총액(gross_total)이다.
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return
    source = _source_view()
    found: dict[str, Any] = {}
    for offset in range(0, len(doc_ids), _SETTLE_DOC_CHUNK):
        chunk = doc_ids[offset : offset + _SETTLE_DOC_CHUNK]
        binds = [f"pay_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        values = ",".join(f"(CAST(:{name} AS VARCHAR(500)))" for name in binds)
        cte = _settle_cte(
            f"SELECT doc_id FROM (VALUES {values}) AS target_list(doc_id)"
        )
        placeholders = ",".join(f"CAST(:{name} AS VARCHAR(50))" for name in binds)
        # CTE(settle·tax_doc)를 본 SELECT 에 바로 조인하면 옵티마이저가 CTE 를 인라인해
        # _GROSS/_PAID 의 거대한 CASE 안 참조마다 다시 계산한다 — 30건에 1.2~1.5초
        # (2026-09-07 실측: tax_doc 단독 0.15초, 조인 끊으면 0.06초). 결과를 테이블
        # 변수에 먼저 담고 조인하면 0.23초, 값은 동일. SET NOCOUNT ON 이 있어야
        # INSERT 의 건수 응답이 앞에 끼지 않아 SELECT 결과가 첫 결과집합으로 온다.
        batch = (
            "SET NOCOUNT ON; "
            "DECLARE @settle TABLE (doc_id varchar(50), uncounted float, vat_extra float, "
            "credit_all float, debit_all float, gasu_settled float); "
            "DECLARE @tax_doc TABLE (doc_id varchar(50), tax_total float, own_sales float); "
            + cte
            + "INSERT INTO @settle (doc_id, uncounted, vat_extra, credit_all, debit_all, gasu_settled) "
            "SELECT doc_id, uncounted, vat_extra, credit_all, debit_all, gasu_settled FROM settle; "
            + cte
            + "INSERT INTO @tax_doc (doc_id, tax_total, own_sales) "
            "SELECT doc_id, tax_total, own_sales FROM tax_doc; "
            + f"SELECT b.doc_id, {_GROSS} AS gross, {_PAID} AS paid, "
            "b.last_received_date "
            f"FROM dbo.a10_receivable_summary b "
            f"LEFT JOIN {source} a ON a.DocID = b.doc_id "
            "LEFT JOIN @settle s ON s.doc_id = b.doc_id "
            "LEFT JOIN @tax_doc t ON t.doc_id = b.doc_id "
            + _EXPENSE_CLOSE_JOIN
            + f"WHERE b.doc_id IN ({placeholders})"
        )
        rows = db.execute(text(batch), params).mappings().all()
        found.update({str(row["doc_id"]): row for row in rows})
    for item in items:
        row = found.get(str(item["doc_id"]))
        if row is not None:
            paid = float(row["paid"] or 0)
            shortfall = float(row["gross"] or 0) - paid
            item["received_total"] = paid
            item["last_received_date"] = (
                row["last_received_date"].isoformat()
                if row["last_received_date"] else None
            )
            # 과입금이면 미수가 음수로 보인다 (2026-09-11 사용자: 90원 더 들어온 건은 미수 -90).
            item["outstanding_amount"] = (
                shortfall if abs(shortfall) > _ROUND_NOISE else 0.0
            )
        else:
            gross = float(item.get("gross_total") or 0)
            item["received_total"] = 0.0
            item["last_received_date"] = None
            item["outstanding_amount"] = gross if gross > _ROUND_NOISE else 0.0


def _expense_closes(
    db: Session, items: "list[dict[str, Any]]"
) -> "dict[str, dict[str, Any]]":
    """실비 종결 활성 표시 — 기준액 덮어쓰기와 화면 배지용 (처리자 이름 포함).

    _GROSS 의 ec 조인과 같은 행(released_at IS NULL)만 읽어야 SQL 합계와
    파이썬 목록이 어긋나지 않는다.
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return {}
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(doc_ids), _DOC_CHUNK):
        chunk = doc_ids[offset : offset + _DOC_CHUNK]
        binds = [f"exc_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        placeholders = ",".join(f"CAST(:{name} AS VARCHAR(50))" for name in binds)
        rows = db.execute(
            text(
                f"SELECT ec.doc_id, ec.closed_amount, ec.closed_at, "
                f"RTRIM(ISNULL(u.EMP, '')) AS closed_by_name "
                f"FROM dbo.a10_expense_close ec "
                f"LEFT JOIN [{database}].dbo.TMWCMN_USR_BAC_INFO u "
                f"  ON u.USR_SEQ = ec.closed_by "
                f"WHERE ec.released_at IS NULL AND ec.doc_id IN ({placeholders})"
            ),
            params,
        ).mappings().all()
        result.update({str(row["doc_id"]): dict(row) for row in rows})
    return result


# 세금계산서는 감정서번호를 두 번(TAMS 캐시 + MOA 발급분) 쓰므로 더 작게 끊는다.
_TAX_DOC_CHUNK = 400


def _tax_invoice_totals(
    db: Session, items: list[dict[str, Any]]
) -> dict[str, dict[str, float]]:
    """감정서별 세금계산서 발행액과 그 감정서 자신의 매출액.

    계산서는 거래처에 실제로 나간 청구서다. 취소·수정분은 음수로 저장돼 상쇄된다.
    원장 [매출총액]이 실제 청구보다 작게 잡힌 건이 있어(컨설팅·정비사업에서
    매출총액이 0인 채 수천만원짜리 계산서가 나간다) 계산서를 기준으로 쓸 수 있어야 한다.

    다만 여러 감정서를 묶어 한 장으로 끊는 '합산청구' 계산서가 있고, 그 전액이
    대표 감정서 하나에 달린다(01-2603-5-0042 는 전표 적요에 '수수료 합산청구'라고
    적혀 있다). 그래서 그 감정서 자신의 매출 전표(401계열)×1.1 을 같이 뽑아,
    계산서가 자기 매출보다 크면 합산분으로 보고 안 쓴다.
      롯데물산 01-2512-5-0188  계산서 71,830,000 vs 자기 매출 11,000,000 → 합산
      서울금남 01-2601-3-0084  계산서 45,157,200 vs 자기 매출 45,157,200 → 채택

    원천은 발급 원장 하나다(2026-09-09) — TAMS 이관분·팝빌 동기화분·MOA 발급분이 한 테이블에
    있고 중복은 이관·동기화 때 걸렀다. 취소(세금취소)는 음수 행이라 SUM 이 곧 순액.
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return {}

    result: dict[str, float] = {}
    for offset in range(0, len(doc_ids), _TAX_DOC_CHUNK):
        chunk = doc_ids[offset : offset + _TAX_DOC_CHUNK]
        binds = [f"tax_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        placeholders = ",".join(":" + name for name in binds)
        rows = db.execute(
            text(
                f"""
                SELECT m.doc_id,
                       SUM(m.amount) AS tax_total,
                       MAX(m.own_sales) AS own_sales,
                       SUM(m.slips) AS slips
                FROM (
                    -- 발급 원장 하나로 본다 (2026-09-09) — TAMS 캐시 UNION·중복 제거 없음
                    SELECT i.doc_id,
                           SUM(CAST(ISNULL(i.total, 0) AS float)) AS amount,
                           0.0 AS own_sales,
                           COUNT(*) AS slips
                    FROM dbo.a10_issued_taxinvoice i
                    WHERE i.doc_id IN ({placeholders}) AND i.is_test = 0 AND i.is_pool = 0
                      AND i.doc_type IN (N'세금계산서', N'세금취소', N'세금수정')
                      AND {_variant_doc_invoice_guard("i.doc_id", "i.total")}
                    GROUP BY i.doc_id
                    UNION ALL
                    -- 이 감정서 자신의 매출 (401계열 순액 × 1.1)
                    SELECT v.management_no, 0.0,
                           ROUND(SUM(CASE WHEN v.debit_credit = '4'
                                          THEN v.amount ELSE -v.amount END) * 1.1, 0),
                           0
                    FROM dbo.a10_voucher_cache v
                    WHERE v.account_code LIKE '401%'
                      AND v.management_no IN ({placeholders})
                    GROUP BY v.management_no
                ) m
                GROUP BY m.doc_id
                """
            ),
            params,
        ).mappings().all()
        result.update({
            str(row["doc_id"]): {
                "tax_total": float(row["tax_total"] or 0),
                "own_sales": float(row["own_sales"] or 0),
                # 장수까지 세는 이유는 아래 tax_issued 설명 참고 — 끊었다 취소해
                # 순액이 0 이 된 건을 '발행'이라 말하면 안 되기 때문이다.
                "slips": int(row["slips"] or 0),
            }
            for row in rows
        })
    return result


def _cash_receipt_totals(
    db: Session, items: list[dict[str, Any]]
) -> dict[str, dict[str, float]]:
    """감정서별 현금영수증 순액·장수 — 발급 원장(a10_issued_taxinvoice) 하나로 (2026-09-09).
    세금계산서 발행여부 열과 짝이 되는 열이다 — 재무팀은 증빙이 계산서로 나갔는지
    현금영수증으로 나갔는지 둘 다 봐야 한다(관공서·보증공사 건은 현금영수증이 많다).
    현금취소 행은 양수 취소금액(MOA·TAMS 이관·팝빌 동기화 모두 같은 규칙)이라 빼고 접는다.
    장수는 0원이 아닌 발행만 센다 (회사 매출실적 화면과 같은 규칙).
    """
    doc_ids = sorted({str(item["doc_id"]) for item in items if item.get("doc_id")})
    if not doc_ids:
        return {}

    result: dict[str, dict[str, float]] = {}
    for offset in range(0, len(doc_ids), _TAX_DOC_CHUNK):
        chunk = doc_ids[offset : offset + _TAX_DOC_CHUNK]
        binds = [f"cash_doc_{index}" for index in range(len(chunk))]
        params: dict[str, Any] = {
            name: chunk[index] for index, name in enumerate(binds)
        }
        placeholders = ",".join(":" + name for name in binds)
        rows = db.execute(
            text(
                f"""
                SELECT i.doc_id,
                       SUM(CASE WHEN i.doc_type = N'현금취소'
                                THEN -ABS(CAST(ISNULL(i.total, 0) AS float))
                                ELSE CAST(ISNULL(i.total, 0) AS float) END
                           ) AS cash_total,
                       SUM(CASE WHEN i.doc_type = N'현금취소' OR ISNULL(i.total, 0) = 0
                                THEN 0 ELSE 1 END) AS slips
                FROM dbo.a10_issued_taxinvoice i
                WHERE i.doc_id IN ({placeholders}) AND i.is_test = 0
                  AND i.doc_type IN (N'현금영수증', N'현금취소')
                GROUP BY i.doc_id
                """
            ),
            params,
        ).mappings().all()
        result.update({
            str(row["doc_id"]).strip(): {
                "cash_total": float(row["cash_total"] or 0),
                "slips": int(row["slips"] or 0),
            }
            for row in rows
        })
    return result


def card_sales_sql(placeholders: str) -> str:
    """카드로 결제된 매출 감정서 — 세무구분 17(카드매출)은 세금계산서를 안 끊는다 (2026-09-10 재무팀).

    세무구분은 매출(401) 줄이 아니라 같은 전표의 부가세예수금(2550000) 줄 raw_json.taxFg 에 있고,
    그 줄엔 관리번호가 없다(적요에만 감정서번호). 그래서 같은 전표 안에서 적요로 짝을 맞추고,
    부가세 줄이 하나뿐인 전표는 그 줄로 본다. 실측 01-2608-3-2564: 비씨카드 입금 3,619,000.
    """
    return f"""
        SELECT DISTINCT s.management_no AS doc_id
        FROM dbo.a10_voucher_cache s
        INNER JOIN dbo.a10_voucher_cache t
                ON t.voucher_date = s.voucher_date AND t.voucher_no = s.voucher_no
               AND t.division_code = s.division_code AND t.account_code = '2550000'
        WHERE s.account_code LIKE '401%' AND s.management_no IN ({placeholders})
          AND JSON_VALUE(t.raw_json, '$.taxFg') = '17'
          AND (t.remark LIKE '%' + s.management_no + '%'
               OR NOT EXISTS (SELECT 1 FROM dbo.a10_voucher_cache u
                              WHERE u.voucher_date = s.voucher_date AND u.voucher_no = s.voucher_no
                                AND u.division_code = s.division_code AND u.account_code = '2550000'
                                AND u.line_no <> t.line_no))
    """


def card_sales_docs(db: Session, doc_ids: "list[str]") -> "set[str]":
    """카드매출(세무구분 17) 감정서 집합 — 일괄발급 제외·발행 칸 '카드' 표시가 같이 쓴다."""
    ids = sorted({str(d).strip() for d in doc_ids if d})
    found: "set[str]" = set()
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        placeholders = ",".join(f"CAST(:cs_{i} AS VARCHAR(100))" for i in range(len(chunk)))
        params = {f"cs_{i}": v for i, v in enumerate(chunk)}
        found.update(str(r[0]).strip() for r in db.execute(text(card_sales_sql(placeholders)), params).all())
    return found


def attach_proof_issued(db: Session, items: list[dict[str, Any]]) -> None:
    """세금계산서/현금영수증 발행 여부를 항목에 붙인다 — 입금현황·미수금현황·감정서 LIST 공통.

    값은 '발행' 하나뿐이고 순액이 양수일 때만이다(끊었다 전액 취소한 건은 빈칸).
    어떤 증빙이 몇 건·얼마인지는 *_slips·*_amount 로 같이 내려 화면 툴팁이 쓴다.
    증빙이 하나도 없는 카드매출(세무구분 17) 건은 '카드'로 표시한다 — 계산서가 필요 없는
    건이 '미발행'으로 보이지 않게 (2026-09-10 사용자 요청).
    """
    tax_totals = _tax_invoice_totals(db, items)
    cash_totals = _cash_receipt_totals(db, items)
    card_docs = card_sales_docs(db, [str(item["doc_id"]) for item in items])
    for item in items:
        tax_row = tax_totals.get(str(item["doc_id"]), {})
        tax_amount = float(tax_row.get("tax_total") or 0)
        item["tax_issued"] = "발행" if tax_amount > 0 else ""
        item["tax_issued_amount"] = tax_amount
        item["tax_issued_slips"] = int(tax_row.get("slips") or 0)
        cash_row = cash_totals.get(str(item["doc_id"]), {})
        cash_amount = float(cash_row.get("cash_total") or 0)
        item["cash_issued"] = "발행" if cash_amount > 0 else ""
        item["cash_issued_amount"] = cash_amount
        item["cash_issued_slips"] = int(cash_row.get("slips") or 0)
        item["card_sales"] = str(item["doc_id"]).strip() in card_docs
        item["proof_issued"] = "발행" if item["tax_issued"] or item["cash_issued"] else ("카드" if item["card_sales"] else "")
        # 발행 금액 합계 — 감정서 LIST 열·엑셀이 쓴다 (2026-09-03). 순액이라 취소분은 빠진다.
        item["proof_issued_amount"] = tax_amount + cash_amount


# 국민 약식수수료 — 400* 의뢰번호 입금은 감정서번호 접두사(01_ 등)에 안 걸려 입금현황에
# 아예 안 보였다. 매출실적처럼 한 줄로 묶되 입금현황은 부가세 포함 금액이다 (2026-08-27 사용자 요청).
KB_SIMPLE_DOC_ID = "국민 약식수수료"
KB_SIMPLE_PURPOSE = "가격자문"


def kb_simple_row_wanted(
    *, mode: str, page: int, doc_id: Any = None, customer_name: Any = None, manager: Any = None,
    scope_person: Any = None, pay_statuses: Any = None, bill_from: Any = None, bill_to: Any = None,
    outstanding_from: Any = None, outstanding_to: Any = None,
) -> bool:
    """묶음 행은 입금현황 첫 페이지에, 감정서를 고르는 조건이 없을 때만 — 조건이 있으면 400* 는 대상이 아니다."""
    return (
        mode == "received" and page == 1
        and not (doc_id or customer_name or manager or scope_person or pay_statuses)
        and bill_from is None and bill_to is None
        and outstanding_from is None and outstanding_to is None
    )


def kb_simple_sql(*, date_from: Any, date_to: Any, division_code: "str | None") -> tuple[str, dict[str, Any]]:
    """전표 캐시의 400* 매출 줄을 기간(전표일)·회계단위로 합치는 SQL.

    처음(2026-08-27)에는 요약 캐시의 '최근 입금일이 기간 안'인 번호의 누적 입금으로
    만들었는데, 발급수수료→본수수료처럼 한 번호에 입금이 두 번 오면 과거분까지
    끼어 기간 입금액이 부풀었다(8/27 실측 906,400원 vs 재무팀 집계 897,600원).
    기간 안 전표에 실제 잡힌 금액으로 바꾼다(2026-08-28 사용자 결정) — 약식은
    전표가 곧 입금이다. 부가세예수금 줄에는 400번호가 안 붙으므로(실측) 매출
    줄만 모으고 부가세는 ×1.1 로 되돌린다(배치가 1.1배 나눠떨어짐을 강제한다).
    """
    conditions = ["v.management_no LIKE '400%'", "v.account_code LIKE '401%'"]
    params: dict[str, Any] = {}
    if date_from:
        conditions.append("v.voucher_date >= :kb_date_from")
        params["kb_date_from"] = date_from
    if date_to:
        conditions.append("v.voucher_date < DATEADD(day, 1, :kb_date_to)")
        params["kb_date_to"] = date_to
    if division_code:
        conditions.append("v.division_code = :kb_division")
        params["kb_division"] = division_code
    on_date_to = "v.voucher_date = :kb_date_to" if date_to else "1 = 0"
    # 취소·정정(차변)은 뺀 순액 — 매출실적의 400* 줄과 같은 셈법이다.
    signed = "CASE WHEN v.debit_credit = '4' THEN v.amount ELSE -v.amount END"
    sql = f"""
        SELECT COUNT(DISTINCT v.management_no) AS docs,
               COALESCE(SUM({signed}), 0) AS sales,
               COALESCE(SUM(CASE WHEN {on_date_to} THEN {signed} ELSE 0 END), 0) AS daily_sales,
               COUNT(DISTINCT CASE WHEN {on_date_to} THEN v.management_no END) AS daily_docs,
               MAX(v.voucher_date) AS last_received_date
        FROM dbo.a10_voucher_cache v
        WHERE {' AND '.join(conditions)}
    """
    return sql, params


def kb_simple_fee_row(
    db: Session, *, date_from: Any, date_to: Any, division_code: "str | None"
) -> "dict[str, Any] | None":
    """입금현황 한 줄 모양의 '국민 약식수수료' 묶음 — 해당 기간에 입금이 없으면 None."""
    sql, params = kb_simple_sql(date_from=date_from, date_to=date_to, division_code=division_code)
    row = db.execute(text(sql), params).mappings().one()
    docs = int(row["docs"] or 0)
    if docs == 0:
        return None
    sales = float(row["sales"] or 0)                 # 공급가액 (매출실적의 금액)
    received = float(round(sales * 1.1))             # 부가세 포함 = 그 기간에 실제 입금된 금액
    billed = received                                # 약식은 입금이 곧 청구 — 미수 개념이 없다
    daily = float(round(float(row["daily_sales"] or 0) * 1.1))
    return {
        "doc_id": KB_SIMPLE_DOC_ID, "kb_simple": True, "kb_simple_docs": docs,
        "purpose": KB_SIMPLE_PURPOSE, "category": None, "customer_name": None, "address": None,
        "manager": None, "charge": None, "receipt_date": None, "send_date": None,
        "progress_status": None, "last_received_date": row["last_received_date"], "receipt_count": docs,
        "appraisal_amount": None, "base_fee": sales, "travel_expense": 0.0,
        "survey_fee": 0.0, "document_fee": 0.0, "land_survey_fee": 0.0,
        "special_service_fee": 0.0, "other_expense": 0.0, "appraisal_cost": 0.0,
        "sales_amount": sales, "vat_amount": billed - sales,
        "assessed_billed": billed, "gross_total": billed, "invoice_total": billed,
        "billed_amount": billed, "voucher_billed_amount": billed, "received_amount": received,
        "advance_received": 0.0, "advance_offset": 0.0, "advance_fully_offset": False,
        "advance_amount": 0.0, "suspense_amount": 0.0, "settled_advance": 0.0,
        "existing_advance_amount": 0.0, "existing_received_amount": received - daily,
        "daily_received_amount": daily, "daily_advance_amount": 0.0,
        "daily_billed_amount": daily, "daily_docs": int(row["daily_docs"] or 0),
        "outstanding_amount": 0.0, "overpaid_amount": 0.0,
        "tax_issued": "", "tax_issued_amount": 0.0, "tax_issued_slips": 0,
        "cash_issued": "", "cash_issued_amount": 0.0, "cash_issued_slips": 0, "proof_issued": "",
    }


def _daily_total_sql(from_sql: str, settle_cte: str = "") -> str:
    """검색 조건에 걸린 감정서 중 '입금 종료일 당일' 입금분만 합산하는 SQL.

    입금액·선수금은 그날 전표에서, 매출총액·미수금은 그 감정서들의 청구서 기준으로
    낸다(목록의 열 구성과 같은 기준). 입금 판정 규칙은 _latest_day_amounts()와 같다
    — 같은 전표에 현금 계정이 움직인 건만 입금으로 보고, 외상매출금 대변이 없으면
    매출에 부가세를 얹어 본다(_direct_deposit_total_sql).
    """
    # 합계 바 첫 줄과 같은 기준을 쓴다 — 매출총액은 _GROSS, 수금액은 _PAID.
    # settle_cte 가 오면 그 CTE 뒤에 target 을 이어 붙인다(WITH 를 두 번 못 쓴다).
    head = f"{settle_cte}, target AS (" if settle_cte else "WITH target AS ("
    return f"""
        {head}
            SELECT b.doc_id,
                   CAST({_GROSS} AS float) AS invoice_total,
                   CAST({_PAID} AS float) AS received_total
            {from_sql} AND b.last_received_date = :sum_date
        ), tagged AS (
            SELECT v.management_no AS doc_id, v.voucher_date, v.voucher_no, v.division_code,
                   SUM(CASE WHEN v.account_code = '1080000' AND v.debit_credit = '4'
                            THEN v.amount ELSE 0 END) AS ar_credit,
                   SUM(CASE WHEN v.account_code LIKE '401%' AND v.debit_credit = '4' THEN v.amount
                            WHEN v.account_code LIKE '401%' AND v.debit_credit = '3' THEN -v.amount
                            ELSE 0 END) AS fee_credit,
                   SUM(CASE WHEN v.account_code = '2590000' AND v.debit_credit = '4' THEN v.amount
                            WHEN v.account_code = '2590000' AND v.debit_credit = '3' THEN -v.amount
                            ELSE 0 END) AS advance_net,
                   SUM(CASE WHEN v.account_code = '2570000' AND v.debit_credit = '4' THEN v.amount
                            WHEN v.account_code = '2570000' AND v.debit_credit = '3' THEN -v.amount
                            ELSE 0 END) AS suspense_net
            FROM dbo.a10_voucher_cache v
            INNER JOIN target t ON t.doc_id = v.management_no
            WHERE v.voucher_date = :sum_date
              AND (v.account_code IN ('1080000','2590000','2570000')
                   OR v.account_code LIKE '401%')
            GROUP BY v.management_no, v.voucher_date, v.voucher_no, v.division_code
        ), cash AS (
            SELECT c.voucher_date, c.voucher_no, c.division_code,
                   SUM(CASE WHEN c.account_code = '1030000' AND c.debit_credit = '3' THEN c.amount
                            WHEN c.account_code = '1030000' AND c.debit_credit = '4' THEN -c.amount
                            ELSE 0 END) AS bank_net,
                   SUM(CASE WHEN c.account_code = '1410001' AND c.debit_credit = '3' THEN c.amount
                            WHEN c.account_code = '1410001' AND c.debit_credit = '4' THEN -c.amount
                            ELSE 0 END) AS hq_net,
                   SUM(CASE WHEN c.account_code = '2550000' AND c.debit_credit = '4' THEN c.amount
                            WHEN c.account_code = '2550000' AND c.debit_credit = '3' THEN -c.amount
                            ELSE 0 END) AS vat_net,
                   SUM(CASE WHEN c.account_code LIKE '401%' AND c.debit_credit = '4' THEN c.amount
                            WHEN c.account_code LIKE '401%' AND c.debit_credit = '3' THEN -c.amount
                            ELSE 0 END) AS fee_total
            FROM dbo.a10_voucher_cache c
            INNER JOIN (SELECT DISTINCT voucher_date, voucher_no, division_code FROM tagged) t
              ON t.voucher_date = c.voucher_date AND t.voucher_no = c.voucher_no
             AND t.division_code = c.division_code
            WHERE c.account_code IN ('1030000','1410001','2550000')
               OR c.account_code LIKE '401%'
            GROUP BY c.voucher_date, c.voucher_no, c.division_code
        ), events AS (
            SELECT t.doc_id, t.advance_net,
                   CASE WHEN (COALESCE(c.bank_net, 0) + COALESCE(c.hq_net, 0)) <> 0
                        THEN t.ar_credit + t.advance_net + t.suspense_net
                           + CASE WHEN t.ar_credit = 0
                                  THEN {_direct_deposit_total_sql('t.fee_credit', 'c.vat_net', 'c.fee_total')} ELSE 0 END
                        ELSE 0 END AS received_delta
            FROM tagged t
            LEFT JOIN cash c ON c.voucher_date = t.voucher_date
                            AND c.voucher_no = t.voucher_no
                            AND c.division_code = t.division_code
        ), money AS (
            SELECT COALESCE(SUM(received_delta), 0) AS daily_received,
                   COALESCE(SUM(advance_net), 0) AS daily_advance
            FROM events
        ), base AS (
            SELECT COUNT(*) AS daily_docs,
                   COALESCE(SUM(invoice_total), 0) AS daily_invoice,
                   COALESCE(SUM(CASE WHEN invoice_total - received_total > 0
                                     THEN invoice_total - received_total
                                     ELSE 0 END), 0) AS daily_outstanding
            FROM target
        )
        SELECT m.daily_received, m.daily_advance,
               b.daily_docs, b.daily_invoice, b.daily_outstanding
        FROM money m CROSS JOIN base b
    """


def management_no_filter(
    prefixes: list[str], column: str = "management_no"
) -> tuple[str, dict[str, Any]]:
    """감정서번호 접두사 목록을 관리번호 필터 SQL과 바인드 파라미터로 변환한다.

    접두사 뒤에 하이픈을 요구하지 않되('01%'), 접두사만 있는 행은 뺀다('01_%').
    재무팀이 잔금·분할 건에 쓰는 '012603-1-0109-1' 같은 번호는 앞 하이픈이 없어
    통째로 걸러졌고, 그 화면(입금 현황·미수금·입금발송내역·챗봇)에서 다 안 보였다
    (2026-08-20 제보). 실측: 1,098건 · 입금 102.3억 · 미수 5.69억이 빠져 있었다.

    다만 관리번호가 접두사 두 자리뿐인 행 6개(01·02·04·10·11·13)는 감정서가
    아니라 잘못 들어간 값이다 — '01' 한 행에만 입금 36.8억이 붙어 있어 합계를
    흔든다. 뒤에 한 글자라도 더 있어야 통과시킨다 (2026-08-20 사용자 지시).

    pyodbc는 문자열을 NVARCHAR로 바인드하는데 대상 컬럼은 varchar(500)라서,
    캐스팅 없이 비교하면 전 행 형변환이 일어나 접두사 검색이 수 초씩 걸린다.
    """
    if not prefixes:
        raise ValueError("접두사 목록이 비어 있습니다.")
    if len(prefixes) == 1:
        return (
            f"{column} LIKE CAST(:docid_prefix AS varchar(500))",
            {"docid_prefix": f"{prefixes[0]}_%"},
        )
    names = [f"docid_prefix_{index}" for index in range(len(prefixes))]
    or_clauses = " OR ".join(
        f"{column} LIKE CAST(:{name} AS varchar(500))" for name in names
    )
    params = {name: f"{prefixes[index]}_%" for index, name in enumerate(names)}
    return f"({or_clauses})", params


def receivable_status_cte(prefix_condition_sql: str) -> str:
    """감정서별 청구·입금·미수·과입금 상태를 계산하는 공통 CTE.

    prefix_condition_sql은 management_no_filter()가 만든 관리번호 접두사 조건.
    """
    return f"""
        WITH tagged_vouchers AS (
            SELECT management_no AS doc_id, voucher_date, voucher_no, division_code,
                   SUM(CASE WHEN account_code = '1080000' AND debit_credit = '3' THEN amount ELSE 0 END) AS ar_debit,
                   SUM(CASE WHEN account_code = '1080000' AND debit_credit = '4' THEN amount ELSE 0 END) AS ar_credit,
                   -- 수수료 매출은 401 계열 전체: 감정수수료(4010001) 외에 기타수수료(4010002,
                   -- 현금영수증 자진발급 등 소액 직접매출)·수수료할인(4010003, 음수)·용역(4010004).
                   -- 4010001만 보면 기타수수료로만 계상된 감정서가 입금현황에서 아예 사라진다
                   -- (2026-07-27 사용자 발견: 01-2607-6-0445).
                   SUM(CASE WHEN account_code LIKE '401%' AND debit_credit = '4' THEN amount
                            WHEN account_code LIKE '401%' AND debit_credit = '3' THEN -amount ELSE 0 END) AS fee_credit,
                   SUM(CASE WHEN account_code = '2590000' AND debit_credit = '4' THEN amount
                            WHEN account_code = '2590000' AND debit_credit = '3' THEN -amount ELSE 0 END) AS advance_net,
                   SUM(CASE WHEN account_code = '2570000' AND debit_credit = '4' THEN amount
                            WHEN account_code = '2570000' AND debit_credit = '3' THEN -amount ELSE 0 END) AS suspense_net
            FROM dbo.a10_voucher_cache
            WHERE (account_code IN ('1080000','2590000','2570000') OR account_code LIKE '401%')
              AND {prefix_condition_sql}
            GROUP BY management_no, voucher_date, voucher_no, division_code
        ), voucher_cash AS (
            SELECT voucher_date, voucher_no, division_code,
                   SUM(CASE WHEN account_code = '1030000' AND debit_credit = '3' THEN amount
                            WHEN account_code = '1030000' AND debit_credit = '4' THEN -amount ELSE 0 END) AS bank_net,
                   SUM(CASE WHEN account_code = '1410001' AND debit_credit = '3' THEN amount
                            WHEN account_code = '1410001' AND debit_credit = '4' THEN -amount ELSE 0 END) AS hq_net
            FROM dbo.a10_voucher_cache
            WHERE account_code IN ('1030000','1410001')
            GROUP BY voucher_date, voucher_no, division_code
        ), voucher_vat AS (
            -- 직접입금 전표의 부가세예수금 실값(관리번호가 없어 전표 단위로만 집계)과
            -- 매출 대변 합계 — 대상 감정서가 걸린 전표만 읽어 전량 스캔을 피한다.
            SELECT c.voucher_date, c.voucher_no, c.division_code,
                   SUM(CASE WHEN c.account_code = '2550000' AND c.debit_credit = '4' THEN c.amount
                            WHEN c.account_code = '2550000' AND c.debit_credit = '3' THEN -c.amount
                            ELSE 0 END) AS vat_net,
                   SUM(CASE WHEN c.account_code LIKE '401%' AND c.debit_credit = '4' THEN c.amount
                            WHEN c.account_code LIKE '401%' AND c.debit_credit = '3' THEN -c.amount
                            ELSE 0 END) AS fee_total
            FROM dbo.a10_voucher_cache c
            INNER JOIN (SELECT DISTINCT voucher_date, voucher_no, division_code FROM tagged_vouchers) t
              ON t.voucher_date = c.voucher_date AND t.voucher_no = c.voucher_no
             AND t.division_code = c.division_code
            WHERE c.account_code = '2550000' OR c.account_code LIKE '401%'
            GROUP BY c.voucher_date, c.voucher_no, c.division_code
        ), voucher_misc AS (
            -- 입금 전표에 같이 적힌 잡이익(9300000 대변)은 그 감정서의 초과 입금이다
            -- (2026-09-11 사용자 결정 — 01-2608-3-2642 잔금이 90원 더 들어와 재무팀이 잡이익으로
            -- 넘겼는데 화면은 완납이었다). 수금은 매출·부가세 대변으로 세므로 잡이익으로 간 돈은
            -- 그냥 두면 어느 감정서에도 안 붙는다. 감정서가 하나뿐인 전표만 — 여러 건을 몰아
            -- 받은 전표(2026-01-13 #178, 2건에 500원)는 누구 몫인지 알 수 없어 안 나눈다.
            -- 적요도 본다 — 같은 전표에 전화요금 단수차액(2·6·9원)을 잡이익으로 얹은 건이 있어
            -- (01-2601-3-0025 등 3건) 감정서번호가 적혔거나 잡이익·초과·절사로 적은 줄만 인정한다.
            SELECT m.voucher_date, m.voucher_no, m.division_code,
                   SUM(CASE WHEN m.debit_credit = '4' THEN m.amount ELSE -m.amount END) AS misc_net
            FROM dbo.a10_voucher_cache m
            INNER JOIN (SELECT voucher_date, voucher_no, division_code, MIN(doc_id) AS doc_id
                        FROM tagged_vouchers
                        GROUP BY voucher_date, voucher_no, division_code
                        HAVING COUNT(DISTINCT doc_id) = 1) t
              ON t.voucher_date = m.voucher_date AND t.voucher_no = m.voucher_no
             AND t.division_code = m.division_code
            WHERE m.account_code = '9300000'
              AND (m.remark LIKE '%' + t.doc_id + '%' OR m.remark LIKE '%잡이익%'
                   OR m.remark LIKE '%초과%' OR m.remark LIKE '%절사%')
            GROUP BY m.voucher_date, m.voucher_no, m.division_code
        ), voucher_events_raw AS (
            -- 지사 감정료는 본사가 수금한다: 지사 (차)본사/(대)감정수수료·외상매출금,
            -- 본사 (차)보통예금/(대)각지사. 지사 장부에는 은행 계정이 없으므로
            -- 본사 계정(1410001)을 입금 수단으로 함께 본다 (2026-07-22 재무팀 확인).
            -- 단 청구 전표(외상매출금 차변)에는 적용하지 않는다 — 청구가 입금으로 잡히면 안 된다.
            SELECT t.*, COALESCE(c.bank_net, 0) AS bank_net,
                   CASE WHEN t.ar_debit = 0 THEN COALESCE(c.hq_net, 0) ELSE 0 END AS hq_net,
                   v.vat_net, v.fee_total, COALESCE(mi.misc_net, 0) AS misc_net
            FROM tagged_vouchers t
            LEFT JOIN voucher_cash c
              ON c.voucher_date = t.voucher_date
             AND c.voucher_no = t.voucher_no
             AND c.division_code = t.division_code
            LEFT JOIN voucher_vat v
              ON v.voucher_date = t.voucher_date
             AND v.voucher_no = t.voucher_no
             AND v.division_code = t.division_code
            LEFT JOIN voucher_misc mi
              ON mi.voucher_date = t.voucher_date
             AND mi.voucher_no = t.voucher_no
             AND mi.division_code = t.division_code
        ), voucher_events AS (
            SELECT e.*,
                   e.ar_debit
                   - CASE
                       -- 현금 연결이 없고 수수료가 음수인 외상매출금 대변은
                       -- 입금이 아니라 기존 매출의 취소 전표다.
                       WHEN e.ar_credit > 0
                        AND (e.bank_net + e.hq_net) = 0
                        AND e.fee_credit < 0
                       THEN e.ar_credit
                       ELSE 0
                     END AS ar_billed_delta,
                   -- 거래처·금액 정정 전표: 현금 없이 발생(차변)+상쇄(대변)가
                   -- 한 전표에 있는 형태. 상쇄를 안 빼면 청구가 이중집계된다
                   -- (2026-08-13 실증 01-2607-3-2317: 544,500 → 1,089,000).
                   -- 선수금·가수금을 상계(차변)하는 전표는 정정이 아니라
                   -- 선수금 정산(지사 관행)이므로 제외 — 12-2507-3-0559 실측.
                   -- 상쇄 인정액은 감정서 단위에서 "다른 전표의 발생액"까지로
                   -- 캡을 둔다(b_raw) — 원 청구 전표가 이 감정서에 없는 상쇄
                   -- (01-2208-3-3909: 타 번호 이관 흔적)까지 빼면 실제 청구가
                   -- 사라진다.
                   CASE WHEN e.ar_credit > 0 AND e.ar_debit > 0
                             AND (e.bank_net + e.hq_net) = 0
                             AND e.fee_credit >= 0
                             AND e.advance_net >= 0 AND e.suspense_net >= 0
                        THEN e.ar_credit ELSE 0 END AS corr_credit,
                   CASE WHEN e.ar_credit > 0 AND e.ar_debit > 0
                             AND (e.bank_net + e.hq_net) = 0
                             AND e.fee_credit >= 0
                             AND e.advance_net >= 0 AND e.suspense_net >= 0
                        THEN e.ar_debit ELSE 0 END AS corr_debit,
                   -- 환불·정산 감액(마이너스 수수료) 전표는 청구도 같이 차감한다.
                   -- 입금(received_delta)은 부호를 안 가리므로 청구만 막으면 허깨비 미수가 남는다.
                   -- (2026-07-22 재무팀 확정: 감액 시 청구 차감 O, 환불금은 입금에서도 차감 O)
                   -- 청구·입금이 같은 환산식을 써야 직접입금에서 1원 미수·과입금이 안 생긴다.
                   CASE WHEN e.ar_debit = 0
                             AND (
                                 (e.bank_net <> 0 OR e.hq_net <> 0)
                                 OR (
                                     e.fee_credit > 0
                                     AND (e.advance_net < 0 OR e.suspense_net < 0)
                                 )
                             )
                             AND e.fee_credit <> 0
                        THEN {_direct_deposit_total_sql('e.fee_credit', 'e.vat_net', 'e.fee_total')} ELSE 0 END AS direct_billed_delta,
                   -- misc_net: 같은 전표의 잡이익 = 이 감정서의 초과 입금 (voucher_misc).
                   CASE WHEN (e.bank_net + e.hq_net) <> 0 THEN
                       e.ar_credit + e.advance_net + e.suspense_net + e.misc_net
                       + CASE WHEN e.ar_credit = 0 THEN {_direct_deposit_total_sql('e.fee_credit', 'e.vat_net', 'e.fee_total')} ELSE 0 END
                   ELSE 0 END AS received_delta
            FROM voucher_events_raw e
        ), b_raw AS (
            SELECT doc_id,
                   SUM(ar_billed_delta + direct_billed_delta)
                   -- 정정 전표의 상쇄(corr_credit)는 "다른 전표의 발생액"
                   -- 한도까지만 청구에서 뺀다 (min 구현). 발생액에는 직접입금
                   -- 청구분(direct_billed_delta 양수)도 포함 — 01-2606-4-0229는
                   -- 원 청구가 직접입금 매출이라 외상 차변만 보면 캡이 0이 된다.
                   - CASE WHEN SUM(corr_credit) < SUM(ar_debit) - SUM(corr_debit)
                          + SUM(CASE WHEN direct_billed_delta > 0
                                     THEN direct_billed_delta ELSE 0 END)
                          THEN SUM(corr_credit)
                          ELSE SUM(ar_debit) - SUM(corr_debit)
                          + SUM(CASE WHEN direct_billed_delta > 0
                                     THEN direct_billed_delta ELSE 0 END)
                     END AS billed_amount,
                   SUM(received_delta) AS received_amount,
                   SUM(advance_net) AS advance_amount,
                   SUM(suspense_net) AS suspense_amount,
                   MAX(CASE WHEN received_delta > 0 THEN voucher_date END) AS last_received_date,
                   COUNT(DISTINCT CASE WHEN received_delta <> 0 THEN
                       CONVERT(varchar(8), voucher_date, 112) + '-' + voucher_no + '-' + division_code END) AS receipt_count
            FROM voucher_events GROUP BY doc_id
        ), b AS (
            SELECT *,
                   CASE WHEN billed_amount > received_amount THEN billed_amount - received_amount ELSE 0 END AS outstanding_amount,
                   CASE
                       WHEN received_amount > billed_amount + CASE WHEN advance_amount > 0 THEN advance_amount ELSE 0 END
                       THEN received_amount - billed_amount - CASE WHEN advance_amount > 0 THEN advance_amount ELSE 0 END
                       ELSE 0
                   END AS overpaid_amount
            FROM b_raw
        )
    """


# 화면의 상태 배지와 같은 판정 우선순위: 선수금 → 과입금 → 완납 → 부분입금 → 미입금.
# 미수금현황은 요약 행이 없는 감정서(전표 0건)도 있어 ISNULL로 감싼다.
_STATUS_CONDITIONS = {
    "선수금": "(ISNULL(b.advance_amount, 0) > 0 AND ISNULL(b.billed_amount, 0) = 0)",
    "과입금": "(ISNULL(b.overpaid_amount, 0) > 0 AND NOT (ISNULL(b.advance_amount, 0) > 0 AND ISNULL(b.billed_amount, 0) = 0))",
    "완납": "(ISNULL(b.billed_amount, 0) > 0 AND ISNULL(b.outstanding_amount, 0) = 0 AND ISNULL(b.overpaid_amount, 0) = 0)",
    "부분입금": "(ISNULL(b.received_amount, 0) > 0 AND ISNULL(b.outstanding_amount, 0) > 0)",
    "미입금": "(ISNULL(b.received_amount, 0) <= 0 AND NOT (ISNULL(b.advance_amount, 0) > 0 AND ISNULL(b.billed_amount, 0) = 0))",
}


# 입금현황은 위 요약 컬럼이 아니라 화면과 같은 기준(_GROSS·_PAID)으로 걸러야 한다.
# 요약 컬럼으로 거르면 화면에 '부분입금'인데 필터에는 '완납'으로 잡히는 건이
# 2026년 본사에서 224건 나온다(미수 1,233만짜리도 '부분입금' 필터에서 빠졌다).
# _status_label() 의 우선순위(선수금 → 과입금 → 완납 → 부분입금 → 미입금)를 그대로 옮긴다.
_ADV_ONLY = "(ISNULL(b.advance_amount, 0) > 0 AND ISNULL(b.billed_amount, 0) = 0)"
_OVER_OK = f"({_PAID} - {_GROSS} > {_ROUND_NOISE})"
# 미수가 잔돈 이하로 남았고 전표 청구액이 있으면 완납이다.
_FULL_OK = f"({_GROSS} - {_PAID} <= {_ROUND_NOISE} AND ISNULL(b.billed_amount, 0) > 0)"
_RECEIVED_STATUS_CONDITIONS = {
    "선수금": _ADV_ONLY,
    "과입금": f"(NOT {_ADV_ONLY} AND {_OVER_OK})",
    "완납": f"(NOT {_ADV_ONLY} AND NOT {_OVER_OK} AND {_FULL_OK})",
    "부분입금": f"(NOT {_ADV_ONLY} AND NOT {_OVER_OK} AND NOT {_FULL_OK} AND {_PAID} > 0)",
    "미입금": f"(NOT {_ADV_ONLY} AND NOT {_OVER_OK} AND NOT {_FULL_OK} AND {_PAID} <= 0)",
}
# 미수금 범위 필터·정렬도 화면에 찍힌 값과 같아야 한다.
_OUTSTANDING_EXPR = (
    f"(CASE WHEN {_GROSS} - {_PAID} > {_ROUND_NOISE} THEN {_GROSS} - {_PAID} ELSE 0 END)"
)


class ReceivableService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        *,
        mode: Literal["received", "outstanding"],
        office_code: str | None = None,
        doc_id: str | None = None,
        customer_name: str | None = None,
        manager: str | None = None,
        scope_person: str | None = None,
        pay_statuses: "list[str] | None" = None,
        date_from: Any = None,
        date_to: Any = None,
        bill_from: float | None = None,
        bill_to: float | None = None,
        outstanding_from: float | None = None,
        outstanding_to: float | None = None,
        sort_by: str | None = None,
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 30,
        force_meta_join: bool = False,
        # 입금현황 기간 기준 (2026-09-02): received=입금일(기본) / send=발송일(원장 SendDate)
        date_basis: Literal["received", "send"] = "received",
    ) -> dict[str, Any]:
        # force_meta_join: 엑셀 내보내기처럼 수만 건을 한 번에 가져올 때는
        # 30건 IN 보강 대신 원본 뷰 조인으로 메타데이터를 한 쿼리에서 채운다.
        # office_code 지정 시 해당 지사 접두사만, None(전체)이면 활성 지사 전체.
        # 매핑 테이블이 비어 있는 초기 환경에서는 기존 본사 접두사로 폴백한다.
        prefixes = docid_prefixes(self.db, office_code) if office_code else (
            docid_prefixes(self.db, None) or ["01"]
        )
        # 집계는 동기화 때 만들어 둔 a10_receivable_summary를 읽는다 (b = 요약 테이블).
        # 단 미수금현황은 원장(a = apw_masterex)을 뿌리로 삼는다 — 오늘 발송돼 전표가
        # 하나도 없는 건은 요약 테이블에 행 자체가 없어서, 요약을 뿌리로 하면 안 보인다
        # (2026-07-29 사용자: "오늘 발송만 됐어도 미수현황에 나와야 한다").
        # 입금현황도 '발송일 기준'이면 같은 이유로 원장을 뿌리로 삼는다 — 발송만 되고
        # 아직 입금 안 된 건도 발송일 기준으로 보이게 (2026-09-03 사용자 요청).
        received_send = mode == "received" and date_basis == "send"
        root_on_view = mode == "outstanding" or received_send
        id_column = "a.DocID" if root_on_view else "b.doc_id"
        prefix_sql, prefix_params = management_no_filter(prefixes, column=id_column)

        # 미수 판정 기준액: 전표 청구액과, 발송된 건이면 청구서(apw_masterex) 총액 중 큰 쪽.
        # 세금계산서 미발행 건은 매출 전표가 없어 전표 청구액이 0이지만 받을 돈은 있다.
        effective_billed = (
            "CASE WHEN a.SendDate IS NOT NULL "
            "AND ISNULL(a.[청구금액], 0) > ISNULL(b.billed_amount, 0) "
            "THEN ISNULL(a.[청구금액], 0) ELSE ISNULL(b.billed_amount, 0) END"
        )
        # 발송일 기준 입금현황은 입금 여부를 안 가린다(그 기간 발송분 전부, 미입금 0원 포함).
        # 입금일 기준은 입금된 건만, 미수금현황은 받을 돈이 남은 건만.
        having = (
            "1 = 1" if received_send
            else "b.received_amount > 0" if mode == "received"
            else f"{effective_billed} > ISNULL(b.received_amount, 0)"
        )
        filters = [prefix_sql, having]
        # settle·tax_doc 계산값(s·t·ec)을 참조하는 조건 — CTE 대상 축소에는 못 쓴다.
        # 기간·지사 조건만으로 좁힌 대상 위에서 걸러도 결과는 같다 (2026-09-02).
        settle_filters: "list[str]" = []
        params: dict[str, Any] = {
            "offset": (page - 1) * page_size,
            "page_size": page_size,
            **prefix_params,
        }
        if doc_id:
            # 감정서 LIST 와 같이 정확일치 — LIKE '%…%' 는 인덱스를 못 타 2초 걸렸다 (2026-09-09)
            filters.append(f"{id_column} = CAST(:doc_id AS VARCHAR(50))")
            params["doc_id"] = doc_id.strip()
        if customer_name:
            filters.append("a.CustName LIKE :customer_name")
            params["customer_name"] = f"%{customer_name}%"
        if manager:
            filters.append("a.Manager LIKE :manager")
            params["manager"] = f"%{manager}%"
        # 데이터 조회 범위: 다른 직원 조회 권한이 없으면 유치자/조사자를 로그인 사용자로 고정한다.
        if scope_person:
            filters.append("(a.Manager LIKE :scope_person OR a.Charge LIKE :scope_person)")
            params["scope_person"] = f"%{scope_person}%"
        # 상태는 여러 개 고를 수 있다 (예: 부분입금 + 미입금). 고른 것들을 OR로 묶는다.
        status_map = (
            _RECEIVED_STATUS_CONDITIONS if mode == "received" else _STATUS_CONDITIONS
        )
        selected_statuses = [
            status for status in (pay_statuses or []) if status in status_map
        ]
        # settle·tax_doc 조인이 필요한지 — 상태·미수금 조건이나 미수금 정렬을 쓸 때다.
        needs_settle = mode == "received" and bool(
            selected_statuses
            or outstanding_from is not None
            or outstanding_to is not None
            or sort_by == "outstanding_amount"
        )
        if selected_statuses:
            status_sql = "(" + " OR ".join(status_map[s] for s in selected_statuses) + ")"
            # 입금현황 상태 판정식은 _GROSS/_PAID(s·t·ec)를 참조한다.
            (settle_filters if mode == "received" else filters).append(status_sql)
        # 미수금현황의 청구액·미수금 범위 필터는 화면 표시와 같은 기준을 쓴다.
        billed_expr = "ISNULL(b.billed_amount, 0)" if mode == "received" else effective_billed
        outstanding_expr = (
            _OUTSTANDING_EXPR if mode == "received"
            else f"({effective_billed} - ISNULL(b.received_amount, 0))"
        )
        if bill_from is not None:
            filters.append(f"{billed_expr} >= :bill_from")
            params["bill_from"] = bill_from
        if bill_to is not None:
            filters.append(f"{billed_expr} <= :bill_to")
            params["bill_to"] = bill_to
        outstanding_filters = settle_filters if mode == "received" else filters
        if outstanding_from is not None:
            outstanding_filters.append(f"{outstanding_expr} >= :outstanding_from")
            params["outstanding_from"] = outstanding_from
        if outstanding_to is not None:
            outstanding_filters.append(f"{outstanding_expr} <= :outstanding_to")
            params["outstanding_to"] = outstanding_to
        # 기간 조건: 입금 현황은 최근 입금일, 미수금 현황은 발송일(원본 뷰) 기준.
        # 감정서번호로 찾을 때는 기간을 무시한다 — 번호까지 아는 사용자에게 기간 밖이라고
        # 안 보여주면 "검색해도 안 나온다"가 된다 (감정서 LIST와 동일 규칙, 2026-07-27).
        if mode == "outstanding":
            # 실비 종결 건은 미수금현황에 안 띄운다 (2026-09-01) —
            # 받을 돈이 처리 시점 수금액으로 확정돼 미수가 없는 건이다.
            filters.append(
                "NOT EXISTS (SELECT 1 FROM dbo.a10_expense_close ec_x "
                "WHERE ec_x.doc_id = a.DocID AND ec_x.released_at IS NULL)"
            )
        date_column = (
            ("a.SendDate" if date_basis == "send" else "b.last_received_date")
            if mode == "received" else "a.SendDate"
        )
        if date_from and not doc_id:
            filters.append(f"{date_column} >= :date_from")
            params["date_from"] = date_from
        if date_to and not doc_id:
            filters.append(f"{date_column} < DATEADD(day, 1, :date_to)")
            params["date_to"] = date_to
        where = " AND ".join(filters + settle_filters)
        # CTE 대상용 — settle 값 참조 조건 제외 (기간·지사·검색어만)
        scope_where = " AND ".join(filters)
        source = _source_view()
        meta_office_sql = ""
        if office_code:
            params["meta_office_code"] = office_code
            if root_on_view:
                # 원장이 뿌리이므로 지사 조건은 WHERE에 직접 건다.
                where += " AND a.Office = CAST(:meta_office_code AS varchar(10))"
                scope_where += " AND a.Office = CAST(:meta_office_code AS varchar(10))"
            else:
                meta_office_sql = " AND a.Office = :meta_office_code"
        meta_sort_fields = {
            "customer_name", "address", "manager", "receipt_date",
            "purpose", "eval_purpose", "category", "progress_status", "send_date",
            "base_fee", "travel_expense", "survey_fee", "document_fee",
            "land_survey_fee", "special_service_fee", "other_expense", "appraisal_amount",
        }
        # 미수금현황은 판정 기준액에 청구서 총액이 들어가므로 항상 원본 뷰를 조인한다.
        needs_metadata = bool(
            # scope_person 은 이 브랜치의 개인범위 조건 — 유치자 이름으로 거르므로
            # 원본 뷰 조인이 필요하다. 병합 때 빠뜨리면 개인 범위가 통째로 무너진다.
            force_meta_join or customer_name or manager or scope_person
            or sort_by in meta_sort_fields
            or mode == "outstanding" or needs_settle
            # 발송일 기준은 날짜 조건이 a.SendDate 라 원본 뷰 조인이 필수다
            or (mode == "received" and date_basis == "send")
        )
        # 목록 쿼리에도 같은 조인을 달아야 s·t·ec 를 참조하는 조건이 산다.
        settle_join_sql = (
            "LEFT JOIN settle s ON s.doc_id = b.doc_id "
            "LEFT JOIN tax_doc t ON t.doc_id = b.doc_id "
            + _EXPENSE_CLOSE_JOIN if needs_settle else ""
        )
        join_sql = (
            f"LEFT JOIN {source} a ON a.DocID = b.doc_id{meta_office_sql}"
            if needs_metadata else ""
        )
        if root_on_view:
            # 원장이 뿌리, 요약은 있으면 붙인다 — 전표가 전혀 없는 발송 건도 포함된다
            # (미수금현황, 그리고 발송일 기준 입금현황).
            from_sql = (
                f"FROM {source} a LEFT JOIN dbo.a10_receivable_summary b "
                f"ON b.doc_id = a.DocID {settle_join_sql}WHERE {where}"
            )
        if needs_metadata:
            if not root_on_view:
                from_sql = (
                    f"FROM dbo.a10_receivable_summary b {join_sql} "
                    f"{settle_join_sql}WHERE {where}"
                )
            select_meta = (
                "a.ReceiptDate AS receipt_date, a.Address AS address, a.CustName AS customer_name, "
                "a.Manager AS manager, a.Charge AS charge, a.LWorkinfo AS purpose, "
                # 업무구분(LWorkinfo)=purpose, 평가목적(LPurpose)=eval_purpose (2026-09-03)
                "a.LPurpose AS eval_purpose, "
                # 물건종류 — 구분건물·토지건물·토지 등 (코드 Category 의 라벨). 화면에서는
                # 뺐지만(2026-09-03) 백엔드는 그대로 둔다.
                "a.LCategory AS category, "
                # 진행상태 — 완료처리(발송)·접수완료(처리전) 등 (코드 Status 의 라벨)
                "a.LStatus AS progress_status, a.SendDate AS send_date, "
                # 순수수료 = 기초수수료 − 절사 (TAMS·매출입력과 같은 정의).
                # 여비및기타(appraisal_cost)는 부대비용 항목 합 그대로 — 절사를 여기서 빼면 안 됨.
                "a.price AS appraisal_amount, "
                "a.[기초수수료] AS base_fee, "   # 청구서 순수수료합계(절사 전), 2026-09-11
                "a.[여비] AS travel_expense, a.[물건조사비] AS survey_fee, "
                "a.[공부발급비] AS document_fee, a.[토지조사비] AS land_survey_fee, "
                "a.[특별용역비] AS special_service_fee, a.[기타실비] AS other_expense, "
                "a.[수수료합계] - a.[기초수수료] + ISNULL(a.[절사금액], 0) AS appraisal_cost, "
                "a.[수수료합계] AS sales_amount, a.[부가가치세] AS vat_amount, "
                "a.[청구금액] AS assessed_billed, a.[매출총액] AS gross_total,"
            )
        else:
            # 기본 목록은 먼저 요약 테이블에서 페이지를 만든 뒤 해당 30건만 원본 뷰에서 보강한다.
            from_sql = f"FROM dbo.a10_receivable_summary b WHERE {where}"
            select_meta = ""
        # 건수·합계는 별도 커넥션에서 페이지 조회와 동시에 계산한다.
        # 매출총액(청구금액)이 원본 뷰에 있어 입금현황 합계 쿼리는 항상 조인한다.
        # 발송일 기준이면 미수금현황처럼 원장이 뿌리라 조인 방향이 뒤집힌다.
        joined_from = (
            f"FROM {source} a LEFT JOIN dbo.a10_receivable_summary b "
            f"ON b.doc_id = a.DocID WHERE {where}"
            if received_send
            else f"FROM dbo.a10_receivable_summary b "
            f"LEFT JOIN {source} a ON a.DocID = b.doc_id{meta_office_sql} WHERE {where}"
        )
        # 기본 조회는 검색 조건(보통 어제 하루)에 걸린 감정서만 먼저 좁혀 정산한다.
        # 상태·미수 조건은 settle/tax_doc 계산값(s·t)을 참조해 대상 축소에는 못 쓰지만,
        # 기간·지사·검색어(scope_where)만으로 좁힌 대상 위에서 걸러도 결과가 같다 —
        # 전에는 상태 필터마다 전체판 CTE로 떨어져 45~55초씩 걸렸다 (2026-09-02
        # 사용자: "입금현황이 좀 느려졌네").
        if received_send:
            # 발송일 기준: 요약에 없는 발송 건도 포함해야 하므로 원장을 뿌리로 좁힌다.
            settle_scope = (
                f"SELECT DISTINCT a.DocID AS doc_id FROM {source} a "
                f"LEFT JOIN dbo.a10_receivable_summary b ON b.doc_id = a.DocID "
                f"WHERE {scope_where}"
            )
        elif mode == "received":
            settle_scope = (
                f"SELECT DISTINCT b.doc_id FROM dbo.a10_receivable_summary b "
                f"LEFT JOIN {source} a ON a.DocID = b.doc_id{meta_office_sql} "
                f"WHERE {scope_where}"
            )
        else:
            settle_scope = f"SELECT DISTINCT b.doc_id {joined_from}"
        settle_cte = _settle_cte(settle_scope)
        if mode == "received":
            # 입금현황 합계는 목록 열과 같은 기준으로 낸다 —
            # 매출총액은 원장 [매출총액], 수금액은 입금액 + 미포착 선수금.
            settle_join = joined_from.replace(
                "WHERE ",
                "LEFT JOIN settle s ON s.doc_id = b.doc_id "
                "LEFT JOIN tax_doc t ON t.doc_id = b.doc_id "
                + _EXPENSE_CLOSE_JOIN + "WHERE ",
                1,
            )
            aggregate_sql = (
                settle_cte
                + "SELECT COUNT_BIG(1) AS total, "
                f"COALESCE(SUM({_GROSS}), 0) AS invoice_sum, "
                f"COALESCE(SUM({_PAID}), 0) AS received_sum, "
                "COALESCE(SUM(CASE WHEN b.advance_amount > 0 THEN b.advance_amount ELSE 0 END), 0) "
                "AS advance_sum, "
                f"COALESCE(SUM(CASE WHEN {_GROSS} - {_PAID} > {_ROUND_NOISE} "
                f"THEN {_GROSS} - {_PAID} ELSE 0 END), 0) AS outstanding_sum, "
                "COALESCE(SUM(b.billed_amount), 0) AS billed_sum, "
                f"COALESCE(SUM(CASE WHEN {_PAID} - {_GROSS} > {_ROUND_NOISE} "
                f"THEN {_PAID} - {_GROSS} ELSE 0 END), 0) AS overpaid_sum "
                + settle_join
            )
        else:
            # 미수금현황 합계 바: 건수·순수수료·여비및기타·매출액·부가세·매출총액·
            # 선수금·입금액·미수금 (TAMS 하단 합계와 같은 구성, 2026-07-29 요청).
            aggregate_sql = (
                "SELECT COUNT_BIG(1) AS total, "
                "COALESCE(SUM(b.billed_amount), 0) AS billed_sum, "
                "COALESCE(SUM(ISNULL(b.received_amount, 0)), 0) AS received_sum, "
                f"COALESCE(SUM(CASE WHEN {effective_billed} - ISNULL(b.received_amount, 0) > 0 "
                f"THEN {effective_billed} - ISNULL(b.received_amount, 0) ELSE 0 END), 0) AS outstanding_sum, "
                "COALESCE(SUM(b.overpaid_amount), 0) AS overpaid_sum, "
                "COALESCE(SUM(a.[기초수수료]), 0) AS fee_sum, "
                "COALESCE(SUM(a.[수수료합계] - a.[기초수수료] + ISNULL(a.[절사금액], 0)), 0) AS extra_sum, "
                "COALESCE(SUM(a.[수수료합계]), 0) AS sales_sum, "
                "COALESCE(SUM(a.[부가가치세]), 0) AS vat_sum, "
                "COALESCE(SUM(a.[청구금액]), 0) AS invoice_sum, "
                "COALESCE(SUM(ISNULL(b.advance_amount, 0)), 0) AS advance_sum "
                + from_sql
            )
        count_future = _COUNT_POOL.submit(_aggregate_rows, aggregate_sql, dict(params))
        # 입금 종료일 '당일'에 들어온 금액만 따로 합산한다 (합계 바 둘째 줄).
        # 발송일 기준에서는 '종료일 당일 입금'이라는 개념이 안 맞아 뺀다 (2026-09-02).
        daily_future = None
        if mode == "received" and date_to and date_basis == "received":
            daily_params = dict(params)
            daily_params["sum_date"] = date_to
            daily_future = _COUNT_POOL.submit(
                _aggregate_rows, _daily_total_sql(settle_join, settle_cte), daily_params
            )
        sort_columns = {
            "doc_id": id_column, "customer_name": "a.CustName",
            "address": "a.Address", "manager": "a.Manager", "charge": "a.Charge",
            "receipt_date": "a.ReceiptDate",
            "purpose": "a.LWorkinfo", "eval_purpose": "a.LPurpose", "category": "a.LCategory",
            "progress_status": "a.LStatus", "send_date": "a.SendDate",
            "appraisal_amount": "a.price",
            "base_fee": "a.[기초수수료]", "travel_expense": "a.[여비]",
            "survey_fee": "a.[물건조사비]", "document_fee": "a.[공부발급비]",
            "land_survey_fee": "a.[토지조사비]",
            "special_service_fee": "a.[특별용역비]", "other_expense": "a.[기타실비]",
            "last_received_date": "b.last_received_date",
            "billed_amount": billed_expr,
            "received_amount": "b.received_amount",
            "outstanding_amount": outstanding_expr,
            "overpaid_amount": "b.overpaid_amount",
        }
        direction = "DESC" if sort_order == "desc" else "ASC"
        if sort_by in sort_columns:
            tie_breaker = "" if sort_by == "doc_id" else f", {id_column} DESC"
            order_sql = f"{sort_columns[sort_by]} {direction}{tie_breaker}"
        elif mode == "received":
            # 기본 정렬은 고른 기간 기준을 따른다 — 발송일 기준이면 발송일순
            order_sql = (
                f"a.SendDate DESC, {id_column} DESC" if date_basis == "send"
                else "b.last_received_date DESC, b.doc_id DESC"
            )
        else:
            order_sql = f"{outstanding_expr} DESC, {id_column} DESC"
        # 요약 행이 없는 감정서(전표 0건)가 뿌리에 섞이는 화면은 b.*를 0으로 채운다
        # — 미수금현황, 그리고 발송일 기준 입금현황(미입금 발송 건 포함).
        if root_on_view:
            summary_select = (
                "ISNULL(b.billed_amount, 0) AS billed_amount, "
                "ISNULL(b.received_amount, 0) AS received_amount, "
                "ISNULL(b.outstanding_amount, 0) AS outstanding_amount, "
                "ISNULL(b.overpaid_amount, 0) AS overpaid_amount, "
                "ISNULL(b.advance_amount, 0) AS advance_amount, "
                "ISNULL(b.suspense_amount, 0) AS suspense_amount, "
                "b.last_received_date, ISNULL(b.receipt_count, 0) AS receipt_count"
            )
        else:
            summary_select = (
                "b.billed_amount, b.received_amount, "
                "b.outstanding_amount, b.overpaid_amount, "
                "b.advance_amount, b.suspense_amount, "
                "b.last_received_date, b.receipt_count"
            )
        rows = self.db.execute(
            text(
                f"""{settle_cte if needs_settle else ""}
                SELECT {id_column} AS doc_id, {select_meta}
                       {summary_select}
                {from_sql}
                ORDER BY {order_sql}
                OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY
                """
            ),
            {**params, "mode": mode},
        ).mappings().all()
        aggregate = count_future.result()
        total = int(aggregate["total"])
        items = [dict(row) for row in rows]
        if items and not needs_metadata:
            bind_names = [f"doc_{index}" for index in range(len(items))]
            doc_params: dict[str, Any] = {
                name: items[index]["doc_id"] for index, name in enumerate(bind_names)
            }
            office_sql = ""
            if office_code:
                office_sql = "Office = :meta_office_code AND "
                doc_params["meta_office_code"] = office_code
            metadata = self.db.execute(
                text(
                    f"SELECT DocID, ReceiptDate, Address, CustName, Manager, Charge, "
                    f"LWorkinfo, LPurpose, LCategory, LStatus, SendDate, "
                    f"price AS appraisal_amount, [기초수수료] AS base_fee, [여비] AS travel_expense, "
                    f"[물건조사비] AS survey_fee, [공부발급비] AS document_fee, "
                    f"[토지조사비] AS land_survey_fee, "
                    f"[특별용역비] AS special_service_fee, [기타실비] AS other_expense, "
                    f"[수수료합계] - [기초수수료] + ISNULL([절사금액], 0) AS appraisal_cost, "
                    f"[수수료합계] AS sales_amount, [부가가치세] AS vat_amount, "
                    f"[청구금액] AS assessed_billed, [매출총액] AS gross_total "
                    f"FROM {source} WHERE {office_sql}DocID IN "
                    f"({','.join(':' + name for name in bind_names)})"
                ),
                doc_params,
            ).mappings().all()
            metadata_by_doc = {row["DocID"]: row for row in metadata}
            for item in items:
                meta = metadata_by_doc.get(item["doc_id"], {})
                item.update(
                    receipt_date=meta.get("ReceiptDate"), address=meta.get("Address"),
                    customer_name=meta.get("CustName"), manager=meta.get("Manager"),
                    charge=meta.get("Charge"), purpose=meta.get("LWorkinfo"),
                    eval_purpose=meta.get("LPurpose"),
                    category=meta.get("LCategory"),
                    progress_status=meta.get("LStatus"),
                    send_date=meta.get("SendDate"), appraisal_amount=meta.get("appraisal_amount"),
                    base_fee=meta.get("base_fee"),
                    travel_expense=meta.get("travel_expense"),
                    survey_fee=meta.get("survey_fee"),
                    document_fee=meta.get("document_fee"),
                    land_survey_fee=meta.get("land_survey_fee"),
                    special_service_fee=meta.get("special_service_fee"),
                    other_expense=meta.get("other_expense"),
                    appraisal_cost=meta.get("appraisal_cost"),
                    sales_amount=meta.get("sales_amount"),
                    vat_amount=meta.get("vat_amount"),
                    assessed_billed=meta.get("assessed_billed"),
                    gross_total=meta.get("gross_total"),
                )
        # 재무팀 신규 열 구성은 입금현황에만 적용한다. 미수금현황은 기존 전표
        # 청구액·입금액·미수금·과입금·상태 구성을 그대로 유지한다.
        if mode == "received":
            advance_history = _advance_history(self.db, items)
            settlement = _advance_settlement(self.db, items)
            tax_totals = _tax_invoice_totals(self.db, items)
            cash_totals = _cash_receipt_totals(self.db, items)
            expense_closes = _expense_closes(self.db, items)
            for item in items:
                history = advance_history.get(str(item["doc_id"]), {})
                received = float(history.get("received") or 0)
                used = float(history.get("offset_amount") or 0)
                # 선수금 대변(받음)이 감정서번호 없이 잡히고 차변(상계·이첩)만
                # 감정서번호를 달고 오는 건이 있다. 선수금은 감정서번호가 나오기
                # 전에 받는 돈이라 그렇다. 실제 사례:
                #   01-2605-A-0079  차변 1,100,000  적요 '선수금 이첩>01-2605-A-0079'
                #   01-2602-7-0019  차변   500,000  적요 '선수금'
                # 그러면 받음 0 · 상계 X 가 되어 잔액이 -X 로 뜬다. 재무팀이
                # '선수금을 두 번 인식한다'고 읽은 그 음수다.
                # 상계된 돈은 어차피 받았던 돈이므로 받음을 상계액까지 올린다.
                received = max(received, used)
                item["advance_received"] = received
                item["advance_offset"] = used
                # 받은 적은 있는데 잔액이 0이면 전액 상계된 것이다.
                item["advance_fully_offset"] = received > 0 and used >= received
            latest_day = _latest_day_amounts(self.db, items)
            for item in items:
                latest = latest_day.get(
                    (str(item["doc_id"]), item.get("last_received_date")), {}
                )
                received_total = float(item.get("received_amount") or 0)
                advance_total = float(item.get("advance_amount") or 0)
                daily_received = float(latest.get("daily_received_amount") or 0)
                daily_advance = float(latest.get("daily_advance_amount") or 0)
                # 매출총액은 청구금액이 아니라 원장 [매출총액]과 세금계산서 발행액
                # 중 큰 쪽을 쓴다. 컨설팅·정비사업에는 원장 [매출총액]이 0인 채로
                # 수천만원짜리 계산서가 나간 건이 있고(반포3주구 4,400만,
                # 안진회계법인 4,070만), 전표 청구액은 취소했다 다시 끊은 분까지
                # 합산돼 두 배로 잡힌다(01-2603-1-0097 — 그래서 기준으로 못 쓴다).
                # 세금계산서는 거래처에 실제로 나간 청구서라 가장 믿을 만하다.
                # 2,036건 대조에서 '다 받았는데 과입금/미달' 오류가 0건이었다
                # (청구금액 기준 48건 · 매출총액만 24건 · 전표 포함 10건).
                #
                # 청구금액은 담당자가 '매출총액 − 선수금'으로 적는 관행이 있어
                # (2026년 본사 38건 실측), 선수금이 청구 차감과 입금액에 두 번
                # 반영돼 완납 건이 허위 과입금(23건)으로, 진행 건은 미수 과소로
                # 나왔다. 원장 [매출총액]은 담당자 입력과 무관해 흔들리지 않는다.
                # (수수료합계+부가세로 직접 더하면 안 된다 — 저장값과 다른 건이 5건 있다)
                gross_amount = float(item.get("gross_total") or 0)
                tax_row = tax_totals.get(str(item["doc_id"]), {})
                tax_amount = float(tax_row.get("tax_total") or 0)
                own_sales = float(tax_row.get("own_sales") or 0)
                # 세금계산서 발행여부 (2026-08-07 요청, 목록 맨 오른쪽 칸).
                # 넣는 값은 '발행' 하나뿐이다 — 아니면 빈칸으로 둔다.
                #
                # 남은 금액(순액)으로 판단한다. 끊었다 전액 취소한 건은 취소분이
                # 음수로 저장돼 순액이 0 이 되므로 여기서 빠진다. 실측(2026년):
                # 계산서가 달린 감정서 1,780개 중 순액 양수 1,776(99.8%) ·
                # 순액 0 이 4건(01-2606-2-0074 등, 모두 2장짜리 취소 건)이다.
                #
                # 여기 tax_amount 는 합산청구 걸러내기(아래) 전 값이라야 한다 —
                # 남의 감정서와 묶여 발행됐어도 '발행된 것'은 사실이다.
                item["tax_issued"] = "발행" if tax_amount > 0 else ""
                item["tax_issued_amount"] = tax_amount
                item["tax_issued_slips"] = int(tax_row.get("slips") or 0)
                # 현금영수증 발행여부 — 세금계산서와 같은 규칙(순액 양수만 '발행').
                # 전액 취소돼 순액이 0 이하면 빈칸이다.
                cash_row = cash_totals.get(str(item["doc_id"]), {})
                cash_amount = float(cash_row.get("cash_total") or 0)
                item["cash_issued"] = "발행" if cash_amount > 0 else ""
                item["cash_issued_amount"] = cash_amount
                item["cash_issued_slips"] = int(cash_row.get("slips") or 0)
                # 화면·엑셀은 '세금계산서/현금영수증' 한 칸이다 — 둘은 받는 주체만
                # 다른 같은 층위의 매출 증빙이라(사업자↔개인) 칸을 나누면 자리만
                # 먹는다. 값은 세금계산서 칸 시절과 똑같이 '발행' 하나로 통일
                # (2026-08-13 원동하) — 어떤 증빙인지는 화면 툴팁이 말한다.
                item["proof_issued"] = (
                    "발행" if item["tax_issued"] or item["cash_issued"] else ""
                )
                voucher_billed = float(item.get("billed_amount") or 0)
                # 계산서가 이 감정서 자신의 매출보다 크면 합산청구분이 섞인 것이다.
                if own_sales > 0 and tax_amount > own_sales * 1.02 + 1000:
                    tax_amount = 0.0
                invoice_total = gross_amount
                # 계산서가 원장보다 클 때는 전표 청구액이 같은 금액을 가리킬 때만 믿는다.
                # 여러 건을 한 장으로 묶어 발행하면 대표 감정서 하나에 전액이 달려
                # 원장의 수십 배가 된다 (01-2512-6-0808 — 원장 55,000 / 계산서 1,870,000
                # / 전표 55,000). 취소분이 음수로 안 들어와 두 번 더해지는 건도 있다
                # (01-2603-3-0783). 전표와 맞아떨어지면 그 건 몫이 맞다
                # (01-2601-3-0084 — 계산서 45,157,200 = 전표 45,157,200, 원장만 496,100).
                if tax_amount > invoice_total and voucher_billed > 0 and abs(
                    tax_amount - voucher_billed
                ) <= max(1000.0, tax_amount * 0.02):
                    # 아직 안 끊은 계산서가 있으면 발행액이 전표 청구액보다 작다.
                    # 큰 쪽을 써야 받을 돈이 다 잡힌다 (01-2607-2-0080 — 계산서
                    # 9장 중 마지막 305,300 이 미발행이라 허위 과입금이 남았다).
                    invoice_total = max(tax_amount, voucher_billed)
                if invoice_total <= 0:
                    # 원장·계산서가 다 비면 전표 청구액으로 떨어진다
                    # (컨설팅·정비사업에 원장 매출총액이 0인 채로 계산서만 나간 건이 있다).
                    invoice_total = voucher_billed
                if invoice_total <= 0:
                    invoice_total = float(item.get("assessed_billed") or 0)
                # 실비 종결 건: 처리 시점 수금액이 최종 매출 (_GROSS 의 ec 와 같은 규칙).
                close = expense_closes.get(str(item["doc_id"]))
                item["expense_closed"] = bool(close)
                item["expense_closed_by"] = (close or {}).get("closed_by_name") or ""
                item["expense_closed_at"] = (
                    close["closed_at"].isoformat(timespec="seconds")
                    if close and close.get("closed_at") else None
                )
                if close:
                    invoice_total = float(close["closed_amount"] or 0)
                # 입금액에 안 잡힌 수금(현금 없이 들어온 선수금 + 그 부가세)을 더한다.
                settle = settlement.get(str(item["doc_id"]), {})
                uncounted = float(settle.get("uncounted") or 0)
                credit_all = float(settle.get("credit_all") or 0)
                debit_all = float(settle.get("debit_all") or 0)
                # 대변이 아예 이 감정서에 안 달리고 차변(상계)만 온 건도 받은 돈이다.
                uncounted = max(uncounted, debit_all - (credit_all - uncounted), 0.0)
                # 수금으로 칠 수 있는 건 '이 감정서 매출에 실제로 상계된 만큼'이다.
                # 아직 안 쓴 선수금은 선수금(잔액) 칸에만 있어야 한다
                # (01-2605-2-0062 — 완납 뒤에 받은 100만이 과입금으로 잡혔다).
                uncounted = min(uncounted, debit_all)
                base_paid = received_total + uncounted + float(
                    settle.get("vat_extra") or 0
                )
                # 가수금→매출 직접 대체분은 기준액까지만 채운다 — 잔여 미수를
                # 지우는 보정이지 과입금의 근거가 아니다 (_PAID 의 상한과 동일).
                gasu_settled = float(settle.get("gasu_settled") or 0)
                paid_total = min(
                    base_paid + gasu_settled, max(base_paid, invoice_total)
                )
                item["settled_advance"] = paid_total - received_total

                # 기존 전표 청구액은 상세 확인용으로 남기고, 입금현황의
                # 매출총액/미수금은 청구서(apw_masterex) 총액으로 계산한다.
                #
                # 선수금 두 칸은 선수금(기)=받은 금액, 선수금=남은 잔액이다.
                # 잔액은 음수가 될 수 없다. 위에서 받음을 상계액까지 올렸으므로
                # 받음 - 상계 로 다시 계산하면 관리번호가 안 붙은 수령 건에서도
                # 0 밑으로 내려가지 않는다.
                item["voucher_billed_amount"] = item.get("billed_amount")
                item["invoice_total"] = invoice_total
                item["advance_amount"] = max(
                    float(item.get("advance_received") or 0)
                    - float(item.get("advance_offset") or 0),
                    0,
                )
                item["existing_advance_amount"] = advance_total - daily_advance
                item["existing_received_amount"] = received_total - daily_received
                item["daily_received_amount"] = daily_received
                item["daily_advance_amount"] = daily_advance
                # 반올림 잔돈은 미수도 과입금도 아니다.
                shortfall = invoice_total - paid_total
                if abs(shortfall) <= _ROUND_NOISE:
                    shortfall = 0.0
                # 미수는 부호를 살린다 — 과입금 건은 미수 칸에 음수(-90)로 보인다
                # (2026-09-11 사용자). 합계 바의 미수는 받을 돈만 더한다(outstanding_sum).
                item["outstanding_amount"] = shortfall
                item["overpaid_amount"] = max(-shortfall, 0)
        else:
            # 미수금현황도 판정 기준액(전표 vs 발송건 청구서 중 큰 쪽)으로 미수를 계산한다.
            # ① 발송만 되고 전표 없음 ② 선수금만 있고 잔액 남음 ③ 외상매출만 있고 미입금
            # ④ 일부만 입금 — 네 경우 모두 이 식 하나로 잡힌다 (2026-07-29 사용자 정의).
            for item in items:
                invoice_total = (
                    float(item.get("assessed_billed") or 0)
                    if item.get("send_date") else 0.0
                )
                effective = max(float(item.get("billed_amount") or 0), invoice_total)
                received_total = float(item.get("received_amount") or 0)
                item["outstanding_amount"] = max(effective - received_total, 0)
                item["billed_amount"] = effective
            # 미수금현황에도 증빙 발행여부 (2026-08-13 요청) — 선발행 미수
            # (계산서·현금영수증은 나갔는데 돈이 안 들어옴)를 이 목록에서
            # 골라내는 게 목적이다. 입금현황·감정서 LIST 와 같은 집계·같은 규칙이라
            # 세 화면·엑셀의 표시가 항상 일치한다.
            attach_proof_issued(self.db, items)
        # 현재 검색 조건 전체(페이지 무관)의 합계 — 목록 하단 합계 바에서 사용.
        sums = {
            "billed_amount": float(aggregate["billed_sum"] or 0),
            "received_amount": float(aggregate["received_sum"] or 0),
            "outstanding_amount": float(aggregate["outstanding_sum"] or 0),
            "overpaid_amount": float(aggregate["overpaid_sum"] or 0),
        }
        if mode == "received":
            sums["invoice_total"] = float(aggregate["invoice_sum"] or 0)
            sums["advance_amount"] = float(aggregate["advance_sum"] or 0)
        else:
            sums.update(
                base_fee=float(aggregate["fee_sum"] or 0),
                appraisal_cost=float(aggregate["extra_sum"] or 0),
                sales_amount=float(aggregate["sales_sum"] or 0),
                vat_amount=float(aggregate["vat_sum"] or 0),
                invoice_total=float(aggregate["invoice_sum"] or 0),
                advance_amount=float(aggregate["advance_sum"] or 0),
            )
        result = {
            "items": items,
            "total": total,
            "sums": sums,
            "page": page,
            "page_size": page_size,
            "mode": mode,
        }
        if daily_future is not None:
            daily = daily_future.result()
            result["daily_sums"] = {
                "date": str(date_to),
                "invoice_total": float(daily["daily_invoice"] or 0),
                "received_amount": float(daily["daily_received"] or 0),
                "advance_amount": float(daily["daily_advance"] or 0),
                "outstanding_amount": float(daily["daily_outstanding"] or 0),
                "count": int(daily["daily_docs"] or 0),
            }
        # 국민 약식수수료 묶음 행 — 첫 페이지 맨 위, 합계 바(전체·종료일 당일)에도 더한다.
        # 지사 사용자는 자기 회계단위에 걸린 400* 만 본다 (a10_office_map.division_code).
        # 약식 400* 은 원장에 없어 발송일이 없다 — 입금일 기준에서만 얹는다 (2026-09-02).
        if date_basis == "received" and kb_simple_row_wanted(
            mode=mode, page=page, doc_id=doc_id, customer_name=customer_name, manager=manager,
            scope_person=scope_person, pay_statuses=pay_statuses, bill_from=bill_from, bill_to=bill_to,
            outstanding_from=outstanding_from, outstanding_to=outstanding_to,
        ):
            office = get_office(self.db, office_code) if office_code else None
            kb_row = kb_simple_fee_row(
                self.db, date_from=date_from, date_to=date_to,
                division_code=office.division_code if office else None,
            )
            if kb_row is not None:
                result["items"] = [kb_row, *items]
                result["total"] = total + 1
                for key in ("invoice_total", "received_amount", "outstanding_amount", "billed_amount"):
                    sums[key] = float(sums.get(key) or 0) + float(kb_row[key] or 0)
                if "daily_sums" in result and kb_row["daily_docs"]:
                    daily_sums = result["daily_sums"]
                    daily_sums["invoice_total"] += kb_row["daily_billed_amount"]
                    daily_sums["received_amount"] += kb_row["daily_received_amount"]
                    daily_sums["count"] += 1
        return result


def _source_view() -> str:
    database = get_settings().mssql_source_db
    if not database.replace("_", "").isalnum():
        raise RuntimeError("MSSQL_SOURCE_DB 이름이 올바르지 않습니다.")
    return f"[{database}].dbo.apw_masterex"
