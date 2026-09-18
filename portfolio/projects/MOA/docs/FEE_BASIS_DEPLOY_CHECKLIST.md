# 보수기준 점검(fee_basis) Git 배포 절차

작성: 2026-07-30

보수기준 검토(fee-review) 화면은 배포하지 않는다. 운영 반영은 ZIP이나 파일별 복사가
아니라 `release/fee-basis-20260730` 브랜치를 검토·병합하는 방식으로 진행한다.

## 1. 기능 소스

새로 전달하거나 변경하는 기능 소스는 다음 5개다.

```text
app/routers/fee_basis.py
app/services/fee_basis.py
app/services/fee_basis_evidence.py
app/services/fee_basis_rules.py
desktop/ui/fee-basis.html
```

- `fee_basis.py`: 업무실적 모집단, 보수 계산, 적용요율, 동결 스냅숏, 의견 저장,
  사전생성 배치를 한곳에서 담당한다.
- `fee_basis_evidence.py`: APWorks 보수사유와 JUN 현재 완료 문서의 근거 검색을 담당한다.
- 화면 JavaScript는 `fee-basis.html`에 포함했다. 기존 `desktop/ui/fee-basis.js`는
  병합 시 삭제된다.
- `fee_basis_rules.py`: 조문 라벨표와 판별 규칙. 이 화면(`fee_basis.py`,
  `fee_basis_evidence.py`)만 쓴다. `TEXT_SIGNALS`에 본문 신호 3개를 추가했으므로
  **함께 배포한다** — 빠뜨리면 `text_signal_hash`가 서버와 달라 사전생성 캐시가
  매번 낡음 판정을 받아 조회할 때마다 재생성된다.

따라서 예전의 `fee_basis_cache.py`, `fee_basis_opinions.py`, `fee_review_runs.py`,
`fee_rules.py`, `fee_applied_rate.py`, `fee_reason_bridge.py`,
`fee_review_evidence.py`, `app/models/fee_review_run.py`,
`app/batch/fee_basis_prepare.py`는 더 이상 필요하지 않다.

## 2. 설정·운영 보조 파일

기능 소스 외에 다음 변경은 운영 준비용이다.

```text
.env.example
app/config.py
scripts/register_fee_prepare_tasks.ps1
scripts/server_redeploy.ps1
scripts/sql/20260729_create_fee_review_run.sql
```

`app/config.py` 변경은 JUN 접속 설정(`jun_sql_*`)과
`fee_review_allow_memory_fallback`에 한정한다.

## 3. 병합에 포함하면 안 되는 것

- `app/models/__init__.py`: 운영본을 유지한다.
- `desktop/ui/context.js`, `desktop/ui/dashboard.css`: 운영본을 유지한다.
- `app/main.py`: 운영본이 이미 `fee_basis` 라우터와 화면을 등록하므로 변경하지 않는다.
- fee-review 전용 라우터·화면·서비스·배치 일체는 포함하지 않는다.

## 4. 병합 전 필수 확인

1. 변경 파일이 이 문서의 목록과 일치하는지 확인한다.
2. `python -m pytest -q -m "not integration"` 전체 테스트를 통과시킨다.
3. `python -m app.services.fee_basis --help`가 정상 실행되는지 확인한다.
4. 인라인 JavaScript 구문 검사와 화면 조회·의견 저장·엑셀 다운로드를 확인한다.
5. 운영 DB나 운영 서버에는 이 단계에서 변경을 적용하지 않는다.

## 5. 운영 DB·환경

1. DBA 검토 후 `scripts/sql/20260729_create_fee_review_run.sql`을 먼저 적용한다.
   앱은 테이블을 자동 생성하지 않는다. 테이블이 없으면 캐시 저장과 의견 저장,
   사전생성 배치가 실패한다.
2. 운영 `.env`에 `JUN_SQL_CONNECTION_STRING` 또는 `JUN_SQL_CONNECTION_FILE`을
   설정한다. 없으면 행 수와 금액 계산은 가능하지만 JUN 근거는 조회되지 않는다.
3. `FEE_REVIEW_ALLOW_MEMORY_FALLBACK`은 설정하지 않거나 `false`로 둔다.

## 6. 병합·배포 후

1. 서버 기동을 확인한다.
2. 예약 배치 등록을 확인한다 — **`server_redeploy.ps1`이 이미 등록한다**
   (`A10Bridge_FeeBasisPrepare`, 매일 23:00, `--months-back 5` = 당월 포함 6개월).
   `scripts/register_fee_prepare_tasks.ps1`을 따로 돌리지 마라 — 옛 개발장비용
   스크립트라 같은 일을 하는 작업이 이중 등록된다(2026-08-11 확인: 운영에는
   어느 쪽도 등록돼 있지 않았고, 캐시는 전부 화면 조회가 즉석 생성한 것이었다).

   ```powershell
   Get-ScheduledTask -TaskName "A10Bridge_FeeBasisPrepare"
   ```

3. 첫 예약 실행(23:00) 전에 캐시를 예열한다 — 안 하면 재무팀 첫 조회가
   기간마다 80초다. 규칙 버전을 올린 배포일에는 필수.

   ```powershell
   schtasks /run /tn "A10Bridge_FeeBasisPrepare"
   ```

4. 당월 상·하반 조회, 의견 저장 후 재조회 복원, 엑셀 다운로드를 확인한다.
5. 할인 적정성 축(2026-08-10, 업무연락 제2026-38호)을 배포한 경우: 재무팀 공지에
   "'할인 한도 초과 의심'·'할인 근거 없음' 배지는 위반 판정이 아니라 **근거 확인
   요청**"임을 명시한다 — 품의로 승인된 할인, 지번이 다른 재의뢰는 시스템이 모른다.

## 7. 알려진 보류

- API는 본사(`office_id=10`) 사용자만 허용한다. 사용자 정보가 없으면 401,
  지사 사용자는 403이다.
- 반월 경계에 걸린 일부 건은 상·하반 양쪽에 보일 수 있다.
- 동일 스냅숏 키의 최초 동시 생성 시 ACTIVE 행이 중복될 수 있으나 조회는 최신 행을 쓴다.
