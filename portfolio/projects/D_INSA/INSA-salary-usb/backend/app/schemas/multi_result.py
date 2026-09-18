from decimal import Decimal

from pydantic import BaseModel


class MultiIndicatorResult(BaseModel):
    indicator_id: int
    indicator_name: str
    avg_score: Decimal | None = None
    response_count: int


class MultiResultResponse(BaseModel):
    """count < 3 이면 익명 보호로 insufficient=true 반환."""

    round_id: int
    evaluatee_id: int
    insufficient: bool
    min_required: int = 3
    indicators: list[MultiIndicatorResult] = []
