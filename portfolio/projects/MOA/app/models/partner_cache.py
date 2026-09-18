"""아마란스 거래처(api16S11) 사업자번호 색인 캐시.

카드전표 검증은 가맹점 사업자번호로 거래처를 찾는데, 아마란스는 한 건씩만
답한다(한 왕복 0.22초). 한 달치 카드내역이면 가맹점이 500곳을 넘어 그것만으로
2분이 걸린다 — 2026-08-20 실측.

전체 거래처는 61,000건이고 통째로 받는 데 84초다. 하루 한 번 받아두면 조회는
우리 DB에서 끝난다. 캐시가 비었거나 낡아도 화면은 죽지 않는다 — 모르는
사업자번호는 예전처럼 아마란스에 직접 묻는다(느릴 뿐 결과는 같다).

거래처코드는 분개에 쓰지 않는다(카드전표 세 줄 모두 카드사 거래처를 쓴다).
'아마란스에 등록된 가맹점'이라는 표시와 기록용이라, 캐시가 조금 낡아도
전표가 틀어지지 않는다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PartnerCache(Base):
    __tablename__ = "a10_partner_cache"
    __table_args__ = (
        # 사업자번호로 찾는 것이 이 표의 유일한 뜨거운 경로다.
        Index("IX_a10_partner_cache_regnb", "reg_no"),
    )

    # 거래처코드가 아마란스 안에서 유일하므로 그대로 열쇠로 쓴다.
    partner_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    reg_no: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    partner_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    partner_type: Mapped[str] = mapped_column(String(2), nullable=False, default="")  # trFg
    use_yn: Mapped[str] = mapped_column(String(1), nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # 한 번에 받은 묶음을 구분한다 — 이번 회차에 안 온 행은 아마란스에서 사라진 것.
    sync_batch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
