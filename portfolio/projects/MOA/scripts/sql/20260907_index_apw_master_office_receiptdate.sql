/*
감정서 리스트 조회 가속 — APW_Master 복합 인덱스.

배경
  감정서 목록 화면(감정서 LIST, 입금현황 등)은 15개 테이블을 조인하는 뷰
  apworksdw.dbo.apw_masterex 를 접수일(ReceiptDate) 순으로 정렬해 페이지를 끊는다.
  Office 필터용 인덱스와 ReceiptDate 단일 인덱스는 있으나, 둘을 함께 쓰는 복합
  인덱스가 없어 "Office = 10 AND ORDER BY ReceiptDate DESC, DocID DESC" 가 조인
  결과 16.5만 건을 통째로 정렬한다(실측 2026-09-07: 페이지 SELECT 약 1.4초,
  COUNT 약 1.85초).

해결
  구동 테이블 APW_Master 에 (Office, ReceiptDate DESC, DocID DESC) 복합 인덱스를
  둔다. 앱은 이 테이블에서 건수·페이지 키를 먼저 뽑고 뷰는 그 페이지분만 상세
  조회하므로(2026-09-07 배포), 이 인덱스가 있으면 페이지 키 선별이 정렬 없이
  인덱스 순서대로 흘러 즉시 끝난다(실측 페이지 키 선별 약 0.8초 → 0.03초).

  DocID 를 키에 포함해 페이지 키 조회(SELECT DocID)를 인덱스만으로 처리(커버링)한다.
  읽기 전용 인덱스라 데이터·계산 결과는 전혀 바뀌지 않는다. 쓰기(감정 접수/수정)
  시 인덱스 유지 비용이 소폭 늘지만, APW_Master 에는 이미 단일 컬럼 인덱스가 30여
  개 있어 한 개 추가의 영향은 미미하다.

주의
  - 대상 DB는 apworksdw(APWorks/TAMS 원본). 생성 중 잠깐 잠금이 걸리므로 업무
    시간 외 실행을 권장한다(16.5만 건 기준 수 초 내 완료).
  - Enterprise 에디션이면 ONLINE=ON 을 켜 잠금을 피할 수 있다(아래 주석 참고).

실행
  SSMS 에서 apworksdw 에 연결해 실행.
*/

USE apworksdw;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_APW_Master_Office_ReceiptDate_DocID'
      AND object_id = OBJECT_ID(N'dbo.APW_Master')
)
BEGIN
    CREATE NONCLUSTERED INDEX IX_APW_Master_Office_ReceiptDate_DocID
        ON dbo.APW_Master (Office ASC, ReceiptDate DESC, DocID DESC);
    -- Enterprise 에디션이면 위 줄 대신 아래처럼 온라인 생성(무중단):
    -- CREATE NONCLUSTERED INDEX IX_APW_Master_Office_ReceiptDate_DocID
    --     ON dbo.APW_Master (Office ASC, ReceiptDate DESC, DocID DESC)
    --     WITH (ONLINE = ON);
    PRINT 'IX_APW_Master_Office_ReceiptDate_DocID 생성 완료';
END
ELSE
    PRINT 'IX_APW_Master_Office_ReceiptDate_DocID 이미 존재 — 건너뜀';
GO
