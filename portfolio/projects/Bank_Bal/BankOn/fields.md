# 신한은행 담보 — 입력 항목

- 입력 컨트롤 68개 (라벨 매칭 66 / 미매칭 2)
- DB 바인딩(TcxDB*) 52개 ← 실제 저장되는 필드

| # | 항목 | 종류 | 현재값 | DB | 매칭 | 컨트롤 | 좌표(L,T) |
|---|------|------|--------|----|------|--------|-----------|
| 1 | 물건순번 | 숫자/금액 | 1 | O | 왼쪽 | TcxDBCurrencyEdit | -1687,167 |
| 2 | 담보용도 | 목록선택 | 대지 | O | 왼쪽 | TcxDBLookupComboBox | -1441,167 |
| 3 | 담보종류 | 목록선택 | 대지 | O | 왼쪽 | TcxDBLookupComboBox | -1686,189 |
| 4 | 도시계획구역구분 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1441,190 |
| 5 | 1:예 2:아니오 | 목록선택 | 1 |  | 위쪽 | TcxComboBox | -1302,197 |
| 6 | 담보세부종류 | 목록선택 | 토지 | O | 왼쪽 | TcxDBLookupComboBox | -1687,212 |
| 7 | 이용상황구분 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1441,213 |
| 8 | 1:예 2:아니오 | 목록선택 | 1 |  | 위쪽 | TcxComboBox | -1302,219 |
| 9 | 사용승인일 | 날짜 |  | O | 왼쪽 | TcxDBDateEdit | -1441,236 |
| 10 | 당행과 협약체결된 전담감정평가사/심사자의 서명날인 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,241 |
| 11 | 담보세부종류 | 텍스트 |  | O | 위쪽 | TcxDBTextEdit | -1813,257 |
| 12 | 감정평가액 | 숫자/금액 | 1,606,800,000 | O | 왼쪽 | TcxDBCurrencyEdit | -1441,259 |
| 13 | 감정평가서의 번호 기재여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,263 |
| 14 | 발송인 날인 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,285 |
| 15 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 83 | O | 위쪽 | TcxDBTextEdit | -1813,294 |
| 16 | 평가단가 | 숫자/금액 | 1,200,000 | O | 왼쪽 | TcxDBCurrencyEdit | -1441,307 |
| 17 | 감정평가의뢰인이 금융기관인지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,307 |
| 18 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 41360 | O | 위쪽 | TcxDBTextEdit | -1687,320 |
| 19 | ※아래 칸은 동미만 주소만 입력 바람. | 텍스트 | 25628 | O | 위쪽 | TcxDBTextEdit | -1632,320 |
| 20 | 감정평가목적이 담보 등인지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,329 |
| 21 | 사정면적 | 숫자/금액 | 1,339.00 | O | 왼쪽 | TcxDBCurrencyEdit | -1441,330 |
| 22 | 기준시점의 적정성 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,351 |
| 23 | 공부면적(수량) | 숫자/금액 | 2,439.00 | O | 왼쪽 | TcxDBCurrencyEdit | -1441,353 |
| 24 | 번지구분 | 목록선택 | 일반 | O | 왼쪽 | TcxDBLookupComboBox | -1687,366 |
| 25 | 기재사항의 적정성 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,373 |
| 26 | 대지권면적 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,376 |
| 27 | 본번지 | 텍스트 | 83 | O | 왼쪽 | TcxDBTextEdit | -1687,389 |
| 28 | 일정한 조건을 전제로 평가한 조건부 감정서가 아닌지 여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,395 |
| 29 | 잔존연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,399 |
| 30 | 부번지 | 텍스트 |  | O | 왼쪽 | TcxDBTextEdit | -1687,412 |
| 31 | 감정평가협약사항의 준수여부(임대차조사등) | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,417 |
| 32 | 내용연수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,422 |
| 33 | 토지등기부번호 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1687,435 |
| 34 | 소재지, 지번, 지목, 면적등의 일치여부 | 목록선택 | 1 |  | 오른쪽 | TcxComboBox | -1302,439 |
| 35 | 해당층수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,445 |
| 36 | 건물등기부번호 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1687,458 |
| 37 | 총층수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,468 |
| 38 | 지목 | 목록선택 | 대지 | O | 왼쪽 | TcxDBLookupComboBox | -1687,481 |
| 39 | 총방수 | 숫자/금액 |  | O | 왼쪽 | TcxDBCurrencyEdit | -1441,491 |
| 40 | 용도지역구분(구) | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1687,504 |
| 41 | 용도지역구분(신) | 목록선택 | 계획관리지역 | O | 왼쪽 | TcxDBLookupComboBox | -1441,514 |
| 42 | 건물구조(구) | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1687,527 |
| 43 | 건물구조(신) | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1441,537 |
| 44 | 매매/분양 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1687,560 |
| 45 | 임대 | 목록선택 | 해당없음 | O | 왼쪽 | TcxDBLookupComboBox | -1441,560 |
| 46 | 튼상가 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1687,583 |
| 47 | 오픈상가 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1441,583 |
| 48 | 공부/현황 불일치 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1687,606 |
| 49 | 제시외건물,종물/부합물 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1441,606 |
| 50 | 미등기 부동산 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1686,629 |
| 51 | 별도 등기 존재 | 목록선택 | 아니오 | O | 왼쪽 | TcxDBLookupComboBox | -1441,629 |
| 52 | 대표,지사장 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1791,689 |
| 53 | 평가사명1 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1541,689 |
| 54 | 평가사명1 | 목록선택 | 김기석 | O | 왼쪽 | TcxDBLookupComboBox | -1430,689 |
| 55 | 대표,지사장2 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1791,712 |
| 56 | 평가사명2 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1541,712 |
| 57 | 심사자 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1791,735 |
| 58 | 평가사명3 | 목록선택 |  | O | 왼쪽 | TcxDBLookupComboBox | -1541,735 |
| 59 | 총감정가액 | 숫자/금액 | 2,010,665,600 | O | 왼쪽 | TcxDBCurrencyEdit | -1791,758 |
| 60 | 총감정가액 | 숫자/금액 |  |  | 왼쪽 | TcxCurrencyEdit | -1540,758 |
| 61 | 기준시점 | 날짜 | 2026-08-18 | O | 왼쪽 | TcxDBDateEdit | -1791,781 |
| 62 | 순수수료 | 숫자/금액 | 1,652,825 | O | 왼쪽 | TcxDBCurrencyEdit | -1540,781 |
| 63 | 현장답사일 | 날짜 | 2026-08-18 | O | 왼쪽 | TcxDBDateEdit | -1791,804 |
| 64 | 현장답사일 | 숫자/금액 |  |  | 왼쪽 | TcxCurrencyEdit | -1540,804 |
| 65 | 실   비 | 숫자/금액 | 142,560 | O | 왼쪽 | TcxDBCurrencyEdit | -1791,827 |
| 66 | 감정평가료 | 숫자/금액 | 1,960,200 | O | 왼쪽 | TcxDBCurrencyEdit | -1540,827 |

## 라벨 미매칭 (수동 확인 필요)

| # | 종류 | 현재값 | 컨트롤 | 좌표(L,T) |
|---|------|--------|--------|-----------|
| 1 | 텍스트 | 12178 | TcxDBTextEdit | -1687,235 |
| 2 | 텍스트 | 경기도 남양주시 화도읍 창현리 | TcxDBTextEdit | -1813,343 |