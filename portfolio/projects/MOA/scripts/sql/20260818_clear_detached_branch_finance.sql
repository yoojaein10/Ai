/* 2026-08-18 — 옛 '지사 재무담당' 묶음을 detach(자동 분리)로 지우면서 개인 예외
   (복사본)로 굳은 것을 정리한다. 사용자 요청: "지사재무담당 권한 붙어있던대 그것도
   없애버려 — 각자 묶음권한은 각자 하는 거야." 즉 각 지사가 자기 묶음으로 다시 세울
   것이므로, 이 옛 개인 예외를 내린다.

   ⚠ 주의 — 이 스크립트를 실행하면 해당 인원(대략 17명)은 지사 재무 권한을 잃는다.
   메뉴가 0개가 되면 **재설정 전까지 로그인이 거절**된다(ACCESS_DENIED). 그러므로
   **각 지사 묶음을 먼저 만들어 그 사람들에게 붙일 준비가 됐을 때** 실행하세요.
   먼저 대상을 눈으로 확인하려면 아래 SELECT 부터 돌려 보세요. */
SET NOCOUNT ON;

-- (확인용) 정리 대상 — 실행 전에 먼저 보고 싶으면 이 SELECT 만 돌린다.
-- SELECT usr_seq, usr_id, menu_overrides_json, view_other_users_override
--   FROM dbo.a10_access_policy
--  WHERE memo = N'묶음 삭제 시 자동 분리(복사)' AND active = 'Y';

UPDATE dbo.a10_access_policy SET active = 'N'
 WHERE memo = N'묶음 삭제 시 자동 분리(복사)' AND active = 'Y';
PRINT N'내린 개인 예외 수: ' + CAST(@@ROWCOUNT AS VARCHAR(10));
