# Amaranth 10 API 요약

> 기준 문서: `doc/amaranth_api/` 아래 공식 PDF 5종 (2026-07-17 판독)
>
> 이 문서는 PDF에 명시된 내용만 정리한다. 문서에 없는 운영 URL, 토큰 만료시간,
> 호출량 제한, 상세 오류 코드는 추정하지 않는다.

## 1. 인증

### 결론

제공된 인증 가이드는 별도의 "토큰 발급 API"를 설명하지 않는다. Amaranth 10
관리자가 연동 시스템을 사전 등록하면 `accessToken`과 `hashKey`가 발급되며,
호출 측은 이 값으로 매 요청마다 인증 헤더와 서명을 만든다.

따라서 현재 문서만으로는 토큰 발급 URL, 발급 파라미터, 만료시간, 갱신 규칙을
구현할 수 없다. 더존에 아래 항목을 확인해야 한다.

- 운영/검증 서버의 정확한 base URL
- `accessToken`과 `hashKey`의 만료 여부 및 재발급 절차
- `callerName`, `groupSeq`의 운영 값
- 허용 IP와 허용 서비스 등록 상태

### 요청 헤더

| 헤더 | 값/규칙 | 필수 |
|---|---|---|
| `callerName` | 더존에서 전달받은 고정 호출 구분명 | 예 |
| `Authorization` | `Bearer {accessToken}` | 예 |
| `transaction-id` | 요청마다 새로 만든 임의의 30자리 문자열 | 예 |
| `timestamp` | 요청 시점 Unix timestamp(초) | 예 |
| `groupSeq` | 더존에서 전달받은 Amaranth 10 그룹 시퀀스 | 예 |
| `wehago-sign` | 아래 HMAC 서명 결과 | 예 |

서명 생성식:

```text
message = accessToken + transaction-id + timestamp + url
wehago-sign = Base64(HMAC-SHA256(key=hashKey, message=message, UTF-8))
```

`url`은 도메인을 제외한 API 경로(예: `/apiproxy/api01A017`)다. API Body는
기존 문서의 구조를 유지한다.

### 비밀정보 취급

스크린샷에 실 운영 가능성이 있는 `accessToken`과 `hashKey`가 포함되어 있다.
두 값은 코드나 이 문서에 옮기지 말고 `.env` 또는 비밀 저장소에서만 관리한다.
노출 가능성이 있다면 더존에서 재발급한다.

## 2. 공통 호출/응답 규약

- 이 문서에서 사용하는 대상 API는 모두 `POST`다.
- 경로는 `/apiproxy/{apiId}` 형식이며, 시스템공통 문서 일부는 `~/apiproxy/...`
  로 표기한다. 실제 호출에서는 base URL 뒤에 `/apiproxy/...`를 붙인다.
- 공통 응답은 `resultCode`, `resultMsg`, `resultData` 구조다.
- 일반 규약은 `resultCode = 0` 성공, 그 외 실패다. 원장 API 실패 예시는 `-1`이다.
- 전체 공통 오류 코드표는 제공된 PDF에 없다. 자동전표 등록의 중복 오류 예시로
  `21010`("데이터 전송중 문제가 발생하였습니다.")만 확인된다.
- 공식 rate limit 값은 제공된 PDF에 없다.

## 3. 거래처 등록/조회

### 거래처 조회 - `api16S11`

`POST /apiproxy/api16S11` (서버 인증)

복수의 일반/금융 거래처를 조회한다.

| 요청 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `coCd` | string(4) | 예 | 회사 코드 |
| `trCd` | string(10) | 아니오 | 거래처 코드 |
| `trNm` | string(60) | 아니오 | 거래처명 |
| `trFg` | string(1) | 아니오 | 거래처 구분 |
| `trFgs` | list | 아니오 | 거래처 구분 다중 조건 |
| `pplNb` | string(100) | 아니오 | 주민등록번호 |
| `regNb` | string(30) | 아니오 | 사업자번호 |
| `attrNm` | string(60) | 아니오 | 거래처 약칭 |
| `ceoNm` | string(30) | 아니오 | 대표자명 |
| `baNb` | string(100) | 조건부 | 신용카드 거래처(`trFg=9`) 조회 시 카드번호 |
| `localCd` | string(4) | 아니오 | 지역코드 |
| `usePagination` | boolean | 아니오 | `true`이면 페이징 |
| `pagingOffset` | number | 아니오 | 0부터 시작하는 오프셋 |
| `pagingCount` | number | 아니오 | 조회 건수 |
| `useDecrypt` | boolean | 아니오 | 계좌번호 복호화 옵션 |
| `confirmDt` | string(14) | 아니오 | 이후 추가·변경분 조회, `yyyyMMddHHmmss` |

`useDecrypt=true`일 때 기본 `pagingCount`는 10,000건이며, 그 이상은
`pagingOffset`과 `pagingCount`를 직접 지정해야 한다.

주요 응답 필드: `trCd`, `trNm`, `trFg`, `regNb`, `pplNb`, `ceoNm`,
`business`, `jongmok`, `zip`, `divAddr1`, `addr2`, `tel`, `fax`, `email`,
`useYn`, `nationCd`, `nationNm`, `pjtCd`, `pjtNm`, 각종 담당자/계좌 필드,
`modifyDt`, `modifyDtRaw`.

거래처 구분(`trFg`): `1` 일반, `2` 수출, `3` 주민, `4` 기타,
`5` 금융기관, `6` 정기예금, `7` 정기적금, `8` 카드사, `9` 신용카드.

### 거래처 등록 - `api16S12`

`POST /apiproxy/api16S12` (서버 인증)

최상위 요청:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `list` | list | 예 | 등록할 거래처 배열 |
| `dupCheck` | boolean | 아니오 | `true` 중복 허용, `false` 중복 불가(기본) |
| `nmBirthGenDupCheck` | boolean | 아니오 | 주민 거래처 이름/생년월일/성별 중복 검사 |
| `insertId` | 문서 미표기 | 아니오 | 등록 관리용 임의 ID |

`list` 항목의 핵심 필드:

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `coCd` | string(4) | 예 | 회사코드 |
| `trNm` | string(60) | 예 | 거래처명 |
| `attrNm` | string(60) | 예 | 거래처 약칭 |
| `trFg` | string(1) | 예 | 거래처 구분 |
| `trCd` | string(10) | 조건부 | `inputFg=1`일 때 외부 지정 코드 |
| `inputFg` | string(1) | 아니오 | `1` 수동 코드, `0`/null 자동채번 |
| `regNb` | string(30) | 아니오 | 사업자번호 |
| `pplNb` | string(100) | 아니오 | 주민 거래처 중복 검사 시 생년월일 6자리+성별 1자리 |
| `ceoNm` | string(30) | 아니오 | 대표자명 |
| `business` / `jongmok` | string(40) | 아니오 | 업태/종목 |
| `zip` | string(7) | 아니오 | 우편번호 |
| `divAddr1` / `addr2` | string(150) | 아니오 | 주소 |
| `tel` / `fax` | string(20) | 아니오 | 전화/팩스 |
| `email` | string(80) | 아니오 | 이메일 |
| `baNb` | string(100) | 조건부 | 계좌번호 입력 시 `jiroCd` 필요 |

거래처 수정은 `api16S13`, 거래처 카운트 조회는 `api16S21`, 금융기관 조회는
`api16S28`이다. 담당자 등록·수정·조회 API도 `api16S14`, `api16S20`,
`api16S24`~`api16S27`, `api16S29`로 별도 제공된다.

## 4. 회계전표 생성/전송

### 자동전표 데이터 등록 - `api11A10`

`POST /apiproxy/api11A10` (서버 인증)

요청은 회사코드와 분개 라인 배열로 구성한다.

```json
{
  "coCd": "2000",
  "data": [
    {
      "inDivCd": "2000",
      "menuDt": "20211222",
      "menuSq": 1,
      "menuLnSq": 1,
      "drcrFg": "3",
      "acctCd": "2550000",
      "acctAm": 10000
    }
  ]
}
```

필수 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| `coCd` | string(4) | 회사코드(최상위) |
| `inDivCd` | string(4) | 회계단위 |
| `menuDt` | string(8) | 작성일자 |
| `menuSq` | number(5) | 작성번호 |
| `menuLnSq` | number(5) | 라인순번 |
| `drcrFg` | string(1) | `3` 차변, `4` 대변 |
| `acctCd` | string(8) | 계정과목 |
| `acctAm` | number(17,4) | 계정금액 |

주요 선택 필드: `isuDoc`, `trCd`, `trNm`, `attrCd`, `rmkDc`, `docuTy`,
부가세 필드(`vatDivCd`, `issDt`, `taxFg`, `supAm` 등), 관리항목
(`ctDept`, `cashCd`, `pjtCd`, `mEmpCd`, `mDivCd` 등), `insertId`, `issNo`,
`exFg`, `dummy2`, `regNb`.

전표유형(`docuTy`): `1` 일반, `2` 매입, `3` 매출, `4` 수금,
`5` 반제, `6` 수정, `7` 본지점, `8` 결산, `9` 결의서.

성공 응답의 `resultData`에는 `coCd`, `divCd`, `menuDt`, `menuSq`,
`menuLnSq`가 포함된다. 동일 작성번호 등의 오류는 라인별 `errorMsg`로 반환된다.

### 관련 자동전표 API

| API | 경로 | 용도 |
|---|---|---|
| `api11A16` | `/apiproxy/api11A16` | 자동전표 데이터 조회 |
| `api11A17` | `/apiproxy/api11A17` | 자동전표 데이터 삭제 |
| `api11A37` | `/apiproxy/api11A37` | 매입매출 자동전표 데이터 등록 |
| `api11A38` | `/apiproxy/api11A38` | 매입매출 자동전표 데이터 조회 |
| `api11A39` | `/apiproxy/api11A39` | 매입매출 자동전표 데이터 삭제 |
| `api11A40` | `/apiproxy/api11A40` | 자동전표 라인순번 조회 |
| `api11A77` | `/apiproxy/api11A77` | 자동전표 데이터 다중 삭제 |

`api11A16`의 필수 조회 조건은 `coCd`, `groupSeq`, `divCd`, `frDt`, `toDt`다.
외부 호출에서는 헤더와 동일한 `groupSeq`를 Body에도 전달한다. 페이징은
`viewPage`, `viewCount`; 처리구분은 `docuFg`(`0` 미발행, `1` 발행), 전표유형
다중 값은 `1|2|` 형식이다.

## 5. 회계 데이터 조회

### 전표출력 조회 - `api11A14`

`POST /apiproxy/api11A14` (서버 인증, 사용자 인증)

필수 조건은 `coCd`, `divCds`, `isuDtFr`, `isuDtTo`다. `divCds` 등 다중 값은
`1000|2000|` 형식이다. 거래처(`trCds`), 계정(`acctStr`), 사용부서,
프로젝트, 승인상태, 전표유형, 금액 범위 등을 선택 필터로 제공한다.
페이징 기본값은 `viewPage=1`, `viewCount=50`이다.

응답 `resultData.datas`의 주요 필드: `isuDt`, `isuSq`, `lnSq`, `fillDt`,
`fillNb`, `acctCd`, `acctNm`, `docuSt`, `drcrFg`, `trCd`, `attrNm`, `rmkDc`,
`drAm`, `crAm`, `acctAm`, `deptCd`, `empCd`, `ctDept`, `pjtCd`, `docuTy`.

### 계정별원장(프로젝트별) - `api11A31`

`POST /apiproxy/api11A31` (서버 인증, 사용자 인증)

필수: `coCd`, `divCds`, `fillDtFrom`, `fillDtTo`, `prtFg`, `acctCd`, `pjtCds`.
`prtFg`는 `1` 계정별, `2` 세목별이다. 응답에는 차변/대변/잔액과 거래처,
프로젝트, 사용부서 등이 포함된다.

### 거래처원장 잔액 - `api11A48`

`POST /apiproxy/api11A48` (서버 인증, 사용자 인증)

필수: `coCd`, `divCds`, `fillDtFrom`, `fillDtTo`, `prtFg`, `acctCd`.
선택: `trFg`, `trCds`, `noCode`, `prtBasis`, `viewPage`, `viewCount`.
응답 주요 필드는 `acctCd`, `acctNm`, `trCd`, `trNm`, `regNb`, `prevAm`,
`drAm`, `crAm`, `restAm`이다.

### 거래처원장 상세 - `api11A49`

`POST /apiproxy/api11A49` (서버 인증, 사용자 인증)

필수: `coCd`, `divCds`, `fillDtFrom`, `fillDtTo`, `prtFg`, `acctCd`, `trFg`,
`trCd`. 응답에는 일자, 적요, 차변/대변/잔액, 거래처, 계좌, 전표번호,
회계단위, 부서, 사원, 프로젝트가 포함된다.

### 매출·비용 집계 구현 시 주의

제공 문서에는 "매출 집계" 또는 "비용 집계" 전용 API가 없다. 중계 서버의
`/api/ledger/sales`, `/api/ledger/expenses`는 `api11A14`, `api11A31`,
`api11A48/49` 결과를 회사의 계정과목 정책에 따라 집계해야 한다. 어떤 계정코드를
매출/비용으로 분류할지는 공식 PDF가 아니라 고객사 회계 기준으로 별도 확정해야 한다.

## 6. 미확정 사항 체크리스트

- 토큰 발급/갱신 API와 만료시간: 문서에 없음
- 운영 및 테스트 base URL: 문서에 확정값 없음
- 공식 전체 오류 코드표: 문서에 없음(별도 "반환 코드 정의" 문서 참조만 존재)
- rate limit: 문서에 없음
- 서버 인증+사용자 인증 API에서 사용자 인증을 추가로 어떻게 전달하는지: 별도 확인 필요
- 매출/비용 계정과목 분류 기준: 고객사 회계 기준 필요

