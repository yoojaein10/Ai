# BankOn — 기업은행 담보 auto-fill 인계 번들

BANK24(금융기관 온라인게이트) **기업은행 담보 감정결과를 자동입력**하는 도구 모음.
`.gam`(감정서) 추출 → 기업 매핑(`ibk.py`) → 화면 자동입력. 검증까지 포함.

> ⚠️ 기업만 떼면 안 돌아갑니다 — `src/bankon` 은 한 덩어리 라이브러리라(build_context가
> 국민·신한 파서까지 물음) 통째로 넣었습니다. **기업 전용은 아래 3파일**뿐입니다.

## 폴더 구조
```
src/bankon/           라이브러리 (통째, 수정 불필요)
   mapping/ibk.py     ★ 기업 매핑 (핵심)
   parse/·sources/·ui/·codes/·model·gam_bridge·resolver·downloader·db·config
tools/
   verify_fill_ibk.py ★ 기업 검증 (화면 대조)
   autofill_ibk.py    ★ 기업 자동입력
   verify_form.py     build_context (.gam+DB → 데이터 조립)
   verify_grid_loop.py 무인 순회(--bank ibk)
   inspect_bankon·map_fields  폼 필드 읽기
   verify_fill_kb·autofill_kb  (국민, 공용헬퍼 fetch_gam_local 때문에 포함)
bin/gamexport.exe     delphi .gam 추출기
.env.example          접속/경로 템플릿 → 값 채워 .env 로 저장
requirements.txt      python 의존성
```
**★ 기업 전용 = ibk.py · verify_fill_ibk.py · autofill_ibk.py (3개).** 나머지는 공용.

## 셋업
1. `pip install -r requirements.txt` (pywinauto·pyodbc 등)
2. `.env.example` → 값 채워 `.env` 로 저장 (DB 192.0.2.10 · FTP 192.0.2.10 · gamexport 경로)
3. `bin/gamexport.exe` 경로가 `.env` 의 `GAMEXPORT_EXE` 와 맞는지 확인
4. `PYTHONPATH=src:tools python -m pytest -q` → 통과하면 환경 정상 (176개)
5. BANK24 실행 + 로그인 (검증하려는 폼/그리드 띄우기)

## 사용법
```bash
# 단건 검증 (화면에 기업 담보폼 열어둔 상태)
python tools/verify_fill_ibk.py 01-2608-3-2683
#  → ✅일치 / ❌불일치 / 🖊우리채움(화면빈칸) / 📄화면만
#  ※ 열린 폼과 문서번호가 같아야 정확

# 무인 그리드 순회 (관리자 권한)
python tools/verify_grid_loop.py --bank ibk --log out.txt --max 20 --cleanup

# 자동입력 (드라이런 → 실입력)
python tools/autofill_ibk.py 01-2608-3-2683           # 계획만(안전)
python tools/autofill_ibk.py 01-2608-3-2683 --live    # 실입력(빈칸만, 연습건 먼저!)
```
- **실사완료 문서만** 대상(= .gam 존재). 지표 = `apw_masterex.ConductDate`(있으면 OK). ReportDate 아님.
- 자동입력 안전: 기본 드라이런 · --live도 빈칸만 · 되읽기검증 · 다물건 순번정합 · 사람이 저장.

## 기업 매핑 상세 / 남은 것
`기업은행_담보_인계.md` 참고 (필드매핑·엣지·해결방향). 요약:
- **정확**: 감정평가액·토지/건물/기계기구/기타 평가금액·면적·평가단가·본번/부번·법정동·수수료·기준시점·등기·부동산구분·소재지·건물구조(집합건물).
- **남은 것**: 물건종류(소스 애매, 공업용→공장만 매핑)·담보구분·동/호(라벨 문제)·콤보/라벨없는칸 자동입력(v2).

## 은행 추가 방법 (앞으로)
새 은행 = **`src/bankon/mapping/<bank>.py` + `tools/verify_fill_<bank>.py` + `autofill_<bank>.py`** 3개만 추가.
공용(파서·추출·입력드라이버)은 그대로 재사용. `verify_grid_loop.py` 의 `BANKS`/`FILLERS` 에 은행 등록.
폼 클래스는 `inspect_bankon`/`map_fields` 로 파악.
