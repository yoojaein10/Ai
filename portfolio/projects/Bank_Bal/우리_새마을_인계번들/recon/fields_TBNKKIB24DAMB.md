# 기업은행 담보 (TBNKKIB24DAMB) — 입력 항목

- 입력 컨트롤 37개 (라벨 매칭 34 / 미매칭 3)
- DB 바인딩(TcxDB*) 34개 ← 실제 저장되는 필드

| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |
|---|------|------|--------|----|------|--------|-----------|
| 1 | 담보구분 | 텍스트 | 임대차포함 | O | 왼쪽 | TcxDBTextEdit | 416,209 |
| 2 | 평가사명 | 목록선택 | 유승민(3872) | O | 왼쪽 | TcxDBLookupComboBox | 416,233 |
| 3 | 순수수료 | 숫자/금액 | 2,947,120 | O | 왼쪽 | TcxDBCurrencyEdit | 794,233 |
| 4 | 물건종류 | 텍스트 | 아파트형공장 | O | 왼쪽 | TcxDBTextEdit | 416,257 |
| 5 | 기준시점 | 날짜 | 2026-08-12 | O | 왼쪽 | TcxDBDateEdit | 416,281 |
| 6 | 실   비 | 숫자/금액 | 88,100 | O | 왼쪽 | TcxDBCurrencyEdit | 794,281 |
| 7 | 감정수수료 | 숫자/금액 | 3,338,500 | O | 왼쪽 | TcxDBCurrencyEdit | 416,305 |
| 8 | 특별용역비 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 794,305 |
| 9 | 부가세 | 숫자/금액 | 303,500 | O | 왼쪽 | TcxDBCurrencyEdit | 794,329 |
| 10 | 일련번호 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | 601,394 |
| 11 | 건 물 명 | 텍스트 | 서울숲엘타워 | O | 왼쪽 | TcxDBTextEdit | 911,394 |
| 12 | 동/호 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | 911,420 |
| 13 | 동/호 | 텍스트 | 703 | O | 왼쪽 | TcxDBTextEdit | 981,420 |
| 14 | 일련번호 | 텍스트 | 서울특별시 성동구  성수동1가 | O | 위쪽 | TcxDBTextEdit | 475,440 |
| 15 | 건물구조 | 텍스트 | 철근콘크리트구조 | O | 왼쪽 | TcxDBTextEdit | 911,446 |
| 16 | 번지구분 | 목록선택 | 일반 | O | 왼쪽 | TcxDBLookupComboBox | 601,464 |
| 17 | 준공일자 | 날짜 | 2026-02-05 | O | 왼쪽 | TcxDBDateEdit | 911,472 |
| 18 | 본번지 | 텍스트 | 656 | O | 왼쪽 | TcxDBTextEdit | 601,488 |
| 19 | 내용년수 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 911,498 |
| 20 | 부번지 | 텍스트 | 1110 | O | 왼쪽 | TcxDBTextEdit | 601,512 |
| 21 | 잔존년수 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 911,524 |
| 22 | 물건종류 | 목록선택 | 건물 | O | 왼쪽 | TcxDBLookupComboBox | 601,536 |
| 23 | 공부면적(전용면적) | 숫자/금액 | 116.30 | O | 왼쪽 | TcxDBCurrencyEdit | 911,550 |
| 24 | 총감정평가액 | 숫자/금액 | 4,033,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | 601,560 |
| 25 | 사정면적 | 숫자/금액 | 116.30 | O | 왼쪽 | TcxDBCurrencyEdit | 911,574 |
| 26 | 평가단가 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 911,600 |
| 27 | 토지평가금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 601,611 |
| 28 | 감정평가액 | 숫자/금액 | 2,024,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | 911,626 |
| 29 | 건물평가금액 | 숫자/금액 | 4,033,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | 601,635 |
| 30 | 기계기구평가금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 601,658 |
| 31 | 비  고 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | 911,677 |
| 32 | 기타평가금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 601,683 |
| 33 | 부동산구분 | 목록선택 | 집합건물 | O | 왼쪽 | TcxDBLookupComboBox | 601,707 |
| 34 | 등기소기준 고유번호 | 숫자/금액 | 24012016000698 | O | 왼쪽 | TcxDBCurrencyEdit | 601,731 |

## 라벨 미매칭 (수동 확인 필요)

| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |
|---|------|--------|--------|-----------|
| 1 | 숫자/금액 |  | TcxCurrencyEdit | 793,209 |
| 2 | 숫자/금액 |  | TcxCurrencyEdit | 794,257 |
| 3 | 텍스트 | 1120011400 | TcxDBTextEdit | 601,418 |