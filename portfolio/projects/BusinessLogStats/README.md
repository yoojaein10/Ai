# 업무일지 통계 통합 화면 (1차)

`SP_IW_S_TaskStats_Mon` 기반 월별 통계 — 데스크톱(WebView2)·모바일 공용 웹 화면.
계획서: `..\BusinessLogStats_Planning\INITIAL_PLAN.md`

## 실행

```
cd D:\AI\Claude\BusinessLogStats
python -m uvicorn server:app --host 127.0.0.1 --port 8630
```

브라우저에서 http://127.0.0.1:8630/ 접속.

## 구성

| 파일 | 역할 |
|---|---|
| `server.py` | FastAPI 서버: `/api/stats?ym=YYYY-MM`, 화면 서빙, 감사 로그 |
| `columns.py` | 결과 컬럼 데이터 계약(그룹·표시명). 컬럼은 이름 기준 매핑 |
| `config.ini` | 인증 모드, 열람 범위, DB 프로파일 (임시 결정 포함) |
| `static/app.html` | 반응형 화면: 요약표·표시 항목 선택·담당자 상세·전체 컬럼 |
| `access.log` | 감사 로그(사용자, 조회 월, 상태, 행수) — 토큰·PII 기록 금지 |

DB 자격증명은 보관하지 않는다 — `..\Y_SqlMcp\settings.ini` 프로파일 재사용.

## 미확정(임시 결정) 항목

계획서 11장 참조: 열람 권한 범위(현재 all), 인증(dev 모드),
구분 2 표시명("HF"), 처리건수 중복 보정 여부.
`config.ini` 의 `mode = dev` 는 로컬 개발 전용이며, 실배포 전에
token(EXE)/session(모바일) 인증 구현으로 교체해야 한다(fail-closed).
