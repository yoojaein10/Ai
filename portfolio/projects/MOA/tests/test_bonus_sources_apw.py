"""원천 DB 리더 (2단계 12) — 실행은 실측 스크립트가 하고, 여기서는 SQL 규칙만 못 박는다."""

from pathlib import Path

from app.services.bonus import sources_apw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "app" / "services" / "bonus" / "sources_apw.py").read_text(encoding="utf-8")


def test_varchar_바인드는_전부_CAST_하고_500건씩_자른다():
    assert "_CHUNK = 500" in SOURCE
    assert SOURCE.count("CAST(:") >= 4
    assert 'f"CAST(:{n} AS varchar(50))"' in SOURCE


def test_원천_표와_조건이_계획대로다():
    assert "dbo.apw_masterex m" in SOURCE and "m.ReceiptDate AS receipt_date" in SOURCE
    assert "APW_Charge_IDX c ON c.MasterID = m.MasterID AND c.iType = 1" in SOURCE
    assert "WHERE ApproState >= 3" in SOURCE and "AND Mul_Amt > 0 AND ApproState >= 3" in SOURCE   # 승인(3) 이상만 — 2026-08-27 확정
    assert "dbo.Apw_Mae_GaPrice" in SOURCE and "AND In_Price > 0" in SOURCE
    assert "OVER (PARTITION BY b.MasterID)" in SOURCE            # my_sales 와 같은 정규화
    assert "USE_YN = 'Y' AND RTRM_FL = '0'" in SOURCE


def test_담당자_비율은_퍼센트로_돌려준다():
    meta = {"ratio_names": "김형식,강무진", "ratio_values": "50,50"}
    assert sources_apw.charge_ratio(meta, "강무진") == 50.0
    assert sources_apw.charge_ratio(meta, "조근렬") is None
    assert sources_apw.charge_ratio({}, "강무진") is None
