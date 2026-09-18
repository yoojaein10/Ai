# BankOn — `.gam` → 뱅크온라인(BANK24) 자동입력

감정평가 결과를 `.gam`·의견서·APW DB에서 뽑아 **뱅크온라인 데스크톱 앱(BANK24)** 의
은행별 담보 입력 화면에 자동으로 채워 넣고 저장한다.

GamJun(감정서 데이터화)과 별개 프로젝트다. GamJun은 DB에 적재하고, BankOn은
화면에 입력한다. 파서 모듈 일부(`hwp_parser`, `gam_bridge`, `downloader`,
`resolver`, `db`)는 GamJun에서 이식했다.

## 대상

- 업무구분: **담보만** (탁상·동산담보·공동주택자문 제외)
- 은행: 신한(`TBNKSHG24DAMB`) · 국민(`TBNKKBB24DAMB`) · 기업(`TBNKKIB24DAMB`) · 농협은행(`TBNKNHB24DAMB`)
  + 2026-09-10 인계본 이식: 수협(`TBNKSSB24DAMB`) · 하나(`TBNKHNB24DAMB`) · 우리(`TBNKWRB24DAMB`) · 새마을금고(`TBNKMGB24DAMB`)
  — 이식 4개는 작성 폼 매핑만(화면 슬롯 하나, 다물건은 첫 슬롯만), 현장조사서 폼 미정찰(PDF 등록만), 빈 폼 LIVE 미실시.
  큐 워커는 `gui_settings.ini [run] banks` 에 적힌 은행만 돌린다(기본값에 이식 4개는 없음).
- 조직: **본사(01지사)** 기준

## 흐름

```
문서번호 → ① APW 경로조회 → ② FTP 다운(.gam)+zlib → ③ gamexport(.gam → 테이블 JSON + HWP)
        → ④ 의견서/명세 파싱 ⑤ APW DB 조회 → ⑥ 은행별 필드 매핑 → ⑦ 화면 입력 + 저장
```

## 데이터 출처

| 뱅크온라인 항목 | 출처 | 확보율 |
|---|---|---|
| 담보종류·담보용도·담보세부종류·용도지역·건물구조·지목·내용/잔존연수·등기번호 | **`.gam` `mullist*`** (신한 전용) | 신한 건의 73%, 그 안에서 94~100% |
| 법정동코드·번지구분·본번지·부번지 | `apw_masterex` REG/EUB/SAN/BUN1/BUN2 | 97.8% |
| 심사자 | `APW_Judgment`(itype=2) ⟕ `TMWCMN_USR_BAC_INFO` | 담보 34% |
| 평가사(복수) | `apw_masterex.manager` | 담보 75% |
| 대표·지사장 | `gam_info.President` / `apw_office.Boss` | ~100% |
| 수수료 계좌·예금주 | `APW_Bill.Account` | 값 있는 건 100% 파싱 (본사 담보 74%가 값 보유) |
| 물건특성 8종 | 의견서 `그 밖의 사항` 표 | 2026 신한 10.6% (없으면 기본값) |
| 표준지 3종 | 의견서 `감정평가 개요` 비교표준지표(`선정` 행) | 50% |
| 소재지·준공일자·총층수 | 의견서 `대상물건 개요` | 85~97% |

**비워두는 항목**: 총세대수(4개 소스에 없음), 재평가 할인 6종(보류),
`mullist` 없는 신한 건의 담보종류·담보용도, 점검항목(사람 판단).

## 설치

```bash
pip install -r requirements.txt
cp .env.example .env   # 값 채우기 — 자격증명은 여기에만
python -m pytest -q
```

`gamexport.exe`는 GamJun 것을 그대로 쓴다(`GAMEXPORT_EXE` 경로).

## 배포 (단일 exe, 2026-08-31)

`python -m PyInstaller --noconfirm bankon_gui.spec` → `dist/BankOn.exe` 하나에 GUI·러너(tools)·src·recon/*.md·gamexport.exe 가 전부 들어간다.
배포 = **BankOn.exe + .env + gui_settings.ini** 세 파일을 한 폴더에. 업데이트는 exe 만 교체. Python 설치 불필요.
큐 워커는 러너를 `BankOn.exe --runner run_kb_full …` 로 자기 재호출한다(`gui_bankon._run_bundled_runner`, `bankon/paths.py`).
`.env` 의 GAMEXPORT_EXE/WORK_DIR/OUTPUT_DIR 을 비우면 번들 gamexport 와 exe 옆 work/·output/ 을 쓴다.

## 실행

```bash
PYTHONPATH=src python -m bankon.cli open 01-2608-3-2529   # 작성 폼까지 열기
PYTHONPATH=src python -m bankon.cli dump 01-2608-3-2529   # 열고 현재 값 출력(읽기 전용)
```

### 화면 이동 흐름 (실물 확인)

```
KadcLoader.exe Bank24 -e
  → TDXLoginDialog      라벨 없는 TEdit 2개(위=아이디, 아래=비밀번호) → '확인'
  → TfrmMain            [금융기관온라인 메인] MDI
  → 감정서조회 칸에 번호 → **'찾 기'**  (※'조 회'는 기간 조회라 목록이 안 좁혀진다)
  → 그리드 첫 행 좌클릭 → 우클릭 → 컨텍스트 메뉴(#32768) → '작 성(열람)' = 가속키 A
  → TBNKSHG24DAMB / TBNKKBB24DAMB
```

**함정 3가지** (실제로 겪고 고친 것):
- `조 회`가 아니라 **`찾 기`** 여야 문서번호로 1건이 된다
- 편집칸은 껍데기(`TcxTextEdit`)가 아니라 **안쪽(`TcxCustomInnerTextEdit`)** 에 써야 값이 들어간다
- 컨텍스트 메뉴는 표준 팝업이라 컨트롤로 못 읽는다 → **가속키**로 고른다

## 화면 정찰 도구

은행 폼이 늘어나면 아래 순서로 항목을 수집한다. **전부 읽기 전용**이고,
콤보 수집만 드롭다운을 열었다 ESC로 닫는다(값 변경 시 즉시 중단하는 안전장치 있음).

```bash
python tools/inspect_bankon.py list                      # 창 목록
python tools/inspect_bankon.py dump --handle 0x...       # 컨트롤 트리
python tools/map_fields.py --handle 0x...                # 라벨↔입력칸 매칭 → 항목표
python tools/list_combo_items.py --handle 0x... --probe  # 콤보 선택지 수집
```

수집 결과는 `recon/` 에 있다.

## 주의

- 뱅크온라인은 Delphi VCL + DevExpress. 라벨과 입력칸이 별개 컨트롤이라 **좌표로 짝짓는다**.
- DevExpress 콤보 목록은 그려진 픽셀이라 `item_texts()`·UIA 모두 못 읽는다 →
  드롭다운을 열고 방향키로 훑어 읽는다.
- 의견서 용어는 `내용**연**수`, 뱅크온라인 라벨은 `내용**년**수` — 검색어 주의.
