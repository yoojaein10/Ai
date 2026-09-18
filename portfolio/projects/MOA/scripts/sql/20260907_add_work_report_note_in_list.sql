/*
업무실적 '작업 저장' — 목록 멤버십 칸 추가 (2026-09-07 사용자 요청).

배경
  업무실적 화면은 체크 상태와 사유(a10_work_report_note.excluded/reason)만 저장하고,
  '어떤 감정서가 목록에 있었나'(멤버십)는 어디에도 남기지 않았다. 수기 추가(extra)는
  화면 입력값이라 쿼리 파라미터로만 전달돼, 화면을 다시 열면 자동선택분만 남고
  수기로 넣은 건이 통째로 사라졌다(재무팀 실사용에서 확인).

내용
  in_list CHAR(1) NOT NULL DEFAULT 'N'
    'Y' = 이 반월 작업 목록에 포함
    'N' = 목록에서 뺌(또는 저장된 적 없음)
  '작업 저장'이 화면의 전 행을 'Y'로 기록하고, 목록에서 빠진 건은 'N'으로 되돌린다.
  저장본을 다시 열면 이 목록이 그대로 화면이 된다.

실행
  SSMS 에서 GamJunDW(= 우리 DB)에 연결해 실행. 재실행해도 안전하다.
*/

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID(N'dbo.a10_work_report_note')
      AND name = N'in_list'
)
BEGIN
    ALTER TABLE dbo.a10_work_report_note
        ADD in_list CHAR(1) NOT NULL CONSTRAINT DF_a10_work_report_note_in_list DEFAULT 'N';
    PRINT 'a10_work_report_note.in_list 추가 완료';
END
ELSE
    PRINT 'a10_work_report_note.in_list 이미 존재 — 건너뜀';
GO
