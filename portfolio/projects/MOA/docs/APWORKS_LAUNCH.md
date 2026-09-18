# APWorks(Delphi 7) → A10 Bridge EXE 연동

APWorks 버튼에서 로그인 사용자의 USR_SEQ를 넘겨 A10 Bridge 데스크톱 창을 연다.

## 실행 규약

```
A10BridgeDesktop.exe --usr-seq "APWorks 로그인 사용자 USR_SEQ"
```

- 값은 `TMWCMN_USR_BAC_INFO.USR_SEQ` (숫자, 사용자마다 유일). 숫자 1~10자리만 허용
  (그 외는 오류 메시지박스 후 종료). `--usr-id`는 과거 호환용 별칭으로 같은 값을 받는다.
- EXE는 서버(`http://192.0.2.10:8010`)의 `/api/users/{usr_seq}/context`로
  사용자·소속 지사를 검증한다. 퇴사자/미등록/미매핑 지사면 화면이 차단된다.
- **이미 실행 중이면 새 창을 띄우지 않고 기존 창을 앞으로 가져온다**
  (다른 usr-seq로 재실행해도 기존 사용자 창이 유지됨 — 사용자 전환은 창을 닫고 재실행).

## Delphi 7 예시

```pascal
uses ShellAPI;

procedure TfrmMain.btnA10BridgeClick(Sender: TObject);
var
  ExePath, Params: string;
begin
  ExePath := 'C:\A10Bridge\A10BridgeDesktop.exe';
  Params  := '--usr-seq "' + IntToStr(giUserSeq) + '"';   // 로그인 사용자 USR_SEQ 전역변수
  ShellExecute(0, 'open', PChar(ExePath), PChar(Params), nil, SW_SHOWNORMAL);
end;
```

## 직원 PC 배포 요건

1. `dist\A10BridgeDesktop\` 폴더를 표준 경로에 배치 (예: `C:\A10Bridge\`)
2. EXE 옆에 `A10BridgeDesktop.ini` 생성 (`A10BridgeDesktop.ini.example` 복사):
   ```ini
   [server]
   url = http://192.0.2.10:8010
   ```
3. WebView2 런타임 (Windows 11 기본 탑재; 구형 PC는 Evergreen 런타임 설치)
4. Python·ODBC 드라이버·DB 계정 **불필요** (전부 중앙 서버가 담당)

## 사용자에게 보일 수 있는 메시지박스

| 메시지 | 원인 |
|---|---|
| "사용자 번호(USR_SEQ)가 전달되지 않았습니다" | --usr-seq 없이 직접 실행 |
| "사용자 번호(USR_SEQ) 형식이 올바르지 않습니다" | 숫자가 아닌 값 전달 |
| "설정 파일을 찾을 수 없습니다" | exe 옆 A10BridgeDesktop.ini 누락 |
| "서버(...)에 연결할 수 없습니다" | 사내망/서버 문제 |

화면 안에서의 차단(빨간 카드): 미등록 사용자, 퇴사자, 소속 지사 미매핑 — 서버 `a10_access_log`에 사유가 기록된다.

## 보안 한계 (운영 참고)

`--usr-seq`는 인증이 아니라 **식별**이다. 임의 번호로 실행하는 것을 막지는 못하며,
사내망 신뢰 경계 + 전 실행 감사 로그(`a10_access_log`)로 추적한다.
권한 통제가 필요해지면 APWorks에서 서명된 일회용 토큰을 함께 전달하는 방식으로 확장한다.
