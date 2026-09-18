"""네이버/쿠팡 가격 추출 테스트 - SSR 가능한 방법들"""
import httpx
import re
import json

HEADERS = {
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
    "Accept-Language": "ko-KR,ko;q=0.9",
}

keyword = "물티슈"

# 1. 네이버 쇼핑 internal API (__NEXT_DATA__)
print("=== NAVER __NEXT_DATA__ ===")
try:
    resp = httpx.get(
        "https://msearch.shopping.naver.com/search/all",
        params={"query": keyword, "sort": "price_asc"},
        headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

    # __NEXT_DATA__ 패턴
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if m:
        data = json.loads(m.group(1))
        # Navigate to products
        props = data.get("props", {}).get("pageProps", {})
        products = props.get("initialState", {}).get("products", {}).get("list", [])
        if not products:
            # Try other paths
            for key in props:
                if isinstance(props[key], dict):
                    for k2 in props[key]:
                        if "product" in k2.lower() or "item" in k2.lower():
                            print(f"Found key: props.pageProps.{key}.{k2}")
        for p in products[:5]:
            item = p.get("item", p)
            title = item.get("productTitle", item.get("title", ""))
            price = item.get("lowPrice", item.get("price", "N/A"))
            print(f"  {title[:40]} -> {price}원")
    else:
        print("No __NEXT_DATA__ found")
        # Try lowPrice in raw text
        prices = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp.text)
        print(f"lowPrice in text: {prices[:10]}")
        prices2 = re.findall(r'"price":\s*"?(\d+)"?', resp.text)
        print(f"price in text: {prices2[:10]}")
except Exception as e:
    print(f"Error: {e}")

# 2. 쿠팡 wing API (검색)
print("\n=== COUPANG WING SEARCH ===")
try:
    resp = httpx.get(
        "https://www.coupang.com/np/goldbox",
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Goldbox status: {resp.status_code}, Length: {len(resp.text)}")
except Exception as e:
    print(f"Error: {e}")

# 3. 쿠팡 rocketgrowth/search (public search endpoint)
print("\n=== COUPANG SEARCH RECO ===")
try:
    resp = httpx.get(
        "https://www.coupang.com/np/campaigns/82",
        params={"q": keyword},
        headers={**HEADERS, "Accept": "text/html"},
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    prices = re.findall(r'"salePrice"\s*:\s*(\d+)', resp.text)
    print(f"salePrice: {prices[:5]}")
except Exception as e:
    print(f"Error: {e}")

# 4. G마켓 (SSR friendly)
print("\n=== GMARKET ===")
try:
    resp = httpx.get(
        "https://browse.gmarket.co.kr/search",
        params={"keyword": keyword, "s": "price"},
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    prices = re.findall(r'class="[^"]*item_price[^"]*"[^>]*>\s*([\d,]+)', resp.text)
    if not prices:
        prices = re.findall(r'"price"[^>]*>([\d,]+)', resp.text)
    if not prices:
        prices = re.findall(r'([\d,]+)\s*원', resp.text[:50000])
    print(f"Prices: {prices[:10]}")
except Exception as e:
    print(f"Error: {e}")

# 5. 11번가 (SSR API)
print("\n=== 11ST ===")
try:
    resp = httpx.get(
        "https://search.11st.co.kr/Search.tmall",
        params={"kwd": keyword, "sortCd": "LP"},
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    # 11번가 가격 패턴
    prices = re.findall(r's_price">\s*([\d,]+)', resp.text)
    if not prices:
        prices = re.findall(r'sale_price">\s*([\d,]+)', resp.text)
    if not prices:
        prices = re.findall(r'<strong[^>]*>([\d,]+)</strong>\s*<span[^>]*>원', resp.text[:50000])
    print(f"Prices: {prices[:10]}")
except Exception as e:
    print(f"Error: {e}")
