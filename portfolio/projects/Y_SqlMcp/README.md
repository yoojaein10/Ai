# Y_SqlMcp — 로컬 SQL MCP 서버

데스크톱 Claude에서 사내망 MSSQL(`192.0.2.10` / `apworksdw` 등)을 조회·작업하기 위한
경량 MCP 서버입니다. 화면(GUI) 없이 백그라운드에서 stdio로 동작합니다.

## 기능 요약

- **다중 프로파일**: `settings.ini`에 `[profile.<이름>]` 섹션만 추가하면 서버/DB를 코드 수정 없이 늘릴 수 있습니다.
- **CRUD 지원**: `SELECT`는 바로 실행, `INSERT/UPDATE/DELETE`는 2단계(미리보기 → 승인) 후 반영.
- **코드 레벨 안전장치**:
  - DDL(`DROP/ALTER/TRUNCATE/CREATE/GRANT` 등)·저장 프로시저 전면 차단 → CRUD만 허용
  - 세미콜론 다중문장 차단(인젝션 방지)
  - 화이트리스트(`allow_tables`)에 등록된 테이블만 접근. **비어 있으면 전부 거부.**
  - 모든 실행은 `logs/sqlmcp.log`에 기록

## 설치

1) ODBC 드라이버 확인 — `ODBC Driver 17 for SQL Server` (기존 Y_BankAuto와 동일). 미설치 시 MS에서 설치.

2) 파이썬 패키지 설치:

```
pip install -r requirements.txt
```

3) `settings.ini` 채우기 — `apworksdw` 프로파일의 `password`와 `allow_tables`를 입력.
   - `password`: 기존 Y_BankAuto의 `dh` 계정 비밀번호
   - `allow_tables`: 조회/작업할 테이블명 (예: `APW_TS_Master, APW_RegHist`). **여기에 없으면 접근 불가.**

4) 데스크톱 Claude에 등록 — `claude_desktop_config.json` 예시 내용을 Claude 설정파일의
   `mcpServers`에 합쳐 넣고 Claude 재시작.
   (보통 위치: `%APPDATA%\Claude\claude_desktop_config.json`)

## 제공 도구

| 도구 | 설명 |
|------|------|
| `list_profiles()` | 등록된 프로파일 목록 |
| `test_connection(profile)` | 접속 확인 |
| `list_allowed_tables(profile)` | 허용 테이블 표시 |
| `describe_table(table, profile)` | 컬럼 구조 (화이트리스트 내) |
| `run_select(sql, profile)` | SELECT 조회 |
| `run_write(sql, profile, confirm)` | INSERT/UPDATE/DELETE |

`profile` 생략 시 `[general] default_profile` 사용.

## 쓰기(run_write) 동작 — 2단계 안전 절차

1. `confirm=False`(기본): 쿼리를 트랜잭션 안에서 실행해 **영향 행수만 확인하고 즉시 롤백**합니다.
   실제 데이터는 변하지 않습니다. Claude가 SQL과 예상 행수를 보여줍니다.
2. 사용자가 승인하면 `confirm=True`로 다시 호출 → **커밋(실제 반영)**.

> 참고: 미리보기 단계에서도 쿼리 자체는 한 번 실행되었다가 롤백되므로,
> 테이블에 트리거/IDENTITY가 걸려 있으면 시드값이 진행될 수 있습니다(데이터는 반영 안 됨).

## 보안 메모

- `settings.ini`에 접속정보가 들어가므로 `.gitignore`로 커밋에서 제외했습니다.
- DB 계정(`dh`) 자체 권한이 1차 방어선입니다. 운영 안전을 높이려면 **읽기 전용 또는 특정 테이블만
  권한이 있는 별도 계정**을 만들어 프로파일에 쓰는 것을 권장합니다.
- 사내망(이 PC) 안에서의 사용을 전제로 합니다. 외부(폰) 원격 조회는 회사 보안정책 검토 대상입니다.
- 카카오톡 연동은 이번 범위에 없습니다(추후 모듈 추가 예정).
