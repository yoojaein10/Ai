# A10 Bridge 데스크톱 앱 (thin 클라이언트)

메뉴 3개(**전표대사 / 입금 현황 / 미수금 현황**)를 제공하는 데스크톱 창.
2026-07-20부로 **thin 클라이언트 구조**로 전환됨 — EXE는 pywebview 창만 띄우고,
화면·API·DB 연동은 전부 중앙 서버(192.0.2.10:8010)가 담당한다.

- 서버 배포: `docs/SERVER_DEPLOY.md`
- APWorks 버튼 연동·직원 PC 배포: `docs/APWORKS_LAUNCH.md`

## 구조

```
A10BridgeDesktop.exe --usr-id "홍길동ID"
  → A10BridgeDesktop.ini에서 서버 URL 읽기
  → 단일 실행 확인 (실행 중이면 기존 창 활성화)
  → {서버}/health 확인
  → pywebview 창: {서버}/desktop?usr=홍길동ID
      → 서버가 사용자·소속 지사 검증 (/api/users/{usr}/context, 감사 로그 기록)
      → 상단에 "이름 · 지사" 표시
      → 본사(또는 권한자): 지사 셀렉트 + 전체 지사 조회 / 그 외: 자기 지사 고정
```

구 버전과의 차이: 로컬 uvicorn·.env(DB 암호)·ODBC 드라이버가 **직원 PC에서 전부 사라짐**.
화면 수정은 서버 재배포만으로 전 직원에게 반영된다.

## 빌드 (개발 PC)

```powershell
scripts\build_exe.ps1          # 릴리즈 (콘솔 없음) → dist\A10BridgeDesktop\ (~37MB)
scripts\build_exe.ps1 -Debug   # 디버그 (콘솔 traceback)
```

개발 모드 실행: 프로젝트 루트에 `A10BridgeDesktop.ini`(로컬 서버 URL) 두고
`python -m desktop.main --usr-id 테스트ID`

## 파일 구성

- `desktop/main.py` — thin 클라이언트 전체 (ini 로드, --usr-id 검증, 단일 실행 mutex, webview)
- `desktop/ui/` — 데스크톱 SPA. **서버가 서빙**(`app/main.py`의 `/desktop`, `/ui`) — EXE에 번들되지 않음
  - `context.js` 사용자 컨텍스트 부트스트랩(실패 시 차단 화면), `shell.js` 메뉴·지사 셀렉트,
    `dashboard-view.js`/`receivables-view.js` 3개 메뉴 뷰
- `desktop/a10bridge_desktop.spec` — PyInstaller 설정 (pywebview만 번들)
- `desktop/A10BridgeDesktop.ini.example` — 서버 URL 템플릿
- `requirements-desktop.txt` — 빌드 전용 (pywebview, pythonnet, pyinstaller)
