# -*- coding: utf-8 -*-
"""일사편리(KRAS) 부동산정보 조회 클라이언트.

로그인 없는 공개 조회 화면(land_info/info/baseInfo/baseInfo.do)을 이용한다.
- 시군구/읍면동 코드: landCode.do?service=selectLandCodeComboBox
- 본조회: baseInfo.do?service=baseInfo&landcode=<19자리>&gblDivName=...
- 건축물대장 표제부 상세: baseInfo.do?service=bldTitle&mgmBldrgstPk=...

검증된 지역: 경기(kras.gg.go.kr). 타 시도는 동일 구조로 추정(도메인만 상이).
"""
import re
import time

import requests
from lxml import html as lxml_html

from addr import jibun_to_bobn_bubn

# 시도명 -> (시도코드 후보, 도메인)
SIDO_INFO = {
    "서울": (["11"], "kras.seoul.go.kr"),
    "부산": (["26"], "kras.busan.go.kr"),
    "대구": (["27"], "kras.daegu.go.kr"),
    "인천": (["28"], "kras.incheon.go.kr"),
    "광주": (["29"], "kras.gwangju.go.kr"),
    "대전": (["30"], "kras.daejeon.go.kr"),
    "울산": (["31"], "kras.ulsan.go.kr"),
    "세종": (["36"], "kras.sejong.go.kr"),
    "경기": (["41"], "kras.gg.go.kr"),
    "강원": (["51", "42"], "kras.gwd.go.kr"),
    "충북": (["43"], "kras.chungbuk.go.kr"),
    "충남": (["44"], "kras.chungnam.go.kr"),
    "전북": (["52", "45"], "kras.jeonbuk.go.kr"),
    "전남": (["46"], "kras.jeonnam.go.kr"),
    "경북": (["47"], "kras.gb.go.kr"),
    "경남": (["48"], "kras.gyeongnam.go.kr"),
    "제주": (["50"], "kras.jeju.go.kr"),
}

# 법정동코드 앞 2자리 -> 시도명 (도메인 결정용)
CODE2_TO_SIDO = {
    "11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주",
    "30": "대전", "31": "울산", "36": "세종", "41": "경기", "42": "강원",
    "51": "강원", "43": "충북", "44": "충남", "45": "전북", "52": "전북",
    "46": "전남", "47": "경북", "48": "경남", "50": "제주",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
REQUEST_DELAY = 0.7  # 초. 서버 부담을 주지 않도록 요청 간 간격


def _clean(text):
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


class KrasClient:
    def __init__(self, sido):
        # sido: 시도명('경기') 또는 법정동코드 앞 2자리('41')
        if sido not in SIDO_INFO and sido in CODE2_TO_SIDO:
            sido = CODE2_TO_SIDO[sido]
        if sido not in SIDO_INFO:
            raise ValueError(f"지원하지 않는 시도: {sido}")
        self.sido = sido
        self.sido_codes, host = SIDO_INFO[sido]
        self.base = f"https://{host}"
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self._last_req = 0.0
        self._code_cache = {}
        # 세션 초기화 + 비정상접근 차단 쿠키.
        # 일부 시도(인천)는 서버가 구식 암호군만 지원해 https 핸드셰이크가 불가능
        # -> http로 폴백 (공개 조회 화면이라 전송 데이터에 민감정보 없음)
        try:
            self._get(f"{self.base}/land_info/info/baseInfo/baseInfo.do")
        except requests.exceptions.SSLError:
            self.base = f"http://{host}"
            self._get(f"{self.base}/land_info/info/baseInfo/baseInfo.do")
        self.s.cookies.set("landuse", "landuse", domain=host,
                           path="/land_info/info/baseInfo/")

    # ---------- HTTP ----------
    def _throttle(self):
        wait = REQUEST_DELAY - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    @staticmethod
    def _decode(r):
        """시도별 인코딩 차이 대응(경기/서울=EUC-KR, 인천=UTF-8).

        UTF-8 한글은 EUC-KR로도 '해석'은 되지만 깨진 한자가 되므로 utf-8 strict를
        먼저 시도하고, 실패하면 euc-kr로 읽는다.
        """
        for enc in ("utf-8", "euc-kr"):
            try:
                return r.content.decode(enc)
            except UnicodeDecodeError:
                continue
        return r.content.decode("euc-kr", errors="replace")

    def _get(self, url, **kw):
        self._throttle()
        r = self.s.get(url, timeout=60, **kw)
        r.raise_for_status()
        return self._decode(r)

    def _post(self, url, **kw):
        self._throttle()
        r = self.s.post(url, timeout=60, **kw)
        r.raise_for_status()
        return self._decode(r)

    # ---------- 코드 조회 ----------
    def _combo(self, search_key, code):
        text = self._post(f"{self.base}/land_info/common/landCode.do",
                          params={"service": "selectLandCodeComboBox",
                                  "searchKey": search_key, "code": code})
        return re.findall(r'<option\s+value="([^"]*)"[^>]*>([^<]*)</option>', text)

    def resolve_umd_code(self, sgg_name, umd_name):
        """시군구명(공백제거)·읍면동명 -> 법정동코드 10자리"""
        key = (sgg_name, umd_name)
        if key in self._code_cache:
            return self._code_cache[key]

        sgg_code = None
        for sido_code in self.sido_codes:
            for code, name in self._combo(sido_code, 0):
                if re.sub(r"\s+", "", name) == sgg_name:
                    sgg_code = code
                    break
            if sgg_code:
                break
        if not sgg_code:
            raise LookupError(f"시군구를 찾을 수 없음: {self.sido} {sgg_name}")

        umd_code = None
        for code, name in self._combo(sgg_code, 1):
            if name.strip() == umd_name:
                umd_code = code
                break
        if not umd_code:
            raise LookupError(f"읍면동을 찾을 수 없음: {sgg_name} {umd_name}")

        self._code_cache[key] = umd_code
        return umd_code

    def make_landcode(self, umd_code, jibun):
        mountain, bobn, bubn = jibun_to_bobn_bubn(jibun)
        return umd_code[:10] + ("2" if mountain else "1") + bobn + bubn

    # ---------- 본조회 ----------
    def fetch_parcel(self, landcode):
        """필지 1건 조회 -> 전체 페이지 HTML (토지/건축물목록/토지이용/공시지가 포함).

        서울 등 일부 시도는 POST를 500으로 거부하므로 GET 사용(경기도 GET 허용 확인).
        bobn/bubn 파라미터가 없으면 서버가 개별공시지가(지자체 백엔드) 조회를 생략하고
        '연결에 실패' 페이지를 반환하므로 landcode에서 잘라 함께 보낸다(경기·서울 검증).
        """
        return self._get(
            f"{self.base}/land_info/info/baseInfo/baseInfo.do",
            params={"service": "baseInfo", "landcode": landcode,
                    "gblDivName": "landUse", "scale": "1000",
                    "gyujae": "1", "label_type": "false",
                    "bobn": landcode[11:15], "bubn": landcode[15:19]})

    def fetch_bld_title(self, pk, landcode, kind_cd="", recap=None):
        """건축물대장 표제부/총괄표제부 상세 HTML.

        총괄표제부의 kind_cd는 시도마다 다름(경기=2, 서울=1) — 호출자가 대장종류를 보고
        recap을 지정할 수 있고, 미지정 시 kind_cd==2로 판단(기존 동작).
        """
        if recap is None:
            recap = kind_cd == "2"
        service = "bldRecapTitle" if recap else "bldTitle"
        params = {"service": service, "mgmBldrgstPk": pk, "landcode": landcode}
        if service == "bldRecapTitle":
            params["regstrKindCd"] = kind_cd or "2"
        return self._get(f"{self.base}/land_info/info/baseInfo/baseInfo.do",
                         params=params)

    # ---------- 파서 ----------
    @staticmethod
    def parse_landuse(page_html):
        """t04 토지이용계획 탭 파싱 -> dict"""
        doc = lxml_html.fromstring(page_html)
        area = doc.xpath('//div[@id="t04"]')
        if not area:
            return None
        area = area[0]
        out = {"소재지": "", "지번": "", "지목": "", "면적": "",
               "국토계획": "", "다른법령": "", "시행령사항": ""}

        tables = area.xpath('.//table')
        if tables:
            row = tables[0].xpath('.//tbody/tr[1]/td')
            if len(row) >= 4:
                out["소재지"] = _clean(row[0].text_content())
                out["지번"] = _clean(row[1].text_content())
                out["지목"] = _clean(row[2].text_content())
                out["면적"] = _clean(row[3].text_content())

        if len(tables) >= 2:
            for tr in tables[1].xpath('.//tr'):
                tds = tr.xpath('./td')
                if len(tds) < 2:
                    continue
                label = _clean("".join(t.text_content() for t in tds[:-1]))
                value = _clean(tds[-1].text_content())
                if "국토의 계획" in label:
                    out["국토계획"] = value
                elif "다른 법령" in label:
                    out["다른법령"] = value
                elif "토지이용규제" in label or "시행령" in label:
                    out["시행령사항"] = value
        return out

    @staticmethod
    def parse_landprice(page_html):
        """t05 개별공시지가 표 파싱 -> 최신년도 공시지가(int) 또는 None.

        지자체 공시지가 서버 장애 시 표가 비어 온다(페이지에 '연결에 실패' 문구).
        """
        doc = lxml_html.fromstring(page_html)
        div = doc.xpath('//div[@id="landPrice_print"]')
        if not div:
            return None
        best = None  # (년도, 가격)
        for tr in div[0].xpath('.//tbody/tr'):
            tds = [_clean(td.text_content()) for td in tr.xpath('./td')]
            if len(tds) < 4:
                continue
            ym = re.search(r"(\d{4})", tds[0])
            pm = re.search(r"([\d,]+)", tds[3])
            if not pm:
                continue
            price = int(pm.group(1).replace(",", ""))
            year = int(ym.group(1)) if ym else 0
            if price > 0 and (best is None or year > best[0]):
                best = (year, price)
        return best[1] if best else None

    @staticmethod
    def landprice_server_down(page_html):
        return "연결에 실패" in page_html

    @staticmethod
    def parse_bld_list(page_html):
        """건축물대장 목록 -> [{'pk','kind_cd','대장종류','대지위치','명칭','주용도','연면적'}]"""
        doc = lxml_html.fromstring(page_html)
        rows = doc.xpath('//tr[starts-with(@onclick, "javascript:getTitleInfo")]')
        out = []
        for tr in rows:
            onclick = tr.get("onclick", "")
            m = re.search(r"getTitleInfo\('([^']*)','([^']*)','([^']*)'\)", onclick)
            if not m:
                continue
            tds = [_clean(td.text_content()) for td in tr.xpath('./td')]
            out.append({
                "pk": m.group(1), "upper_pk": m.group(2), "kind_cd": m.group(3),
                "대장종류": tds[0] if len(tds) > 0 else "",
                "대지위치": tds[1] if len(tds) > 1 else "",
                "명칭": tds[2] if len(tds) > 2 else "",
                "동명칭": tds[3] if len(tds) > 3 else "",
                "주용도": tds[4] if len(tds) > 4 else "",
                "연면적": tds[5] if len(tds) > 5 else "",
            })
        return out

    @staticmethod
    def parse_bld_title(title_html):
        """표제부 상세 파싱 -> dict (th 다음 td를 값으로 매핑) + 층별현황/최고층"""
        doc = lxml_html.fromstring(title_html)
        fields = {}
        for tr in doc.xpath('//table//tr'):
            cells = tr.xpath('./th|./td')
            i = 0
            while i < len(cells):
                if cells[i].tag == "th":
                    label = _clean(cells[i].text_content())
                    vals = []
                    j = i + 1
                    while j < len(cells) and cells[j].tag == "td":
                        vals.append(_clean(cells[j].text_content()))
                        j += 1
                    if label and label not in fields:
                        fields[label] = " ".join(v for v in vals if v).strip()
                    i = j
                else:
                    i += 1

        # 층별현황: '층별현황' 이후 테이블에서 (구분, 층, 구조, 용도, 면적)
        floors = []
        for tr in doc.xpath('//table//tr'):
            tds = [_clean(td.text_content()) for td in tr.xpath('./td')]
            if len(tds) >= 5 and re.match(r"^(지상|지하|옥탑)", tds[0] or ""):
                floors.append({"구분": tds[0], "층": tds[1], "구조": tds[2],
                               "용도": tds[3], "면적": tds[4]})

        top_floor = 0
        for f in floors:
            if f["구분"].startswith("지상"):
                m = re.search(r"(\d+)", f["층"])
                if m:
                    top_floor = max(top_floor, int(m.group(1)))

        fields["_층별현황"] = floors
        fields["_최고층"] = top_floor
        return fields


def pct_to_ratio(text):
    """'56.89%' -> 0.5689 (float). 실패 시 None"""
    m = re.search(r"([\d,.]+)\s*%", text or "")
    if not m:
        return None
    try:
        return round(float(m.group(1).replace(",", "")) / 100, 6)
    except ValueError:
        return None
