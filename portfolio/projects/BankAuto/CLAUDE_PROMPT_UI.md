# [Claude Code용 UI 프롬프트] - 자동화 제어 환경 디자인

당신은 UI/UX 엔지니어입니다. `bank24.exe` 수집 프로그램의 사용 편의성을 위한 제어 센터 및 로그 창을 디자인하세요.

## 📊 화면 구성 요구사항
1. **Status Dashboard:** 현재 자동화 진행 단계(로그인, 조회, 수집 중, 완료)를 실시간으로 표시하는 로그 창을 만드세요.
2. **Config Manager:** 아이디, 비밀번호, MSSQL 접속 정보, 수집할 날짜 범위를 입력하고 저장할 수 있는 설정 영역을 만드세요. (GUI 또는 설정 파일 연동)
3. **Execution Control:** '수집 시작', '강제 종료' 버튼을 직관적으로 배치하세요.
4. **Visual Feedback:** 윈도우 알림(Toast Notification) 등을 활용하여 수집 완료 시 사용자에게 알리세요.

## ✨ 스타일 가이드
- **Aesthetics:** `Modern Dark Mode` 또는 `Clean Enterprise` 스타일을 적용하세요.
- **Library:** `PyQt6` 또는 `CustomTkinter`를 권장합니다. (이미 해당 환경에 PyQt6 경험이 있음)
- **Responsiveness:** 창 크기 조절이 가능하고, 로그가 많아질 때 자동 스크롤이 되어야 합니다.
