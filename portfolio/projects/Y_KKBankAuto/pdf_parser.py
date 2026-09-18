"""pdf_parser.py — Bank24 신한은행 의뢰서 PDF 파싱
PyMuPDF(fitz) 사용. parse_bank24_pdf(pdf_path) → Y_BankAuto item dict 반환.
"""
import re
import fitz

_STOP_WORDS = [
    '▣', '기  본', '소   속', '세  금', '계산서', '의뢰기관',
    '감정서번호', '담보감정', '감정평가법인',
]
_NAME_EXCL = {
    '사업', '사업자', '대표자', '담당자', '채무자', '소유자', '신청인',
    '의뢰', '기관', '감정', '물건', '번호', '주소', '연락', '전화',
    '이메일', '정보', '계산서', '세금', '담보', '수수료', '금융', '보증',
    '지점', '영업', '임대차', '등기부', '공부',
    '서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '강원',
    '충청', '전라', '경상', '제주',
    '성명', '업종', '업태', '본사', '지부', '구분', '기본', '소재지',
    '사업번호', '수신처명', '평가서', '평가사명', '내선번호', '수신처',
    '소요부수', '대표번호', '감정목적', '감정구분', '감정총희망일자',
    '공부요청구분', '참고사항', '새주소', '새주소상세', '건물명', '동호', '동/호',
    '휴대폰', '핸드폰', '휴대전화', '집전화번호', '직장전화번호',
    '상품명', '요청부서명', '담당자연락처', '신청인고객번호',
    '기 타', '정 보', '비 고',
}
_LOC_ENDINGS = set('역동로길가읍면구시군리점사관')
_LABEL_SET = {
    '담당자', '의뢰', '기관', '전화번호', '연락처', '이메일',
    '성명', '성 명', '성   명', '지점', '영업점', '소속',
    '의뢰점', '요청부서명', '금고',
    '사업번호', '수신처명', '평가서', '평가사명', '내선번호', '수신처',
    '소요부수', '대표번호', '감정목적', '감정구분', '참고사항',
    '새주소', '새주소상세', '건물명', '동호', '동/호',
    '휴대폰', '핸드폰', '휴대전화', '집전화번호', '직장전화번호',
    '대표자명',
}
_VALID_BRANCH_ENDING_CHARS = set('역동로길가읍면구시군리점사관')
_VALID_BRANCH_ENDINGS = {'센터', '지점', '금고', '본점', '영업점', '팀', '창구', '부서', '영업부', '금융센터', '금융지점', '단지'}
_BRANCH_ORG_SUFFIXES = ('구청', '시청', '군청', '출장소', '영업부', '금융센터', '금융지점', '센터', '지점', '금고', '본점', '영업점')
_BAD_BRANCH_ENDINGS   = ('여부', '구분', '요청', '번호', '연락처', '이메일', '일자', '사항', '부수')
_BRANCH_SCAN_SKIP_LABELS = frozenset([
    '담당자', '담 당 자', '담당자명', '성명', '성 명',
    '채무자', '소유자', '의뢰지점', '의뢰지점전화번호',
    '전화번호', '연락처', '의뢰일자', '감정요구일자', '출장희망일자',
    '기 타', '기타', '정 보', '정보', '상품명',
    '비 고', '비고', '신청인고객번호', '담당자 E-Mail', '담당자E-Mail',
])
_HUG_DEBTOR_INVALID = frozenset({
    "상품명", "의뢰", "기관", "기 타", "정 보", "비 고",
})


# ── 유틸리티 ──────────────────────────────────────────────────────────────────

def _is_stop(s):    return any(w in s for w in _STOP_WORDS) if s else True
def _is_phone(s):
    if not s: return False
    digits = re.sub(r'[\s\-]', '', s)
    if not digits.isdigit(): return False
    if not digits.startswith('0'): return False
    n = len(digits)
    if n > 12 or n < 9: return False
    if digits.startswith('050'):         return 11 <= n <= 12   # 안심번호
    if digits.startswith('02'):          return 9  <= n <= 10   # 서울
    if re.match(r'^0[3-6]\d', digits):   return 10 <= n <= 11   # 지역번호
    if re.match(r'^01[016789]', digits): return 10 <= n <= 11   # 휴대폰
    return False
def _is_date(s):
    v = str(s).strip()
    if re.fullmatch(r'\d{4}[-./년]\d{1,2}(?:[-./월]\d{1,2}일?)?', v):
        return True
    m8 = re.fullmatch(r'\d{8}', v)
    if m8:
        if not (v.startswith('19') or v.startswith('20')): return False
        mo, dy = int(v[4:6]), int(v[6:])
        return (1 <= mo <= 12) and (1 <= dy <= 31)
    return False
def _is_person_name(s):
    if not s: return False
    s = s.strip()
    if not re.match(r'^[가-힣]{2,4}$', s): return False
    if s[-1] in _LOC_ENDINGS: return False
    return not any(w in s for w in _NAME_EXCL)
_COMPANY_KO_ENDINGS = frozenset(['공업', '산업', '건설', '물산', '전자', '기업', '상사', '상회', '농업', '수산'])
def _is_company(s):
    if not s: return False
    if any(k in s for k in ['주식회사','(주)','㈜','Ltd','Co.','법인','공사','(유)','(합)','(사)']): return True
    for sfx in _COMPANY_KO_ENDINGS:
        if s.endswith(sfx) and len(s) >= len(sfx) + 2: return True
    return False
def _is_name(s):    return (_is_person_name(s) or _is_company(s)) if s else False
def _is_address(s):
    return any(k in s for k in [
        '시 ','구 ','군 ','동 ','읍 ','리 ','로 ',
        '서울','경기','인천','부산','대구','광주','대전','울산','강원',
        '충청','전라','경상','제주',
    ]) if s else False
def _is_label(s):   return s in _LABEL_SET if s else False

_BIZ_LABEL_KEYWORDS = frozenset([
    '번호', '일자', '구분', '평가서', '수신처',
    '소요부수', '사업번호', '내선번호', '참고사항',
    '감정목적', '감정구분',
    '휴대폰', '핸드폰', '휴대전화', '집전화', '직장전화',
])
_EMP_LABEL_EXCL = frozenset(['성명', '담당자명', '수신처명', '평가사명', '담당자', '수신처'])
_BIGO_STOP_COMPACT = frozenset(s.replace(' ', '') for s in (
    '채무자', '채무자 성명', '채무자성명', '채 무 자',
    '차주', '차 주',
    '소유자', '소 유 자',
    '소재지', '소 재 지',
    '세금', '세  금',
))
_CATEGORY_SKIP = frozenset([
    '소유자', '채무자', '성명', '성 명', '전화번호', '연락처',
    '새주소', '새   주   소',
    '물건내역', '물 건 내 역', '▣물건내역', '▣ 물건내역', '▣물 건 내 역',
])
_PROPERTY_TYPE_NAMES = frozenset([
    "아파트", "빌라", "오피스텔", "단독주택", "다세대", "연립주택",
    "근린생활시설", "상가", "공장", "토지", "임야", "전", "답",
    "대지", "집합건물", "구분건물",
])

def _is_business_label(s: str) -> bool:
    """영업점/담당자/소유자 후보에서 제외할 업무·문서 라벨 여부"""
    if not s: return True
    s = s.strip()
    if _is_label(s): return True
    if s in _NAME_EXCL: return True
    return any(kw in s for kw in _BIZ_LABEL_KEYWORDS)

_BAD_ENTITY_KEYWORDS = frozenset([
    "의뢰", "감정", "접수", "출장", "담당", "전화", "연락",
    "주소", "우편", "물건", "공부", "요청", "임대차",
    "발송", "지점", "센터", "번호", "구분", "여부",
    "기본정보", "기본사항", "대표자명", "사업자번호",
])

def _is_entity_name(s: str) -> bool:
    """owner/debtor 전용 후보 판정 — 긴 한글 단지명·업체명 포함."""
    s = (s or "").strip()
    compact = s.replace(" ", "")
    if len(compact) < 2 or len(compact) > 25:
        return False
    if compact.isdigit():
        return False
    if re.fullmatch(r"[\d\-]+", compact):
        return False
    if not re.fullmatch(r"[가-힣A-Za-z0-9()㈜\.\-&]+", compact):
        return False
    if _is_phone(compact) or _is_date(compact):
        return False
    if _is_business_label(compact):
        return False
    if compact in _LABEL_SET or compact in _NAME_EXCL:
        return False
    if compact in _PROPERTY_TYPE_NAMES:
        return False
    cat_compact = compact.replace("▣", "")
    if cat_compact in _CATEGORY_SKIP:
        return False
    if any(k in compact for k in _BAD_ENTITY_KEYWORDS):
        return False
    return True

def _is_employee_name_candidate(s: str) -> bool:
    """담당자 이름 후보 판정 — _LOC_ENDINGS 배제 없음 ('관' 등 허용)"""
    if not s: return False
    s = s.strip()
    if _is_business_label(s): return False
    if _is_date(s) or _is_phone(s) or _is_address(s) or _is_company(s): return False
    if s in _EMP_LABEL_EXCL: return False
    if re.match(r'^[가-힣]{2,4}$', s):
        return not any(w in s for w in _NAME_EXCL)
    if re.match(r'^[A-Z][A-Z\s]{1,25}$', s) and len(s) >= 3:
        return True
    return False

_BIGO_NAME_EXCL_TOKENS = frozenset([
    '평가사', '배정', '요망', '타행대환', '건임', '메모', '현장안내', '센터담당',
])
_ORG_MARKERS_BIGO = frozenset(['병원', '의원', '한의원', '치과', '약국'])

def _is_bigo_name_candidate(v: str) -> bool:
    """비고 블록에서 실제 회사/병원명 후보 판정 (비고 문장과 분리용)"""
    if not v: return False
    v = v.strip()
    if not (2 <= len(v) <= 40): return False
    if _is_business_label(v): return False
    if _is_phone(v) or _is_date(v): return False
    if '.' in v or ',' in v: return False
    if any(tok in v for tok in _BIGO_NAME_EXCL_TOKENS): return False
    if _is_name_flexible(v): return True
    if any(k in v for k in _ORG_MARKERS_BIGO): return True
    return False

_BIGO_CANDIDATE_EXCL_TOKENS = frozenset([
    '평가사', '배정', '요망', '타행대환', '건임', '메모', '현장안내', '센터담당',
])
_ORG_MARKERS_BIGO_EXTRA = frozenset([
    '병원', '의원', '한의원', '치과', '약국',
    '상사', '산업', '개발', '건설',
    '리더스', '애비뉴', '타워', '빌딩', '프라자', '센터',
    '(주)', '주식회사',
])

def _is_debtor_owner_candidate_from_bigo(v: str) -> bool:
    """비고 블록에서 채무자/소유자 후보 판정 — 조직명 확장 포함"""
    if not v: return False
    v = v.strip()
    if '.' in v or ',' in v: return False
    if any(tok in v for tok in _BIGO_CANDIDATE_EXCL_TOKENS): return False
    if not (2 <= len(v) <= 50): return False
    if _is_business_label(v) or _is_phone(v) or _is_date(v): return False
    if _is_bigo_name_candidate(v): return True
    return any(k in v for k in _ORG_MARKERS_BIGO_EXTRA)

def _is_valid_branch(s):
    if not s: return False
    s = s.strip()
    if len(s) < 2 or len(s) > 20: return False
    if not any('가' <= c <= '힣' for c in s): return False
    if len(s) <= 5: return True
    if s[-1] in _VALID_BRANCH_ENDING_CHARS: return True
    return any(s.endswith(suf) for suf in _VALID_BRANCH_ENDINGS)
def _is_branch_org_name(s):
    if not s: return False
    s = s.strip()
    return any(s.endswith(suf) for suf in _BRANCH_ORG_SUFFIXES)
def _ls(text):      return [l.strip() for l in text.split('\n')]

def _extract_hug_full_addr(ls: list) -> str:
    """HUG 전체주소 추출. '전체주소' + '(HUG기준)' 다음 줄 주소, 우편번호 prefix 제거."""
    for i, line in enumerate(ls):
        if line.strip() == '전체주소':
            for j in range(i + 1, min(i + 4, len(ls))):
                if '(HUG기준)' in ls[j]:
                    for k in range(j + 1, min(j + 4, len(ls))):
                        v = ls[k].strip()
                        if not v or v.isdigit():
                            continue
                        if _is_address(v):
                            v = re.sub(r'^\(\d+\)\s*', '', v).strip()
                            v = re.sub(r'^\d{5},\s*', '', v).strip()
                            return v
                    break
    return ""

def _extract_hug_branch_from_ls(ls: list, good_branch_fn) -> str:
    """HUG PDF ▣의뢰내역 이후 이메일→전화번호→요청부서명 순으로 영업점 추출."""
    _HUG_SEC = None
    for i, line in enumerate(ls):
        if '▣의뢰내역' in line:
            _HUG_SEC = i
            break
    if _HUG_SEC is None:
        return ""

    window = ls[_HUG_SEC + 1: _HUG_SEC + 25]

    # 이메일(@) 위치
    email_idx = None
    for j, line in enumerate(window):
        if '@' in line:
            email_idx = j
            break
    if email_idx is None:
        return ""

    # 이메일 이후 전화번호 위치
    phone_idx = None
    for j in range(email_idx + 1, len(window)):
        if _is_phone(window[j].strip()):
            phone_idx = j
            break
    if phone_idx is None:
        return ""

    _SKIP_EXACT = frozenset([
        '기 타', '기타', '정 보', '정보', '비 고', '비고', '신청인고객번호',
    ])
    _SKIP_CONTAINS = ('기 신청번호', '회신 필요 없음', '도로명주소')

    for j in range(phone_idx + 1, min(phone_idx + 10, len(window))):
        v = window[j].strip()
        if not v:
            continue
        if v in _SKIP_EXACT:
            continue
        if any(kw in v for kw in _SKIP_CONTAINS):
            continue
        if len(v) > 20 and any(c in v for c in ('*', '**')):
            continue
        if v == '본점':
            return v
        if v.endswith('지사'):
            return v
        if '센터' in v and len(v) <= 15:
            return v
        if good_branch_fn(v):
            return v
    return ""

def _extract_hug_applicant_name(ls: list) -> str:
    """HUG 신청인명 추출. '신청인명' 라벨 이후 1~6줄에서 이름 후보를 반환."""
    for i, line in enumerate(ls):
        if line.replace(' ', '') == '신청인명':
            for j in range(i + 1, min(i + 7, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                compact = v.replace(' ', '')
                if compact == '전화번호':
                    continue
                if _is_phone(v) or _is_date(v):
                    continue
                if _is_business_label(v):
                    continue
                if v in _NAME_EXCL or compact in _NAME_EXCL:
                    continue
                if v in _LABEL_SET or compact in _LABEL_SET:
                    continue
                if _is_name_flexible(v) or _is_entity_name(v):
                    return v
    return ""


def _extract_hug_applicant_phone(ls: list) -> str:
    """HUG 신청인명 영역 전화번호 추출 (채무자 연락처용).
    '신청인명' 라벨 이후 소유자 섹션 진입 전 첫 번호 반환."""
    _STOP_LABELS = frozenset([
        '소유자', '소 유 자', '물건정보', '세부주소', '물건종류',
        '▣물건정보', '▣물건내역', '담보물정보',
    ])
    for i, line in enumerate(ls):
        if line.replace(' ', '') == '신청인명':
            for j in range(i + 1, min(i + 15, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                if v in _STOP_LABELS or v.replace(' ', '') in _STOP_LABELS:
                    break
                if _is_phone(v):
                    return v
            break
    return ""

def _extract_hug_collateral_purpose(ls: list) -> str:
    """HUG 감정평가담보구분 추출. '담보제공용' 또는 '일반거래용' 반환, 없으면 ''."""
    _SKIP_COMPACT = frozenset([
        "소유자", "성명", "전화번호", "물건", "정보", "세부주소", "번호", "부동산용도",
    ])
    for i, line in enumerate(ls):
        if line.replace(" ", "") == "감정평가담보구분":
            for j in range(i + 1, min(i + 6, len(ls))):
                candidate = ls[j].strip()
                if not candidate:
                    continue
                compact = candidate.replace(" ", "")
                if compact in _SKIP_COMPACT:
                    continue
                if candidate in ("담보제공용", "일반거래용"):
                    return candidate
    return ""

# ── HUG 신청번호/상품명/이의신청여부/내부조사신청여부/기의뢰신청번호 추출 ─────────

_HUG_EXTRA_INVALID_COMPACT = frozenset([
    "신청번호", "상품명", "보증상품명", "이의신청여부", "내부조사신청여부", "기의뢰신청번호",
    "담보물정보", "물건정보", "고객정보", "신청인명", "소유자", "세부주소",
    "전화번호", "우편번호", "부동산용도", "감정평가담보구분",
])

_HUG_PRODUCT_EXCL_COMPACT = frozenset([
    "신청번호", "이의신청여부", "내부조사신청여부", "기의뢰신청번호",
    "감정평가담보구분", "부동산용도",
])

_HUG_PREV_NO_INVALID = frozenset(["-", "없음", "해당없음", "해당 없음"])

_HUG_LABEL_COMPACT_MAP = [
    ("신청번호",        "application_no"),
    ("보증상품명",       "product_name"),
    ("상품명",          "product_name"),
    ("이의신청여부",     "objection_yn"),
    ("내부조사신청여부", "internal_review_yn"),
    ("기의뢰신청번호",   "prev_application_no"),
]


def _hug_extract_inline(line: str, label_compact: str) -> str:
    """원본 line에서 label_compact 라벨 이후 값을 원본 공백 포함으로 추출."""
    stripped = line.strip()
    pos = 0
    for ch in label_compact:
        while pos < len(stripped) and stripped[pos] == " ":
            pos += 1
        if pos < len(stripped) and stripped[pos] == ch:
            pos += 1
        else:
            return ""
    return stripped[pos:].strip()


def _hug_validate_value(v: str, field: str) -> str:
    """필드별 값 유효성 검사. 무효이면 빈값 반환."""
    if not v:
        return ""
    compact = v.replace(" ", "")
    if field in ("application_no", "prev_application_no"):
        return compact if compact.isdigit() else ""
    if field in ("objection_yn", "internal_review_yn"):
        u = v.strip().upper()
        return u if u in ("Y", "N") else ""
    if field == "product_name":
        if compact.isdigit():
            return ""
        if any(excl in compact for excl in _HUG_PRODUCT_EXCL_COMPACT):
            return ""
        return v.strip()
    return v.strip()


def _extract_hug_request_extra(ls: list) -> dict:
    """HUG ▣의뢰내역 섹션에서 신청번호/상품명/이의신청여부/내부조사신청여부/기의뢰신청번호 추출."""
    result = {
        "application_no":      "",
        "product_name":        "",
        "objection_yn":        "",
        "internal_review_yn":  "",
        "prev_application_no": "",
    }

    # 탐색 범위: ▣의뢰내역 ~ 다음 ▣ 섹션 전까지, 없으면 전체 ls
    sec_start = None
    for i, line in enumerate(ls):
        if "▣의뢰내역" in line:
            sec_start = i
            break

    if sec_start is not None:
        sec_end = len(ls)
        for i in range(sec_start + 1, len(ls)):
            if "▣" in ls[i] and "의뢰내역" not in ls[i]:
                sec_end = i
                break
        scope = ls[sec_start + 1: sec_end]
    else:
        scope = ls

    for i, line in enumerate(scope):
        compact = line.replace(" ", "")
        if not compact:
            continue

        for label_compact, field_name in _HUG_LABEL_COMPACT_MAP:
            if result[field_name]:
                continue  # 이미 추출됨
            if not compact.startswith(label_compact):
                continue

            # 1. 같은 줄 inline 값 시도
            inline = _hug_extract_inline(line, label_compact)
            if inline:
                v = _hug_validate_value(inline, field_name)
                if v:
                    result[field_name] = v
                    break

            # 2. 이후 1~5줄 탐색
            for j in range(i + 1, min(i + 6, len(scope))):
                vline = scope[j].strip()
                if not vline:
                    continue
                vcompact = vline.replace(" ", "")
                if any(vcompact.startswith(lk) for lk, _ in _HUG_LABEL_COMPACT_MAP):
                    break
                if vcompact in _HUG_EXTRA_INVALID_COMPACT:
                    break
                v = _hug_validate_value(vline, field_name)
                if v:
                    result[field_name] = v
                    break
            break

    # 상품명 특별 처리: 라벨이 ▣의뢰내역 이전 헤더에 있는 경우
    # ▣의뢰내역 이후 이메일 라인 직전까지 텍스트를 수집해 상품명으로 사용
    if not result["product_name"] and scope:
        parts = []
        for _vl in scope:
            _v = _vl.strip()
            if not _v:
                continue
            if "@" in _v:
                break
            if re.search(r'기\s+본|세\s+금|소\s+속', _v):
                break
            _vc = _v.replace(" ", "")
            if _vc in _HUG_EXTRA_INVALID_COMPACT:
                continue
            if any(_vc.startswith(_lk) for _lk, _ in _HUG_LABEL_COMPACT_MAP):
                break
            parts.append(_v)
        if parts:
            _candidate = " ".join(parts)
            _pv = _hug_validate_value(_candidate, "product_name")
            if _pv:
                result["product_name"] = _pv

    if result["prev_application_no"] in _HUG_PREV_NO_INVALID:
        result["prev_application_no"] = ""

    return result


def _after(lines, label, start=0, max_look=12):
    for i in range(start, len(lines)):
        if label in lines[i]:
            for j in range(i+1, min(i+max_look+1, len(lines))):
                if lines[j]: return lines[j]
    return None

def _before(lines, label, max_look=5):
    for i, line in enumerate(lines):
        if label in line:
            for j in range(i-1, max(i-max_look-1,-1), -1):
                if lines[j]: return lines[j]
    return None

def _all_after(lines, label, max_look=12):
    for i, line in enumerate(lines):
        if label in line:
            result = []
            for j in range(i+1, min(i+max_look+1, len(lines))):
                if lines[j]: result.append(lines[j])
            return result
    return []

def _person_name_after(lines, label, start=0, max_look=15):
    for i in range(start, len(lines)):
        if label in lines[i]:
            for j in range(i+1, min(i+max_look+1, len(lines))):
                v = lines[j]
                if not v or _is_stop(v) or _is_date(v) or _is_phone(v) or _is_company(v): continue
                if _is_person_name(v): return v
    return None

def _clean_addr(addr):
    if not addr or len(addr) < 20: return addr
    half = len(addr) // 2
    if addr[:half].strip() == addr[half:].strip(): return addr[:half].strip()
    return addr.strip()

def _same_line_value(lines, label):
    """'라벨값' 처럼 라벨+값이 붙어있는 경우 값 추출"""
    for line in lines:
        if line.startswith(label) and len(line) > len(label):
            return line[len(label):].strip()
    return None

_DATE_LABEL_PREFIXES = ('출장희망일자', '감정요구일자', '처리기한', '접수일자', '의뢰일자')

def _find_date_token(text: str) -> str:
    """text에서 날짜 토큰 추출. YYYY-MM-DD 형식 우선, 8자리 숫자 fallback."""
    if not text:
        return ""
    # 연도가 반드시 19xx 또는 20xx여야 함 — 감정서번호 조각("2605-3-16") 오인 방지
    m = re.search(r'(?:19|20)\d{2}[-./]\d{1,2}[-./]\d{1,2}', text)
    if m:
        return m.group(0)
    # 8자리 숫자 날짜 — 앞뒤 숫자 연속 시 불매칭 (사업자번호/의뢰번호 오인 방지)
    m = re.search(r'(?<!\d)(?:19|20)\d{6}(?!\d)', text)
    if m and _is_date(m.group(0)):
        return m.group(0)
    return ""

def _extract_date(lines, *labels):
    for label in labels:
        v_inline = _same_line_value(lines, label)
        if v_inline:
            tok = _find_date_token(v_inline)
            if tok: return tok
        for i, line in enumerate(lines):
            if label in line:
                # 1순위: 라벨 이후 줄
                for j in range(i+1, min(i+6, len(lines))):
                    candidate = lines[j]
                    if not candidate: continue
                    if any(candidate.startswith(p) for p in _DATE_LABEL_PREFIXES if p != label):
                        continue
                    tok = _find_date_token(candidate)
                    if tok: return tok
                # 2순위: 라벨 이전 최대 3줄 (이후 줄 탐색 실패 시)
                for j in range(i-1, max(i-4, -1), -1):
                    candidate = lines[j]
                    if not candidate: continue
                    tok = _find_date_token(candidate)
                    if tok: return tok
                break
    return ""

def _is_name_flexible(s):
    """한글 이름 또는 영문 대문자 이름(예: PARK KWAN HYUNG)"""
    if not s: return False
    if _is_name(s): return True
    if re.match(r'^[A-Z][A-Z\s]{1,25}$', s.strip()) and len(s.strip()) >= 3:
        return True
    return False


# ── 새마을금고 전용 helpers ───────────────────────────────────────────────────

_SMG_BAD_BRANCH_LABELS = frozenset(['비   고', '기 타', '정 보', '정보', '비고'])

def _extract_saemaeul_request_info(ls: list) -> dict:
    """새마을금고 ▣의뢰내역 블록에서 의뢰 정보 추출."""
    _empty = {"debtor": "", "request_date": "", "cust_phone": "", "branch": "", "bigo": "", "cust_emp": ""}
    sec_start = -1
    for i, line in enumerate(ls):
        if '▣의뢰내역' in line:
            sec_start = i
            break
    if sec_start == -1:
        return _empty

    idx = sec_start + 1

    debtor = ""
    while idx < len(ls):
        v = ls[idx].strip(); idx += 1
        if v:
            debtor = v; break

    request_date = ""
    while idx < len(ls):
        v = ls[idx].strip(); idx += 1
        m = re.search(r'((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})', v)
        if m:
            y, mo, d = m.group(1), m.group(2), m.group(3)
            request_date = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"; break

    cust_phone = ""; cust_phone_idx = -1
    while idx < len(ls):
        v = ls[idx].strip()
        if v and _is_phone(v):
            cust_phone = v; cust_phone_idx = idx; idx += 1; break
        idx += 1

    kibon_idx = -1
    for i in range(idx, len(ls)):
        if ls[i].strip() == '기  본':
            kibon_idx = i; break
    if kibon_idx == -1:
        return {**_empty, "debtor": debtor, "request_date": request_date, "cust_phone": cust_phone}

    chaju_phone_idx = -1
    for i in range(kibon_idx - 1, max(cust_phone_idx, sec_start), -1):
        v = ls[i].strip()
        if v and _is_phone(v):
            chaju_phone_idx = i; break

    branch = ""; branch_idx = -1
    if chaju_phone_idx > 0:
        for i in range(chaju_phone_idx - 1, max(cust_phone_idx, sec_start), -1):
            v = ls[i].strip()
            if v:
                if v not in _SMG_BAD_BRANCH_LABELS:
                    branch = v
                branch_idx = i; break

    bigo_end = branch_idx if branch_idx > cust_phone_idx else (chaju_phone_idx if chaju_phone_idx > 0 else kibon_idx)
    bigo_lines = []
    for i in range(cust_phone_idx + 1, bigo_end):
        v = ls[i].strip()
        if v:
            bigo_lines.append(v)
    bigo = " ".join(bigo_lines)

    cust_emp = ""
    for i in range(kibon_idx, len(ls)):
        if ls[i].strip() == '금고 담당자명':
            for j in range(i + 1, min(i + 6, len(ls))):
                v = ls[j].strip()
                if v:
                    cust_emp = v; break
            break

    return {"debtor": debtor, "request_date": request_date, "cust_phone": cust_phone,
            "branch": branch, "bigo": bigo, "cust_emp": cust_emp}


def _extract_saemaeul_object_info(ls: list) -> dict:
    """새마을금고 소유자/물건정보 블록 추출."""
    owner = ""; owner_phone = ""; in_owner = False; found_phone_label = False
    for line in ls:
        v = line.strip()
        if v == '소유자':
            in_owner = True; continue
        if in_owner:
            if v == '물건':
                break
            if v in ('성   명', '성  명', '성명'):
                continue
            if v == '전화번호':
                found_phone_label = True; continue
            if found_phone_label:
                if not v:
                    continue
                if _is_phone(v):
                    owner_phone = v; found_phone_label = False; continue
                else:
                    if not owner:
                        owner = v
                    found_phone_label = False
                continue
            if v and not owner:
                owner = v

    sojaegi = ""
    for i, line in enumerate(ls):
        if line.strip() == '세부주소':
            for j in range(i + 1, min(i + 5, len(ls))):
                v = ls[j].strip()
                if v:
                    v = re.sub(r'\s+일반\s+', ' ', v)
                    v = re.sub(r'\s+', ' ', v).strip()
                    sojaegi = v; break
            break

    category = ""
    for i, line in enumerate(ls):
        if line.strip() == '물건종류':
            for j in range(i + 1, min(i + 5, len(ls))):
                v = ls[j].strip()
                if v:
                    category = v; break
            break

    return {"owner": owner, "owner_phone": owner_phone, "sojaegi": sojaegi, "category": category}


# ── 국민은행 전용 helpers ─────────────────────────────────────────────────────

_KB_EXCLUDE = frozenset([
    '정  보', '정보', '기 타', '기타', '사업번호', '상호', '대표자명',
    '주소', '은행', '금융', 'Email', '기본', '업태', '업종', '의뢰', '기관',
])

def _is_kb_phoneish(s: str) -> bool:
    """국민은행 전용 전화번호 판정 — 숫자만 7~12자리. 전역 _is_phone()과 별개."""
    if not s:
        return False
    s = s.strip()
    return s.isdigit() and 7 <= len(s) <= 12


_KB_BIGO_STOP_COMPACT = frozenset([
    '기타정보', '공부요청구분', '임대차포함여부', '임대차표함여부',
    '감정목적', '정규담보취득제한부동산', '세금계산서정보', '물건정보',
    '기타', '정보',
])

def _extract_kb_bigo(ls: list) -> str:
    """국민은행 참고사항 → Bigo.
    '참고사항' 라벨 다음의 실제 내용만 수집하고,
    기타정보/공부요청구분 등 다음 섹션 라벨이 나타나면 즉시 수집을 종료한다."""
    for i, line in enumerate(ls):
        if '참고사항' not in line:
            continue
        parts = []
        for j in range(i + 1, min(i + 15, len(ls))):
            v = ls[j].strip()
            if not v:
                continue
            vc = v.replace(' ', '')
            if vc in _KB_BIGO_STOP_COMPACT:
                break
            if '▣' in v:
                break
            if _is_stop(v) or _is_date(v):
                break
            parts.append(v)
        return ' '.join(parts).strip()
    return ""


def _extract_kookmin_request_info(ls: list) -> dict:
    """▣의뢰내역 이후 국민은행 의뢰 정보(채무자/의뢰일자/영업점/담당자/연락처) 추출."""
    result = {"debtor": "", "request_date": "", "branch": "", "cust_emp": "", "cust_phone": ""}
    sec = None
    for i, line in enumerate(ls):
        if '▣의뢰내역' in line:
            sec = i
            break
    if sec is None:
        return result

    # 날짜 위치 탐색 (▣의뢰내역 이후 첫 20xx-xx-xx)
    date_idx = None
    date_val = ""
    for i in range(sec + 1, min(sec + 40, len(ls))):
        v = ls[i].strip()
        if not v:
            continue
        m = re.match(r'((?:19|20)\d{2}-\d{1,2}-\d{1,2})', v)
        if m:
            date_idx = i
            date_val = m.group(1)
            break

    if date_idx is None:
        return result

    result["request_date"] = date_val

    # debtor: 날짜 바로 앞 비어 있지 않은 값
    for i in range(date_idx - 1, max(sec, date_idx - 10), -1):
        v = ls[i].strip()
        if v:
            result["debtor"] = v
            break

    # branch: 날짜 이후 비어 있지 않은 첫 번째 줄 (제외 조건 적용)
    branch_idx = None
    for i in range(date_idx + 1, min(date_idx + 12, len(ls))):
        v = ls[i].strip()
        if not v:
            continue
        if v in _KB_EXCLUDE or v.replace(' ', '') in _KB_EXCLUDE:
            continue
        if '@' in v or _is_date(v) or _is_address(v):
            continue
        result["branch"] = v
        branch_idx = i
        break

    if branch_idx is None:
        return result

    # cust_emp / cust_phone: branch 이후 비어 있지 않은 줄 최대 3개 탐색
    candidates = []
    for i in range(branch_idx + 1, min(branch_idx + 10, len(ls))):
        v = ls[i].strip()
        if not v:
            continue
        if v in _KB_EXCLUDE or v.replace(' ', '') in _KB_EXCLUDE:
            continue
        if '@' in v or _is_address(v):
            continue
        candidates.append(v)
        if len(candidates) >= 3:
            break

    if candidates:
        first = candidates[0]
        if _is_kb_phoneish(first):
            result["cust_phone"] = first
        elif _is_employee_name_candidate(first) or _is_person_name(first):
            result["cust_emp"] = first
            for c in candidates[1:]:
                if _is_kb_phoneish(c):
                    result["cust_phone"] = c
                    break

    return result


def _extract_kookmin_objects(ls: list) -> list:
    """국민은행 물건정보 블록 추출 → [{address, owner, owner_phone, category}, ...]."""
    # 블록 시작: ls[i]=="물건" and ls[i+1]=="정보" and ls[i+2]=="일련번호"
    block_starts = []
    for i in range(len(ls) - 2):
        if ls[i] == '물건' and ls[i + 1] == '정보' and ls[i + 2] == '일련번호':
            block_starts.append(i)

    if not block_starts:
        return []

    objects = []
    for b_idx, start in enumerate(block_starts):
        end = block_starts[b_idx + 1] if b_idx + 1 < len(block_starts) else len(ls)
        block = ls[start:end]

        address = owner = owner_phone = ""
        land_eval = condo_eval = bldg_eval = mach_eval = ""

        i = 0
        while i < len(block):
            line = block[i]
            lc = line.replace(' ', '')

            if lc == '주소':
                for j in range(i + 1, min(i + 4, len(block))):
                    v = block[j].strip()
                    if v:
                        address = v
                        break

            elif lc == '성명':
                for j in range(i + 1, min(i + 4, len(block))):
                    v = block[j].strip()
                    if v:
                        owner = v
                        break

            elif lc == '전화번호' and owner:
                # 소유자 이후 전화번호만 owner_phone으로
                for j in range(i + 1, min(i + 4, len(block))):
                    v = block[j].strip()
                    if v and v.isdigit():
                        owner_phone = v
                        break

            elif line == '토지평가':
                for j in range(i + 1, min(i + 4, len(block))):
                    if block[j].strip() == '여부':
                        for k in range(j + 1, min(j + 3, len(block))):
                            v = block[k].strip()
                            if v in ('평가', '미평가'):
                                land_eval = v
                                break
                        break

            elif line == '집합건물':
                for j in range(i + 1, min(i + 4, len(block))):
                    if block[j].strip() == '평가여부':
                        for k in range(j + 1, min(j + 3, len(block))):
                            v = block[k].strip()
                            if v in ('평가', '미평가'):
                                condo_eval = v
                                break
                        break

            elif line == '건물평가':
                for j in range(i + 1, min(i + 4, len(block))):
                    if block[j].strip() == '여부':
                        for k in range(j + 1, min(j + 3, len(block))):
                            v = block[k].strip()
                            if v in ('평가', '미평가'):
                                bldg_eval = v
                                break
                        break

            elif line == '기계기구':
                for j in range(i + 1, min(i + 4, len(block))):
                    if block[j].strip() == '평가여부':
                        for k in range(j + 1, min(j + 3, len(block))):
                            v = block[k].strip()
                            if v in ('평가', '미평가'):
                                mach_eval = v
                                break
                        break

            i += 1

        # 물건종류 추론
        if condo_eval == '평가':
            category = '집합건물'
        elif land_eval == '평가' and bldg_eval == '평가' and mach_eval == '평가':
            category = '토지건물기계기구'
        elif land_eval == '평가' and bldg_eval == '평가':
            category = '토지건물'
        elif land_eval == '평가':
            category = '토지'
        elif bldg_eval == '평가':
            category = '건물'
        elif mach_eval == '평가':
            category = '기계기구'
        else:
            category = ''

        objects.append({
            "address":     address,
            "owner":       owner,
            "owner_phone": owner_phone,
            "category":    category,
        })

    return objects


# ── 하나은행 전용 helpers ─────────────────────────────────────────────────────

_HANA_BIGO_EXCL = frozenset([
    "한글", "기 본", "소 속", "(주)대화감정평가법인 본사",
])

# 다호수 판정: 법정동+지번+호수 전체 패턴
_HANA_UNIT_PTN = re.compile(
    r'^(?P<region>.+?(?:동|읍|면|리))\s+'
    r'(?P<lot>(?:산\s*)?\d+(?:-\d+)?)\s+'
    r'(?P<unit>\d+(?:-\d+)?)\s*호?\s*$'
)
# 건물명 범위 패턴: 법정동+지번+건물명+시작~종료호
_HANA_BUILDING_PTN = re.compile(
    r'^(?P<region>.+?(?:동|읍|면|리))\s+'
    r'(?P<lot>(?:산\s*)?\d+(?:-\d+)?)\s+'
    r'(?P<building>.+?)\s+'
    r'(?P<start>\d+(?:-\d+)?)\s*~\s*'
    r'(?P<end>\d+(?:-\d+)?)\s*호\s*$'
)
_HANA_PHONE_UNIT_PTN = re.compile(r'^\d{2,3}-\d{3,4}-\d{4}$')
_HANA_DATE_UNIT_PTN  = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _last_dong_token(region: str) -> str:
    """region에서 마지막 법정동 토큰(동/읍/면/리 끝) 반환."""
    for tok in reversed(region.split()):
        if tok and re.search(r'[동읍면리]$', tok):
            return tok
    return ""


def _norm_lot_cmp(lot: str) -> str:
    """지번 비교용 정규화: 앞자리 0 제거. 저장값은 변경하지 않는다."""
    lot = lot.strip().replace(' ', '')
    parts = lot.split('-')
    try:
        normed = [str(int(p)) if p.isdigit() else p for p in parts]
    except (ValueError, TypeError):
        return lot
    return '-'.join(normed)
_HANA_BIGO_STOP = frozenset(["감정요구일자", "감정출장희망일자"])


def _extract_hana_request_info(ls: list) -> dict:
    """하나은행 ▣의뢰내역 블록에서 채무자/의뢰일자/영업점/담당자/연락처/비고 추출."""
    result = {"debtor": "", "request_date": "", "branch": "", "cust_emp": "", "cust_phone": "", "bigo": ""}
    sec = None
    for i, line in enumerate(ls):
        if "▣의뢰내역" in line:
            sec = i
            break
    if sec is None:
        return result

    idx = sec + 1
    end = len(ls)

    # debtor: 첫 비어 있지 않은 값
    while idx < end:
        v = ls[idx].strip(); idx += 1
        if v:
            result["debtor"] = v
            break

    # request_date: 날짜 패턴(YYYY-MM-DD) 포함하는 첫 값
    while idx < end:
        v = ls[idx].strip(); idx += 1
        if not v:
            continue
        if re.search(r"\d{4}-\d{2}-\d{2}", v):
            result["request_date"] = v
            break

    # branch: 다음 비어 있지 않은 값
    while idx < end:
        v = ls[idx].strip(); idx += 1
        if v:
            result["branch"] = v
            break

    # cust_emp: 다음 비어 있지 않은 값
    while idx < end:
        v = ls[idx].strip(); idx += 1
        if v:
            result["cust_emp"] = v
            break

    # cust_phone: 다음 비어 있지 않은 값이 전화번호이면 저장 후 idx 진행
    while idx < end:
        v = ls[idx].strip()
        if not v:
            idx += 1
            continue
        if _is_phone(v):
            result["cust_phone"] = v
            idx += 1
        break

    # bigo: "한글" 다음부터 stop 전까지 수집
    bigo_parts = []
    in_bigo = False
    for i in range(idx, end):
        v = ls[i].strip()
        if not v:
            continue
        if v in _HANA_BIGO_STOP:
            break
        if v == "한글":
            in_bigo = True
            continue
        if not in_bigo:
            continue
        if v in _HANA_BIGO_EXCL:
            continue
        bigo_parts.append(v)
    result["bigo"] = " ".join(bigo_parts)

    return result


def _extract_hana_object_info(ls: list) -> dict:
    """하나은행 소유자/세부주소/물건종류 + 다호수/건물명 추출."""
    result = {
        "owner": "", "owner_phone": "", "sojaegi": "", "category": "",
        "db_primary_ho": "", "db_hoetc": "", "db_building": "",
    }

    # 소유자 섹션 → 전화번호 라벨 탐색
    owner_sec = None
    for i, line in enumerate(ls):
        if line.strip() == "소유자":
            owner_sec = i
            break
    if owner_sec is not None:
        phone_label_idx = None
        for i in range(owner_sec + 1, min(owner_sec + 10, len(ls))):
            if ls[i].strip() == "전화번호":
                phone_label_idx = i
                break
        if phone_label_idx is not None:
            idx = phone_label_idx + 1
            while idx < len(ls):
                v = ls[idx].strip(); idx += 1
                if not v:
                    continue
                if _is_phone(v):
                    result["owner_phone"] = v
                    while idx < len(ls):
                        vv = ls[idx].strip(); idx += 1
                        if vv:
                            result["owner"] = vv
                            break
                else:
                    result["owner"] = v
                break

    # 모든 "세부주소" 값 수집 (빈값 제거, 중복 제거, 순서 유지)
    # orig_addrs: 원본 공백 보존 (sojaegi 저장용)
    # collected_addrs: 정규화 버전 (다호수 비교/건물명 매칭용)
    seen_addrs: set = set()
    orig_addrs: list = []
    collected_addrs: list = []
    for i, line in enumerate(ls):
        if line.strip() == "세부주소":
            for j in range(i + 1, min(i + 5, len(ls))):
                v = ls[j].strip()
                if v:
                    norm = re.sub(r'\s+', ' ', v).strip()
                    if norm and norm not in seen_addrs:
                        seen_addrs.add(norm)
                        orig_addrs.append(v)      # 원본 공백 보존
                        collected_addrs.append(norm)
                    break

    # 첫 주소를 대표 소재지로 (원본 공백 보존)
    if orig_addrs:
        result["sojaegi"] = orig_addrs[0]

    # 물건종류 → category ("우편번호" 또는 숫자이면 빈값)
    for i, line in enumerate(ls):
        if line.strip() == "물건종류":
            for j in range(i + 1, min(i + 5, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                if v == "우편번호" or re.fullmatch(r"\d+", v):
                    result["category"] = ""
                else:
                    result["category"] = v
                break
            break

    # 다호수 판정: 2건 이상, 전체 패턴 일치, 동일 지번, 고유 호수 2개 이상
    if len(collected_addrs) >= 2:
        matches = [_HANA_UNIT_PTN.fullmatch(a) for a in collected_addrs]
        if all(m is not None for m in matches):
            valid_units = all(
                not _HANA_PHONE_UNIT_PTN.fullmatch(m.group("unit"))
                and not _HANA_DATE_UNIT_PTN.fullmatch(m.group("unit"))
                for m in matches
            )
            if valid_units:
                regions = [re.sub(r'\s+', ' ', m.group("region")).strip() for m in matches]
                lots    = [m.group("lot").replace(' ', '') for m in matches]
                units   = [m.group("unit") for m in matches]
                if len(set(regions)) == 1 and len(set(lots)) == 1:
                    seen_u: set = set()
                    unique_units: list = []
                    for u in units:
                        if u not in seen_u:
                            seen_u.add(u)
                            unique_units.append(u)
                    if len(unique_units) >= 2:
                        result["db_primary_ho"] = unique_units[0]
                        result["db_hoetc"] = f"{len(unique_units) - 1}개호"

    # 건물명 추출: 대표 세부주소의 법정동+지번과 일치하는 범위 라인 탐색
    if collected_addrs:
        rep_m = _HANA_UNIT_PTN.fullmatch(collected_addrs[0])
        if rep_m:
            rep_dong    = _last_dong_token(rep_m.group("region"))
            rep_lot_cmp = _norm_lot_cmp(rep_m.group("lot"))
        else:
            rep_dong = rep_lot_cmp = ""

        if rep_dong:
            for line in ls:
                bm = _HANA_BUILDING_PTN.fullmatch(
                    re.sub(r'\s+', ' ', line.strip())
                )
                if not bm:
                    continue
                if _last_dong_token(bm.group("region")) != rep_dong:
                    continue
                if _norm_lot_cmp(bm.group("lot")) != rep_lot_cmp:
                    continue
                raw_bldg = bm.group("building").strip()
                toks = raw_bldg.split()
                if len(toks) >= 2 and toks[-1] == "공장":
                    building = "".join(toks[:-1]) + "공장"
                else:
                    building = re.sub(r'\s+', ' ', raw_bldg)
                if building:
                    result["db_building"] = building
                break

    return result


# ── 농협은행 전용 helpers ─────────────────────────────────────────────────────

_NH_SKIP_LABELS = frozenset([
    '전달사항', '요청기한', '채무자', '성   명', '의뢰', '기관', '의뢰일자',
])


def _extract_nh_request_info(ls: list) -> dict:
    """농협은행 ▣의뢰내역 블록에서 채무자/의뢰일자/처리기한/영업점/담당자/연락처/비고 추출."""
    result = {
        "debtor": "", "request_date": "", "deadline_date": "",
        "branch": "", "cust_emp": "", "cust_phone": "", "bigo": "",
        "debtor_phone": "",
    }

    sec = None
    for i, line in enumerate(ls):
        if "▣의뢰내역" in line:
            sec = i
            break
    if sec is None:
        return result

    # 블록 끝: 세  금 또는 ▣물건내역
    block_end = len(ls)
    for i in range(sec + 1, len(ls)):
        if '세  금' in ls[i] or '▣물건내역' in ls[i]:
            block_end = i
            break

    # ── request_date: '의뢰일자' 이후 날짜 포함 라인
    for i in range(sec, block_end):
        if '의뢰일자' in ls[i]:
            for j in range(i + 1, min(i + 5, block_end)):
                v = ls[j].strip()
                if v and re.search(r"\d{4}-\d{2}-\d{2}", v):
                    result["request_date"] = v
                    break
            break

    # ── deadline_date: '요청기한' 이후 날짜 포함 라인
    deadline_abs_idx = None
    for i in range(sec, block_end):
        if '요청기한' in ls[i]:
            for j in range(i + 1, min(i + 5, block_end)):
                v = ls[j].strip()
                if v and re.search(r"\d{4}-\d{2}-\d{2}", v):
                    result["deadline_date"] = v
                    deadline_abs_idx = j
                    break
            break

    # ── debtor / bigo: deadline_date 다음부터 첫 '우편번호' 전까지
    debtor_abs_idx = None
    if deadline_abs_idx is not None:
        candidates = []
        candidate_indices = []
        for i in range(deadline_abs_idx + 1, block_end):
            v = ls[i].strip()
            if not v:
                continue
            if v == '우편번호':
                break
            if v in _NH_SKIP_LABELS:
                continue
            if re.search(r"\d{4}-\d{2}-\d{2}", v):
                continue
            if _is_phone(v):
                continue
            candidates.append(v)
            candidate_indices.append(i)
        if candidates:
            result["debtor"] = candidates[-1]
            result["bigo"] = " ".join(candidates[:-1]) if len(candidates) > 1 else ""
            debtor_abs_idx = candidate_indices[-1]

    # 채무자 이후 우편번호 구간에서 채무자 전화번호 탐색
    if debtor_abs_idx is not None:
        _postal_idx = None
        for i in range(debtor_abs_idx + 1, block_end):
            if ls[i].strip() == '우편번호':
                _postal_idx = i
                break
        if _postal_idx is not None:
            _PHONE_STOP = frozenset(['직장전화', '주 소', '영업점'])
            for i in range(_postal_idx + 1, block_end):
                v = ls[i].strip()
                if not v:
                    continue
                if v in _PHONE_STOP:
                    break
                if _is_phone(v):
                    result["debtor_phone"] = re.sub(r'[\s\-]', '', v)
                    break

    # ── branch: '영업점' 이후 첫 비어 있지 않은 값
    for i in range(sec, block_end):
        if ls[i].strip() == '영업점':
            for j in range(i + 1, min(i + 5, block_end)):
                v = ls[j].strip()
                if v and v not in ('출장요청일자',):
                    result["branch"] = v
                    break
            break

    # ── cust_emp + cust_phone: 첫 '담당자' 이후, '전달사항'/'전송센터' 전
    for i in range(sec, block_end):
        if ls[i].strip() == '담당자':
            for j in range(i + 1, block_end):
                v = ls[j].strip()
                if not v:
                    continue
                if v in ('전달사항', '전송센터'):
                    break
                result["cust_emp"] = v
                for k in range(j + 1, block_end):
                    kv = ls[k].strip()
                    if not kv:
                        continue
                    if kv in ('전달사항', '전송센터'):
                        break
                    if kv == '전화번호':
                        for m in range(k + 1, min(k + 4, block_end)):
                            mv = ls[m].strip()
                            if mv and mv not in ('전달사항', '전송센터'):
                                result["cust_phone"] = mv
                                break
                        break
                break
            break

    return result


def _extract_nh_additional_lots(ls: list) -> str:
    """농협 반복 ▣물건내역 블록에서 추가 필지 지번을 추출, ', '로 연결해 반환."""
    _ADDR_SKIP = frozenset([
        '우편번호', '소재지', '소 재 지', '주소', '주 소', '일련번호',
        '물건내역', '소유자', '채무자', '담보종류',
        '세  금', '기  본', '소   속',
    ])

    block_starts = []
    for i, line in enumerate(ls):
        if '▣물건내역' in line:
            block_starts.append(i)

    if len(block_starts) < 2:
        return ""

    def _block_address(bstart, bend):
        for i in range(bstart + 1, bend):
            v = ls[i].strip()
            if v.replace(' ', '') in ('우편번호주소', '우편번호'):
                for j in range(i + 1, min(i + 6, bend)):
                    vv = ls[j].strip()
                    if not vv:
                        continue
                    if vv.isdigit():
                        continue
                    if vv in _ADDR_SKIP:
                        continue
                    if '▣' in vv:
                        break
                    return vv
                break
        return None

    addresses = []
    for k, bstart in enumerate(block_starts):
        bend = block_starts[k + 1] if k + 1 < len(block_starts) else len(ls)
        addr = _block_address(bstart, bend)
        if addr:
            addresses.append(addr)

    if len(addresses) < 2:
        return ""

    rep_addr = addresses[0]

    def _lot(addr):
        m = re.search(r'\s산\s*(\d+)(?:-(\d+))?\s*$', addr)
        if m:
            return (True, m.group(1), m.group(2) or "")
        m = re.search(r'\s(\d+)(?:-(\d+))?\s*$', addr)
        if m:
            return (False, m.group(1), m.group(2) or "")
        return (None, "", "")

    rep_is_san, rep_bun1, _ = _lot(rep_addr)

    parts = []
    for addr in addresses[1:]:
        is_san, bun1, bun2 = _lot(addr)
        if is_san is None:
            continue
        if is_san:
            parts.append(f"산{bun1}-{bun2}" if bun2 else f"산{bun1}")
        elif not rep_is_san and bun1 == rep_bun1:
            parts.append(f"-{bun2}" if bun2 else f"-{bun1}")
        else:
            parts.append(f"{bun1}-{bun2}" if bun2 else bun1)

    return ", ".join(parts)


_NH_DONG_HO_RE = re.compile(
    r'(?:([A-Za-z가-힣])\s*동\s+)?(\d+)\s*호\s*$'
)
_NH_LOT_RE = re.compile(r'\s(\d+)\s*$')


def _extract_nh_multiunit_hoetc(ls: list) -> dict | None:
    """농협 동일 필지 다호수 추출.

    ▣물건내역 블록별 우편번호주소를 수집하고,
    모두 같은 지번이면 호수 오름차순 정렬 후 분리한다.

    Returns dict with:
        raw_addrs   : 수집된 원본 우편번호주소 목록
        primary_addr: 대표 주소 (가장 작은 호수)
        primary_ho  : 대표 호수 문자열 (예 "101")
        dong        : 동 (예 "B동", 없으면 "")
        hoetc       : 나머지 호수 포맷 (예 "102, 107, 201호")
    or None if not a same-lot multi-unit.
    """
    _SKIP = frozenset(['우편번호', '소재지', '소 재 지', '주소', '주    소'])

    # 1. ▣물건내역 블록 시작 인덱스
    block_starts = [i for i, ln in enumerate(ls) if '▣물건내역' in ln]
    if len(block_starts) < 2:
        return None

    # 2. 각 블록에서 우편번호주소 추출
    raw_addrs = []
    for k, bstart in enumerate(block_starts):
        bend = block_starts[k + 1] if k + 1 < len(block_starts) else len(ls)
        for i in range(bstart + 1, bend):
            v = ls[i].strip()
            if v.replace(' ', '') != '우편번호주소':
                continue
            for j in range(i + 1, min(i + 6, bend)):
                vv = ls[j].strip()
                if not vv or vv.isdigit():
                    continue
                if vv.replace(' ', '') in _SKIP:
                    continue
                if '▣' in vv:
                    break
                raw_addrs.append(vv)
                break
            break

    if len(raw_addrs) < 2:
        return None

    # 3. 각 주소에서 (lot, dong, ho) 파싱
    units = []
    for addr in raw_addrs:
        m_dh = _NH_DONG_HO_RE.search(addr)
        if not m_dh:
            continue
        dong = m_dh.group(1) or ""
        ho   = int(m_dh.group(2))
        base = addr[:m_dh.start()].strip()
        m_lot = _NH_LOT_RE.search(base)
        if not m_lot:
            continue
        lot = m_lot.group(1)
        # 동 suffix 표준화: 단독 알파벳/한글 문자이면 '동' suffix 붙임
        dong_full = (dong + "동") if dong else ""
        units.append({"addr": addr, "lot": lot, "dong": dong_full, "ho": ho})

    if len(units) < 2:
        return None

    # 4. 동일 필지 확인 (다필지면 기존 로직에 위임)
    if len({u["lot"] for u in units}) > 1:
        return None

    # 5. 호수 오름차순 정렬
    units.sort(key=lambda u: u["ho"])

    # 6. 대표 (가장 작은 호수), hoetc (나머지)
    primary = units[0]
    others  = units[1:]
    hoetc   = (", ".join(str(u["ho"]) for u in others) + "호") if others else ""

    return {
        "raw_addrs":   raw_addrs,
        "primary_addr": primary["addr"],
        "primary_ho":   str(primary["ho"]),
        "dong":         primary["dong"],
        "hoetc":        hoetc,
    }


_IBK_SOJAEGI_FALLBACK_PTN = re.compile(
    r'(?:동|읍|면|리)\s+'
    r'\d+(?:-\d+)?\s*,\s*\d+\s+'
    r'(?P<floor>\d+)\s*층\s+'
    r'(?P<ho>\d{2,5})\s*호'
)


def _extract_ibk_address_extra(ls: list) -> dict:
    """기업은행 '새주소 상세' 다호수 + '소재지' fallback에서 호수/층 추출."""
    empty = {"primary_ho": "", "hoetc": "", "floor": ""}

    # 1단계: 새주소 상세 시도
    for i, line in enumerate(ls):
        if line.replace(' ', '') == '새주소상세':
            for j in range(i + 1, min(i + 4, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                raw_tokens = [t.strip() for t in v.split(",")]
                tokens = [re.sub(r"호$", "", t.strip()) for t in raw_tokens if t.strip()]
                if not tokens:
                    break  # 유효값 없음 → fallback 계속
                if not all(re.fullmatch(r"\d+(?:-\d+)?", t) for t in tokens):
                    break  # 형식 불일치 → fallback 계속
                primary_ho = tokens[0]
                if len(tokens) == 1:
                    return {"primary_ho": primary_ho, "hoetc": "", "floor": ""}
                hoetc = ",".join(tokens[1:]) + "호"
                return {"primary_ho": primary_ho, "hoetc": hoetc, "floor": ""}
            break  # 새주소상세 라벨 발견 후 루프 종료 → fallback으로

    # 2단계: 소재지/소 재 지 fallback (다필지 주소 뒤 층·호 추출)
    for i, line in enumerate(ls):
        if line.strip() in ('소재지', '소 재 지'):
            for j in range(i + 1, min(i + 4, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                m = _IBK_SOJAEGI_FALLBACK_PTN.search(v)
                if m:
                    return {"primary_ho": m.group("ho"), "hoetc": "", "floor": m.group("floor")}
                break
            break

    return empty


# ── 수협은행 전용 helpers ─────────────────────────────────────────────────────

_SUHYUP_BRANCH_KEYWORDS = ("지점", "센터", "본부", "금융")
_SUHYUP_LABEL_SKIP = frozenset(["의뢰점", "담당자", "의뢰", "기관"])


def _extract_suhyup_request_info(ls: list) -> dict:
    """수협은행 헤더/기본정보 블록에서 의뢰 관련 필드 추출."""
    result = {
        "est_no": "", "debtor": "", "request_date": "", "deadline_date": "",
        "branch": "", "cust_emp": "", "cust_phone": "", "bigo": "",
        "regional_cust_name": "",
    }

    # ── 감정서번호: 라벨+값 합친 줄에서 추출
    for line in ls[:20]:
        m_est = re.search(r"감정서번호\s*([0-9]{2,6}-\d{1,4}-\d{1,4}(?:-\d+)?)", line)
        if m_est:
            result["est_no"] = m_est.group(1)
            break

    # ── 첫 번째 '▣' 위치
    first_tri = len(ls)
    for i, v in enumerate(ls):
        if v == '▣':
            first_tri = i
            break

    # ── 헤더 시작: 첫 번째 ▣ 이전의 마지막 '정보' 라인
    hdr_start = None
    for i in range(first_tri - 1, -1, -1):
        if ls[i] == '정보':
            hdr_start = i
            break

    if hdr_start is not None:
        values = []
        for i in range(hdr_start + 1, first_tri):
            v = ls[i].strip()
            if not v:
                continue
            if v in _SUHYUP_LABEL_SKIP:
                continue
            if v == '수협은행':
                continue
            if '수산업협동조합' in v:
                if not result['regional_cust_name']:
                    result['regional_cust_name'] = v.strip()
                continue
            if v == 'E-MAIL':
                continue
            values.append(v)

        if len(values) >= 3:
            result["branch"] = values[0]
            result["debtor"] = values[-2]
            result["cust_emp"] = values[-1]
        elif len(values) == 2:
            if any(kw in values[0] for kw in _SUHYUP_BRANCH_KEYWORDS):
                result["branch"] = values[0]
                result["debtor"] = values[1]
                result["cust_emp"] = ""
            else:
                result["branch"] = ""
                result["debtor"] = values[0]
                result["cust_emp"] = values[1]
        elif len(values) == 1:
            result["branch"] = ""
            result["debtor"] = values[0]
            result["cust_emp"] = ""

    # ── 의뢰일자: '의뢰일자' 라벨 직전 2줄 합치기
    for i, v in enumerate(ls):
        if v == '의뢰일자' and i >= 2:
            part1 = ls[i - 2].strip()
            part2 = ls[i - 1].strip()
            if part1:
                result["request_date"] = (part1 + " " + part2).strip()
            break

    # ── 처리기한: '요구일자' 라벨 다음 첫 날짜값
    for i, v in enumerate(ls):
        if v == '요구일자':
            for j in range(i + 1, min(i + 5, len(ls))):
                nv = ls[j].strip()
                if nv and re.search(r'\d{4}-\d{2}-\d{2}', nv):
                    result["deadline_date"] = nv
                    break
            break

    # ── 담당자 연락처: 첫 번째 '전화번호' 라벨 다음 유효값
    for i, v in enumerate(ls):
        if v == '전화번호':
            for j in range(i + 1, min(i + 4, len(ls))):
                nv = ls[j].strip()
                if nv:
                    result["cust_phone"] = nv
                    break
            break

    # ── 비고: '비 고' 라벨 다음부터 '▣' 전까지, 순수 숫자 제외
    bigo_parts = []
    in_bigo = False
    for v in ls:
        if v == '비 고':
            in_bigo = True
            continue
        if in_bigo:
            if v == '▣':
                break
            s = v.strip()
            if not s:
                continue
            if re.fullmatch(r'\d+', s):
                continue
            bigo_parts.append(s)
    result["bigo"] = " ".join(bigo_parts)

    return result


def _extract_suhyup_object_info(ls: list) -> dict:
    """수협은행 물건정보 블록에서 소유자/소재지/물건종류 추출."""
    result = {"owner": "", "owner_phone": "", "sojaegi": "", "category": ""}

    _OWN_SKIP = frozenset(['성명', '자택전화번호', '직장전화번호', '휴대폰번호', '품목명', '동 산'])

    # ── 물건종류: 두 번째 '구 분' (다음 값이 '상호'가 아닌 것)
    for i, v in enumerate(ls):
        if v == '구 분':
            for j in range(i + 1, min(i + 5, len(ls))):
                nv = ls[j].strip()
                if not nv:
                    continue
                if nv == '상호':
                    break
                result["category"] = nv
                break
            if result["category"]:
                break

    # ── 소유자: '소유자' 라벨 이후 1~5줄에서 유효 이름
    for i, v in enumerate(ls):
        if v == '소유자':
            for j in range(i + 1, min(i + 6, len(ls))):
                nv = ls[j].strip()
                if not nv:
                    continue
                if nv in _OWN_SKIP:
                    break
                result["owner"] = nv
                break
            break

    # ── 소재지: '물건내역' 이후 '소재지' 라벨 다음 첫 유효값
    found_mulgeon = False
    for i, v in enumerate(ls):
        if v == '물건내역':
            found_mulgeon = True
            continue
        if found_mulgeon and v == '소재지':
            for j in range(i + 1, min(i + 5, len(ls))):
                nv = ls[j].strip()
                if nv:
                    result["sojaegi"] = nv
                    break
            break

    return result


# ── 헤더 ──────────────────────────────────────────────────────────────────────

def _parse_header(text, ls):
    """(은행명, 의뢰번호, 감정서번호) 추출"""
    # 1. 하이픈형 감정서번호 우선 (신한은행 등)
    docid = None
    for i, line in enumerate(ls):
        if '감정서번호' in line:
            for j in range(i, min(i+5, len(ls))):
                m = re.search(r'(\d{2}-\d{4}-\d-\d{4})', ls[j])
                if m: docid = m.group(1); break
            if docid: break

    # 2. 기존 정규식: 형태 A (의뢰기관:\n은행명\n숫자)
    bank_nm = None
    cust_docid = None
    m_hdr = re.search(
        r'의뢰기관:\s*\n(?:의뢰번호:\s*\n|감정서번\s*\n)?([^\n\d][^\n]*?)\n(\d[\d]+)',
        text
    )
    if m_hdr:
        bank_nm    = m_hdr.group(1).strip()
        cust_docid = m_hdr.group(2).strip()

    # 3. 은행명 fallback: bank_nm 비어 있을 때
    if not bank_nm:
        for i, line in enumerate(ls):
            if '의뢰기관:' not in line:
                continue
            # 형태 B: "의뢰기관: 기업은행" — 같은 줄에 값 있음
            after = line[line.index('의뢰기관:') + len('의뢰기관:'):].strip()
            if after:
                bank_nm = after
                break
            # 형태 A: 다음 줄 탐색
            for j in range(i+1, min(i+4, len(ls))):
                v = ls[j].strip()
                if not v:
                    continue
                if v.isdigit():
                    continue
                if any(lbl in v for lbl in ('의뢰번호', '감정서번호', '감정서')):
                    break
                bank_nm = v
                break
            break

    # 4. 숫자형 감정서번호 fallback (기업은행 등) — hyphened docid 없을 때만
    if not docid:
        for i, line in enumerate(ls):
            if '감정서번호' not in line and line.strip() != '감정서':
                continue
            # 같은 줄 suffix (예: "감정서번호0490260547")
            if '감정서번호' in line:
                suffix = line[line.index('감정서번호') + len('감정서번호'):].strip()
                if suffix and re.fullmatch(r'\d{8,12}', suffix) and not _is_date(suffix):
                    docid = suffix; break
            # 다음 1~5줄 탐색
            for j in range(i+1, min(i+6, len(ls))):
                v = ls[j].strip()
                if not v: continue
                if any(lbl in v for lbl in _DATE_LABEL_PREFIXES): continue
                if re.fullmatch(r'\d{8,12}', v) and not _is_date(v):
                    docid = v; break
            if docid: break

    # 5. cust_docid가 순수 숫자형이면 docid로도 사용
    if not docid and cust_docid and re.fullmatch(r'\d{8,12}', cust_docid) and not _is_date(cust_docid):
        docid = cust_docid

    return bank_nm, cust_docid, docid


# ── 값 섹션 ───────────────────────────────────────────────────────────────────

def _get_values_section(ls):
    sec_start = None
    for i, line in enumerate(ls):
        if '▣의뢰내역' in line: sec_start = i; break
    if sec_start is None: return []
    values = []
    for j in range(sec_start+1, len(ls)):
        v = ls[j]
        if not v: continue
        if any(w in v for w in ['세  금','기  본','소   속']): break
        values.append(v)
    return values

def _parse_values(vs):
    result = {}
    for v in vs:
        if _is_name(v) and not _is_phone(v) and not _is_date(v):
            result['채무자'] = v; break
    for v in vs:
        if _is_phone(v): result['담당자 연락처'] = v; break
    found_phone = False
    for v in vs:
        if _is_phone(v): found_phone = True; continue
        if found_phone and _is_person_name(v): result['담당자_hint'] = v; break
    debtor = result.get('채무자')
    for v in vs:
        if _is_phone(v) or _is_date(v) or _is_stop(v): continue
        if '@' in v or 'E-Mail' in v: continue
        if _is_label(v): continue
        if v == debtor: continue
        if re.match(r'^[\d\s\-]+$', v): continue
        if not _is_valid_branch(v): continue
        result['영업점'] = v; break
    return result


# ── 메인 파싱 ─────────────────────────────────────────────────────────────────

def _pdf_fail_dict(pdf_path, reason: str, docid: str = "") -> dict:
    return {
        "처리상태": "실패",
        "실패사유": reason,
        "의뢰번호": docid, "감정서번호": "",
        "상세창 의뢰번호": docid, "상세창 감정서번호": "",
        "은행": "", "영업점": "", "담당자": "", "담당자 연락처": "",
        "채무자": "", "소유자": "", "소유자 연락처": "", "비고": "",
        "addresses": [],
        "pdf_우편번호주소": "", "pdf_소재지": "", "물건종류": "",
        "접수일자": "", "의뢰일자": "", "처리기한": "",
        "감정평가담보구분": "",
        "신청번호": "",
        "상품명": "",
        "이의신청 여부": "",
        "내부조사 신청여부": "",
        "기 의뢰 신청번호": "",
        "DB 건물명": "",
        "DB 대표층": "",
        "DB 대표호수": "",
        "DB hoetc": "",
        "채무자 연락처": "",
        "pdf_path": str(pdf_path),
    }


def parse_bank24_pdf(pdf_path: str) -> dict:
    """Bank24 의뢰서 PDF 파싱 → Y_BankAuto item dict 반환"""
    try:
        doc  = fitz.open(pdf_path)
        text = '\n'.join(page.get_text() for page in doc)
        doc.close()
    except Exception as e:
        return _pdf_fail_dict(pdf_path, f"PDF 열기 실패: {e}")

    try:
        ls = _ls(text)

        bank_nm, cust_docid, docid = _parse_header(text, ls)

        # ── 오류 PDF 감지 ─────────────────────────────────────────────────────
        # Bank24가 내려주는 오류 PDF: "오류" 단독 라인 존재 + 핵심 섹션/주소 없음
        compact_text = "\n".join(t.strip() for t in ls if t.strip())
        has_error_line = any(t.strip() == "오류" for t in ls)
        has_object_info = any(
            k in compact_text
            for k in ("▣물건내역", "소재지", "세부주소", "주 소", "주    소")
        )
        if has_error_line and not has_object_info:
            return _pdf_fail_dict(pdf_path, "PDF 오류 문서", docid=cust_docid or "")

        # 의뢰번호 ↔ 감정서번호 상호 fallback (기업은행 등)
        if not docid and cust_docid and not _is_date(cust_docid):
            docid = cust_docid
        if not cust_docid and docid:
            cust_docid = docid

        vs        = _get_values_section(ls)
        vs_parsed = _parse_values(vs) if vs else {}

        # ── 채무자 ────────────────────────────────────────────────────────────
        debtor = vs_parsed.get('채무자')
        if not debtor:
            for i, line in enumerate(ls):
                if line == '채무자' and i > 2:
                    for j in range(i-1, max(i-6,-1), -1):
                        v = ls[j]
                        if v and (_is_name(v) or _is_entity_name(v)) and v != bank_nm and not _is_stop(v) and not _is_date(v):
                            debtor = v; break
                    break
        if not debtor:
            for v in _all_after(ls, '신청인명'):
                if _is_name(v) and not _is_phone(v): debtor = v; break

        # 채무자 라벨 확장 fallback: "채무자 성명", "채무자성명", "채 무 자" 등
        if not debtor:
            for lbl in ("채무자 성명", "채무자성명", "채 무 자", "채무자", "차 주", "차주"):
                # 1. 같은 줄 값 (예: "채무자 성명 (주)서린상사")
                v = _same_line_value(ls, lbl)
                if v:
                    if v.startswith("성명"):
                        v = v[len("성명"):].strip()
                    if _is_name_flexible(v) or _is_entity_name(v):
                        debtor = v; break
                # 2. 라벨 다음 max_look=6 줄 탐색
                for i, line in enumerate(ls):
                    if not line.startswith(lbl):
                        continue
                    for j in range(i+1, min(i+7, len(ls))):
                        vv = ls[j].strip()
                        if not vv: continue
                        if (_is_name_flexible(vv) or _is_entity_name(vv)) and not _is_phone(vv) and not _is_date(vv) and not _is_stop(vv):
                            debtor = vv; break
                    break
                if debtor: break

        # ── 소유자 + 소유자 연락처 ────────────────────────────────────────────
        # PDF 레이아웃 예: '소유자' / '연락처' / '050217236413' / 'PARK KWAN HYUNG'
        owner = None
        owner_phone = None
        for i, line in enumerate(ls):
            if line.strip() in ('소유자', '소 유 자'):
                # 이후 max 8줄에서 전화번호 + 이름 탐색
                for j in range(i+1, min(i+9, len(ls))):
                    v = ls[j]
                    if not v: continue
                    if _is_phone(v) and not owner_phone:
                        owner_phone = v; continue
                    if (
                        (_is_name_flexible(v) or _is_entity_name(v))
                        and not _is_phone(v)
                        and not _is_date(v)
                        and not _is_stop(v)
                        and not _is_business_label(v)
                        and v not in _PROPERTY_TYPE_NAMES
                    ):
                        if not _is_label(v) and v not in ('연락처', '성 명', '성명'):
                            if not owner:
                                owner = v
                break
        # fallback: 기존 방식
        if not owner:
            for label in ['소유자', '소 유 자']:
                v = _before(ls, label, max_look=3)
                if v and (_is_name_flexible(v) or _is_entity_name(v)) and not _is_phone(v) and not _is_date(v) and not _is_business_label(v) and v not in _PROPERTY_TYPE_NAMES:
                    owner = v; break
        # 소유자 연락처 fallback
        if not owner_phone:
            for label in ['소유자 연락처', '안심번호', '소유자연락처']:
                v = _after(ls, label, max_look=5)
                if v and _is_phone(v): owner_phone = v; break

        # ── 영업점 ────────────────────────────────────────────────────────────
        def _bad(v):
            if not v: return True
            if _is_stop(v) or _is_date(v) or _is_phone(v) or _is_label(v): return True
            if '@' in v or 'E-Mail' in v: return True
            if any(v.endswith(e) for e in _BAD_BRANCH_ENDINGS): return True
            return len(v) < 2

        def _good_branch(v):
            return bool(v and not _bad(v) and not _is_business_label(v) and _is_valid_branch(v))

        # 1. 명시 라벨 탐색 우선
        branch = None
        for label in ('지점명', '지 점 명', '영업점', '영 업 점', '의뢰점', '요청부서명', '금   고'):
            for candidate in (
                _same_line_value(ls, label),
                _after(ls, label, max_look=5),
                _before(ls, label, max_look=3),
            ):
                if _good_branch(candidate):
                    branch = candidate
                    break
            if branch:
                break
            # 추가: 라벨 이후 1~6줄 다중 스캔 (라벨 직후 값 누락 케이스 대응)
            for i, line in enumerate(ls):
                if label not in line:
                    continue
                for j in range(i + 1, min(i + 7, len(ls))):
                    v = ls[j].strip()
                    if not v:
                        continue
                    if _bad(v):
                        continue
                    if _is_business_label(v):
                        continue
                    if _is_date(v):
                        continue
                    if _is_phone(v):
                        continue
                    if _is_address(v) and not _is_valid_branch(v):
                        continue
                    if _is_name_flexible(v) and not _is_valid_branch(v):
                        continue
                    if v in _BRANCH_SCAN_SKIP_LABELS:
                        continue
                    if _good_branch(v) and (not _is_person_name(v) or _is_branch_org_name(v)):
                        branch = v
                        break
                if branch:
                    break
            if branch:
                break

        # 2. vs_parsed fallback (검증 통과 시에만)
        if not branch:
            v = vs_parsed.get('영업점')
            if v and _good_branch(v):
                branch = v

        # 3. HUG 전용: 요청부서명 추출 + 신청번호/상품명 등 추가 필드
        if bank_nm == "주택도시보증공사":
            hug_extra = _extract_hug_request_extra(ls)
            if '▣의뢰내역' in text:
                _hug_branch = _extract_hug_branch_from_ls(ls, _good_branch)
                if _hug_branch:
                    branch = _hug_branch
        else:
            hug_extra = {}

        # ── 담당자 연락처 ──────────────────────────────────────────────────────
        cust_phone = vs_parsed.get('담당자 연락처')
        if not cust_phone:
            for label in ['금고 전화번호','담당자연락처','의뢰지점전화번호','대표번호']:
                v = _after(ls, label)
                if v and _is_phone(v): cust_phone = v; break
        if not cust_phone:
            phone_cands = []
            for i, line in enumerate(ls):
                if line.strip() == '전화번호':
                    v = _after(ls, '전화번호', start=i)
                    if v and _is_phone(v): phone_cands.append(v)
            if phone_cands: cust_phone = phone_cands[-1]

        # ── 담당자 ────────────────────────────────────────────────────────────
        cust_emp = None
        # 1. 명시 라벨 탐색 (_is_employee_name_candidate 사용)
        for label in ('담당자명', '담 당 자', '담당자', '금고 담당자명'):
            v = _same_line_value(ls, label)
            if v and _is_employee_name_candidate(v):
                cust_emp = v; break
            for i, line in enumerate(ls):
                if label in line:
                    for j in range(i+1, min(i+7, len(ls))):
                        vv = ls[j].strip()
                        if vv and _is_employee_name_candidate(vv):
                            cust_emp = vv; break
                    break
            if cust_emp: break
        # 2. 기존 fallback (business label 아닌 경우만)
        if not cust_emp:
            v = vs_parsed.get('담당자_hint')
            if v and not _is_business_label(v): cust_emp = v
        if not cust_emp:
            v = _person_name_after(ls, '담당자')
            if v and not _is_business_label(v): cust_emp = v
        if cust_emp and cust_emp == debtor:
            cust_emp = vs_parsed.get('담당자_hint')
        if not cust_emp:
            cust_emp = vs_parsed.get('담당자_hint')
        # 3. 의뢰점 라벨 주변 담당자 보정 (cust_emp 비어 있을 때만)
        if not cust_emp:
            for i, line in enumerate(ls):
                if '의뢰점' not in line:
                    continue
                for j in range(i + 1, min(i + 7, len(ls))):
                    if ls[j].strip() not in ('담당자', '담 당 자'):
                        continue
                    for k in range(j + 1, min(j + 4, len(ls))):
                        v = ls[k].strip()
                        if not v:
                            continue
                        if _is_business_label(v) or _is_phone(v) or _is_date(v):
                            continue
                        if _is_valid_branch(v) and not _is_employee_name_candidate(v):
                            continue
                        if _is_employee_name_candidate(v):
                            cust_emp = v
                            break
                    break
                if cust_emp:
                    break

        # ── 우편번호주소 ──────────────────────────────────────────────────────
        # PDF 레이아웃: '우편번호주소경기도 가평군 상면 율길리' (라벨+값 동일 줄)
        postal_addr = None
        for label in ['우편번호주소','우 편 번 호 주 소']:
            v = _same_line_value(ls, label)            # 동일 줄 우선
            if v and _is_address(v):
                postal_addr = _clean_addr(v); break
            v = _after(ls, label, max_look=5)          # 다음 줄 fallback
            if v and _is_address(v):
                postal_addr = _clean_addr(v); break

        # ── 소재지 ────────────────────────────────────────────────────────────
        # 물건내역 섹션 이후 주소 우선 탐색 → fallback: 전체 라벨 탐색
        _OBJECT_ADDR_LABELS = ('주    소', '주 소', '주소', '소재지', '소 재 지')
        sojaegi = None
        _obj_sec = None
        for i, line in enumerate(ls):
            if '물건내역' in line.replace(' ', ''):
                _obj_sec = i
                break
        if _obj_sec is not None:
            for i in range(_obj_sec + 1, len(ls)):
                if not any(lbl in ls[i] for lbl in _OBJECT_ADDR_LABELS):
                    continue
                for j in range(i + 1, min(i + 6, len(ls))):
                    v = ls[j].strip()
                    if not v or _is_phone(v) or _is_date(v) or _is_label(v):
                        continue
                    if len(v) > 5 and _is_address(v):
                        sojaegi = _clean_addr(v)
                        break
                if sojaegi:
                    break
        if not sojaegi:
            for label in ['소재지', '소 재 지', '세부주소', '주    소']:
                v = _after(ls, label)
                if v and len(v) > 5 and _is_address(v):
                    sojaegi = _clean_addr(v)
                    break
        if not postal_addr and sojaegi:
            postal_addr = sojaegi

        # HUG 전체주소 → pdf_우편번호주소 갱신
        if bank_nm == "주택도시보증공사":
            _hug_full = _extract_hug_full_addr(ls)
            if _hug_full:
                postal_addr = _hug_full

        # ── 담보종류 ──────────────────────────────────────────────────────────
        _CHECKBOX = {'▣', '□', '☑', '■'}
        category = None
        for label in ['담보종류','담 보 종 류','물건종류','물 건 종 류','담보물종류','부동산용도','부동산 용도']:
            for v in _all_after(ls, label, max_look=8):
                vv = v.strip()
                if not vv: continue
                if _is_stop(vv) or _is_date(vv) or _is_phone(vv): continue
                if vv.isdigit(): continue
                if re.match(r'^[\-\s\d]+$', vv): continue
                if vv in _CHECKBOX: continue
                if vv in _LABEL_SET: continue
                if vv in _CATEGORY_SKIP: continue
                compact = vv.replace(" ", "").replace("▣", "")
                if compact == "물건내역": continue
                if _is_company(vv): continue
                category = vv; break
            if category: break

        # ── 날짜 ──────────────────────────────────────────────────────────────
        receipt_date  = _extract_date(ls, '접수일자', '접 수 일 자')
        request_date  = _extract_date(ls, '의뢰일자', '의 뢰 일 자')
        deadline_date = _extract_date(ls, '처리기한', '처 리 기 한', '감정요구일자')

        # ── 비고 ──────────────────────────────────────────────────────────────
        bigo = None
        bigo_name_candidate = ""
        for label in ['비   고','비 고1','비 고','전달사항','참고사항']:
            for i, line in enumerate(ls):
                if label in line:
                    parts = []
                    found_content = False
                    for j in range(i+1, min(i+20, len(ls))):
                        v = ls[j]
                        if not v: continue
                        if _is_stop(v) or _is_date(v): break
                        if re.match(r'^▣|^기  본|^소   속|^세  금|^수수료|^물건|^소유자|^소재지|^일련번호', v): break
                        if v in ('비 고2','비고2','비   고','탁상자문번호','수수료지급','주체','당행','당행 외','차주'): break
                        v_compact = v.replace(' ', '')
                        if v_compact in _BIGO_STOP_COMPACT: break
                        if found_content and _is_company(v): break
                        if len(v_compact) <= 4 and re.match(r'^[가-힣]+$', v_compact):
                            if found_content: break
                            else: continue
                        if found_content and _is_debtor_owner_candidate_from_bigo(v):
                            lookahead = [ls[k].replace(' ', '') for k in range(j+1, min(j+4, len(ls))) if ls[k]]
                            if any(x in ('채무자', '소유자', '채무자성명', '소유자성명') for x in lookahead):
                                bigo_name_candidate = v.strip()
                                break
                        parts.append(v); found_content = True
                    if parts: bigo = ' '.join(parts[:3]); break
            if bigo and len(bigo) > 3: break

        if not debtor and bigo:
            dm = re.search(r'채무자[:：]\s*([^/\n]+)', bigo)
            if dm: debtor = dm.group(1).strip()

        # 소유자 최종 방어: business label이면 제거
        if owner and _is_business_label(owner):
            owner = ""

        # bigo_name_candidate fallback: 채무자/소유자 직전에서 분리한 이름 후보
        if bigo_name_candidate and _is_debtor_owner_candidate_from_bigo(bigo_name_candidate):
            if not debtor:
                debtor = bigo_name_candidate
            if not owner or _is_business_label(owner):
                owner = bigo_name_candidate

        # HUG 채무자 보정: 상품명 등 무효값이면 신청인명으로 교체
        if bank_nm == "주택도시보증공사":
            if not debtor or debtor in _HUG_DEBTOR_INVALID:
                _hug_applicant = _extract_hug_applicant_name(ls)
                if _hug_applicant:
                    debtor = _hug_applicant

        # HUG 감정평가담보구분 + 의뢰번호 보정 (신청번호)
        if bank_nm == "주택도시보증공사":
            hug_collateral_purpose = _extract_hug_collateral_purpose(ls)
            if hug_extra.get("application_no"):
                cust_docid = hug_extra["application_no"]
        else:
            hug_collateral_purpose = ""

        addresses = []
        if sojaegi:    addresses.append(sojaegi)
        elif postal_addr: addresses.append(postal_addr)

        db_building = ""
        db_floor = ""
        db_primary_ho = ""
        db_hoetc = ""
        debtor_phone = ""

        # HUG 신청인 전화번호 → 채무자 연락처 (debtor_phone 초기화 이후에 적용)
        if bank_nm == "주택도시보증공사":
            _hug_app_phone = _extract_hug_applicant_phone(ls)
            if _hug_app_phone:
                debtor_phone = _hug_app_phone

        # ── 국민은행 전용 보정 ───────────────────────────────────────────────────
        _is_kb = (bank_nm == "국민은행") or ("국민은행－" in text)
        if _is_kb:
            kb_req  = _extract_kookmin_request_info(ls)
            kb_objs = _extract_kookmin_objects(ls)

            if kb_req.get("debtor"):        debtor        = kb_req["debtor"]
            if kb_req.get("request_date"):  request_date  = kb_req["request_date"]
            if kb_req.get("branch"):        branch        = kb_req["branch"]
            cust_emp   = kb_req.get("cust_emp")   or ""
            cust_phone = kb_req.get("cust_phone") or ""

            # KB 참고사항 → Bigo (공부요청구분 등 다음 라벨 오염 방지)
            bigo = _extract_kb_bigo(ls)

            if kb_objs:
                first = kb_objs[0]
                if first["address"]:
                    sojaegi    = first["address"]
                    postal_addr = first["address"]
                if first["owner"]:        owner       = first["owner"]
                if first["owner_phone"]: owner_phone = first["owner_phone"]
                if first["category"]:    category    = first["category"]
                addresses = [o["address"] for o in kb_objs if o["address"]]

        # ── 새마을금고 전용 보정 ─────────────────────────────────────────────
        _is_smg = (bank_nm == "새마을금고") or any("새마을금고" in t for t in ls[:30])
        if _is_smg:
            smg_req = _extract_saemaeul_request_info(ls)
            smg_obj = _extract_saemaeul_object_info(ls)

            if smg_req.get("debtor"):       debtor        = smg_req["debtor"]
            if smg_req.get("request_date"): request_date  = smg_req["request_date"]
            if smg_req.get("branch"):       branch        = smg_req["branch"]
            if smg_req.get("cust_emp"):     cust_emp      = smg_req["cust_emp"]
            if smg_req.get("cust_phone"):   cust_phone    = smg_req["cust_phone"]
            if smg_req.get("bigo"):         bigo          = smg_req["bigo"]
            if smg_obj.get("owner"):        owner         = smg_obj["owner"]
            if smg_obj.get("owner_phone"):  owner_phone   = smg_obj["owner_phone"]
            if smg_obj.get("sojaegi"):
                sojaegi     = smg_obj["sojaegi"]
                postal_addr = smg_obj["sojaegi"]
                addresses   = [smg_obj["sojaegi"]]
            if smg_obj.get("category"):     category      = smg_obj["category"]

        # ── 하나은행 전용 보정 ─────────────────────────────────────────────
        _is_hana = (
            bank_nm in ("KEB하나은행", "하나은행")
            or any("KEB하나은행" in t or "하나은행" in t for t in ls[:30])
        )
        if _is_hana:
            hana_req = _extract_hana_request_info(ls)
            hana_obj = _extract_hana_object_info(ls)

            if hana_req["debtor"]:       debtor        = hana_req["debtor"]
            if hana_req["request_date"]: request_date  = hana_req["request_date"]
            if hana_req["branch"]:       branch        = hana_req["branch"]
            if hana_req["cust_emp"]:     cust_emp      = hana_req["cust_emp"]
            cust_phone = hana_req["cust_phone"] or ""
            if hana_req["bigo"]:         bigo          = hana_req["bigo"]

            if hana_obj["owner"]:        owner         = hana_obj["owner"]
            if hana_obj["owner_phone"]:  owner_phone   = hana_obj["owner_phone"]
            if hana_obj["sojaegi"]:
                sojaegi     = hana_obj["sojaegi"]
                postal_addr = hana_obj["sojaegi"]
                addresses   = [hana_obj["sojaegi"]]  # 대표주소 1건만
            if hana_obj["category"]:     category      = hana_obj["category"]
            elif category in ("우편번호",):
                category = ""
            if hana_obj["db_primary_ho"]: db_primary_ho = hana_obj["db_primary_ho"]
            if hana_obj["db_hoetc"]:      db_hoetc      = hana_obj["db_hoetc"]
            if hana_obj["db_building"]:   db_building   = hana_obj["db_building"]

        # ── 농협은행/농협중앙회 전용 보정 ────────────────────────────────────
        _is_nh = (
            bank_nm in ("농협은행", "농협중앙회")
            or any(("농협은행" in t or "농협중앙회" in t) for t in ls[:30])
        )
        if _is_nh:
            nh_req = _extract_nh_request_info(ls)

            if nh_req["debtor"]:        debtor       = nh_req["debtor"]
            if nh_req["request_date"]:  request_date = nh_req["request_date"]
            if nh_req["deadline_date"]: deadline_date = nh_req["deadline_date"]
            if nh_req["branch"]:        branch       = nh_req["branch"]
            if nh_req["cust_emp"]:      cust_emp     = nh_req["cust_emp"]
            cust_phone = nh_req["cust_phone"] or ""
            bigo       = nh_req["bigo"]
            if nh_req.get("debtor_phone"):
                debtor_phone = nh_req["debtor_phone"]

            # 동일 필지 다호수 처리 (▣물건내역 반복 블록)
            nh_multiunit = _extract_nh_multiunit_hoetc(ls)
            if nh_multiunit:
                # 대표 주소(가장 작은 호수)로 교체, Ho/hoetc 설정
                _mu_addr = nh_multiunit["primary_addr"]
                addresses     = [_mu_addr]
                sojaegi       = _mu_addr   # pdf_소재지도 대표 주소로 갱신
                postal_addr   = _mu_addr   # pdf_우편번호주소도 대표 주소로 갱신
                db_primary_ho = nh_multiunit["primary_ho"]
                db_hoetc      = nh_multiunit["hoetc"]
            else:
                # 기존 다필지 처리
                nh_additional_lots = _extract_nh_additional_lots(ls)
                if nh_additional_lots and not db_hoetc:
                    db_hoetc = nh_additional_lots

        # ── 수협은행 전용 보정 ─────────────────────────────────────────────
        regional_cust_name = ""
        _is_suhyup = (
            bank_nm == "수협은행"
            or any("수협은행" in t or "수산업협동조합" in t for t in ls[:30])
        )
        if _is_suhyup:
            sh_req = _extract_suhyup_request_info(ls)
            sh_obj = _extract_suhyup_object_info(ls)

            if sh_req["est_no"]:        docid         = sh_req["est_no"]
            if sh_req["debtor"]:        debtor        = sh_req["debtor"]
            if sh_req["request_date"]:  request_date  = sh_req["request_date"]
            if sh_req["deadline_date"]: deadline_date = sh_req["deadline_date"]
            if sh_req["branch"]:        branch        = sh_req["branch"]

            cust_emp          = sh_req["cust_emp"]          or ""
            cust_phone        = sh_req["cust_phone"]        or ""
            bigo              = sh_req["bigo"]              or ""
            regional_cust_name = sh_req.get("regional_cust_name", "") or ""

            if sh_obj["owner"]:
                owner = sh_obj["owner"]
            elif owner in ("품목명", "동 산", "E-MAIL"):
                owner = ""

            if sh_obj["owner_phone"]:  owner_phone = sh_obj["owner_phone"]
            if sh_obj["sojaegi"]:
                sojaegi     = sh_obj["sojaegi"]
                postal_addr = sh_obj["sojaegi"]
                addresses   = [sh_obj["sojaegi"]]
            if sh_obj["category"]:     category    = sh_obj["category"]

        # ── 기업은행 새주소 상세 다호수 보정 ──────────────────────────────────
        if bank_nm == "기업은행":
            ibk_extra = _extract_ibk_address_extra(ls)
            if ibk_extra.get("primary_ho"):
                db_primary_ho = ibk_extra["primary_ho"]
            if ibk_extra.get("hoetc"):
                db_hoetc = ibk_extra["hoetc"]
            if ibk_extra.get("floor"):
                db_floor = ibk_extra["floor"]

        return {
            "의뢰번호":          cust_docid    or "",
            "감정서번호":         docid         or "",
            "상세창 의뢰번호":    cust_docid    or "",
            "상세창 감정서번호":  docid         or "",
            "은행":              bank_nm       or "",
            "영업점":            branch        or "",
            "담당자":            cust_emp      or "",
            "담당자 연락처":      cust_phone    or "",
            "채무자":            debtor        or "",
            "소유자":            owner         or "",
            "소유자 연락처":      owner_phone   or "",
            "비고":              bigo          or "",
            "addresses":         addresses,
            "pdf_우편번호주소":   postal_addr   or "",
            "pdf_소재지":         sojaegi       or "",
            "물건종류":           category      or "",
            "접수일자":           receipt_date,
            "의뢰일자":           request_date,
            "처리기한":           deadline_date,
            "감정평가담보구분":    hug_collateral_purpose,
            "신청번호":           hug_extra.get("application_no", ""),
            "상품명":             hug_extra.get("product_name", ""),
            "이의신청 여부":       hug_extra.get("objection_yn", ""),
            "내부조사 신청여부":   hug_extra.get("internal_review_yn", ""),
            "기 의뢰 신청번호":    hug_extra.get("prev_application_no", ""),
            "지역수협명":         regional_cust_name or "",
            "DB 건물명":          db_building,
            "DB 대표층":          db_floor,
            "DB 대표호수":        db_primary_ho,
            "DB hoetc":           db_hoetc,
            "채무자 연락처":       debtor_phone,
            "처리상태":           "성공",
            "실패사유":           "",
        }
    except Exception as e:
        return _pdf_fail_dict(pdf_path, f"PDF 파싱 실패: {type(e).__name__}: {e}")
