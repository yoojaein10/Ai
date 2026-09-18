# 기업은행 담보 (TBNKKIB24DAMB) — 입력 항목

- 입력 컨트롤 32개 (라벨 매칭 29 / 미매칭 3)
- DB 바인딩(TcxDB*) 29개 ← 실제 저장되는 필드

| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |
|---|------|------|--------|----|------|--------|-----------|
| 1 | 담보구분 | 텍스트 | 임대차포함 | O | 왼쪽 | TcxDBTextEdit | 416,209 |
| 2 | 평가사명 | 목록선택 | 전영배(2182) | O | 왼쪽 | TcxDBLookupComboBox | 416,233 |
| 3 | 순수수료 | 숫자/금액 | 3,622,267 | O | 왼쪽 | TcxDBCurrencyEdit | 794,233 |
| 4 | 물건종류 | 텍스트 | 단독주택 | O | 왼쪽 | TcxDBTextEdit | 416,257 |
| 5 | 기준시점 | 날짜 | 2026-08-25 | O | 왼쪽 | TcxDBDateEdit | 416,281 |
| 6 | 실   비 | 숫자/금액 | 69,900 | O | 왼쪽 | TcxDBCurrencyEdit | 794,281 |
| 7 | 감정수수료 | 숫자/금액 | 4,061,200 | O | 왼쪽 | TcxDBCurrencyEdit | 416,305 |
| 8 | 특별용역비 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 794,305 |
| 9 | 부가세 | 숫자/금액 | 369,200 | O | 왼쪽 | TcxDBCurrencyEdit | 794,329 |
| 10 | 일련번호 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | 601,394 |
| 11 | 공부지목 | 목록선택 | 대지 | O | 왼쪽 | TcxDBLookupComboBox | 907,394 |
| 12 | 용도지역 | 목록선택 | 자연녹지지역 | O | 왼쪽 | TcxDBLookupComboBox | 907,419 |
| 13 | 일련번호 | 텍스트 | 서울특별시 강남구  수서동 | O | 위쪽 | TcxDBTextEdit | 475,440 |
| 14 | 공부면적 | 숫자/금액 | 318.00 | O | 왼쪽 | TcxDBCurrencyEdit | 907,446 |
| 15 | 번지구분 | 목록선택 | 일반 | O | 왼쪽 | TcxDBLookupComboBox | 601,464 |
| 16 | 사정면적 | 숫자/금액 | 318.00 | O | 왼쪽 | TcxDBCurrencyEdit | 907,472 |
| 17 | 본번지 | 텍스트 | 461 | O | 왼쪽 | TcxDBTextEdit | 601,488 |
| 18 | 평가단가 | 숫자/금액 | 15,800,000 | O | 왼쪽 | TcxDBCurrencyEdit | 907,498 |
| 19 | 부번지 | 텍스트 | 17 | O | 왼쪽 | TcxDBTextEdit | 601,512 |
| 20 | 감정평가액 | 숫자/금액 | 5,024,400,000 | O | 왼쪽 | TcxDBCurrencyEdit | 907,524 |
| 21 | 물건종류 | 목록선택 | 대지 | O | 왼쪽 | TcxDBLookupComboBox | 601,536 |
| 22 | 총감정평가액 | 숫자/금액 | 5,100,478,080 | O | 왼쪽 | TcxDBCurrencyEdit | 601,560 |
| 23 | 비  고 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | 907,575 |
| 24 | 토지평가금액 | 숫자/금액 | 5,024,400,000 | O | 왼쪽 | TcxDBCurrencyEdit | 601,611 |
| 25 | 건물평가금액 | 숫자/금액 | 76,078,080 | O | 왼쪽 | TcxDBCurrencyEdit | 601,635 |
| 26 | 기계기구평가금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 601,658 |
| 27 | 기타평가금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 601,683 |
| 28 | 부동산구분 | 목록선택 | 토지 | O | 왼쪽 | TcxDBLookupComboBox | 601,707 |
| 29 | 등기소기준 고유번호 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | 601,731 |

## 라벨 미매칭 (수동 확인 필요)

| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |
|---|------|--------|--------|-----------|
| 1 | 숫자/금액 |  | TcxCurrencyEdit | 793,209 |
| 2 | 숫자/금액 |  | TcxCurrencyEdit | 794,257 |
| 3 | 텍스트 | 1168011500 | TcxDBTextEdit | 601,418 |