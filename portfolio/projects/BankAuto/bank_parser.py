"""bank_parser.py — 은행별 담보감정평가의뢰서 PDF 파싱 모듈
FastReport PDF → PyMuPDF 텍스트 추출 → DB 컬럼 딕셔너리 반환

DB 컬럼 매핑:
  Docid      = 감정서번호
  CustDocid  = 의뢰번호 (기업은행=감정서번, 주택도시보증공사=신청번호)
  CustNm     = 의뢰기관명
  CustNm_Sub = 영업점/지점명/의뢰점/금고/요청부서명
  Purpose_Nm = '' (항상 공란)
  Category_Nm= '' (항상 공란)
  Reg        = 법정리
  Eub        = 읍/면/동/리/가
  Bun1       = 번지 본번
  Bun2       = 번지 부번
  Addr       = 물건 주소
  CustEmp    = 의뢰기관 담당자명
  CustPhone  = 의뢰기관 전화번호
  Debtor     = 채무자/신청인 성명
  Bigo       = 비고/참고사항/전달사항
"""
import re
import fitz


# ─── 분류 상수 ────────────────────────────────────────────────────────────────

_STOP_WORDS = ['▣', '기  본', '소   속', '세  금', '계산서', '의뢰기관',
               '감정서번호', '담보감정', '감정평가법인']

# 사람 이름 아닌 단어 (한글 2~4자 필터링용)
_NAME_EXCL = {
    '사업', '사업자', '대표자', '담당자', '채무자', '소유자', '신청인',
    '의뢰', '기관', '감정', '물건', '번호', '주소', '연락', '전화',
    '이메일', '정보', '계산서', '세금', '담보', '수수료', '금융', '보증',
    '지점', '영업', '임대차', '등기부', '공부', '임대차',
    '서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산',
    '성명', '업종', '업태', '본사', '지부', '구분', '기본',
}

# 지명/기관명 끝 글자 (사람 이름 끝 글자 아님)
_LOC_ENDINGS = set('역동로길가읍면구시군리점사관')

# 라벨성 단어
_LABEL_SET = {
    '담당자', '의뢰', '기관', '전화번호', '연락처', '이메일',
    '성명', '성 명', '성   명', '지점', '영업점', '소속',
    '의뢰점', '요청부서명', '금고',
}

# 지점명(CustNm_Sub)으로 인정하는 끝 글자/접미사
_VALID_BRANCH_ENDING_CHARS = set('역동로길가읍면구시군리점사관')
_VALID_BRANCH_ENDINGS = {'센터', '지점', '금고', '본점', '영업점', '팀', '창구', '부서'}

# 직접 라벨 검색 결과로 CustNm_Sub를 거부할 끝 어절
_BAD_BRANCH_ENDINGS = ('여부', '구분', '요청', '번호', '연락처', '이메일', '일자')


# ─── 유틸리티 함수 ────────────────────────────────────────────────────────────

def _is_stop(s: str) -> bool:
    return any(w in s for w in _STOP_WORDS) if s else True


def _is_phone(s: str) -> bool:
    if not s:
        return False
    cleaned = re.sub(r'[\s\-]', '', s)
    return bool(re.match(r'^\d{8,11}$', cleaned))


def _is_date(s: str) -> bool:
    return bool(re.match(r'\d{4}[-./년]\d{1,2}|\d{8}$', str(s).strip()))


def _is_person_name(s: str) -> bool:
    """한글 개인 이름 (2~4자, 지명·라벨 제외)"""
    if not s:
        return False
    s = s.strip()
    if not re.match(r'^[가-힣]{2,4}$', s):
        return False
    if s[-1] in _LOC_ENDINGS:
        return False
    for w in _NAME_EXCL:
        if w in s:
            return False
    return True


def _is_company(s: str) -> bool:
    keywords = ['주식회사', '(주)', '㈜', 'Ltd', 'Co.', '법인', '공사']
    return any(k in s for k in keywords) if s else False


def _is_name(s: str) -> bool:
    return (_is_person_name(s) or _is_company(s)) if s else False


def _is_address(s: str) -> bool:
    return any(k in s for k in ['시 ', '구 ', '군 ', '동 ', '읍 ', '리 ',
                                  '로 ', '서울', '경기', '인천', '부산',
                                  '시\n', '가 ']) if s else False


def _is_label(s: str) -> bool:
    return s in _LABEL_SET if s else False


def _is_bigo_hint(s: str) -> bool:
    """비고성 내용 (평가사님, 건임 등)"""
    return any(k in s for k in ['평가사', '님(', '건임', '연락처', '@',
                                  '방문', '통화', '요청']) if s else False


def _is_valid_branch(s: str) -> bool:
    """유효한 지점명 여부: 짧은 이름 허용, 긴 이름은 접미사 검증"""
    if not s:
        return False
    s = s.strip()
    if len(s) < 2 or len(s) > 20:
        return False
    if not any('\uac00' <= c <= '\ud7a3' for c in s):
        return False  # 한글 없음
    if len(s) <= 5:
        return True   # 짧은 이름 (부평, 오포, 본점, 대림역 등)
    if s[-1] in _VALID_BRANCH_ENDING_CHARS:
        return True
    for suffix in _VALID_BRANCH_ENDINGS:
        if s.endswith(suffix):
            return True
    return False


def _ls(text: str) -> list:
    return [l.strip() for l in text.split('\n')]


def _after(lines: list, label: str, start: int = 0, max_look: int = 12) -> str | None:
    """label 포함 줄 이후 첫 비어있지 않은 줄"""
    for i in range(start, len(lines)):
        if label in lines[i]:
            for j in range(i + 1, min(i + max_look + 1, len(lines))):
                if lines[j]:
                    return lines[j]
    return None


def _before(lines: list, label: str, max_look: int = 5) -> str | None:
    """label 포함 줄 이전 비어있지 않은 첫 줄"""
    for i, line in enumerate(lines):
        if label in line:
            for j in range(i - 1, max(i - max_look - 1, -1), -1):
                if lines[j]:
                    return lines[j]
    return None


def _all_after(lines: list, label: str, max_look: int = 12) -> list:
    """label 이후 비어있지 않은 줄 목록"""
    for i, line in enumerate(lines):
        if label in line:
            result = []
            for j in range(i + 1, min(i + max_look + 1, len(lines))):
                if lines[j]:
                    result.append(lines[j])
            return result
    return []


def _person_name_after(lines: list, label: str, start: int = 0, max_look: int = 15) -> str | None:
    """label 이후 첫 개인 이름 — 회사명·라벨·전화·날짜 건너뜀"""
    for i in range(start, len(lines)):
        if label in lines[i]:
            for j in range(i + 1, min(i + max_look + 1, len(lines))):
                v = lines[j]
                if not v or _is_stop(v) or _is_date(v) or _is_phone(v) or _is_company(v):
                    continue
                if _is_person_name(v):
                    return v
    return None


# ─── 헤더 파싱 ────────────────────────────────────────────────────────────────

def _parse_header(text: str, ls: list) -> tuple:
    """(CustNm, CustDocid, Docid) 추출"""
    # Docid: 감정서번호 라벨 이후 N줄 안에 있는 숫자-하이픈 조합
    docid = None
    for i, line in enumerate(ls):
        if '감정서번호' in line:
            for j in range(i, min(i + 5, len(ls))):
                m = re.search(r'(\d{2}-\d{4}-\d-\d{4})', ls[j])
                if m:
                    docid = m.group(1)
                    break
            if docid:
                break

    # CustNm + CustDocid: "의뢰기관:\n[선택라벨]\n은행명\n번호"
    m_hdr = re.search(
        r'의뢰기관:\s*\n(?:의뢰번호:\s*\n|감정서번\s*\n)?([^\n\d][^\n]*?)\n(\d[\d]+)',
        text
    )
    if m_hdr:
        return m_hdr.group(1).strip(), m_hdr.group(2).strip(), docid
    return None, None, docid


# ─── 값 섹션 추출 ─────────────────────────────────────────────────────────────

def _get_values_section(ls: list) -> list:
    """▣의뢰내역 이후 의뢰 값 목록 (세금/기본 섹션 이전까지)"""
    sec_start = None
    for i, line in enumerate(ls):
        if '▣의뢰내역' in line:
            sec_start = i
            break
    if sec_start is None:
        return []

    values = []
    for j in range(sec_start + 1, len(ls)):
        v = ls[j]
        if not v:
            continue
        if any(w in v for w in ['세  금', '기  본', '소   속']):
            break
        values.append(v)
    return values


def _parse_values(vs: list) -> dict:
    """값 섹션에서 Debtor, CustNm_Sub, CustPhone, CustEmp_hint 추출"""
    result = {}

    # Debtor: 첫 이름 (개인 또는 회사)
    for v in vs:
        if _is_name(v) and not _is_phone(v) and not _is_date(v):
            result['Debtor'] = v
            break

    # CustPhone: 섹션 전체에서 첫 전화번호
    for v in vs:
        if _is_phone(v):
            result['CustPhone'] = v
            break

    # CustEmp 힌트: CustPhone 이후 첫 개인 이름
    found_phone = False
    for v in vs:
        if _is_phone(v):
            found_phone = True
            continue
        if found_phone and _is_person_name(v) and not _is_bigo_hint(v):
            result['CustEmp_hint'] = v
            break

    # CustNm_Sub: 지점명 특성의 값 (위치 무관 스캔)
    debtor = result.get('Debtor')
    for v in vs:
        if _is_phone(v) or _is_date(v) or _is_stop(v):
            continue
        if '@' in v or 'E-Mail' in v or 'email' in v.lower():
            continue
        if _is_bigo_hint(v) or _is_label(v):
            continue
        if v == debtor:
            continue
        if re.match(r'^[\d\s\-]+$', v):  # 숫자/공백/하이픈만
            continue
        if not _is_valid_branch(v):
            continue
        result['CustNm_Sub'] = v
        break

    return result


# ─── 주소 분해 ────────────────────────────────────────────────────────────────

def _parse_addr_components(addr: str) -> tuple:
    """지번주소 → (Reg, Eub, Bun1, Bun2)
    Reg, Eub는 공백 반환.
    Bun1, Bun2는 '0000' 형식 4자리 zero-pad.
    """
    if not addr:
        return '', '', '0000', '0000'

    bm = re.search(r'(\d+)\s*-\s*(\d+)', addr)
    if bm:
        bun1 = str(int(bm.group(1))).zfill(4)
        bun2 = str(int(bm.group(2))).zfill(4)
    else:
        bm2 = re.search(r'\b(\d+)\b', addr.rstrip())
        bun1 = str(int(bm2.group(1))).zfill(4) if bm2 else '0000'
        bun2 = '0000'

    return '', '', bun1, bun2


def _clean_addr(addr: str) -> str:
    """중복 주소 정제"""
    if not addr or len(addr) < 20:
        return addr
    half = len(addr) // 2
    if addr[:half].strip() == addr[half:].strip():
        return addr[:half].strip()
    return addr.strip()


# ─── 메인 파싱 함수 ───────────────────────────────────────────────────────────

def parse_pdf(pdf_path: str) -> dict:
    """PDF 파싱 → DB 컬럼 딕셔너리"""
    doc = fitz.open(pdf_path)
    text = '\n'.join(page.get_text() for page in doc)
    doc.close()
    ls = _ls(text)

    # ── 헤더 ──────────────────────────────────────────────────────────────
    cust_nm, cust_docid, docid = _parse_header(text, ls)

    # ── 값 섹션 파싱 (▣의뢰내역 이후) ────────────────────────────────────
    vs = _get_values_section(ls)
    vs_parsed = _parse_values(vs) if vs else {}

    # ── Debtor ────────────────────────────────────────────────────────────
    debtor = vs_parsed.get('Debtor')

    # Strategy2: 채무자 라벨 이전 이름 (값이 라벨 앞에 오는 스타일)
    if not debtor:
        for i, line in enumerate(ls):
            if line == '채무자' and i > 2:
                for j in range(i - 1, max(i - 6, -1), -1):
                    v = ls[j]
                    if v and _is_name(v) and v != cust_nm and not _is_stop(v) and not _is_date(v):
                        debtor = v
                        break
                break

    # Strategy3: 신청인명 (주택도시보증공사)
    if not debtor:
        for v in _all_after(ls, '신청인명'):
            if _is_name(v) and not _is_phone(v):
                debtor = v
                break

    # ── CustNm_Sub ────────────────────────────────────────────────────────
    cust_nm_sub = None

    def _is_bad_branch(v):
        """직접 라벨 검색 결과로 CustNm_Sub를 거부"""
        if not v:
            return True
        if _is_stop(v) or _is_date(v) or _is_phone(v) or _is_label(v):
            return True
        if '@' in v or 'E-Mail' in v or 'email' in v.lower():
            return True
        if any(v.endswith(e) for e in _BAD_BRANCH_ENDINGS):
            return True
        if len(v) < 2:
            return True
        return False

    # 1순위: 직접 라벨 검색 (영업점, 지점명 등)
    for label in ['영 업 점', '영업점', '지 점 명', '지점명', '요청부서명', '금   고']:
        # _after 먼저
        v = _after(ls, label)
        if v and not _is_bad_branch(v):
            cust_nm_sub = v
            break
        # _before
        v = _before(ls, label)
        if v and not _is_bad_branch(v):
            cust_nm_sub = v
            break

    # 2순위: 의뢰점 (수협은행: 값이 라벨 앞, 신한은행: 값이 라벨 뒤)
    if not cust_nm_sub:
        v = _before(ls, '의뢰점')
        if v and not _is_bad_branch(v) and len(v) > 2:
            cust_nm_sub = v

    if not cust_nm_sub:
        for v in _all_after(ls, '의뢰점'):
            if (not _is_bad_branch(v) and not _is_person_name(v) and len(v) >= 3):
                cust_nm_sub = v
                break

    # 3순위: 값 섹션 (vs_parsed)
    if not cust_nm_sub:
        cust_nm_sub = vs_parsed.get('CustNm_Sub')

    # ── CustPhone ─────────────────────────────────────────────────────────
    cust_phone = None

    # 1순위: 전용 라벨 검색 (기업은행: 대표번호, 새마을: 금고 전화번호 등)
    for label in ['금고 전화번호', '담당자연락처', '의뢰지점전화번호', '대표번호']:
        v = _after(ls, label)
        if v and _is_phone(v):
            cust_phone = v
            break

    # 2순위: '전화번호' 정확 일치 라인 스캔 (수협, 신한, 농협, 우리 등)
    if not cust_phone:
        phone_candidates = []
        for i, line in enumerate(ls):
            if line.strip() == '전화번호':
                v = _after(ls, '전화번호', start=i)
                if v and _is_phone(v) and not _is_date(v):
                    phone_candidates.append(v)
        if phone_candidates:
            cust_phone = phone_candidates[-1]  # 우리은행: 두 번째 담당자 전화번호

    # 3순위: 값 섹션 (광주, 국민, 새마을, 하나 등)
    if not cust_phone:
        cust_phone = vs_parsed.get('CustPhone')

    # ── CustEmp ───────────────────────────────────────────────────────────
    cust_emp = None
    emp_candidates = []

    for label in ['금고 담당자명', '담 당 자', '담당자명']:
        for i, line in enumerate(ls):
            if label in line:
                v = _person_name_after(ls, label, start=i)
                if v:
                    emp_candidates.append(v)

    if emp_candidates:
        cust_emp = emp_candidates[-1]  # 우리은행: 두번째 담당자명

    if not cust_emp:
        v = _person_name_after(ls, '담당자')
        if v:
            cust_emp = v

    # 라벨 검색이 채무자를 반환한 경우 값 섹션 힌트로 교정 (국민은행)
    if cust_emp and cust_emp == debtor:
        cust_emp = vs_parsed.get('CustEmp_hint')

    # 값 섹션 힌트 사용 (라벨 검색 전체 실패 시)
    if not cust_emp:
        cust_emp = vs_parsed.get('CustEmp_hint')

    # ── Addr ──────────────────────────────────────────────────────────────
    addr = None
    for label in ['세부주소', '소재지', '소 재 지', '우편번호주소', '주    소']:
        v = _after(ls, label)
        if v and len(v) > 5 and _is_address(v):
            addr = _clean_addr(v)
            break

    # ── Bigo ──────────────────────────────────────────────────────────────
    bigo = None
    for label in ['비   고', '비 고1', '비 고', '전달사항', '참고사항']:
        for i, line in enumerate(ls):
            if label in line:
                parts = []
                found_content = False
                for j in range(i + 1, min(i + 20, len(ls))):
                    v = ls[j]
                    if not v:
                        continue
                    # 확실한 섹션 종료 마커
                    if _is_stop(v) or _is_date(v):
                        break
                    if re.match(r'^▣|^기  본|^소   속|^세  금|^수수료|^물건|^소유자|^소재지|^일련번호', v):
                        break
                    if v in ('비 고2', '비고2', '비   고', '탁상자문번호', '수수료지급', '주체',
                             '당행', '당행 외', '차주'):
                        break
                    # 짧은 순한글 단어 (라벨 패턴): 내용 수집 전이면 skip, 후면 stop
                    v_compact = v.replace(' ', '')
                    if len(v_compact) <= 4 and re.match(r'^[가-힣]+$', v_compact):
                        if found_content:
                            break
                        else:
                            continue
                    parts.append(v)
                    found_content = True
                if parts:
                    bigo = ' '.join(parts[:3])  # 최대 3줄 합침
                break
        if bigo and len(bigo) > 3:
            break

    # 신한은행: 비고에서 채무자 추출 (회사명·공백 포함 대응)
    if not debtor and bigo:
        dm = re.search(r'채무자[:：]\s*([^/\n]+)', bigo)
        if dm:
            debtor = dm.group(1).strip()

    # ── 주소 분해 ──────────────────────────────────────────────────────────
    reg, eub, bun1, bun2 = _parse_addr_components(addr or '')

    return {
        'Docid':       docid,
        'CustDocid':   cust_docid,
        'CustNm':      cust_nm,
        'CustNm_Sub':  cust_nm_sub,
        'Purpose_Nm':  '',
        'Category_Nm': '',
        'Reg':         reg,
        'Eub':         eub,
        'Bun1':        bun1,
        'Bun2':        bun2,
        'Addr':        addr,
        'CustEmp':     cust_emp,
        'CustPhone':   cust_phone,
        'Debtor':      debtor,
        'Bigo':        bigo,
    }
