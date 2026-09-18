# APWorks 전표 Outbox 연동

APWorks의 발송 처리가 성공한 트랜잭션 안에서 아래 행을 추가합니다. 대상 DB는 `GamJunDW`, 테이블은 `dbo.a10_voucher_outbox`입니다.

```sql
INSERT INTO GamJunDW.dbo.a10_voucher_outbox
    (event_id, doc_id, event_type, requested_by, payload)
VALUES
    (:event_id, :doc_id, 'APWORKS_SEND', :requested_by, :payload);
```

Delphi 7 파라미터 쿼리 예시:

```pascal
Qry.SQL.Text :=
  'INSERT INTO GamJunDW.dbo.a10_voucher_outbox ' +
  '(event_id, doc_id, event_type, requested_by) ' +
  'VALUES (:event_id, :doc_id, ''APWORKS_SEND'', :requested_by)';
Qry.ParamByName('event_id').AsString := DocID + '-SEND-' + SendHistoryID;
Qry.ParamByName('doc_id').AsString := DocID;
Qry.ParamByName('requested_by').AsString := UserID;
Qry.ExecSQL;
```

- `event_id`: 한 번의 발송을 유일하게 식별하는 값입니다. 같은 값을 다시 넣으면 고유키 오류가 발생하여 중복 전표를 막습니다. 가능하면 APWorks 발송이력 PK를 조합하세요.
- `doc_id`: `apw_masterex.DocID`와 동일한 감정서번호입니다.
- `requested_by`: 발송 사용자 ID이며 선택값입니다.
- `payload`: 추가 정보용 JSON 문자열이며 선택값입니다.
- APWorks에서는 처리 상태, 재시도, 잠금 및 결과 열을 수정하지 않습니다. 이 열들은 A10BRIDGE가 관리합니다.

최초 상태는 `PENDING`입니다. 작업자는 처리 중 `PROCESSING`, 성공 시 `COMPLETED`, 재시도 시 `RETRY`, 최종 실패 시 `FAILED`를 사용합니다.
