// ============================================================
// 기존 프로그램에서 ScheduleLauncher 호출 예시 (Delphi)
//
// uses: Windows, ShlObj, ShellAPI, SysUtils
// ============================================================

procedure TFormMain.btnCalendarClick(Sender: TObject);
const
  DEPLOY_LAUNCHER = '\\server\DATA1\전산\SEAT\ScheduleAppDeploy\ScheduleLauncher.exe';
var
  LocalAppDataBuf : array[0..MAX_PATH] of Char;
  LocalDir        : string;
  LocalLauncher   : string;
begin
  // 1. %LOCALAPPDATA% 경로 획득
  SHGetFolderPath(0, CSIDL_LOCAL_APPDATA, 0, SHGFP_TYPE_CURRENT, LocalAppDataBuf);
  LocalDir      := IncludeTrailingPathDelimiter(string(LocalAppDataBuf)) + 'ScheduleApp';
  LocalLauncher := LocalDir + '\ScheduleLauncher.exe';

  // 2. 로컬 런처가 없으면 공유폴더에서 복사
  if not FileExists(LocalLauncher) then
  begin
    if not ForceDirectories(LocalDir) then
    begin
      MessageBox(0, '폴더 생성 실패. 관리자에게 문의하세요.', '오류', MB_ICONERROR);
      Exit;
    end;
    if not CopyFile(PChar(DEPLOY_LAUNCHER), PChar(LocalLauncher), False) then
    begin
      MessageBox(0, '런처 설치 실패. 네트워크 연결을 확인하세요.', '오류', MB_ICONERROR);
      Exit;
    end;
  end;

  // 3. 로컬 런처 실행 (MyApwID 전달)
  //    런처가 버전 비교 후 필요 시 ScheduleApp.exe 업데이트, 이후 실행
  ShellExecute(
    0,
    'open',
    PChar(LocalLauncher),
    PChar(MyApwID),    // 기존과 동일하게 사번 전달
    nil,
    SW_SHOWNORMAL
  );
end;

// ============================================================
// 변경 전 (참고용 — 삭제 또는 주석 처리)
// ------------------------------------------------------------
// ShellExecute(
//   0,
//   'open',
//   PChar('\\server\DATA1\전산\SEAT\ScheduleApp.exe'),
//   PChar(MyApwID),
//   nil,
//   SW_SHOWNORMAL
// );
// ============================================================
