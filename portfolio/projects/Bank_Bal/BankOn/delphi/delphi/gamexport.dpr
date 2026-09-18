program gamexport;

{
  gamexport - .gam(EasyTable) 추출기

  용도: Python 본체가 처리할 수 있도록 .gam 에서
    1) BLOB 첨부(HWP 의견서 등)를 파일로 추출
       - Ole0 등 'Ole%' 테이블: OLE 객체(의견서 HWP 가 여기 들어있음)
       - 'pf_hwp%' 테이블: 외부 첨부파일(문서에 따라 존재)
       두 경우 모두 Content(Blob) 를 파일로 저장. EasyTable 이 BLOB 압축을 자체 해제.
    2) gam_info 등 구조화 테이블을 UTF-8 JSON 으로 덤프

  사용법: gamexport.exe <입력.gam> <출력폴더>
  종료코드: 0 성공, 1 사용법오류, 2 DB열기실패, 3 처리중오류

  추출 파일명: <테이블>__<recno>__<title 또는 FilePath>
  (확장자가 없을 수 있음 - Python 쪽에서 HWP5 시그니처로 판별)
}

{$APPTYPE CONSOLE}

uses
  Windows, SysUtils, Classes, DB, EasyTable;

const
  EXPORT_TABLES: array[0..4] of string =
    ('gam_info', 'land_list0', 'land_list_20', 'mullist0',
     'Binder_detail');  // .gam 내 전체 테이블 카탈로그(table_name 컬럼)
  BLOB_PATTERNS: array[0..1] of string = ('Ole%', 'pf_hwp%');

const
  CP_KOREAN = 949;
  // 손상 .gam 방어용 절대 행 상한. 정상 명세는 수천 행 수준이므로 여유가 크다.
  MAX_DUMP_ROWS = 100000;

// 손상 .gam 에서 커서가 EOF 를 못 찍고 처음으로 되감기는 경우 감지
// (실사례 10-2604-1-0071 pbs_land0: 같은 ~36행 무한 반복 → 1GB JSON).
// RecNo 역행 = 되감김. RecNo 를 못 읽는 데이터셋(0 이하)은 감지에서 제외.
function CursorWrapped(DS: TDataSet; var LastRec: Integer): Boolean;
var
  cur: Integer;
begin
  Result := False;
  try
    cur := DS.RecNo;
  except
    cur := 0;
  end;
  if cur > 0 then
  begin
    Result := cur <= LastRec;
    if not Result then LastRec := cur;
  end;
end;

// 끝에 매달린 외톨이 CP949 선행바이트($81..$FE) 제거.
// 소스 필드가 고정길이에서 글자 중간에 잘리면(예: '문'=B9AE 중 AE 가 잘려 B9 만 남음)
// 변환 시 '?' 쓰레기가 생기므로, 짝 없는 선행바이트는 버린다.
function StripDanglingLead(const S: AnsiString): AnsiString;
var
  i, n: Integer;
begin
  Result := S;
  n := Length(Result);
  i := 1;
  while i <= n do
  begin
    if Byte(Result[i]) >= $81 then
    begin
      if i = n then  // 마지막 바이트가 선행바이트 → 짝 없음, 잘라냄
      begin
        Result := Copy(Result, 1, n - 1);
        Exit;
      end;
      Inc(i, 2);     // 정상 2바이트 문자
    end
    else
      Inc(i);        // 단일바이트(ASCII)
  end;
end;

function Utf8FromAnsi(const S: AnsiString): AnsiString;
var
  T: AnsiString;
  W: WideString;
  wlen: Integer;
begin
  // Delphi7 문자열은 CP949(ANSI). 명시적 CP949 로 변환(시스템 ACP 비의존) 후 UTF-8.
  T := StripDanglingLead(S);
  if T = '' then
  begin
    Result := '';
    Exit;
  end;
  wlen := MultiByteToWideChar(CP_KOREAN, 0, PAnsiChar(T), Length(T), nil, 0);
  SetLength(W, wlen);
  MultiByteToWideChar(CP_KOREAN, 0, PAnsiChar(T), Length(T), PWideChar(W), wlen);
  Result := UTF8Encode(W);
end;

function JsonEscape(const S: AnsiString): AnsiString;
var
  i: Integer;
  c: AnsiChar;
begin
  Result := '';
  for i := 1 to Length(S) do
  begin
    c := S[i];
    case c of
      '"': Result := Result + '\"';
      '\': Result := Result + '\\';
      #8:  Result := Result + '\b';
      #9:  Result := Result + '\t';
      #10: Result := Result + '\n';
      #13: Result := Result + '\r';
    else
      if c < #32 then
        Result := Result + '\u' + LowerCase(IntToHex(Ord(c), 4))
      else
        Result := Result + c;
    end;
  end;
end;

function SanitizeFileName(const S: string): string;
var
  i: Integer;
begin
  Result := Trim(S);
  for i := 1 to Length(Result) do
    if Result[i] in ['\', '/', ':', '*', '?', '"', '<', '>', '|', #0..#31] then
      Result[i] := '_';
  if Result = '' then Result := 'noname';
end;

// Memo 필드 내용을 블롭 스트림으로 읽는다. TMemoField.AsString 은 Delphi 버전에 따라
// '(MEMO)' 표시문자열을 돌려줄 수 있어 스트림으로 직접 읽는 쪽이 확실하다.
// (bill30 area5~area13 등 — 담당자 실비 내역 메모가 area6 에 들어있다, 2026-09-02 실증 01-2608-3-2743)
function ReadMemoField(DS: TDataSet; Fld: TField): AnsiString;
var
  BS: TStream;
begin
  Result := '';
  BS := DS.CreateBlobStream(Fld, bmRead);
  try
    if BS.Size > 0 then
    begin
      SetLength(Result, BS.Size);
      BS.ReadBuffer(Result[1], BS.Size);
    end;
  finally
    BS.Free;
  end;
end;

procedure DumpTableToJson(GamDB: TEasyDatabase; const TableName, OutDir: string);
var
  Q: TEasyQuery;
  F: TextFile;
  i, recno, lastRec: Integer;
  line, val: AnsiString;
begin
  Q := TEasyQuery.Create(nil);
  try
    Q.DatabaseName := GamDB.DatabaseName;
    Q.SQL.Text := 'select * from ' + TableName;
    try
      Q.Open;
    except
      Exit; // 해당 테이블이 없는 .gam 도 있다 - 조용히 건너뜀
    end;

    AssignFile(F, IncludeTrailingPathDelimiter(OutDir) + TableName + '.json');
    Rewrite(F);
    Write(F, '[');
    recno := 0;
    lastRec := 0;
    // 손상 .gam 방어: 행 읽기 중 스트림 오류(TAbstractFile.ReadBuffer 등)가 나도
    // 그 테이블만 중단하고 지금까지의 행으로 유효한 JSON 을 남긴다(부분 구제).
    try
      while not Q.Eof do
      begin
        if CursorWrapped(Q, lastRec) or (recno >= MAX_DUMP_ROWS) then
        begin
          Writeln('  WARN table ', TableName, ': cursor wrap/row cap at ', recno, ' rows');
          Break;
        end;
        if recno > 0 then Write(F, ',');
        line := '{';
        for i := 0 to Q.FieldCount - 1 do
        begin
          // 바이너리 BLOB 컬럼은 JSON 에 넣지 않는다(별도 파일 추출).
          // 단 Memo(텍스트 블롭)는 포함 — bill30 area6 실비 내역 등.
          if Q.Fields[i].IsBlob and
             not (Q.Fields[i].DataType in [ftMemo, ftFmtMemo]) then Continue;
          if Length(line) > 1 then line := line + ',';
          if Q.Fields[i].IsBlob then
            val := JsonEscape(Utf8FromAnsi(ReadMemoField(Q, Q.Fields[i])))
          else
            val := JsonEscape(Utf8FromAnsi(AnsiString(Q.Fields[i].AsString)));
          line := line + '"' + AnsiString(Q.Fields[i].FieldName) + '":"' + val + '"';
        end;
        line := line + '}';
        Write(F, line);
        Inc(recno);
        Q.Next;
      end;
    except
      on E: Exception do
        Writeln('  WARN table ', TableName, ': dump aborted at row ', recno, ': ', E.Message);
    end;
    Write(F, ']');
    CloseFile(F);
    Writeln('  table ', TableName, ': ', recno, ' rows');
  finally
    Q.Free;
  end;
end;

procedure ExtractBlobsFromTable(GamDB: TEasyDatabase; const TableName, OutDir: string);
var
  Tbl: TEasyTable;
  blob, nameFld: TField;
  recno, lastRec: Integer;
  fname, outPath: string;
begin
  Tbl := TEasyTable.Create(nil);
  try
    try
      Tbl.DatabaseName := GamDB.DatabaseName;
      Tbl.TableName := TableName;
      Tbl.Open;
    except
      on E: Exception do
      begin
        Writeln('  skip table ', TableName, ': ', E.Message);
        Exit;
      end;
    end;

    recno := 0;
    lastRec := 0;
    // 손상 .gam 방어: 스트림 오류 시 해당 BLOB 테이블만 중단(부분 구제).
    try
      while not Tbl.Eof do
      begin
        if CursorWrapped(Tbl, lastRec) or (recno >= MAX_DUMP_ROWS) then
        begin
          Writeln('  WARN table ', TableName, ': cursor wrap/row cap at ', recno, ' rows');
          Break;
        end;
        blob := Tbl.FindField('Content');
        if (blob <> nil) and blob.IsBlob and (not blob.IsNull)
           and (TBlobField(blob).BlobSize > 0) then
        begin
          nameFld := Tbl.FindField('FilePath');
          if nameFld = nil then nameFld := Tbl.FindField('title');
          if nameFld <> nil then fname := Trim(nameFld.AsString) else fname := '';
          fname := SanitizeFileName(TableName + '__' + IntToStr(recno) + '__' + fname);
          outPath := IncludeTrailingPathDelimiter(OutDir) + fname;
          try
            TBlobField(blob).SaveToFile(outPath);
            Writeln('  blob: ', TableName, '#', recno, ' (', TBlobField(blob).BlobSize, 'B) -> ', fname);
          except
            on E: Exception do
              Writeln('  blob save fail ', TableName, '#', recno, ': ', E.Message);
          end;
        end;
        Inc(recno);
        Tbl.Next;
      end;
    except
      on E: Exception do
        Writeln('  WARN blob table ', TableName, ': aborted at #', recno, ': ', E.Message);
    end;
    try
      Tbl.Close;
    except
      // 손상 파일은 Close 도 던질 수 있다 - Free 가 정리한다
    end;
  finally
    Tbl.Free;
  end;
end;

procedure ExtractBlobs(GamDB: TEasyDatabase; const Pattern, OutDir: string);
var
  Names: TEasyQuery;
begin
  Names := TEasyQuery.Create(nil);
  try
    Names.DatabaseName := GamDB.DatabaseName;
    Names.SQL.Text :=
      'select bd.table_name from Binder B, Binder_detail bd ' +
      'where B.code = bd.code and bd.table_name like ' + QuotedStr(Pattern);
    try
      Names.Open;
    except
      Exit;
    end;
    while not Names.Eof do
    begin
      ExtractBlobsFromTable(GamDB, Names.FieldByName('table_name').AsString, OutDir);
      Names.Next;
    end;
  finally
    Names.Free;
  end;
end;

// Binder_detail 카탈로그에 등재된 모든 테이블을 동적으로 덤프한다.
// 평가유형마다 명세 테이블이 다르므로(land_list0/section_build0/calculation50 ...)
// 고정 목록 대신 .gam 이 실제로 보유한 테이블 전체를 내보낸다.
procedure DumpAllTables(GamDB: TEasyDatabase; const OutDir: string);
var
  Cat: TEasyQuery;
  name: string;
begin
  Cat := TEasyQuery.Create(nil);
  try
    Cat.DatabaseName := GamDB.DatabaseName;
    Cat.SQL.Text := 'select distinct table_name from Binder_detail';
    try
      Cat.Open;
    except
      Exit;
    end;
    while not Cat.Eof do
    begin
      name := Trim(Cat.FieldByName('table_name').AsString);
      if name <> '' then
        try
          DumpTableToJson(GamDB, name, OutDir);
        except
          on E: Exception do
            Writeln('  WARN table ', name, ': ', E.Message);
        end;
      Cat.Next;
    end;
  finally
    Cat.Free;
  end;
end;

var
  GamPath, OutDir: string;
  GamDB: TEasyDatabase;
  t: Integer;
begin
  if ParamCount < 2 then
  begin
    Writeln('usage: gamexport.exe <input.gam> <output_dir>');
    Halt(1);
  end;
  GamPath := ParamStr(1);
  OutDir := ParamStr(2);
  ForceDirectories(OutDir);

  GamDB := TEasyDatabase.Create(nil);
  try
    GamDB.DatabaseName := '__GAMEXPORT__';
    GamDB.DatabaseFileName := GamPath;
    try
      GamDB.Open;
    except
      on E: Exception do
      begin
        Writeln('ERROR open .gam: ', E.Message);
        Halt(2);
      end;
    end;

    try
      for t := Low(BLOB_PATTERNS) to High(BLOB_PATTERNS) do
        try
          ExtractBlobs(GamDB, BLOB_PATTERNS[t], OutDir);
        except
          on E: Exception do
            Writeln('  WARN blobs ', BLOB_PATTERNS[t], ': ', E.Message);
        end;
      // gam_info 는 Binder_detail 에 없으므로 명시적으로 덤프.
      for t := Low(EXPORT_TABLES) to High(EXPORT_TABLES) do
        try
          DumpTableToJson(GamDB, EXPORT_TABLES[t], OutDir);
        except
          on E: Exception do
            Writeln('  WARN table ', EXPORT_TABLES[t], ': ', E.Message);
        end;
      // 그 외 .gam 이 보유한 모든 테이블(명세 포함)을 동적 덤프.
      DumpAllTables(GamDB, OutDir);
    except
      on E: Exception do
      begin
        Writeln('ERROR processing: ', E.Message);
        Halt(3);
      end;
    end;

    GamDB.Close;
  finally
    GamDB.Free;
  end;
  Writeln('done.');
end.
