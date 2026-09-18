# -*- coding: utf-8 -*-
'우리은행 최상단 담당자 행 좌표 기반 추출 회귀 테스트.\n\n전부 합성(REDACTED_CONFIGURE_LOCALLY) 좌표 데이터로만 구성한다. 실제 PDF에서 복사한 값이 아니라\n가상 인물명(홍길동/김철수)과 문서화용 더미 번호(010-0000-0000 등)만 사용한다.\n단독 pytest 프로세스로 실행 가능하며 공용 tmp 경로를 사용하지 않는다.\n'
import pytest

import pdf_parser as P


# 합성 단어 튜플 헬퍼: (x0, y0, x1, y1, text, block, line, wordno)
def W(x0, y0, text):
    return (x0, y0, x0 + 40.0, y0 + 12.0, text, 0, 0, 0)


# 우리은행 양식 근사: 상단 행(y=100)과 하단 행(y=130). 라벨 x는 실제 양식과
# 동일한 상대 배치(담당자명 왼쪽, 전화번호 오른쪽)를 흉내낸 합성값.
def make_two_rows(top_name="홍길동", top_phone_tokens=("010-0000-0000",),
                  bot_name="김철수", bot_phone_tokens=("02-000-0000",)):
    rows = []
    # 상단(첫 번째) 행 — 채택 대상
    rows.append(W(95.0, 100.0, "담당자명"))
    rows.append(W(168.0, 100.0, top_name))
    rows.append(W(345.0, 100.0, "전화번호"))
    x = 417.0
    for tok in top_phone_tokens:
        rows.append(W(x, 100.0, tok)); x += 45.0
    # 하단(두 번째) 행 — 무시 대상
    rows.append(W(345.0, 130.0, "담당자명"))
    rows.append(W(417.0, 130.0, bot_name))
    rows.append(W(95.0, 130.0, "전화번호"))
    rows.append(W(168.0, 130.0, bot_phone_tokens[0]))
    return rows


def test_selects_top_row():
    words = make_two_rows()
    name, phone = P._select_woori_top_contact(words)
    assert name == "홍길동"
    assert phone == "010-0000-0000"


def test_ignores_bottom_row():
    words = make_two_rows(top_name="홍길동", bot_name="김철수")
    name, phone = P._select_woori_top_contact(words)
    assert name != "김철수"
    assert name == "홍길동"


def test_word_order_shuffled_is_stable():
    words = make_two_rows()
    # 단어 반환 순서를 결정론적으로 뒤섞어도 좌표 기준 결과는 동일해야 한다.
    shuffled = list(reversed(words))
    # 추가로 인덱스 회전
    shuffled = shuffled[3:] + shuffled[:3]
    a = P._select_woori_top_contact(words)
    b = P._select_woori_top_contact(shuffled)
    assert a == b == ("홍길동", "010-0000-0000")


def test_only_same_y_band_combined():
    # 상단 라벨과 같은 밴드가 아닌(다른 y) 곳에 유효한 이름을 놓아도 결합되면 안 된다.
    words = make_two_rows()
    words.append(W(180.0, 100.0 + P._WOORI_Y_TOL + 5.0, "박영수"))  # 밴드 밖
    name, phone = P._select_woori_top_contact(words)
    assert name == "홍길동"


def test_phone_split_tokens_normalized():
    # 번호가 여러 단어로 쪼개진 경우 이어붙여 정규화한다.
    words = make_two_rows(top_phone_tokens=("010", "0000", "0000"))
    name, phone = P._select_woori_top_contact(words)
    assert name == "홍길동"
    assert P._is_phone(phone)
    assert phone == '010-0000-0000'


def test_phone_whitespace_collapsed():
    # 연속 공백은 하나로 축약되고 앞뒤 공백은 제거된다.
    words = make_two_rows(top_phone_tokens=("010 ", " 0000  0000",))
    name, phone = P._select_woori_top_contact(words)
    assert "  " not in phone
    assert phone == phone.strip()
    assert P._is_phone(phone)


def test_fallback_when_name_invalid():
    # 이름 자리에 라벨/비이름 값 → 이름 추출 실패 → None (호출부가 범용 결과 유지).
    words = make_two_rows(top_name="전화번호")  # 이름이 아님
    name, phone = P._select_woori_top_contact(words)
    assert name is None


def test_fallback_when_phone_invalid():
    # 형식에 맞지 않는 번호 → phone None.
    words = make_two_rows(top_phone_tokens=("123",))  # 0으로 시작 안함/자리수 미달
    name, phone = P._select_woori_top_contact(words)
    assert phone is None


def test_fallback_when_no_label():
    # '담당자명' 라벨이 없으면 (None, None).
    words = [W(95.0, 100.0, "소유자"), W(168.0, 100.0, "홍길동")]
    assert P._select_woori_top_contact(words) == (None, None)


def test_caller_override_contract():
    # 호출부 계약: 이름·전화번호가 모두 유효할 때만 신규 결과 적용, 아니면 범용 유지.
    generic_name, generic_phone = "기존담당", "031-000-0000"

    def apply(w_name, w_phone):
        emp, ph = generic_name, generic_phone
        if w_name and w_phone:
            emp, ph = w_name, w_phone
        return emp, ph

    assert apply("홍길동", "010-0000-0000") == ("홍길동", "010-0000-0000")
    assert apply(None, "010-0000-0000") == (generic_name, generic_phone)
    assert apply("홍길동", None) == (generic_name, generic_phone)
    assert apply(None, None) == (generic_name, generic_phone)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
