# BankOn — 우리은행·새마을금고 담보 auto-fill 인계 번들

BANK24 담보 감정결과를 **자동입력**하는 도구 모음 (우리 WRB · 새마을 MGB).
`.gam`(감정서) 추출 → 은행 매핑 → 화면 자동입력. 검증까지 포함.

> ⚠️ 은행 전용만 떼면 안 돌아갑니다 — `src/bankon` 은 한 덩어리 라이브러리라
> 통째로 넣었습니다. **은행 전용은 아래 파일**뿐입니다.

## 📄 먼저 읽을 것 — 인계문서 2개
- **`우리은행_담보_인계.md`** — 우리(TBNKWRB24DAMB) 매핑·검증·자동입력·콤보·다물건순회
- **`새마을금고_담보_인계.md`** — 새마을(TBNKMGB24DAMB) 매핑·토지특성·일단지·콤보

## 폴더 구조
```
우리은행_담보_인계.md · 새마을금고_담보_인계.md   ← 인계문서(먼저 읽기)
src/bankon/           라이브러리 (통째, 수정 불필요)
   mapping/wrb.py     ★ 우리 매핑
   mapping/mgb.py     ★ 새마을 매핑
   parse/outline.py     토지특성(도로/형상/지세) 파서 포함
tools/
   verify_fill_wrb.py · autofill_wrb.py     ★ 우리 검증·자동입력
   verify_fill_mgb.py                       ★ 새마을 검증
   elevated_fill.ps1                        ★ 관리자 승격 실행(UAC)
   list_combo_items.py · recon_form.py      콤보·폼 항목표 probe
   verify_form.py · verify_grid_loop.py     build_context · 무인순회
   (다른 은행 도구도 공용헬퍼 때문에 포함)
recon/
   fields_TBNKWRB24DAMB.md · combo_… · wrb_screen.json   우리 실폼
   fields_TBNKMGB24DAMB.md · combo_… · mgb_screen.json   새마을 실폼
bin/gamexport.exe     .gam 추출기
.env.example          접속/경로 템플릿 → 값 채워 .env 로 저장
requirements.txt · pytest.ini · tests/
```
**★ 은행 전용:**
- 우리 = `wrb.py · verify_fill_wrb.py · autofill_wrb.py` (3개)
- 새마을 = `mgb.py · verify_fill_mgb.py` (2개, autofill_mgb 는 우리 패턴 복제로 추가)
- 공용 = `elevated_fill.ps1`(승격) · `outline.py`(토지특성) · 라이브러리 전체

## 셋업
1. `pip install -r requirements.txt`
2. `.env.example` → 값 채워 `.env` 로 저장 (DB·FTP·gamexport 경로)
3. `PYTHONUTF8=1 PYTHONPATH="src;tools" python -m pytest -q` → 통과하면 정상 (340개)
4. BANK24 실행 + 로그인

## 사용법 (Windows, 세미콜론 PYTHONPATH)
```
# 검증 (화면에 해당은행 담보폼 열어둔 상태)
python tools\verify_fill_wrb.py 01-2608-3-2668      # 우리
python tools\verify_fill_mgb.py 01-2609-3-2762      # 새마을

# 자동 순회 검증 (승격, 감정서조회 목록 떠 있을 때)
python tools\verify_grid_loop.py --bank wrb --max 20
python tools\verify_grid_loop.py --bank mgb --max 20

# 실입력 — 관리자 승격 필요(UAC "예")
powershell -ExecutionPolicy Bypass -File tools\elevated_fill.ps1 <문서> -Live
```

## ⭐ 왜 승격(관리자)이 필요한가
BANK24가 High integrity로 떠서, 일반(Medium) 세션은 UIPI로 **쓰기가 차단**된다(읽기·검증은 됨).
`elevated_fill.ps1` 이 UAC 로 High 자식프로세스를 띄워 우회(하나에서 12칸 실측 완료).

## 안전장치 (양 은행 공통)
- 기본 **드라이런** · **빈칸만** · **되읽기 검증** · **순번 정합**(불명확하면 보류) · **사람이 저장**
- **미지원 가드**(부동산 아니면 보류) · **rollup·일단지 가드**
- **--all --live·--select 봉인**(감사 P0 — 틀린행·저장커밋 위험 → `--i-understand-experimental` 로만)
- 대상 = **실사완료(.gam 존재)** 문서만

## 검증 수준 (정직하게)
- **우리**: 자동순회 20건 매핑버그 0. 21물건 다물건 순회 실측. 위치밴드 위험 제거.
- **새마을**: 자동순회 73건. 실입력 드라이런 대조 ✅29/0(우리값=실입력값 완전일치).
- **실제 쓰기**: 하나은행에서 12칸 실측(공용코드라 우리·새마을 동일 작동). 각 은행 첫 실입력은
  실사완료+미입력 연습건에서 드라이런→육안→--live 순으로 한 번 확인 권장.
