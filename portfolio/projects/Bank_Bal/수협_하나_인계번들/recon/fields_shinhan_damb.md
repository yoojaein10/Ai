# 신한은행 담보 — 입력 항목

- 입력 컨트롤 68개 (라벨 매칭 66 / 미매칭 2)
- DB 바인딩(TcxDB*) 52개 ← 실제 저장되는 필드

| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |
|---|------|------|--------|----|------|--------|-----------|
| 1 | 물건순번 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | 2806,146 |
| 2 | 담보용도 | 목록선택 | 상가(중/소형) | O | 왼쪽 | TcxDBLookupComboBox | 3052,146 |
| 3 | 담보종류 | 목록선택 | 집합상가 | O | 왼쪽 | TcxDBLookupComboBox | 2807,168 |
| 4 | 도시계획구역구분 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 3052,169 |
| 5 | 1:예 2:아니오 | 목록선택 | 1 |  | 위쪽 | TcxComboBox | 3191,176 |
| 6 | 담보세부종류 | 목록선택 | 건물 | O | 왼쪽 | TcxDBLookupComboBox | 2806,191 |
| 7 | 이용상황구분 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 3052,192 |
| 8 | 1:예 2:아니오 | 목록선택 | 1 |  | 위쪽 | TcxComboBox | 3191,198 |
| 9 | 사용승인일 | 날짜 | 2018-12-26 | O | 왼쪽 | TcxDBDateEdit | 3052,215 |
| 10 | 당행과 협약체결된 전담감정평가사/심사자의 서명날인 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,220 |
| 11 | 담보세부종류 | 텍스트 |  | O | 위쪽 | TcxDBTextEdit | 2680,236 |
| 12 | 감정평가액 | 숫자/금액 | 621,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,238 |
| 13 | 감정평가서의 번호 기재여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,242 |
| 14 | 발송인 날인 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,264 |
| 15 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 1601-10외 3필지 서초어반하이오피스텔 1층 제101호 | O | 위쪽 | TcxDBTextEdit | 2680,273 |
| 16 | 평가단가 | 숫자/금액 | 0 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,286 |
| 17 | 감정평가의뢰인이 금융기관인지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,286 |
| 18 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 11650 | O | 위쪽 | TcxDBTextEdit | 2806,299 |
| 19 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 10800 | O | 위쪽 | TcxDBTextEdit | 2861,299 |
| 20 | 감정평가목적이 담보 등인지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,308 |
| 21 | 사정면적 | 숫자/금액 | 42.85 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,309 |
| 22 | 기준시점의 적정성 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,330 |
| 23 | 공부면적(수량) | 숫자/금액 | 42.85 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,332 |
| 24 | 번지구분 | 목록선택 | 일반 | O | 왼쪽 | TcxDBLookupComboBox | 2806,345 |
| 25 | 기재사항의 적정성 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,352 |
| 26 | 대지권면적 | 숫자/금액 | 7.68 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,355 |
| 27 | 본번지 | 텍스트 | 1601 | O | 왼쪽 | TcxDBTextEdit | 2806,368 |
| 28 | 일정한 조건을 전제로 평가한 조건부 감정서가 아닌지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,374 |
| 29 | 잔존연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | 3052,378 |
| 30 | 부번지 | 텍스트 | 10 | O | 왼쪽 | TcxDBTextEdit | 2806,391 |
| 31 | 감정평가협약사항의 준수여부(임대차조사등) | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,396 |
| 32 | 내용연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | 3052,401 |
| 33 | 토지등기부번호 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | 2806,414 |
| 34 | 소재지, 지번, 지목, 면적등의 일치여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | 3191,418 |
| 35 | 해당층수 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,424 |
| 36 | 건물등기부번호 | 숫자/금액 | 11012019000035 | O | 왼쪽 | TcxDBCurrencyEdit | 2806,437 |
| 37 | 총층수 | 숫자/금액 | 20 | O | 왼쪽 | TcxDBCurrencyEdit | 3052,447 |
| 38 | 지목 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2806,460 |
| 39 | 총방수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | 3052,470 |
| 40 | 용도지역구분(구) | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2806,483 |
| 41 | 용도지역구분(신) | 목록선택 | 일반상업지역 | O | 왼쪽 | TcxDBLookupComboBox | 3052,493 |
| 42 | 건물구조(구) | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2806,506 |
| 43 | 건물구조(신) | 목록선택 | 철근콘크리트구조 | O | 왼쪽 | TcxDBLookupComboBox | 3052,516 |
| 44 | 매매/분양 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 2806,539 |
| 45 | 임대 | 목록선택 | 임대있음 | O | 왼쪽 | TcxDBLookupComboBox | 3052,539 |
| 46 | 튼상가 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 2806,562 |
| 47 | 오픈상가 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 3052,562 |
| 48 | 공부/현황 불일치 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 2806,585 |
| 49 | 제시외건물,종물/부합물 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 3052,585 |
| 50 | 미등기 부동산 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 2807,608 |
| 51 | 별도 등기 존재 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | 3052,608 |
| 52 | 대표,지사장 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2702,668 |
| 53 | 평가사명1 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2952,668 |
| 54 | 평가사명1 | 목록선택 | 이영준 | O | 왼쪽 | TcxDBLookupComboBox | 3063,668 |
| 55 | 대표,지사장2 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2702,691 |
| 56 | 평가사명2 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2952,691 |
| 57 | 심사자 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2702,714 |
| 58 | 평가사명3 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | 2952,714 |
| 59 | 총감정가액 | 숫자/금액 | 2,863,000,000 | O | 왼쪽 | TcxDBCurrencyEdit | 2702,737 |
| 60 | 총감정가액 | 숫자/금액 |  |  | 왼쪽 | TcxCurrencyEdit | 2953,737 |
| 61 | 기준시점 | 날짜 | 2026-08-11 | O | 왼쪽 | TcxDBDateEdit | 2702,760 |
| 62 | 순수수료 | 숫자/금액 | 2,198,320 | O | 왼쪽 | TcxDBCurrencyEdit | 2953,760 |
| 63 | 현장답사일 | 날짜 | 2026-08-11 | O | 왼쪽 | TcxDBDateEdit | 2702,783 |
| 64 | 현장답사일 | 숫자/금액 |  |  | 왼쪽 | TcxCurrencyEdit | 2953,783 |
| 65 | 실   비 | 숫자/금액 | 121,990 | O | 왼쪽 | TcxDBCurrencyEdit | 2702,806 |
| 66 | 감정평가료 | 숫자/금액 | 2,539,900 | O | 왼쪽 | TcxDBCurrencyEdit | 2953,806 |

## 라벨 미매칭 (수동 확인 필요)

| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |
|---|------|--------|--------|-----------|
| 1 | 텍스트 | 06654 | TcxDBTextEdit | 2806,214 |
| 2 | 텍스트 | 서울특별시 서초구  서초동 | TcxDBTextEdit | 2680,322 |