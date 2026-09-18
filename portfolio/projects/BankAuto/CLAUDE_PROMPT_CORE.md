# [Claude Code용 코딩 프롬프트] - Bank24 자동화 핵심 로직

당신은 전문 Python 자동화 개발자입니다. 다음 명세서에 따라 `bank24.exe` 제어 프로그램을 작성하세요.

## 🎯 목표
`C:\KADC\X11\bank24.exe` (델파이 기반 앱)를 제어하여 데이터를 수집하고 MSSQL/XLSX로 저장하는 단일 실행용 자동화 툴을 개발합니다.

## 🛠️ 기술적 데이터 (조사 완료)
- **Target App:** `C:\KADC\X11\bank24.exe`
- **Window Class:** `TDXLoginDialog` (로그인 창)
- **Control Tree (UIA Backend):**
    - **ID Field:** `auto_id="402020"`, `control_type="Edit"` (좌표: 997, 538 부근)
    - **PW Field:** `auto_id="1122982"`, `control_type="Edit"` (좌표: 997, 563 부근)
    - **OK Button:** `title="확인"`, `auto_id="1122960"`
- **Main Grid Logic:** 왼쪽 메뉴의 "Excel 변환" 버튼을 클릭하여 전체 데이터를 확보하세요.
- **Detail Logic:** 그리드 로우 우클릭 -> '접수(열람)' 클릭 -> '종합접수' 창의 주소 필드 추출.

## 📋 핵심 기능 구현 요구사항
1. **Safe Login:** `pywinauto`를 우선 사용하되, 보안 모듈 간섭 시 `pyautogui`로 좌표 클릭 및 `typewrite` 조합으로 로그인하세요. (interval=0.1 필수)
2. **Search Filter:** 왼쪽 사이드바의 라디오 버튼('담보', '탁상' 등)과 날짜 필드를 설정 파일(`config.json`)을 읽어 자동 설정하세요.
3. **Data Join:** 엑셀로 추출된 기본 데이터와 상세 창에서 가져온 '주소' 정보를 '의뢰번호' 기준으로 병합하세요.
4. **Data Sink:** 
    - 최종 데이터를 `result_YYYYMMDD.xlsx`로 저장.
    - MSSQL 서버에 연결(`pyodbc`)하여 테이블에 INSERT/UPDATE 하세요.
5. **Stability:** 모든 단계에 적절한 `time.sleep()`과 예외 처리(Try-Except)를 포함하여 프로그램이 중단되지 않게 하세요.

## 📦 배포 준비
- 설정값은 별도의 `config.json` 또는 `.env`에서 관리하도록 작성하세요.
- `PyInstaller`로 단일 EXE 빌드가 가능하도록 모든 의존성을 관리하세요.
