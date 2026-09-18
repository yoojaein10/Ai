import re
import hashlib
import pyodbc
from datetime import datetime, date, timedelta


def _make_conn_str(db_config: dict) -> str:
    driver   = db_config.get("driver", "ODBC Driver 17 for SQL Server")
    server   = db_config.get("server", "")
    port     = str(db_config.get("port", "1433"))
    database = db_config.get("database", "")
    username = db_config.get("username", "")
    password = db_config.get("password", "")
    trust    = db_config.get("trust_server_certificate", True)
    trust_str = "yes" if str(trust).lower() in ("true", "yes", "1") else "no"
    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"TrustServerCertificate={trust_str};"
    )


def normalize_cust_docid(value) -> str:
    """의뢰번호 정규화: 앞뒤 공백 제거, 엑셀식 작은따옴표 prefix 제거.
    앞자리 0 유지, 숫자 변환 금지. 빈값 → ""
    """
    s = str(value or "").strip()
    if s.startswith("'"):
        s = s[1:].strip()
    return s


def fetch_kapa_credentials(db_config: dict, user_name: str = "이일우") -> tuple[str, str]:
    """실서버 KAPA 계정을 조회한다. 조회값은 로그나 예외 메시지에 포함하지 않는다."""
    conn = None
    try:
        conn = pyodbc.connect(_make_conn_str(db_config), timeout=10)
        cur = conn.cursor()
        cur.execute(
            "SELECT Kapa_Id, Kapa_Pw "
            "FROM apworksdw.dbo.Apw_YJI_KapaID_List "
            "WHERE User_Name = ?",
            (str(user_name or "").strip(),),
        )
        row = cur.fetchone()
        if row is None:
            raise LookupError("KAPA_CREDENTIALS_NOT_FOUND")
        user_id = str(row[0] or "").strip()
        user_pass = str(row[1] or "")
        if not user_id or not user_pass:
            raise LookupError("KAPA_CREDENTIALS_EMPTY")
        return user_id, user_pass
    except (LookupError,):
        raise
    except Exception as exc:
        raise RuntimeError("KAPA_CREDENTIALS_LOOKUP_FAILED") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def find_existing_cust_docids(
    db_config: dict,
    cust_docids,
    log=None,
) -> dict:
    """APW_Master에 이미 저장된 CustDocID 집합 조회.

    반환: {"ok": bool, "existing": set[str], "error": str}
    - ok=False 시 existing=set() (전체 SKIP 금지, 최종 SP 직전 재확인)
    - 빈 목록이면 DB 연결 없이 즉시 반환
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    normalized = list(dict.fromkeys(
        d for d in (normalize_cust_docid(v) for v in cust_docids) if d
    ))

    if not normalized:
        return {"ok": True, "existing": set(), "error": ""}

    conn = None
    existing = set()
    try:
        conn = pyodbc.connect(_make_conn_str(db_config), timeout=10)
        cur = conn.cursor()
        BATCH = 500
        for start in range(0, len(normalized), BATCH):
            batch = normalized[start:start + BATCH]
            placeholders = ",".join("?" * len(batch))
            sql = (
                f"SELECT CustDocID FROM dbo.APW_Master "
                f"WHERE Office = ? AND CustDocID IN ({placeholders})"
            )
            cur.execute(sql, ["11"] + batch)
            for row in cur.fetchall():
                val = normalize_cust_docid(row[0])
                if val:
                    existing.add(val)
        try:
            cur.close()
        except Exception:
            pass
        return {"ok": True, "existing": existing, "error": ""}
    except Exception as e:
        _log(f"[DB][DUP-CHECK][WARN] 기존 의뢰번호 조회 실패: {type(e).__name__}")
        return {"ok": False, "existing": set(), "error": type(e).__name__}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _parse_address(addr: str) -> dict:
    """주소에서 San, Bun1, Bun2, address_body 추출.

    반환: {"address_body": str, "San": int, "Bun1": str, "Bun2": str}

    San 규칙: 일반 지번 → 1 / 산 지번 → 2 / 주소 없음/미파싱 기본값 → 1

    탐색 우선순위:
    1단계: 산 지번 + 번지 키워드 (주소 전체)
    2단계: 일반 지번 + 번지 키워드 (주소 전체) — false positive 방지용
    3단계: 번지 없이 주소 끝 숫자 fallback
    """
    addr = re.sub(r'\s+', ' ', addr).strip()
    addr = re.sub(r"(?<=\d)\s*-\s*(?=\d)", "-", addr)

    # 1단계: 산 지번 + "번지" 키워드 — 주소 어디서든 매칭
    # 예: "정남면 산 220-5번지 건물명", "정남면 산220번지"
    m = re.search(r'(?<!\S)산\s*(\d+)(?:-(\d+))?\s*번지', addr)
    if m:
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 2,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    # 2단계: 일반 지번 + "번지" 키워드 — 주소 어디서든 매칭
    # 반드시 앞에 공백이 있어야 함 → "광희동2가"의 "2"를 오인하지 않음
    # 예: "명일동 47-12번지 건물명", "광희동2가 359번지"
    m = re.search(r'\s(\d+)(?:-(\d+))?\s*번지', addr)
    if m:
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 1,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    # 2.3단계: 지번 + 호수 패턴 — "동/읍/면/리 + 지번 + 제N호" 구조
    # 끝 숫자 fallback보다 앞에 배치해 후속 지번을 대표 지번으로 오인 방지
    # 예: "마곡동 774-2 제1202호. 791-7" → Bun1=774, Bun2=2
    m = re.match(
        r'^(?P<body>.+?(?:동|읍|면|리))\s+(?P<bun1>\d+)(?:-(?P<bun2>\d+))?\s+(?P<ho>(?:제\s*)?\d+\s*호)',
        addr,
    )
    if m:
        return {
            "address_body": m.group("body").strip(),
            "San": 1,
            "Bun1": m.group("bun1"),
            "Bun2": m.group("bun2") or "",
        }

    # 2.4단계: 지목 토큰 + 지번 + 건물상세 구조 (지번 뒤 suffix 있는 경우만)
    # 예: "서울특별시 송파구 문정동 일반 645-2 에이치비지니스파크 C 712,713,714,715"
    m = re.match(
        r'^(?P<body>.+?)\s+(?:일반|대|전|답|임야|잡종지|공장용지|도로|과수원|목장용지|창고용지|주차장|체육용지|종교용지|학교용지|하천|구거|유지|공원|묘지|기타)\s+(?P<bun1>\d+)(?:-(?P<bun2>\d+))?(?=\s+.+)',
        addr,
    )
    if m:
        body = re.sub(r'\s+', ' ', m.group('body')).strip()
        return {
            "address_body": body,
            "San": 1,
            "Bun1": m.group('bun1'),
            "Bun2": m.group('bun2') or "",
        }

    # 2.4.1단계: 지목 토큰 + 지번 (suffix 없이 끝나는 경우)
    # 예: "선유리 일반 1372-8", "금곡동 일반 599-2", "목동 일반 499-2"
    # \s+지목\s+ 요구 → "대전광역시"의 "대" 같은 지명 일부 미매칭
    m = re.match(
        r'^(?P<body>.+?)\s+(?:일반|대|전|답|임야|잡종지|공장용지|도로|하천|구거|유지|창고용지)\s+(?P<bun1>\d+)(?:-(?P<bun2>\d+))?\s*$',
        addr,
    )
    if m:
        body = re.sub(r'\s+', ' ', m.group('body')).strip()
        return {
            "address_body": body,
            "San": 1,
            "Bun1": m.group('bun1'),
            "Bun2": m.group('bun2') or "",
        }

    # 2.5단계: 콤마 다중 지번 — 첫 번째 지번이 대표값
    # 예: "귤현동 287-1, 287-7, 287-8" → San=1, Bun1=287, Bun2=1
    m = re.search(r'(?<!\S)산\s*(\d+)(?:-(\d+))?\s*,\s*\d+(?:-\d+)?', addr)
    if m:
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 2,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    m = re.search(r'\s(\d+)(?:-(\d+))?\s*,\s*\d+(?:-\d+)?', addr)
    if m:
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 1,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    # 2.5.1단계: "외 n필지" 패턴 — "193-1외 1필지", "193-1 외 1 필지"
    # 기존 2.5 콤마 다중 지번 이후, 2.6 정수지번 이전에 배치
    m = re.search(r'(?<!\S)산?\s*(\d+)-(\d+)\s*외\s*\d+\s*필지', addr)
    if m:
        is_san = '산' in m.group(0)
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 2 if is_san else 1,
            "Bun1": m.group(1),
            "Bun2": m.group(2),
        }

    # 2.6단계: 행정동/읍/면/리 + 3~4자리 정수 지번 + 한글 건물명 + 호수
    # 예: "식사동 1529 위시티일산자이 주상복합 119-1호"
    # 하이픈 지번/번지/지목보다 낮은 우선순위, 건물명+호수 동시 존재 필수
    m = re.match(
        r'^(?P<body>.+?(?:동|읍|면|리))\s+(?P<bun1>\d{3,4})(?=\s+[가-힣].+(?:\d+-\d+|\d+)\s*호)',
        addr,
    )
    if m:
        return {
            "address_body": m.group('body').strip(),
            "San": 1,
            "Bun1": m.group('bun1'),
            "Bun2": "",
        }

    # 2.7단계: 행정구역 + 지번 + suffix 있는 경우 (HUG 세부주소 패턴)
    # 예: "화곡동 938-11 805" → body=화곡동, Bun1=938, Bun2=11 (suffix=805는 건물상세)
    # 예: "논현동 40-0 103 101" → body=논현동, Bun1=40, Bun2=0
    # suffix 없으면 3단계로 진행 (봉천동 649-36 등 정상 케이스 영향 없음)
    m = re.match(
        r'^(?P<body>.+?(?:동|가|리|읍|면))\s+(?P<bun1>\d+)(?:-(?P<bun2>\d+))?\s+(?P<suffix>\S.*)$',
        addr,
    )
    if m:
        return {
            "address_body": m.group("body").strip(),
            "San": 1,
            "Bun1": m.group("bun1"),
            "Bun2": m.group("bun2") or "",
        }

    # 3단계: "번지" 없이 주소 끝 숫자 fallback — 끝부분에만 적용
    # 산 지번 끝: "정남면 산 220-5", "산69-6"
    m = re.search(r'(?<!\S)산\s*(\d+)(?:-(\d+))?\s*$', addr)
    if m:
        return {
            "address_body": addr[:m.start()].rstrip(),
            "San": 2,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    # 일반 지번 끝: "광희동2가 359", "정남면 220-4", "107-65"
    # 단, 뒤에 한글이 오면 매칭 안 함 (동/가/길 등 주소 구성요소 방지)
    m = re.search(r'(?<!\S)(\d+)(?:-(\d+))?\s*$', addr)
    if m:
        # 매칭된 숫자 바로 앞 토큰이 한글로 끝나는지 확인 (지번일 가능성)
        preceding = addr[:m.start()]
        # 앞 토큰이 한글+숫자+한글 형태(광희동2가, 상계3동 등)면 그 숫자가 지번 아님
        # → 이미 \s 앞에서 분리됐으므로 m.start() 이전에 공백이 있어야 정상
        return {
            "address_body": preceding.rstrip(),
            "San": 1,
            "Bun1": m.group(1),
            "Bun2": m.group(2) or "",
        }

    san = 2 if re.search(r'\b산\b', addr) else 1
    return {"address_body": addr, "San": san, "Bun1": "", "Bun2": ""}


def _format_bun(value) -> str:
    """Bun1/Bun2를 4자리 zero-padding 문자열로 변환. 빈값이면 '0000'."""
    s = str(value or "").strip()
    if not s:
        return "0000"
    if s.isdigit() and len(s) <= 4:
        return s.zfill(4)
    return s


# 시·도 약칭 → 공식 명칭 후보. 원본 address_body는 변경하지 않고 AS1 조회에만 사용.
_SIDO_ALIAS: dict[str, list[str]] = {
    "경북": ["경상북도"],
    "경남": ["경상남도"],
    "충북": ["충청북도"],
    "충남": ["충청남도"],
    "전북": ["전북특별자치도", "전라북도"],
    "전남": ["전라남도"],
    "강원": ["강원특별자치도", "강원도"],
    "제주": ["제주특별자치도", "제주도"],
}


def _expand_sido(token: str) -> list:
    """시·도 첫 토큰에서 AS1 조회용 후보 목록 반환. 원본 우선, 공식명 추가, 중복 제거.
    공식 명칭(경상북도 등)이 이미 입력된 경우 그대로 1개만 반환."""
    seen: set = set()
    result: list = []
    for cand in [token] + _SIDO_ALIAS.get(token, []):
        if cand not in seen:
            seen.add(cand)
            result.append(cand)
    return result


def lookup_reg_eub(conn, address_body: str,
                   reg_lookup_table: str = "apworksdw.dbo.APW_RegHist") -> dict:
    """address_body로 APW_RegHist 조회 → Reg/Eub/AS1~AS4/official_addr 반환.

    반환: {"Reg": str, "Eub": str, "matched": bool, "source": str,
           "NAME": str, "AS1": str, "AS2": str, "AS3": str, "AS4": str,
           "official_addr": str}
    """
    empty = {
        "Reg": "", "Eub": "", "matched": False, "source": "",
        "NAME": "", "AS1": "", "AS2": "", "AS3": "", "AS4": "",
        "official_addr": "",
    }
    if not address_body:
        return empty

    tokens = [t for t in address_body.split() if t]
    if not tokens:
        return empty

    cur = conn.cursor()

    def _q(conds, params):
        sql = (
            f"SELECT TOP 5 REG, EUB, NAME, AS1, AS2, AS3, AS4 "
            f"FROM {reg_lookup_table} "
            f"WHERE FUSE='1' AND {' AND '.join(conds)}"
        )
        cur.execute(sql, params)
        return cur.fetchall()

    t = tokens
    strategies = []

    if len(t) >= 4:
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS3 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%", f"{t[2]}%", f"{t[3]}%"],
        ))
        # AS3 NULL 도시지역 (시-구-동 구조)
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%", f"{t[-1]}%"],
        ))
        # 3번째 토큰이 AS2인 경우 (예: 안산시-상록구-팔곡일동)
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[2]}%", f"{t[-1]}%"],
        ))

    if len(t) >= 5:
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS3 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%", f"{t[3]}%", f"{t[4]}%"],
        ))
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS3 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%", f"{t[2]}%", f"{t[4]}%"],
        ))

    if len(t) >= 3:
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?", "AS4 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%", f"{t[2]}%"],
        ))

    if len(t) >= 2:
        strategies.append((
            ["AS1 LIKE ?", "AS2 LIKE ?"],
            [f"{t[0]}%", f"{t[1]}%"],
        ))

    strategies.append((["AS1 LIKE ?"], [f"{t[0]}%"]))

    # 시·도 약칭 확장: 원본 토큰 먼저, 이후 공식 명칭 후보 순으로 시도.
    # address_body 자체는 변경하지 않고 AS1 파라미터에만 적용.
    as1_candidates = _expand_sido(t[0])

    for conds, params in strategies:
        tried_as1: set = set()
        for as1_cand in as1_candidates:
            as1_param = f"{as1_cand}%"
            if as1_param in tried_as1:
                continue
            tried_as1.add(as1_param)
            expanded_params = [as1_param] + params[1:]
            rows = _q(conds, expanded_params)
            if rows:
                reg  = (rows[0][0] or "").strip()
                eub  = (rows[0][1] or "").strip()
                name = (rows[0][2] or "").strip()
                as1  = (rows[0][3] or "").strip()
                as2  = (rows[0][4] or "").strip()
                as3  = (rows[0][5] or "").strip()
                as4  = (rows[0][6] or "").strip()
                official_addr = " ".join(p for p in [as1, as2, as3, as4] if p)
                return {
                    "Reg": reg, "Eub": eub, "matched": True, "source": reg_lookup_table,
                    "NAME": name, "AS1": as1, "AS2": as2, "AS3": as3, "AS4": as4,
                    "official_addr": official_addr,
                }

    return empty


def _should_use_official_addr(parsed_body: str, lu_reg: dict) -> bool:
    """APW_RegHist 공식 주소를 SP @ADDR에 써도 안전한지 판단.

    True 조건:
    1. matched=True
    2. official_addr 비어있지 않음
    3. AS2 비어있지 않음
    4. AS4 비어있지 않음
    5. parsed_body 마지막 토큰이 AS4 또는 NAME과 일치
    """
    if not lu_reg.get("matched"):
        return False
    official_addr = lu_reg.get("official_addr", "")
    if not official_addr:
        return False
    as2 = lu_reg.get("AS2", "")
    if not as2:
        return False
    as4 = lu_reg.get("AS4", "")
    if not as4:
        return False
    body = (parsed_body or "").strip()
    if not body:
        return False
    last_token = body.split()[-1]
    name = lu_reg.get("NAME", "")
    return last_token == as4 or (name and last_token == name)


_CUST_TABLE = "apworksdw.dbo.APW_Customer"
_BRANCH_SUFFIXES = ("지점", "금융센터", "센터", "영업부", "본점", "출장소")

# 농협중앙회 지역농협 영업점명 정규화 상한(병적/장문 입력 fail-closed)
_NH_OFFICE_MAX_LEN = 100


def _has_forbidden_ctrl(s: str) -> bool:
    """NUL·CR/LF 등 제어문자 포함 여부(포함 시 매칭 실패 처리용)."""
    return any(ord(ch) < 0x20 or ch == "\x7f" for ch in (s or ""))


def _safe_ref(doc_id: str) -> str:
    """의뢰번호 원문 대신 로그용 비식별 참조(짧은 해시). 원문을 노출하지 않는다."""
    s = (doc_id or "").strip()
    if not s:
        return "none"
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()[:10]


def normalize_nonghyup_office_name(name: str):
    """'○○농협 △△지점' → '○○농업협동조합 △△지점' (지역농협 명칭 끝의 '농협'만 변환).

    반환: 정규화 문자열. 비정상 입력은 None(fail-closed).
    - 앞뒤 공백 제거 + 연속 공백 1칸 정규화
    - 제어문자/NUL/CR/LF 포함 또는 상한 초과 → None
    - '농협'이 한글 뒤 + (공백|끝) 위치일 때만 변환(앵커드). 문장 내부·독립 '농협' 제외
    - '농협은행'/'NH농협은행'은 '농협' 뒤가 '은행'이라 변환되지 않음
    - 이미 '농업협동조합'인 이름은 해당 토큰이 없어 중복 변환되지 않음
    - 단순 앵커드 치환이라 병적 입력에서도 과도한 백트래킹이 없음
    """
    if name is None:
        return None
    s = str(name)
    if _has_forbidden_ctrl(s):
        return None
    if len(s) > _NH_OFFICE_MAX_LEN:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return None
    # 한글 바로 뒤 + (공백|문자열끝)인 '농협'만 '농업협동조합'으로 치환.
    return re.sub(r"(?<=[가-힣])농협(?=\s|$)", "농업협동조합", s)


def _like_escape(s: str) -> str:
    """SQL Server LIKE 특수문자 이스케이프 (ESCAPE '\\' 전제).

    순서: 먼저 escape 문자 '\\', 그다음 %,_,[,]. 이후 코드가 %접두·접미를 붙인다.
    사용자 입력의 %,_,[,],\\ 가 LIKE 패턴으로 해석되지 않게 한다.
    """
    s = s.replace("\\", "\\\\")
    for ch in ("%", "_", "[", "]"):
        s = s.replace(ch, "\\" + ch)
    return s


def _rank_nh(rows):
    """농협중앙회 후보 결정론적 정렬: Active='Y' 우선 → 짧은 이름 → CustID."""
    def key(r):
        cid, cname, active = r
        cid    = cid    or ""
        cname  = cname  or ""
        active = active or ""
        s = 0
        if active == 'Y':
            s -= 100
        s += len(cname)
        return (s, cid)
    return sorted(rows, key=key)


def _lookup_nh_jungang_regional(conn, branch_name: str) -> dict:
    """농협중앙회 지역농협 거래처 조회 (조회 전용, 쓰기 트랜잭션 없음).

    후보 우선순위:
      1) 변환된 영업점 전체 이름 정확 매칭
      2) 원본 영업점 전체 이름 정확 매칭
      3) 변환된 영업점 이름 안전한 부분 매칭(LIKE ESCAPE)
      4) 원본 영업점 이름 안전한 부분 매칭(LIKE ESCAPE)
    '농협중앙회%' bank_only fallback을 사용하지 않으며, 정상 후보가 없으면
    다른 농협중앙회 지점을 선택하지 않고 fail-closed(matched=False, 빈 값)한다.
    모든 검색값은 ? 파라미터 바인딩으로만 전달한다.
    """
    empty = {"CustCode": "", "matched": False, "CustName": "", "method": "", "multi": False}
    raw = branch_name or ""
    # fail-closed: 제어문자/NUL/CR/LF·장문 입력
    if _has_forbidden_ctrl(raw) or len(raw) > _NH_OFFICE_MAX_LEN:
        return empty
    original = re.sub(r"\s+", " ", raw).strip()
    if not original:
        return empty
    transformed = normalize_nonghyup_office_name(original)

    cur = conn.cursor()

    def _q_exact(name):
        cur.execute(
            f"SELECT CustID, CustName, Active FROM {_CUST_TABLE} "
            f"WHERE Office='11' AND CustName = ?",
            [name],
        )
        return cur.fetchall()

    def _q_partial(name):
        pattern = "%" + _like_escape(name) + "%"
        cur.execute(
            f"SELECT CustID, CustName, Active FROM {_CUST_TABLE} "
            f"WHERE Office='11' AND CustName LIKE ? ESCAPE '\\'",
            [pattern],
        )
        return cur.fetchall()

    candidates = []
    has_transform = bool(transformed) and transformed != original
    if has_transform:
        candidates.append((_q_exact,   transformed, "nh_regional_exact_transformed"))
    candidates.append((_q_exact,   original,    "nh_regional_exact_original"))
    if has_transform:
        candidates.append((_q_partial, transformed, "nh_regional_partial_transformed"))
    candidates.append((_q_partial, original,    "nh_regional_partial_original"))

    for query, name, method in candidates:
        rows = query(name)
        if rows:
            best = _rank_nh(rows)[0]
            return {
                "CustCode": (best[0] or "").strip(),
                "matched":  True,
                "CustName": (best[1] or "").strip(),
                "method":   method,
                "multi":    len(rows) > 1,
            }
    return empty


def lookup_cust_code(conn, bank_name: str, branch_name: str) -> dict:
    """bank_name + branch_name 기반으로 APW_Customer에서 CustID 조회.

    반환: {"CustCode": str, "matched": bool, "CustName": str, "method": str, "multi": bool}
    """
    empty = {"CustCode": "", "matched": False, "CustName": "", "method": "", "multi": False}
    bank_name   = (bank_name   or "").strip()
    branch_name = (branch_name or "").strip()
    # 농협중앙회 지역농협은 전용 경로로 처리(다른 지점 bank_only fallback 금지, fail-closed).
    # 다른 은행/농협은행의 아래 일반 검색 동작은 변경하지 않는다.
    if bank_name == "농협중앙회":
        return _lookup_nh_jungang_regional(conn, branch_name)
    if not bank_name and not branch_name:
        return empty

    full_name = f"{bank_name} {branch_name}".strip() if branch_name else bank_name

    # branch_name suffix 보정 후보
    branch_variants = [branch_name] if branch_name else []
    if branch_name and not any(branch_name.endswith(s) for s in _BRANCH_SUFFIXES):
        branch_variants.append(branch_name + "지점")

    cur = conn.cursor()

    def _q(extra_conds, params, active_only):
        conds = ["Office='11'"]
        if active_only:
            conds.append("Active='Y'")
        conds.extend(extra_conds)
        sql = (
            f"SELECT CustID, CustName, Active "
            f"FROM {_CUST_TABLE} WHERE {' AND '.join(conds)}"
        )
        cur.execute(sql, params)
        return cur.fetchall()

    def _rank(rows):
        def key(r):
            cid, cname, active = r
            cid    = cid    or ""
            cname  = cname  or ""
            active = active or ""
            s = 0
            if active == 'Y':                              s -= 100
            if bank_name   and cname.startswith(bank_name): s -= 10
            if branch_name and branch_name in cname:        s -= 5
            s += len(cname)
            return (s, cid)
        return sorted(rows, key=key)

    def _try(active_only):
        suffix = "" if active_only else "_inactive_fallback"

        # 1차: 정확 매칭
        rows = _q(["CustName=?"], [full_name], active_only)
        if rows:
            return _rank(rows), f"exact_active{suffix}" if active_only else f"exact{suffix}"

        # 2차: LIKE 부분 매칭 (branch_name 변형 포함)
        for bv in branch_variants:
            if bank_name and bv:
                rows = _q(
                    ["CustName LIKE ?", "CustName LIKE ?"],
                    [f"{bank_name}%", f"%{bv}%"],
                    active_only,
                )
                if rows:
                    method = "partial_active" if active_only else "partial_inactive_fallback"
                    if bv != branch_name:
                        method += "_suffix_corrected"
                    return _rank(rows), method

        # 3차: 은행명 LIKE만
        if bank_name:
            rows = _q(["CustName LIKE ?"], [f"{bank_name}%"], active_only)
            if rows:
                return _rank(rows), f"bank_only{'_inactive_fallback' if not active_only else ''}"

        return [], ""

    ranked, method = _try(active_only=True)
    if not ranked:
        ranked, method = _try(active_only=False)
    if not ranked:
        return empty

    best = ranked[0]
    return {
        "CustCode": (best[0] or "").strip(),
        "matched":  True,
        "CustName": (best[1] or "").strip(),
        "method":   method,
        "multi":    len(ranked) > 1,
    }


def _to_date(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None


def extract_debtor_from_bigo(bigo: str) -> str:
    """비고 텍스트에서 '채무자:' 뒤 값을 추출. 없으면 빈 문자열 반환."""
    if not bigo:
        return ""
    m = re.search(
        r'채무자\s*:\s*(.+?)(?=[/\n]|현장안내:|HP:| 본사|센터담당:|$)',
        bigo,
    )
    return m.group(1).strip() if m else ""


def has_unit_no(addr: str) -> bool:
    """소재지에 호수(동/층/호)가 있으면 True. 호선·호수공원 등 지명은 제외."""
    if not addr:
        return False
    # 기존: "호" 포함 패턴
    if re.search(r'(?:제\s*)?(?:[A-Za-z]\s*)?\d+\s*호(?=$|[\s,)/])', addr):
        return True
    # suffix 탐색: 번지 → 지목 → 끝숫자 순
    # 예: "경기 하남시 신장동 427-93번지 베라시떼 1-2001"
    # 예: "서울특별시 송파구 문정동 일반 645-2 에이치비지니스파크 C 712,713,714,715"
    m = re.search(r'\s산?\s*\d+(?:-\d+)?\s*번지', addr)
    if not m:
        m = re.search(r'\s(?:일반|대|전|답|임야|잡종지|공장용지|도로|과수원|목장용지|창고용지|주차장|체육용지|종교용지|학교용지|하천|구거|유지|공원|묘지|기타)\s+\d+(?:-\d+)?\s+', addr)
    if not m:
        m = re.search(r'\s산?\s*\d+(?:-\d+)?\s*$', addr)
    if m:
        suffix = addr[m.end():].strip()
        if re.search(r'[가-힣A-Za-z][가-힣A-Za-z0-9\s]*\s+\d{1,4}-\d{1,4}$', suffix):
            return True
        if re.search(r'[가-힣A-Za-z][가-힣A-Za-z0-9\s]*\s+[A-Za-z가-힣]{1,3}\s+\d{1,4}(?:,\s*\d{1,4})+', suffix):
            return True
    # 2.7단계: 행정구역 + 지번 + suffix 숫자 패턴 (HUG 세부주소)
    m27 = re.match(
        r'^.+?(?:동|가|리|읍|면)\s+\d+(?:-\d+)?(?=\s+\S)',
        addr,
    )
    if m27:
        suf = addr[m27.end():].strip()
        if re.search(r'\d', suf):
            return True
    return False


def is_condo_category(category_name: str) -> bool:
    """구분건물 계열 물건종류이면 True."""
    if not category_name:
        return False
    s = category_name.strip()
    _CONDO_KEYWORDS = (
        "아파트", "오피스텔", "빌라", "다세대", "연립",
        "근린생활시설", "상가", "집합건물", "구분건물", "집합물건",
    )
    return any(kw in s for kw in _CONDO_KEYWORDS)


_SOLO_PROPERTY_KEYWORDS = ("단독주택", "토지", "임야", "전", "답", "건물", "기계기구")

# 단독·구분 양쪽 가능한 물건종류: 건물명 유무로 결정
_AMBIGUOUS_PROPERTY_KEYWORDS = frozenset(["근린생활시설"])

def resolve_category_code(item: dict, rep_addr: str, building_name: str = "") -> str:
    """물건종류 기반 우선, 그 다음 주소 기반 호수 여부로 Category 코드 결정."""
    cat = (item.get("물건종류") or "").strip()
    if cat:
        if any(kw in cat for kw in _AMBIGUOUS_PROPERTY_KEYWORDS):
            return "30" if ((building_name or "").strip() or has_unit_no(rep_addr)) else "03"
        if is_condo_category(cat):
            return "30"
        if any(kw in cat for kw in _SOLO_PROPERTY_KEYWORDS):
            return "03"
    return "30" if has_unit_no(rep_addr) else "03"


def _production_from_cust_name(cust_name: str) -> str:
    s = (cust_name or "").strip()
    if s.endswith("이사장"):
        return s[:-3].strip()
    if s.endswith("사장"):
        return s[:-2].strip()
    if s.endswith("장"):
        return s[:-1].strip()
    return s


def _ensure_cust_name_title_suffix(cust_name: str) -> str:
    s = (cust_name or "").strip()
    if not s:
        return ""
    if s.endswith("장"):
        return s
    return s + "장"


def _normalize_branch_suffix(branch_name: str) -> str:
    branch = (branch_name or "").strip()
    if not branch:
        return ""
    if branch.endswith(("지점", "센터", "본부", "출장소", "금융센터")):
        return branch
    return branch + "지점"


def _normalize_hana_cust_name(cust_name: str, branch_name: str = "") -> str:
    s = (cust_name or "").strip()
    branch = _normalize_branch_suffix(branch_name)
    if s.startswith("KEB하나은행"):
        s = "하나은행" + s[len("KEB하나은행"):]
    if s == "하나은행" and branch:
        s = ("하나은행 " + branch).strip()
    return _ensure_cust_name_title_suffix(s)


def _normalize_woori_cust_name(cust_name: str, branch_name: str = "") -> str:
    branch = (branch_name or "").strip()
    s = (cust_name or "").strip()
    if branch:
        return f"우리은행 여신업무센터({branch})장"
    if s.startswith("우리은행 여신업무센터"):
        return _ensure_cust_name_title_suffix(s)
    return _ensure_cust_name_title_suffix(s)


def _normalize_saemaeul_branch_name(branch_name: str) -> str:
    branch = (branch_name or "").strip()
    branch = re.sub(r"\s+", " ", branch)
    if not branch:
        return ""
    parts = branch.split()
    if len(parts) >= 2:
        base = parts[0]
        sub = " ".join(parts[1:]).strip()
    else:
        base = branch
        sub = ""
    if base.endswith("새마을금고"):
        prefix = base
    else:
        prefix = f"{base}새마을금고"
    if sub == "본점" or not sub:
        return f"{prefix}이사장"
    if sub.endswith(("지점", "센터", "출장소")):
        return f"{prefix} {sub}장"
    return f"{prefix} {sub}지점장"


def resolve_sp_cust_name(
    item: dict,
    matched_cust_name: str,
    bank_name: str,
    branch_name: str,
) -> str:
    bank = (bank_name or item.get("은행", "") or "").strip()
    branch = (branch_name or item.get("영업점", "") or "").strip()
    matched = (matched_cust_name or "").strip()

    if bank == "주택도시보증공사":
        return "주택도시보증공사 사장"

    if bank == "우리은행":
        return _normalize_woori_cust_name(matched, branch)

    if bank in ("KEB하나은행", "하나은행"):
        return _normalize_hana_cust_name(matched, branch)

    if bank == "새마을금고":
        smg_name = _normalize_saemaeul_branch_name(branch)
        if smg_name:
            return smg_name
        return _ensure_cust_name_title_suffix(matched)

    # 농협중앙회 지역농협: 매칭 실패 시 직함 '장'을 만들지 않고 빈 CustName(fail-closed).
    # (호출부에서 이미 SKIP되지만, 방어적으로 임의 fallback 이름 생성을 차단한다.)
    if bank == "농협중앙회" and not matched:
        return ""

    if matched:
        return _ensure_cust_name_title_suffix(matched)

    fallback = (bank + (" " + branch if branch else "")).strip()
    return _ensure_cust_name_title_suffix(fallback)


_D1_BANKS = frozenset({
    "농협중앙회",
    "수협중앙회",
    "새마을금고",
    "신협중앙회",
    "산림조합중앙회",
})

_DEBTR_PHONE_TRUE = frozenset({
    "농협은행",
    "농협중앙회",
    "새마을금고",
    "주택도시보증공사",
})


def _should_store_debtor_phone(bank_name: str) -> bool:
    return (bank_name or "").strip() in _DEBTR_PHONE_TRUE


def resolve_debtr_phone(item: dict, bank_name: str) -> str:
    """SP DebtrPhone: 채무자 연락처 우선, 없으면 소유자 연락처 fallback (HUG 제외).
    HUG는 소유자 연락처를 DebtrPhone으로 사용하지 않는다."""
    if not _should_store_debtor_phone(bank_name):
        return ""
    debtor_phone = str(item.get("채무자 연락처", "") or "").strip()
    if (bank_name or "").strip() == "주택도시보증공사":
        return debtor_phone
    return debtor_phone or str(item.get("소유자 연락처", "") or "").strip()


def resolve_cust_charge(item: dict, bank_name: str) -> str:
    """SP CustCharge: HUG는 담당자명 뒤에 '(HUG)' suffix를 붙인다.
    담당자명이 비어 있으면 suffix만 단독 저장하지 않는다."""
    charge = str(item.get("담당자", "") or "").strip()
    if (bank_name or "").strip() == "주택도시보증공사":
        if not charge:
            return ""
        if not charge.endswith("(HUG)"):
            charge = charge + "(HUG)"
    return charge


def _is_kb_docno_format(pdf_no: str, grid_no: str) -> bool:
    """국민은행 의뢰번호 형식 검증: grid(13자리) = internal(9자리) + 숫자 suffix(4자리)"""
    p = (pdf_no  or "").strip()
    g = (grid_no or "").strip()
    return (
        g.isdigit() and len(g) == 13
        and p.isdigit() and len(p) == 9
        and g.startswith(p)
        and len(g[9:]) == 4
    )


def _is_regional_suhyup_customer(cust_name: str) -> bool:
    s = (cust_name or "").strip()
    return ("수협" in s) and not s.startswith("수협은행")


def _compact_regional_suhyup_name(regional_cust_name: str) -> str:
    """'xxx수산업협동조합' → 'xxx수협'  (APW_Customer 검색용)"""
    s = (regional_cust_name or "").strip()
    s = re.sub(r"수산업협동조합$", "수협", s)
    return s


def _resolve_customer_lookup_bank_name(item: dict) -> str:
    """lookup_cust_code() 호출 시 사용할 은행명 반환.
    지역수협 PDF는 bank_nm='수협은행'이지만 APW_Customer에는 'xxx수협'으로 등록됨."""
    bank_name = (item.get("은행", "") or "").strip()
    regional  = (item.get("지역수협명", "") or "").strip()
    if bank_name == "수협은행" and regional:
        compact = _compact_regional_suhyup_name(regional)
        if compact:
            return compact
    # 농협중앙회는 lookup_cust_code() 내부 전용 경로(_lookup_nh_jungang_regional)에서
    # 영업점명 정규화·매칭을 처리한다. 여기서는 은행명을 그대로 전달한다.
    return bank_name


def resolve_purpose_code(item: dict, cust_name: str = "") -> str:
    bank_name = (item.get("은행", "") or "").strip()
    hug_gubun = (item.get("감정평가담보구분", "") or "").strip()
    cust_name = (cust_name or "").strip()

    if bank_name == "주택도시보증공사":
        if hug_gubun == "담보제공용":
            return "H1"
        if hug_gubun == "일반거래용":
            return "H2"
        return "22"

    regional = (item.get("지역수협명", "") or "").strip()
    if regional:
        return "D1"

    if bank_name in _D1_BANKS:
        return "D1"

    if _is_regional_suhyup_customer(cust_name):
        return "D1"

    return "22"


def resolve_workinfo_code(item: dict) -> str:
    """SP WorkInfo(업무정보) 코드 결정.

    기본 '30'. 단, 주택도시보증공사(HUG)이면서 감정평가담보구분이 '일반거래용'이면 '80'.
    """
    bank_name = (item.get("은행", "") or "").strip()
    hug_gubun = (item.get("감정평가담보구분", "") or "").strip()
    if bank_name == "주택도시보증공사" and hug_gubun == "일반거래용":
        return "80"
    return "30"


def resolve_title_text(item: dict, debtor_nm: str) -> str:
    """SP Title 필드 결정. HUG는 '상품명(신청번호)', 그 외는 '{채무자} 담보물'."""
    bank_name = (item.get("은행", "") or "").strip()
    if bank_name == "주택도시보증공사":
        app_no = (
            item.get("신청번호", "")
            or item.get("의뢰번호", "")
            or item.get("상세창 의뢰번호", "")
            or ""
        ).strip()
        product_name = (item.get("상품명", "") or "").strip()
        if product_name and app_no:
            return f"{product_name}({app_no})"
        if product_name:
            return product_name
        if app_no:
            return app_no
    return (debtor_nm + " 담보물") if debtor_nm else ""


def resolve_bigo_text(item: dict, default_bigo: str) -> str:
    """SP Bigo 필드 결정. HUG + 이의신청 Y일 때만 전용 비고 생성, 그 외는 기존값."""
    default_bigo = default_bigo or ""
    bank_name = (item.get("은행", "") or "").strip()

    if bank_name != "주택도시보증공사":
        return default_bigo

    objection = (item.get("이의신청 여부", "") or "").strip()
    if objection != "Y":
        return default_bigo

    internal = (item.get("내부조사 신청여부", "") or "").strip()
    prev_no = (item.get("기 의뢰 신청번호", "") or "").strip()
    if prev_no in ("-", "없음", "해당없음", "해당 없음"):
        prev_no = ""

    parts = [f"이의신청 여부 {objection}"]
    if internal:
        parts.append(f"내부조사 신청여부 {internal}")
    if prev_no:
        parts.append(f"기 의뢰 신청번호 {prev_no}")

    return " ".join(parts)


def extract_hoetc_from_addr(addr: str, primary_ho: str = "") -> str:
    """다호수 주소에서 대표 Ho 이후 나머지 호수를 hoetc로 반환한다."""
    text = (addr or "").strip()
    if not text:
        return ""

    primary = (primary_ho or "").strip()
    primary = re.sub(r"\s*호$", "", primary).strip()

    # 다중 지번 primary가 hoetc로 오인되는 것을 방지한다.
    if re.fullmatch(r"\d{2,5}-\d{1,5}", primary):
        return ""

    # 712,713,714,715 / 712, 713, 714, 715 형태
    multi = re.findall(r"\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)+", text)
    if not multi:
        return ""

    # 주소 안에서 마지막 다호수 묶음을 사용한다.
    nums = re.split(r"\s*,\s*", multi[-1].strip())
    nums = [n.strip() for n in nums if n.strip()]
    if not nums:
        return ""

    if primary and nums[0] == primary:
        nums = nums[1:]
    elif primary and primary in nums:
        nums = [n for n in nums if n != primary]
    else:
        return ""

    return ",".join(nums)[:50]


def extract_additional_lot_hoetc(addr: str, primary_ho: str = "") -> str:
    """다필지 주소에서 첫 지번 이후 추가 지번을 hoetc로 반환한다."""
    text = (addr or "").strip()
    if not text:
        return ""
    if (primary_ho or "").strip():
        return ""
    segments = text.split(",")
    lots = []
    for seg in segments:
        seg = seg.strip()
        if re.search(r'외\s*\d+\s*필지', seg):
            continue
        m = re.search(r'(?:산\s*)?\d+-\d+', seg)
        if m:
            lots.append(m.group(0).strip())
    if len(lots) < 2:
        return ""
    result = ", ".join(lots[1:])
    return result[:50]


def parse_building_detail(addr: str) -> dict:
    """소재지에서 건물명/동/층/호를 분리한다.

    반환: {"building": str, "dong": str, "floor": str, "ho": str}
    SP_I_APW_Master_Expand @Building/@Dong/@Floor/@Ho 파라미터용.
    """
    empty = {"building": "", "dong": "", "floor": "", "ho": ""}
    if not addr:
        return empty
    try:
        # 호외N개호 패턴: 대표 단일 호수 확정 불가 → 전부 빈값 (m0보다 먼저)
        if re.search(r'\d+\s*호\s*외\s*\d+\s*개호', addr):
            return empty

        # ── 0. 지번 + 호수 패턴 우선 처리 ──────────────────────────────────
        # 예: "마곡동 774-2 제1202호. 791-7" → ho="제1202호", 나머지 빈값
        m0 = re.match(
            r'^(?:.+?(?:동|읍|면|리))\s+\d+(?:-\d+)?\s+(?P<ho>(?:제\s*)?\d+\s*호)(?!동)',
            addr,
        )
        if m0:
            return {
                "building": "",
                "dong":     "",
                "floor":    "",
                "ho":       m0.group("ho").strip()[:10],
            }

        # ── 1. suffix 추출 (지번 이후 문자열) ──────────────────────────────
        m = re.search(r'\s산?\s*\d+(?:-\d+)?\s*번지', addr)
        if not m:
            m = re.search(r'\s(?:일반|대|전|답|임야|잡종지|공장용지|도로|과수원|목장용지|창고용지|주차장|체육용지|종교용지|학교용지|하천|구거|유지|공원|묘지|기타)\s+\d+(?:-\d+)?\s+', addr)
        # 2.7단계: 행정구역 + 지번(-bun2) + suffix 패턴 (HUG 세부주소)
        # 끝숫자 fallback보다 먼저 시도 → 지번 뒤 suffix 숫자가 지번으로 삼켜지는 것 방지
        m27 = None
        if not m:
            m27 = re.match(
                r'^(?P<body>.+?(?:동|가|리|읍|면))\s+\d+(?:-\d+)?(?=\s+\S)',
                addr,
            )
        if not m and not m27:
            m = re.search(r'\s산?\s*\d+(?:-\d+)?\s*$', addr)
        from_hug = bool(m27)
        if m27:
            suffix = addr[m27.end():].strip()
        elif not m:
            # 2.6단계: 행정동 + 정수지번 + 한글 건물명 + 호수
            m26 = re.match(
                r'^.+?(?:동|읍|면|리)\s+\d{3,4}\s+([가-힣].+(?:\d+-\d+|\d+)\s*호.*)$',
                addr,
            )
            if m26:
                suffix = m26.group(1).strip()
            else:
                return empty
        else:
            suffix = addr[m.end():].strip()
        if not suffix:
            return empty

        # ── "외 n필지" → 단위 없음 (필지 전체가 대상)
        if re.search(r"외\s*\d+\s*필지", suffix):
            return empty

        # 반복 법정동 제거: suffix 첫 토큰 == address_body 마지막 토큰이면 제거
        if m27:
            _addr_body = m27.group("body")
        elif m:
            _addr_body = addr[:m.start()].strip()
        else:
            _addr_body = ""
        if _addr_body:
            _last_addr_tok = _addr_body.split()[-1]
            _sfx_toks = suffix.split()
            if _sfx_toks and _sfx_toks[0] == _last_addr_tok:
                suffix = " ".join(_sfx_toks[1:]).strip()
                if not suffix:
                    return empty

        # ── 1.5. 다중 호수 패턴 우선 처리 ──────────────────────────────────
        # 예: 에이치비지니스파크 C 712,713,714,715 → 대표 호수(첫 번째)만 사용
        m_multi = re.match(
            r'^(?P<building>.+?)\s+(?P<dong>[A-Za-z가-힣]{1,3})\s+(?P<hos>\d{1,4}(?:,\s*\d{1,4})+)$',
            suffix,
        )
        if m_multi:
            hos = [h.strip() for h in m_multi.group('hos').split(',')]
            return {
                "building": m_multi.group('building').strip()[:100],
                "dong":     m_multi.group('dong').strip()[:22],
                "floor":    "",
                "ho":       (hos[0] if hos else "")[:10],
            }

        # ── 1.6. 숫자 두 개 → Dong + Ho (예: "103 101") ────────────────────
        m_dd = re.match(r'^(\d{1,4})\s+(\d{1,4})$', suffix)
        if m_dd:
            return {
                "building": "",
                "dong":     m_dd.group(1),
                "floor":    "",
                "ho":       m_dd.group(2),
            }

        # ── 1.7. "N호동 M호" / "C동 M호" 패턴 우선 처리 ─────────────────────
        # 예: "1호동 307호" → Dong=1호동, Ho=307호
        m_dongho = re.match(
            r'^(?P<dong>\d+호동|[A-Za-z]\s*동|\d{1,4}동)\s+(?P<ho>\d+(?:-\d+)?\s*호)$',
            suffix,
        )
        if m_dongho:
            return {
                "building": "",
                "dong":     m_dongho.group("dong").strip()[:22],
                "floor":    "",
                "ho":       m_dongho.group("ho").strip()[:10],
            }

        # ── 2. Ho 추출 (마지막 매치) ────────────────────────────────────────
        ho = ""
        m_ho = None
        for m_ho in re.finditer(
            r'(?:제\s*)?(?:[A-Za-z][-\s]*)?\d+(?:-\d+)?\s*호(?=$|[\s,)/])', suffix
        ):
            pass
        if m_ho:
            ho = m_ho.group(0).strip()
            suffix = (suffix[:m_ho.start()] + suffix[m_ho.end():]).strip()

        # ── 3. Floor 추출 (마지막 매치) ─────────────────────────────────────
        floor = ""
        m_fl = None
        for m_fl in re.finditer(r'(?:제\s*)?(?:지하\s*)?\d+\s*층', suffix):
            pass
        if m_fl:
            floor = re.sub(r'\s+', '', m_fl.group(0))  # 내부 공백 제거
            suffix = (suffix[:m_fl.start()] + suffix[m_fl.end():]).strip()

        # ── 4. Dong 추출 (마지막 매치) ──────────────────────────────────────
        dong = ""
        m_dong = None
        for m_dong in re.finditer(r'(?:[A-Za-z가-힣]{1,3}|\d{1,4})\s*동', suffix):
            pass
        if m_dong:
            dong_val = m_dong.group(0).strip()
            suffix = (suffix[:m_dong.start()] + suffix[m_dong.end():]).strip()
            dong = dong_val

        # ── 4.5. ho 미추출 + "건물명 숫자-숫자" 패턴 ──────────────────────────
        # 예: "베라시떼 1-2001" → building="베라시떼", ho="1-2001"
        if not ho:
            m_numho = re.match(r'^(?P<building>.+?)\s+(?P<ho>\d{1,4}-\d{1,4})$', suffix)
            if m_numho:
                ho     = m_numho.group("ho").strip()
                suffix = m_numho.group("building").strip()

        # ── 4.6. HUG 전용: 호/층/동 미추출 시 끝 bare 숫자 → Ho ──────────────
        # 예: "805" → ho=805,  "한강더퍼스트타워 1610" → building=..., ho=1610
        if from_hug and not ho and not floor:
            m_bare = re.match(r'^(?P<building>.*?)\s*(?P<ho>\d{1,4})$', suffix)
            if m_bare:
                ho     = m_bare.group("ho").strip()
                suffix = m_bare.group("building").strip()

        # ── 5. Building: 남은 suffix 정리 ───────────────────────────────────
        building = re.sub(r'\s+', ' ', suffix.strip(" ,/.-")).strip(" ,/.-")
        if (not building
                or building.isdigit()
                or (len(building) == 1 and building.isalpha())
                or len(building) < 2):
            building = ""

        if building and re.search(r"외\s*\d+\s*필지", building):
            return empty

        return {
            "building": building[:100],
            "dong":     dong[:22],
            "floor":    floor[:10],
            "ho":       ho[:10],
        }
    except Exception:
        return empty


def _supplement_building_detail(bld: dict, item: dict) -> dict:
    """bld에 Ho/Dong/Building이 모두 없으면 pdf_우편번호주소로 보조 시도."""
    if bld.get("ho") or bld.get("dong") or bld.get("building"):
        return bld
    postal = (item.get("pdf_우편번호주소") or "").strip()
    if not postal:
        return bld
    bld2 = parse_building_detail(postal)
    _INVALID_BUILDING_LITERALS = {"건물", "토지"}
    if bld2["building"] in _INVALID_BUILDING_LITERALS:
        bld2["building"] = ""
    if bld2["ho"] or bld2["dong"] or bld2["building"]:
        return {
            "building": bld2["building"] or bld["building"],
            "dong":     bld2["dong"]     or bld["dong"],
            "floor":    bld2["floor"]    or bld["floor"],
            "ho":       bld2["ho"]       or bld["ho"],
        }
    return bld


def build_representative_address(item: dict) -> tuple:
    """대표 소재지 + DB 저장용 Addr 문자열 계산.

    반환: (rep_addr: str, addr_for_db: str, addr_count: int)
    """
    seen = []
    candidates = (
        [item.get("pdf_소재지", "").strip()]
        + [a.strip() for a in item.get("addresses", [])]
        + [item.get("주소", "").strip()]
    )
    for c in candidates:
        if c and c not in seen:
            seen.append(c)

    n = len(seen)
    if n == 0:
        return ("", "", 0)
    if n == 1:
        return (seen[0], seen[0], 1)
    return (seen[0], f"{seen[0]} 외 {n-1}필지", n)


# ── SP helpers ────────────────────────────────────────────────────────────────

def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "on")
    return bool(v)


def _limit_date_from_today(today: date | None = None) -> str:
    """SP LimitDate: 실행일 기준 +3 영업일(월~금). today를 주입하면 테스트에 사용."""
    base = today if today is not None else date.today()
    bdays = 0
    d = base
    while bdays < 3:
        d += timedelta(days=1)
        if d.weekday() < 5:   # 0=월 … 4=금
            bdays += 1
    return d.strftime("%Y-%m-%d")


def _format_sp_date(value):
    """date/datetime/str → 'YYYY-MM-DD' 문자열. 빈값/None → None.

    지원: YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD, YYYYMMDD,
          YYYY-MM-DD 오전/오후/AM/PM h:mm:ss (시간 부분은 버림).
    """
    if value is None:
        return None
    if isinstance(value, date):          # datetime은 date의 서브클래스
        return value.strftime("%Y-%m-%d")
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    # 1순위: YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD (뒤에 시간/한국어 있어도 추출)
    m = re.search(r'(\d{4})[-./](\d{1,2})[-./](\d{1,2})', v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass
    # 2순위: YYYYMMDD (\b 로 14자리 의뢰번호 202606100000136 등 차단)
    m = re.search(r'\b(20\d{2}|19\d{2})(\d{2})(\d{2})\b', v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date(y, mo, d)
            return f"{y:04d}-{mo:02d}-{d:02d}"
        except ValueError:
            pass
    return None


# ── SP_I_APW_Master_Expand 파라미터 정의 (111개) ─────────────────────────────

SP_EXPAND_PARAM_NAMES = [
    "GUBUN", "DocID", "Office", "ReceiptDate", "RequestDate",
    "Priority", "LimitDate", "WorkInfo", "Purpose", "Category",
    "Inventory", "ReceiptCharge", "CustID", "CustName", "Production",
    "CustPart", "CustCharge", "CustPhone", "CustDocID",
    "OwnerName", "OwnerPhone", "Debtor", "DebtrID", "DebtrPhone",
    "Title", "Status", "Allocate", "Judgment", "ConductDate",
    "Result", "ReturnReason", "Part", "Locked", "LockDate",
    "Report", "ReportDate", "SendDate", "SendMan", "SendMethod",
    "Deposit", "price", "Commission", "Payment", "Complete",
    "Bigo", "Ts_MasterID", "AddrEtc", "AddrPyoung",
    "BuildingEtc", "BuildingPyoung", "SuSuSum", "Tax", "Total",
    "ToJiChk", "ToJiMon", "ToUseChk", "ToUseMon",
    "JiJukChk", "JiJukMon", "BuildChk", "BuildMon",
    "BuiPyoChk", "BuiPyoMon", "BuiJunChk", "BuiJunMon",
    "CadChk", "CadMon", "LandChk", "LandMon",
    "BuiDeungChk", "BuiDeungMon", "JipHapChk", "JipHapMon",
    "GongBuTotal", "CustChargeHP", "DebtorHP", "Guid",
    "HouseCnt", "Reported", "Signer", "Signer_Act",
    "Trans_Master", "Add_Master", "Merge_Master",
    "JudgCnt", "JudgResult",
    "MstID",        # OUTPUT
    "NewDocID",     # OUTPUT
    "RefType", "RefDocID", "YCode", "Client", "Chaksugum", "Row_ID",
    "REG", "EUB", "SAN", "ADDR", "BUN1", "BUN2",
    "Building", "Dong", "Floor", "Ho", "hoetc",
    "SEQ",          # OUTPUT
    "BookingStr", "BookingCode", "Ratio",
    "BookingSeq",   # OUTPUT
    "gamsimsa",
]  # 총 111개

_SP_OUTPUT_PARAMS = {"MstID", "NewDocID", "SEQ", "BookingSeq"}
_SP_INPUT_NAMES   = [n for n in SP_EXPAND_PARAM_NAMES if n not in _SP_OUTPUT_PARAMS]


def _build_sp_wrapper() -> str:
    parts = []
    for name in SP_EXPAND_PARAM_NAMES:
        if name in _SP_OUTPUT_PARAMS:
            parts.append(f"    @{name} = @{name} OUTPUT")
        else:
            parts.append(f"    @{name} = ?")
    return (
        "SET NOCOUNT ON;\n\n"
        "DECLARE @MstID bigint = 0,\n"
        "        @NewDocID varchar(50) = '',\n"
        "        @SEQ int = 0,\n"
        "        @BookingSeq int = 0;\n\n"
        "EXEC dbo.SP_I_APW_Master_Expand\n"
        + ",\n".join(parts)
        + ";\n\n"
        "SELECT @MstID AS MstID,\n"
        "       @NewDocID AS NewDocID,\n"
        "       @SEQ AS SEQ,\n"
        "       @BookingSeq AS BookingSeq;"
    )


_SP_EXPAND_SQL = _build_sp_wrapper()


def _fetch_sp_output_and_drain(cur):
    """SP 실행 후 output row(MstID/NewDocID/SEQ/BookingSeq)를 찾고
    나머지 result set을 모두 소진한다."""
    output_cols = {"MstID", "NewDocID", "SEQ", "BookingSeq"}
    output_row = None

    while True:
        try:
            desc = cur.description
        except Exception:
            desc = None

        if desc is not None:
            col_names = {d[0] for d in desc}
            is_output_set = output_cols.issubset(col_names)
            try:
                if is_output_set and output_row is None:
                    output_row = cur.fetchone()
                    try:
                        cur.fetchall()
                    except Exception:
                        try:
                            while cur.fetchone() is not None:
                                pass
                        except Exception:
                            pass
                else:
                    try:
                        cur.fetchall()
                    except Exception:
                        try:
                            while cur.fetchone() is not None:
                                pass
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            if not cur.nextset():
                break
        except Exception:
            break

    return output_row


def insert_apw_master_expand(
    items: list,
    db_config: dict,
    log=None,
    rollback_test: bool = False,
) -> dict:
    """처리상태 == '성공'인 item마다 dbo.SP_I_APW_Master_Expand 호출.

    반환: {"enabled", "mode", "tried", "success", "fail",
           "errors", "outputs", "rollback_test"}
    """
    rollback_test = _as_bool(rollback_test)

    result = {
        "enabled":          True,
        "mode":             "SP_I_APW_Master_Expand",
        "tried":            0,
        "success":          0,
        "fail":             0,
        "duplicate_skipped": 0,
        "errors":           [],
        "outputs":          [],
        "rollback_test":    rollback_test,
    }

    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    conn = None
    try:
        conn = pyodbc.connect(_make_conn_str(db_config), timeout=10)
        _log("DB 연결 성공")
    except Exception as e:
        err_msg = re.sub('PWD=REDACTED_CONFIGURE_LOCALLY;]*', 'PWD=***', str(e))
        _log(f"DB 연결 실패: {err_msg}")
        result["errors"].append({"error": f"DB 연결 실패: {type(e).__name__}"})
        return result

    reg_db   = db_config.get("reg_lookup_database", "apworksdw")
    reg_tbl  = db_config.get("reg_lookup_table",    "APW_RegHist")
    reg_full = f"{reg_db}.dbo.{reg_tbl}"

    success_items = [it for it in items if it.get("처리상태") == "성공"]

    # 안전 검증용 사전 계산
    input_names   = _SP_INPUT_NAMES
    sql_q_count   = _SP_EXPAND_SQL.count("?")

    for idx, item in enumerate(success_items):
        _bank_nm = (item.get("은행", "") or "").strip()
        _app_no  = normalize_cust_docid(item.get("신청번호", ""))
        if _bank_nm == "주택도시보증공사" and _app_no:
            # HUG: DB CustDocID = 신청번호, 그리드 의뢰번호는 API/검증용으로 별도 보존
            cust_doc = _app_no
            grid_doc = normalize_cust_docid(
                item.get("상세창 의뢰번호") or item.get("의뢰번호", "")
            )
        elif _bank_nm == "국민은행":
            # 국민은행: 그리드(13자리) = 내부(9자리) + suffix(4자리)
            # DB CustDocID = PDF 내부 의뢰번호, GUI 매칭용 그리드는 별도 보존
            _pdf_doc = normalize_cust_docid(item.get("의뢰번호", ""))
            _grid    = normalize_cust_docid(item.get("상세창 의뢰번호") or "")
            if _pdf_doc and _grid and _is_kb_docno_format(_pdf_doc, _grid):
                cust_doc = _pdf_doc
                grid_doc = _grid
            else:
                cust_doc = normalize_cust_docid(
                    item.get("상세창 의뢰번호") or item.get("의뢰번호", "")
                )
                grid_doc = cust_doc
        else:
            cust_doc = normalize_cust_docid(
                item.get("상세창 의뢰번호") or item.get("의뢰번호", "")
            )
            grid_doc = cust_doc

        # 소재지 보호
        rep_addr, addr_for_db, addr_count = build_representative_address(item)
        if addr_count == 0:
            try:
                conn.rollback()
            except Exception:
                pass
            result["tried"] += 1
            result["fail"] += 1
            result["errors"].append({
                "index": idx + 1, "의뢰번호": cust_doc, "error": "소재지 없음",
            })
            _log(f"[SP] 실패: 의뢰번호={cust_doc}, 오류=소재지 없음")
            continue

        parsed = (
            _parse_address(rep_addr) if rep_addr
            else {"address_body": "", "San": 1, "Bun1": "", "Bun2": ""}
        )
        pdf_postal = item.get("pdf_우편번호주소", "").strip()
        reg_body   = (
            (_parse_address(pdf_postal)["address_body"] or pdf_postal)
            if pdf_postal else parsed["address_body"]
        )

        bld = _supplement_building_detail(parse_building_detail(rep_addr), item)

        bank_name   = (item.get("은행",   "") or "")
        branch_name = (item.get("영업점", "") or "")

        lu_reg = (
            lookup_reg_eub(conn, reg_body, reg_full)
            if reg_body else {"matched": False, "Reg": "", "Eub": ""}
        )
        lu_cust   = lookup_cust_code(conn, _resolve_customer_lookup_bank_name(item), branch_name)
        cust_code = lu_cust["CustCode"]

        # 농협중앙회 지역농협 매칭 실패 → fail-closed: 다른 지점 fallback/빈 CustCode SP 전달
        # 금지. SP 호출 없이 이 건만 안전 SKIP(정상 건 처리에는 영향 없음).
        if bank_name.strip() == "농협중앙회" and not lu_cust.get("matched"):
            try:
                conn.rollback()
            except Exception:
                pass
            result["tried"] += 1
            result["fail"] += 1
            result["errors"].append({
                "index": idx + 1, "의뢰번호": cust_doc,
                "error": "농협중앙회 거래처 매칭 실패",
            })
            _log(f"[CustCode][SKIP] ref={_safe_ref(cust_doc)} code=NH_REGIONAL_NO_MATCH")
            continue

        bigo_text   = (item.get("비고",   "") or "")
        bigo_text   = resolve_bigo_text(item, bigo_text)
        debtor_pdf  = (item.get("채무자", "") or "")
        owner_nm    = (item.get("소유자", "") or "")
        debtor_bigo = extract_debtor_from_bigo(bigo_text)
        debtor_nm   = debtor_bigo or debtor_pdf or owner_nm
        cust_doc_log = (item.get("의뢰번호", "") or "")
        if debtor_bigo:
            _log(f"  [Debtor] {cust_doc_log} 채무자(비고): {debtor_nm}")
        elif debtor_pdf:
            _log(f"  [Debtor] {cust_doc_log} 채무자(PDF): {debtor_nm}")
        else:
            _log(f"  [Debtor] {cust_doc_log} 소유자 fallback: {debtor_nm or '(없음)'}")

        reg      = lu_reg["Reg"] if lu_reg["matched"] else ""
        eub      = lu_reg["Eub"] if lu_reg["matched"] else ""
        category = resolve_category_code(item, rep_addr, building_name=bld.get("building", ""))
        workinfo = resolve_workinfo_code(item)

        # CustName / Production — 은행별 정규화
        _raw_cust_name = lu_cust.get("CustName", "") if lu_cust.get("matched") and lu_cust.get("CustName") else ""

        sp_cust_name = resolve_sp_cust_name(
            item=item,
            matched_cust_name=_raw_cust_name,
            bank_name=bank_name,
            branch_name=branch_name,
        )
        sp_production = _production_from_cust_name(sp_cust_name)

        # DebtrPhone — 은행별 저장 여부 (채무자 연락처 우선, fallback 소유자 연락처)
        debtr_phone = resolve_debtr_phone(item, bank_name)

        purpose_code = resolve_purpose_code(item, _raw_cust_name)

        # SP용 주소: RegHist 공식 주소 사용 가능하면 치환, 아니면 PDF 파싱값 유지
        parsed_body = parsed["address_body"] or ""
        if _should_use_official_addr(parsed_body, lu_reg):
            sp_addr     = lu_reg["official_addr"]
            addr_source = "RegHist"
        else:
            sp_addr     = parsed_body or rep_addr
            addr_source = "PDF"

        # SP용 Ho: DB 대표호수 우선, 없으면 기존 bld["ho"]
        sp_ho = (
            (item.get("DB 대표호수") or "").strip()
            or bld["ho"]
        )
        if sp_ho.endswith("호"):
            sp_ho = re.sub(r'\s+', ' ', sp_ho[:-1].strip())

        if (item.get("DB hoetc") or "").strip():
            hoetc_text = (item.get("DB hoetc") or "").strip()[:50]
        else:
            hoetc_text = extract_hoetc_from_addr(rep_addr, sp_ho)
            if not hoetc_text:
                hoetc_text = extract_additional_lot_hoetc(rep_addr, sp_ho)

        # SP용 Floor: DB 대표층 우선, 없으면 기존 bld["floor"]; "층" suffix 제거
        _db_floor = (item.get("DB 대표층") or "").strip()
        sp_floor = _db_floor or bld["floor"]
        if sp_floor.endswith("층"):
            sp_floor = re.sub(r'\s+', '', sp_floor[:-1].strip())

        _log(f"[SP] 매핑: 의뢰번호={cust_doc}, CustID={cust_code}, "
             f"REG={reg}, EUB={eub}, Purpose={purpose_code}, Category={category}, WorkInfo={workinfo}, "
             f"Addr={sp_addr}, AddrSource={addr_source}, DisplayAddr={addr_for_db}")

        sp = {
            "GUBUN":          None,
            "DocID":          None,
            "Office":         "11",
            "ReceiptDate":    _format_sp_date(datetime.now().date()),
            "RequestDate":    _format_sp_date(item.get("의뢰일자", "")),
            "Priority":       "1",
            "LimitDate":      _limit_date_from_today(),
            "WorkInfo":       workinfo,
            "Purpose":        purpose_code,
            "Category":       category,
            "Inventory":      addr_count,
            "ReceiptCharge":  1930,
            "CustID":         cust_code,
            "CustName":       sp_cust_name,
            "Production":     sp_production,
            "CustPart":       None,
            "CustCharge":     resolve_cust_charge(item, _bank_nm),
            "CustPhone":      (item.get("담당자 연락처", "") or ""),
            "CustDocID":      cust_doc,
            "OwnerName":      None,
            "OwnerPhone":     None,
            "Debtor":         debtor_nm,
            "DebtrID":        None,
            "DebtrPhone":     debtr_phone,
            "Title":          resolve_title_text(item, debtor_nm),
            "Status":         "10",
            "Allocate":       "N",
            "Judgment":       "N",
            "ConductDate":    None,
            "Result":         "01",
            "ReturnReason":   None,
            "Part":           None,
            "Locked":         "N",
            "LockDate":       None,
            "Report":         "Y",
            "ReportDate":     None,
            "SendDate":       None,
            "SendMan":        None,
            "SendMethod":     None,
            "Deposit":        None,
            "price":          None,
            "Commission":     None,
            "Payment":        None,
            "Complete":       "N",
            "Bigo":           bigo_text,
            "Ts_MasterID":    None,
            "AddrEtc":        None,
            "AddrPyoung":     None,
            "BuildingEtc":    None,
            "BuildingPyoung": None,
            "SuSuSum":        None,
            "Tax":            None,
            "Total":          None,
            "ToJiChk":        None, "ToJiMon":     None,
            "ToUseChk":       None, "ToUseMon":    None,
            "JiJukChk":       None, "JiJukMon":    None,
            "BuildChk":       None, "BuildMon":    None,
            "BuiPyoChk":      None, "BuiPyoMon":   None,
            "BuiJunChk":      None, "BuiJunMon":   None,
            "CadChk":         None, "CadMon":      None,
            "LandChk":        None, "LandMon":     None,
            "BuiDeungChk":    None, "BuiDeungMon": None,
            "JipHapChk":      None, "JipHapMon":   None,
            "GongBuTotal":    None,
            "CustChargeHP":   None,
            "DebtorHP":       None,
            "Guid":           None,
            "HouseCnt":       None,
            "Reported":       None,
            "Signer":         None,
            "Signer_Act":     None,
            "Trans_Master":   None,
            "Add_Master":     None,
            "Merge_Master":   None,
            "JudgCnt":        None,
            "JudgResult":     "01",
            "MstID":          None,   # OUTPUT
            "NewDocID":       None,   # OUTPUT
            "RefType":        None,
            "RefDocID":       None,
            "YCode":          None,
            "Client":         None,
            "Chaksugum":      None,
            "Row_ID":         None,
            "REG":            reg,
            "EUB":            eub,
            "SAN":            str(parsed["San"]),
            "ADDR":           sp_addr[:350],
            "BUN1":           _format_bun(parsed["Bun1"]),
            "BUN2":           _format_bun(parsed["Bun2"]),
            "Building":       (item.get("DB 건물명") or "").strip() or bld["building"],
            "Dong":           bld["dong"],
            "Floor":          sp_floor,
            "Ho":             sp_ho,
            "hoetc":          hoetc_text,
            "SEQ":            None,   # OUTPUT
            "BookingStr":     None,
            "BookingCode":    None,
            "Ratio":          None,
            "BookingSeq":     None,   # OUTPUT
            "gamsimsa":       None,
        }

        input_values = [sp[n] for n in input_names]

        # SP 호출 전 안전 검증
        n_names  = len(input_names)
        n_values = len(input_values)
        n_q      = sql_q_count
        if not (n_names == 107 and n_values == 107 and n_q == 107):
            msg = (f"[SP][ERROR] placeholder/input 개수 불일치: "
                   f"names={n_names} values={n_values} sql_q={n_q}")
            _log(msg)
            try:
                conn.rollback()
            except Exception:
                pass
            result["tried"] += 1
            result["fail"] += 1
            result["errors"].append({
                "index": idx + 1, "의뢰번호": cust_doc,
                "error": f"placeholder 불일치: names={n_names} values={n_values} sql_q={n_q}",
            })
            continue

        duplicate_exists = False
        if cust_doc:
            _dup_cur = None
            try:
                _dup_cur = conn.cursor()
                _dup_cur.execute(
                    "SELECT TOP (1) 1"
                    " FROM dbo.APW_Master WITH (UPDLOCK, HOLDLOCK)"
                    " WHERE Office = ? AND CustDocID = ?",
                    ("11", cust_doc),
                )
                duplicate_exists = _dup_cur.fetchone() is not None
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                result["tried"] += 1
                result["fail"] += 1
                result["errors"].append({
                    "index": idx + 1,
                    "의뢰번호": cust_doc,
                    "error": f"중복 확인 실패: {type(e).__name__}",
                })
                _log(
                    f"[DB][DUP-CHECK][FAIL] 의뢰번호={cust_doc} "
                    f"중복 확인 실패({type(e).__name__}) - INSERT 보류"
                )
                continue
            finally:
                if _dup_cur is not None:
                    try:
                        _dup_cur.close()
                    except Exception:
                        pass

        if duplicate_exists:
            try:
                conn.rollback()
            except Exception:
                pass
            result["duplicate_skipped"] += 1
            _log(
                f"[DB][DUP-SKIP] 의뢰번호={cust_doc} "
                "이미 APW_Master에 존재 - SP 호출 생략"
            )
            continue

        result["tried"] += 1

        try:
            cur = conn.cursor()
            cur.execute(_SP_EXPAND_SQL, input_values)
            row = _fetch_sp_output_and_drain(cur)
            mstid       = row[0] if row else None
            new_docid   = row[1] if row else None
            seq         = row[2] if row else None
            booking_seq = row[3] if row else None

            # men_gbn 업데이트
            if mstid:
                try:
                    cur2 = conn.cursor()
                    cur2.execute(
                        "UPDATE apworksdw.dbo.APW_Master SET men_gbn='99' WHERE MasterID=?",
                        (mstid,)
                    )
                except Exception as _ue:
                    _log(f"[SP] men_gbn UPDATE 실패: MstID={mstid} / {type(_ue).__name__}")

            # 건별 commit / rollback_test 시 rollback
            if rollback_test:
                try:
                    conn.rollback()
                except Exception:
                    pass
                _log(f"[SP][ROLLBACK_TEST] rollback: 의뢰번호={cust_doc}")
            else:
                try:
                    conn.commit()
                except Exception as _ce:
                    _log(f"[SP] commit 실패: 의뢰번호={cust_doc} / {type(_ce).__name__}")
                    raise

            _log(f"[SP] 성공: 의뢰번호={cust_doc}, NewDocID={new_docid}, "
                 f"MstID={mstid}, SEQ={seq}")
            result["success"] += 1
            result["outputs"].append({
                "의뢰번호":       cust_doc,
                "그리드_의뢰번호": grid_doc,
                "MstID":          mstid,
                "NewDocID":       str(new_docid) if new_docid is not None else "",
                "SEQ":            seq,
                "BookingSeq":     booking_seq,
            })
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            result["fail"] += 1
            err_msg = re.sub('PWD=REDACTED_CONFIGURE_LOCALLY;]*', 'PWD=***', str(e))
            _log(f"[SP] 실패: 의뢰번호={cust_doc}, 오류={type(e).__name__}: {err_msg}")
            result["errors"].append({
                "index": idx + 1, "의뢰번호": cust_doc,
                "error": f"{type(e).__name__}: {err_msg}",
            })

    # 건별 commit/rollback 완료 — 최종 집계 로그
    if result["success"] > 0 and not rollback_test:
        _log(f"[SP] commit 완료: {result['success']}건")
    elif rollback_test:
        _log(f"[SP][ROLLBACK_TEST] rollback 완료 (success={result['success']}, fail={result['fail']})")
    elif result["success"] == 0 and result["fail"] == 0:
        _log("[SP] INSERT 대상 없음")

    try:
        conn.close()
    except Exception:
        pass

    return result


def insert_bank_requests(items: list, db_config: dict, log=None) -> dict:
    """처리상태 == '성공'인 item을 YJI_BankRequest에 INSERT.

    반환: {"tried": int, "success": int, "fail": int, "errors": list}
    """
    result = {"tried": 0, "success": 0, "fail": 0, "errors": []}

    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    conn = None
    try:
        conn = pyodbc.connect(_make_conn_str(db_config), timeout=10)
        _log("DB 연결 성공")
    except Exception as e:
        err_msg = re.sub('PWD=REDACTED_CONFIGURE_LOCALLY;]*', 'PWD=***', str(e))
        _log(f"DB 연결 실패: {err_msg}")
        result["errors"].append({"error": f"DB 연결 실패: {type(e).__name__}"})
        return result

    table    = db_config.get("table", "YJI_BankRequest")
    reg_db   = db_config.get("reg_lookup_database", "apworksdw")
    reg_tbl  = db_config.get("reg_lookup_table",    "APW_RegHist")
    reg_full = f"{reg_db}.dbo.{reg_tbl}"

    success_items = [it for it in items if it.get("처리상태") == "성공"]
    today = datetime.now().date()

    INSERT_SQL = (
        f"INSERT INTO {table} "
        "(Docid,CustDocid,ReceiptDate,RequestDate,"
        "CustCode,CustNm,CustNm_Sub,Purpose_Nm,Category_Nm,"
        "Reg,Eub,San,Bun1,Bun2,Addr,"
        "CustEmp,CustPhone,Debtor,DebtorHP,Bigo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    for idx, item in enumerate(success_items):
        result["tried"] += 1
        doc_no   = (item.get("상세창 감정서번호") or item.get("감정서번호",   "")).strip()
        cust_doc = (item.get("상세창 의뢰번호")   or item.get("의뢰번호",     "")).strip()

        # 대표 소재지 + 다중 소재지 처리
        rep_addr, addr_for_db, addr_count = build_representative_address(item)

        parsed = (
            _parse_address(rep_addr) if rep_addr
            else {"address_body": "", "San": 1, "Bun1": "", "Bun2": ""}
        )

        # Reg/Eub 매칭: 우편번호주소 우선, 없으면 rep_addr 기준 address_body
        pdf_postal = item.get("pdf_우편번호주소", "").strip()
        reg_body   = (_parse_address(pdf_postal)["address_body"] or pdf_postal) if pdf_postal \
                     else parsed["address_body"]

        reg_val = eub_val = ""
        if reg_body:
            try:
                lu = lookup_reg_eub(conn, reg_body, reg_full)
                if lu["matched"]:
                    reg_val = lu["Reg"]
                    eub_val = lu["Eub"]
                    _log(f"  [Reg/Eub] {cust_doc} → Reg={reg_val} Eub={eub_val}")
                else:
                    _log(f"  [Reg/Eub] {cust_doc} 매칭 실패 ({reg_body!r})")
            except Exception as e:
                _log(f"  [Reg/Eub] {cust_doc} 조회 오류: {e}")

        category_code = resolve_category_code(item, rep_addr)
        workinfo_code = "30"   # SP 호출용 (INSERT 미사용)
        # 구분건물은 대표 소재지 1개만 저장 (외 N필지 제거)
        if category_code == "30":
            addr_for_db = rep_addr
        cust_sub = (item.get("영업점") or item.get("의뢰영업점", "")).strip()

        cl = {"CustCode": "", "matched": False, "CustName": "", "method": "", "multi": False}
        cust_code = ""
        try:
            cl = lookup_cust_code(conn, _resolve_customer_lookup_bank_name(item), cust_sub)
            cust_code = cl["CustCode"]
            if (item.get("은행", "") or "").strip() == "농협중앙회" and not cl.get("matched"):
                # fail-closed: 매칭 실패 건은 INSERT/commit 없이 SKIP(빈 CustCode 미전달)
                result["fail"] += 1
                result["errors"].append({
                    "index": idx + 1, "의뢰번호": cust_doc,
                    "error": "농협중앙회 거래처 매칭 실패",
                })
                _log(f"  [CustCode][SKIP] ref={_safe_ref(cust_doc)} code=NH_REGIONAL_NO_MATCH")
                continue
            if cl["matched"]:
                label = item.get("은행", "") + (" " + cust_sub if cust_sub else "")
                if cl["multi"]:
                    _log(f"  [CustCode] 복수 매칭: {label} → {cust_code} ({cl['CustName']})")
                else:
                    _log(f"  [CustCode] {label} → {cust_code} ({cl['CustName']})")
            else:
                _log(f"  [CustCode] {item.get('은행','')} {cust_sub} 매칭 실패")
        except Exception as e:
            _log(f"  [CustCode] 조회 오류: {e}")

        bigo_text   = (item.get("비고",   "") or "")
        bigo_text   = resolve_bigo_text(item, bigo_text)
        debtor_pdf  = (item.get("채무자", "") or "")
        owner_nm    = (item.get("소유자", "") or "")
        debtor_bigo = extract_debtor_from_bigo(bigo_text)
        debtor_nm   = debtor_bigo or debtor_pdf or owner_nm
        if debtor_bigo:
            _log(f"  [Debtor] {cust_doc} 채무자(비고): {debtor_nm}")
        elif debtor_pdf:
            _log(f"  [Debtor] {cust_doc} 채무자(PDF): {debtor_nm}")
        else:
            _log(f"  [Debtor] {cust_doc} 소유자 fallback: {debtor_nm or '(없음)'}")

        _raw_cust_name = cl.get("CustName", "") if cl.get("matched") and cl.get("CustName") else ""
        insert_cust_name = resolve_sp_cust_name(
            item=item,
            matched_cust_name=_raw_cust_name,
            bank_name=item.get("은행", "") or "",
            branch_name=cust_sub,
        )

        params = (
            doc_no[:30],
            cust_doc[:50],
            today,
            _to_date(item.get("의뢰일자", "")),
            cust_code[:10],
            insert_cust_name[:30],
            cust_sub[:30],
            resolve_purpose_code(item, cl.get("CustName", "") if cl.get("matched") else "")[:30],
            category_code[:30],
            reg_val[:5],
            eub_val[:5],
            parsed["San"],
            _format_bun(parsed["Bun1"])[:5],
            _format_bun(parsed["Bun2"])[:5],
            addr_for_db[:350],
            (item.get("담당자",        "") or "")[:30],
            (item.get("담당자 연락처", "") or "")[:30],
            debtor_nm[:30],
            ((item.get("채무자 연락처", "") or item.get("소유자 연락처", "") or "") if _should_store_debtor_phone(item.get("은행", "") or "") else "")[:30],
            bigo_text[:1000],
        )

        try:
            cur = conn.cursor()
            cur.execute(INSERT_SQL, params)
            try:
                conn.commit()
            except Exception as _ce:
                _log(f"  [commit 실패] {cust_doc}/{doc_no}: {type(_ce).__name__}")
                raise
            result["success"] += 1
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            result["fail"] += 1
            err_msg = re.sub('PWD=REDACTED_CONFIGURE_LOCALLY;]*', 'PWD=***', str(e))
            result["errors"].append({
                "index":    idx + 1,
                "의뢰번호":  cust_doc,
                "감정서번호": doc_no,
                "error":   f"{type(e).__name__}: {err_msg}",
            })
            _log(f"  [INSERT 실패] {cust_doc}/{doc_no}: {type(e).__name__}")

    # 건별 commit/rollback 완료 — 최종 집계 로그
    if result["success"] > 0:
        _log(f"DB commit 완료 ({result['success']}건)")
    elif result["success"] == 0 and result["fail"] == 0:
        _log("INSERT 대상 없음")

    try:
        conn.close()
    except Exception:
        pass

    return result
