# BankOn — 수협·하나은행 담보 auto-fill 인계 번들

BANK24 담보 감정결과를 **자동입력**하는 도구 모음 (수협 SSB · 하나 HNB).
`.gam`(감정서) 추출 → 은행 매핑 → 화면 자동입력. 검증까지 포함.

> ⚠️ 은행 전용만 떼면 안 돌아갑니다 — `src/bankon` 은 한 덩어리 라이브러리라
> 통째로 넣었습니다. **은행 전용은 아래 파일**뿐입니다.

## 📄 먼저 읽을 것 — 인계문서 2개
- **`수협_담보_인계.md`** — 수협(TBNKSSB24DAMB) 매핑·검증·자동입력·콤보·엣지
- **`하나은행_담보_인계.md`** — 하나(TBNKHNB24DAMB) 매핑·검증·자동입력·콤보·엣지

## 폴더 구조
```
수협_담보_인계.md · 하나은행_담보_인계.md   ← 인계문서(먼저 읽기)
src/bankon/           라이브러리 (통째, 수정 불필요)
   mapping/ssb.py     ★ 수협 매핑
   mapping/hnb.py     ★ 하나 매핑
   parse/·sources/·ui/·codes/·model·gam_bridge·resolver·downloader·db·config
tools/
   verify_fill_ssb.py · autofill_ssb.py     ★ 수협 검증·자동입력
   verify_fill_hnb.py · autofill_hnb.py     ★ 하나 검증·자동입력
   check_ssb_offline.py                     수협 오프라인 회귀(EXPECT)
   verify_docs_live.py · elevated_verify.ps1 ★ 문서번호로 BANK24 자동 열람·대조(양 은행, 읽기전용)
   elevated_fill.ps1                        ★ 관리자 승격 실입력(UAC) — -Bank ssb|hnb
   list_combo_items.py · recon_form.py      콤보·폼 항목표 probe
   verify_form.py · verify_grid_loop.py     build_context · 무인순회
   (국민·기업·농협·신한 도구도 공용헬퍼 때문에 포함)
recon/
   fields_TBNKSSB24DAMB.md · combo_… · ssb_screen.json    수협 실폼 항목·콤보
   fields_TBNKHNB24DAMB.md · combo_… · hnb_screen.json    하나 실폼 항목·콤보
bin/gamexport.exe     .gam 추출기
.env.example          접속/경로 템플릿 → 값 채워 .env 로 저장
requirements.txt · pytest.ini
tests/                환경 검증용
```
**★ 은행 전용:**
- 수협 = `ssb.py · verify_fill_ssb.py · autofill_ssb.py · check_ssb_offline.py` (4개)
- 하나 = `hnb.py · verify_fill_hnb.py · autofill_hnb.py` (3개)
- 공용 = `elevated_fill.ps1`(승격 실입력) · `verify_docs_live.py`+`elevated_verify.ps1`(자동 대조) · 나머지 라이브러리 전체

## 셋업
1. `pip install -r requirements.txt` (pywinauto·pyodbc 등)
2. `.env.example` → 값 채워 `.env` 로 저장 (DB 192.0.2.10 · FTP 192.0.2.10 · gamexport 경로)
3. `PYTHONUTF8=1 PYTHONPATH="src;tools" python -m pytest -q` → 통과하면 환경 정상 (340개)
4. BANK24 실행 + 로그인

## 사용법 (Windows, 세미콜론 PYTHONPATH)
```
# 검증 (a) 화면에 해당은행 담보폼 열어둔 상태에서 한 건
python tools\verify_fill_ssb.py 01-2608-3-2609      # 수협
python tools\verify_fill_hnb.py 01-2609-3-2751      # 하나
# 검증 (b) 문서번호만 주면 BANK24 를 열어 자동 열람·대조(읽기 전용, 관리자 UAC 1회) — 여러 건
powershell -ExecutionPolicy Bypass -File tools\elevated_verify.ps1 -Bank ssb -Recent 5
powershell -ExecutionPolicy Bypass -File tools\elevated_verify.ps1 -Bank hnb -Docs "01-2609-3-2751 01-2608-3-2746"
   → reports\verify_live_<bank>_<시각>.log (도는 동안 마우스·키보드 건드리지 말 것)
# 검증 (c) 문서가 BANK24 어느 탭·어떤 행(상태·의뢰일자·접수일자)에 있는지만 — 은행 무관, 폼 안 엶
powershell -ExecutionPolicy Bypass -File tools\elevated_verify.ps1 -LocateOnly -Docs "01-2609-3-2780"
   (실측 2026-09-08: BANK24 조회기간은 **의뢰일자** 기준. 은행이 전날 저녁 보낸 건은 APW 의뢰일 하루 조회로 안 잡힌다)

# 자동입력 드라이런(안전, 계획만)
python tools\autofill_ssb.py 01-2608-3-2609
python tools\autofill_hnb.py 01-2609-3-2751

# 실입력 — 관리자 승격 필요(UAC "예"). -Bank 생략 시 수협.
powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 01-2608-3-2609 -Live              # 수협
powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 01-2609-3-2751 -Bank hnb -Live    # 하나
```

**verify_docs_live 가 굳힌 화면 규칙(2026-09-08 실측, 수협 5·하나 4건 전건 불일치 0)**
- 실사완료(작성·발송 끝난) 건은 **발송완료 탭**(또는 전체)에 있다. 작성 탭엔 미발송 건만.
- 아직 작성 전인 문서는 감정서번호가 BANK24 에 없어 '찾 기'에 안 잡힌다 → 건너뜀(정상).
- 그리드에 대상 행이 확인될 때만 키(Shift+F10/가속키)를 보낸다. 빈 그리드에 보내면 다른 앱으로 샌다.

## ⭐ 왜 승격(관리자)이 필요한가
BANK24가 High integrity(관리자)로 떠서, 일반(Medium) 세션은 UIPI로 **쓰기가 차단**된다
(읽기·검증은 됨). `elevated_fill.ps1` 이 UAC 로 High 자식프로세스를 띄워 우회한다(실측: 쓰기·
되읽기·콤보 probe 다 통과). 콤보 목록 probe 도 승격으로:
```
powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 <문서> -Bank ssb|hnb -Live   # 실입력
powershell -ExecutionPolicy Bypass -File tools\elevated_verify.ps1 -Bank ssb|hnb -Recent 5   # 자동 대조
python tools\list_combo_items.py --handle <폼핸들> --probe             # 콤보(승격 cmd에서)
```

## 안전장치 (양 은행 공통)
- 기본 **드라이런**(--live 없으면 안 씀) · **빈칸만**(--overwrite여야 덮음)
- **되읽기 검증** · **순번/번지 정합**(불명확하면 보류) · **사람이 저장**(자동제출 X)
- **미지원 가드**: 부동산 아니면(선박·어업권 등) 보류 · **집계형·일단지** 보류
- **--select(콤보 자동선택) 봉인**: 감사 P0-D(닫힌 드롭다운 ENTER→저장 커밋) 위험 →
  콤보는 사람이 선택. `--i-understand-experimental` 로만 해제.
- 대상 = **실사완료(.gam 존재, apw_masterex.ConductDate 있음)** 문서만.

## 남은 것 (인계문서 6·7절 참조)
- 수협: 실입력 라이브 실측(하나는 12칸 실측 완료) · 선박(6종)·어업권 매핑 · 일단지 residual.
- 하나: 동/호 물건별 추출 · --all 순회/--select 봉인 해제(2차앵커·콤보가드 완성 후).
