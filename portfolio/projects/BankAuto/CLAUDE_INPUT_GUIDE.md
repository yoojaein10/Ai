# [Claude Code 입력 가이드] - Bank24 자동화 수집기 구축 순서

지침서(**ARCHITECT_MANIFESTO**)에 따라 다음 순서로 Claude Code에 위 프롬프트들을 입력하여 개발을 진행하세요.

### ⏱️ 작업 순서 (Input Sequence)

1. **Step 1: UI 환경 구축 (`CLAUDE_PROMPT_UI.md` 입력)**
   - 먼저 제어 창과 로그 시스템을 구축합니다. 로그가 제대로 찍히는지 확인하는 것이 최우선입니다.
   - `python main_gui.py` 실행을 통해 화면 구성을 먼저 확정하세요.

2. **Step 2: 핵심 수집 로직 구현 (`CLAUDE_PROMPT_CORE.md` 입력)**
   - 구축된 UI 위에 실제 `pywinauto`와 `pyautogui` 기반의 수집 코드를 얹습니다.
   - 로그인 테스트 -> 조회 테스트 -> 상세 데이터 수집 테스트 순으로 모듈별로 개발하세요.

3. **Step 3: 데이터 연동 및 배포 테스트**
   - MSSQL 연동 확인 및 엑셀 저장 기능을 붙입니다.
   - 마지막으로 `PyInstaller`를 이용해 `.exe`로 빌드하여 다른 PC에서 구동되는지 테스트하세요.

### ⚠️ 주의 사항
- 개발 도중 `bank24.exe` 창이 가려지지 않도록 주의하세요 (PyAutoGUI 사용 시 필수).
- 보안 모듈 간섭이 감지되면 즉시 입력 딜레이(`interval`)를 조정하도록 지시하세요.
