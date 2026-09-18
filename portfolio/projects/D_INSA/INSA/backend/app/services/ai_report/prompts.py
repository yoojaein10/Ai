"""Gemini 프롬프트 템플릿 v1.0."""
from __future__ import annotations

from typing import Any

PROMPT_VERSION = "v1.0"

SYSTEM_PROMPT = """당신은 한국 기업의 인사평가 보조 분석가입니다.
주어진 평가 데이터를 종합해 HR 담당자가 면담·코칭에 참고할 리포트를 작성합니다.

다음 원칙을 반드시 지키세요:
1. 당신은 평가자가 아니라 데이터 요약·정리 도우미입니다. 등급 변경 추천 금지.
2. 점수의 절대적 우월/열등을 단정하지 말고, 패턴·맥락 중심으로 서술합니다.
3. 다면평가 데이터가 입력에 없으면 다면 관련 언급을 하지 마세요.
4. 모든 출력은 한국어 존댓말. 객관적이고 따뜻한 톤.
5. 개인 식별자(이름·사번)가 입력에 placeholder로 들어와 있으면 그대로 사용합니다.

JSON 스키마로만 응답:
{
  "strengths": "강점 영역 (3~5문장)",
  "improvements": "개선이 필요한 영역 (3~5문장)",
  "coaching": "구체적 코칭 포인트 (3~5문장, 행동 단위)",
  "interview_guide": "1on1 면담 시 활용할 질문·체크포인트 (3~5문장)"
}
"""


def render_user_prompt(masked_input: dict[str, Any]) -> str:
    h = masked_input["header"]
    multi_block = (
        f"평균 {h['multi_score']} (응답 {h['multi_response_count']}명)"
        if h["multi_included"]
        else "(데이터 부족으로 제외)"
    )
    self_comments = "\n".join(
        f"- [{e['indicator']}] {e['score']}/5: {e.get('comment') or '(코멘트 없음)'}"
        for e in masked_input["self_evals"]
    ) or "(없음)"
    boss_comments = "\n".join(
        f"- [{e['indicator']}] {e['score']}/5 by {e['evaluator_placeholder']}: {e.get('comment') or '(코멘트 없음)'}"
        for e in masked_input["boss_evals"]
    ) or "(없음)"
    sar_records = "\n".join(
        f"- {s['date']} (관찰자 {s['observer_placeholder']}): "
        f"S={s.get('situation') or ''} / A={s.get('action') or ''} / R={s.get('result') or ''}"
        for s in masked_input["sars"]
    ) or "(없음)"
    multi_summary = "\n".join(
        f"- [{m['indicator']}] 평균 {m['avg_score']}/5 (응답 {m['response_count']}명)"
        for m in masked_input["multi_summary"]
    ) or "(없음)"

    return f"""평가 회차: {masked_input['round']['year']}년 {masked_input['round']['name']}
대상: {masked_input['employee_placeholder']} ({h['dept_name']} / {h['job_rank']})

[정량 점수]
- 성과: {h['perf_score']}
- 역량: {h['comp_score']}
- 다면: {multi_block}
- 종합: {h['total_score']} (등급 {h['final_grade']})

[본인평가 코멘트]
{self_comments}

[상사평가 코멘트]
{boss_comments}

[SAR 관찰기록]
{sar_records}

[다면평가 요약]
{multi_summary}
"""
