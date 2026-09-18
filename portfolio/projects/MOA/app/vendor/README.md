# app/vendor — 외부에서 그대로 들여온 코드

여기 있는 파일은 **우리가 쓴 코드가 아니다.** 손대지 말고, 고쳐야 하면 원본 관리자에게
알린 뒤 위쪽(`app/services/*`)에서 감싸서 처리한다.

## gamjun_search.py

- **원본** `Y:\PUBLIC_SOURCE\gamjun_search.py` (2026-08-05 사본 — 평가사 이름
  추출 개선·복수지역 '합쳐' 패턴 반영판. 챗 UI 번들 `_chatui/`·`server.py` 포함 원본)
- **무엇** 감정서 DB 자연어 조회 — 질문 → 필터 추출(Gemini) → SQL → 마크다운
- **원본 관리자** 대화감정평가법인 RAG 담당 (본서버 챗봇이 같은 코드를 쓴다)
- **DB** `192.0.2.10 / gamjundw` 의 `jun` 스키마 (apw_case 73만 · chunk 145만)
- **접속** pymssql (우리 앱 나머지는 pyodbc를 쓴다 — 이 모듈만 다르다)

### 우리가 쓰는 방식

`app/services/gamjun_chat.py` 가 감싸서 쓴다. 직접 부르지 말 것.

### 알려진 문제 — 본문 키워드 검색이 느리다

`_build_where()` 의 키워드 절이 이 형태다.

```sql
(a.title LIKE ? OR a.building_name LIKE ? OR a.client_name LIKE ?
 OR a.doc_id_raw IN (SELECT ... FROM jun.chunk ch WHERE CONTAINS(ch.content, ?)))
```

`OR` 가 해시 세미조인을 막아 행별 프로브로 전락한다. 실측(2026-08-04):

| 키워드 | 이 형태 | UNION-IN 으로 내렸을 때 |
|---|---:|---:|
| 효성빌라 | 40초+ 시한초과 | 25.1초 |
| 시점수정 | 40초+ 시한초과 | 21.2초 |
| 전세사기 | 12.0초 | 3.7초 |
| 거래사례비교법 | 3.7초 | 12.5초 |

한 번은 CPU를 35분 태웠다(읽기는 508뿐 · CXPACKET 병렬 플랜).
서버 부하에 따라 편차가 커서 본서버에서는 안 걸릴 때가 많다.

**원본 저자도 같은 문제를 알고 있다** — `person`(평가사) 절에는 주석까지 달아
UNION-IN 으로 고쳐 놨는데(`실측 90s+ → 3.0s`), 키워드 절에는 안 했다.

그래서 우리 화면은 **키워드를 빼고 부른다**(`gamjun_chat.SUPPORTED_FILTERS`).
소재지·물건종류·목적·기간·금액·평가사·감정서번호 검색은 1~4초로 잘 된다.

### 오피스 필터도 느리다 — 스냅샷으로 우회 (2026-08-05)

`office` 절은 `APWORKSDW.dbo.APW_MASTEREX`(HEAP, 73만 행) 전량 스캔 +
`LOffice LIKE '%라벨%'` 이라 매 질의 ~0.4초를 문다. APWORKSDW 는 우리 권한이
CONNECT 뿐이라 인덱스를 못 건다. 그래서 **gamjundw(우리가 db_owner)에
`dbo.a10_office_doc`(DocID PK, LOffice + 인덱스) 스냅샷**을 만들어 두고,
래퍼(`gamjun_chat._swap_office_sql`)가 벤더가 만든 SQL 문자열의 서브쿼리만
치환한다 — 벤더 파일은 그대로다. 실측 LOffice 는 정확 라벨 20종뿐이라 LIKE 의
contains 의미를 "값 목록 매칭 → IN(등호 시크)"로 보존한다 (0.37초 → 0.004초).

- 갱신: 6시간마다 첫 질문이 백그라운드 MERGE (~수 초). 스냅샷이 없거나 낡으면
  원본 서브쿼리로 동작한다 — 무해 폴백.
- MASTEREX 자체에 `(LOffice) INCLUDE (DocID)` 인덱스를 걸어 주면 스냅샷이
  필요 없어진다 → RAG 담당 협의 안건.
- `jun.apw_case` 에 `receipt_date` 인덱스가 없어 목록 정렬이 매번 전체 정렬이다
  (남는 0.3~0.9초의 대부분) → 이것도 RAG 담당 협의 안건.
