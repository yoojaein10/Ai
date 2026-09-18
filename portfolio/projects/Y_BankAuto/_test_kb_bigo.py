'국민은행 Bigo(참고사항) 파싱 회귀 테스트\n참고 PDF: Y:\\PUBLIC_SOURCE\\3022027152008_20260624_160435.pdf\n'
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))

from pdf_parser import _extract_kb_bigo, parse_bank24_pdf

PASS = 0; FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  [OK] {label}: {got!r}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}: got={got!r}  expected={expected!r}")
        FAIL += 1

def check_not_contains(label, got, bad):
    global PASS, FAIL
    if bad not in (got or ""):
        print(f"  [OK] {label}: {got!r} ('{bad}' 없음)")
        PASS += 1
    else:
        print(f"  [FAIL] {label}: got={got!r} — '{bad}'가 포함됨")
        FAIL += 1

# ── 1. _extract_kb_bigo 단위 테스트 ────────────────────────────────────────────
print("=== 1. _extract_kb_bigo 단위 테스트 ===")

# 참고사항이 비어있고 바로 '기 타' 섹션이 나오는 경우 (참고 PDF 구조)
_EMPTY_CASE = [
    "▣의뢰내역", "박소영", "2026-06-24 오후 4:01:00", "신도림", "028114480",
    "의뢰", "기관", "참고사항",
    "기 타", "정 보", "공부요청구분", "요청",
    "임대차포함여부", "미요청", "감정목적", "담보",
]
check("빈 참고사항 → ''", _extract_kb_bigo(_EMPTY_CASE), "")

# 참고사항에 실제 내용이 있는 경우
_CONTENT_CASE = [
    "참고사항",
    "감정 시 현장 확인 필요",
    "기 타", "정 보", "공부요청구분", "요청",
]
check("내용 있는 참고사항", _extract_kb_bigo(_CONTENT_CASE), "감정 시 현장 확인 필요")

# 참고사항 내용 뒤에 공부요청구분이 와도 내용만 저장
_CONTENT_THEN_STOP = [
    "참고사항",
    "특이사항: 임차인 거주 중",
    "공부요청구분", "요청",
]
check("내용 후 공부요청구분 stop", _extract_kb_bigo(_CONTENT_THEN_STOP), "특이사항: 임차인 거주 중")

# 참고사항 없는 경우 → ''
_NO_LABEL = ["의뢰내역", "박소영", "공부요청구분", "요청"]
check("참고사항 라벨 없음 → ''", _extract_kb_bigo(_NO_LABEL), "")

# 각 stop 라벨 테스트
for stop_label in ["공부요청구분", "임대차포함여부", "임대차표함여부", "감정목적",
                   "정규담보취득제한부동산", "세금계산서정보", "물건정보"]:
    ls = ["참고사항", stop_label, "기타값"]
    result = _extract_kb_bigo(ls)
    check(f"stop={stop_label!r}", result, "")

# '기 타' / '기타' 직후 stop
check("'기 타' stop", _extract_kb_bigo(["참고사항", "기 타", "공부요청구분"]), "")
check("'기타' stop",  _extract_kb_bigo(["참고사항", "기타",  "공부요청구분"]), "")
check("'정 보' stop", _extract_kb_bigo(["참고사항", "정 보", "공부요청구분"]), "")

print()

# ── 2. 참고 PDF 통합 테스트 ────────────────────────────────────────────────────
PDF_PATH = 'Y:\\PUBLIC_SOURCE\\3022027152008_20260624_160435.pdf'
if not os.path.exists(PDF_PATH):
    print(f"=== 2. PDF 통합 테스트 SKIP (파일 없음) ===")
else:
    print("=== 2. 참고 PDF 통합 테스트 ===")
    p = parse_bank24_pdf(PDF_PATH)
    check("처리상태", p.get("처리상태"), "성공")
    check("비고 == ''", p.get("비고", ""), "")
    check_not_contains("Bigo에 '공부요청구분' 없음", p.get("비고", ""), "공부요청구분")
    check_not_contains("Bigo에 '요청' 없음",       p.get("비고", ""), "요청")

print()

# ── 3. 다른 은행 Bigo 영향 없음 확인 ─────────────────────────────────────────
print("=== 3. 다른 은행(HUG) bigo 함수 미호출 확인 ===")
# _extract_kb_bigo 는 KB 전용이며 HUG는 별도 로직 사용
# 단순히 is_kb 조건이 없으면 호출되지 않음 → 테스트: HUG 라인에서 호출해도 빈값
_HUG_LINES = [
    "주택도시보증공사", "의뢰번호:", "202606100000260",
    "참고사항", "이의신청 접수 건입니다",
    "공부요청구분", "미요청",
]
# _extract_kb_bigo는 참고사항 내용을 반환하지만 HUG는 이 함수를 호출하지 않음
# (테스트 목적: 함수 자체의 동작만 확인)
hug_result = _extract_kb_bigo(_HUG_LINES)
check("HUG 라인에서도 참고사항 내용만 반환", hug_result, "이의신청 접수 건입니다")

print()
print(f"결과: PASS={PASS}  FAIL={FAIL}")
if FAIL == 0:
    print("ALL UNIT TESTS PASS")
    sys.exit(0)
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
