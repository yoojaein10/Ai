# HUG(주택도시보증)은행 담보 (TBNKHUG24DAMB) — 입력 항목

- 입력 컨트롤 46개 (라벨 매칭 42 / 미매칭 4)
- DB 바인딩(TcxDB*) 41개 ← 실제 저장되는 필드

| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |
|---|------|------|--------|----|------|--------|-----------|
| 1 | 건 명 | 텍스트 | 임대보증금보증(세대_사용검사 후)(2026007235) | O | 왼쪽 | TcxDBTextEdit | -1464,215 |
| 2 | 감정구분 | 목록선택 | 임대차미포함 | O | 왼쪽 | TcxDBLookupComboBox | -1464,239 |
| 3 | 감정수수료 | 숫자/금액 | 655,600 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,240 |
| 4 | 기준시점 | 날짜 | 2026-08-31 | O | 왼쪽 | TcxDBDateEdit | -1464,263 |
| 5 | 부가세 | 숫자/금액 | 59,600 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,263 |
| 6 | 작성일자 | 날짜 | 2026-08-31 | O | 왼쪽 | TcxDBDateEdit | -1464,286 |
| 7 | 순수수료 | 숫자/금액 | 546,560 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,287 |
| 8 | 평가사성명 | 텍스트 | 안창덕 | O | 왼쪽 | TcxDBTextEdit | -1464,311 |
| 9 | 총감정평가액 | 숫자/금액 | 387,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | -1464,335 |
| 10 | 실비 | 숫자/금액 | 50,000 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,335 |
| 11 | 지세 | 숫자/금액 |  |  | 오른쪽* | TcxCurrencyEdit | -1464,359 |
| 12 | 특별용역비 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,359 |
| 13 | 할증할인여부 | 목록선택 | 없음 | O | 왼쪽 | TcxDBLookupComboBox | -1464,383 |
| 14 | 감정기관정산여부 | 목록선택 | 추가 정산 없음 | O | 왼쪽 | TcxDBLookupComboBox | -1100,383 |
| 15 | 수수료환불구분 | 목록선택 | 징수 | O | 왼쪽 | TcxDBLookupComboBox | -1464,407 |
| 16 | 정산수수료금액 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | -1100,408 |
| 17 | 물건일련번호 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | -1261,449 |
| 18 | 용 도 | 목록선택 | 아파트 | O | 왼쪽 | TcxDBLookupComboBox | -993,449 |
| 19 | 물건종류 | 목록선택 | 건물 | O | 왼쪽 | TcxDBLookupComboBox | -1261,473 |
| 20 | 공부상지목 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -993,473 |
| 21 | 공부면적 | 숫자/금액 | 23.47 | O | 왼쪽 | TcxDBCurrencyEdit | -993,497 |
| 22 | 사정지목 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -993,521 |
| 23 | 번지구분 | 목록선택 | 일반 | O | 왼쪽 | TcxDBLookupComboBox | -1261,545 |
| 24 | 사정면적 | 숫자/금액 | 23.47 | O | 왼쪽 | TcxDBCurrencyEdit | -993,545 |
| 25 | 본번 | 텍스트 | 777 | O | 왼쪽 | TcxDBTextEdit | -1261,569 |
| 26 | 단 가 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | -993,569 |
| 27 | 부번 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | -1261,593 |
| 28 | 감정가액 | 숫자/금액 | 215,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | -993,593 |
| 29 | 건물명 | 텍스트 | 씨앤에스타워 | O | 왼쪽 | TcxDBTextEdit | -1261,617 |
| 30 | 동 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | -1261,641 |
| 31 | 건물구조 | 텍스트 | 철근콘크리트구조 | O | 왼쪽 | TcxDBTextEdit | -993,643 |
| 32 | 호 | 텍스트 | 405 | O | 왼쪽 | TcxDBTextEdit | -1261,665 |
| 33 | 용도지역 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -993,667 |
| 34 | 표준지공시기준일 | 날짜 |  | O | 왼쪽 | TcxDBDateEdit | -1261,689 |
| 35 | 내용연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -993,691 |
| 36 | 표준지소재지 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | -1261,713 |
| 37 | 잔존연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -993,715 |
| 38 | 표준지공시지가 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | -1261,737 |
| 39 | 준공일자 | 날짜 | 2017-12-28 | O | 왼쪽 | TcxDBDateEdit | -993,739 |
| 40 | 등기고유번호 | 텍스트 | 25012018002087 | O | 왼쪽 | TcxDBTextEdit | -1261,761 |
| 41 | 비고 | 여러줄 |  | O | 왼쪽 | TcxDBMemo | -993,763 |
| 42 | 건축물대장고유번호 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | -1261,785 |

## 라벨 미매칭 (수동 확인 필요)

| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |
|---|------|--------|--------|-----------|
| 1 | 숫자/금액 |  | TcxCurrencyEdit | -1100,311 |
| 2 | 숫자/금액 | 0.00 | TcxDBCurrencyEdit | -1128,377 |
| 3 | 텍스트 | 1154510100 | TcxDBTextEdit | -1261,497 |
| 4 | 텍스트 | 서울특별시 금천구  가산동 | TcxDBTextEdit | -1387,521 |