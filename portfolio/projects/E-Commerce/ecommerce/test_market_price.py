"""시장 최저가 크롤링 테스트"""
import re
import httpx

HEADERS_MOBILE = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

HEADERS_PC = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}

keyword = "물티슈"

# --- Coupang mobile ---
print("=== COUPANG MOBILE ===")
resp = httpx.get(
    "https://m.coupang.com/nm/search",
    params={"q": keyword},
    headers=HEADERS_MOBILE,
    follow_redirects=True,
    timeout=10,
)
print(f"Status: {resp.status_code}, URL: {resp.url}")
print(f"Content length: {len(resp.text)}")

# Save for debugging
with open("/tmp/coupang_search.html", "w", encoding="utf-8") as f:
    f.write(resp.text)

p1 = re.findall(r'data-price="(\d+)"', resp.text)
print(f"data-price: {p1[:5]}")

p2 = re.findall(r'"sale_price":(\d+)', resp.text)
print(f"sale_price JSON: {p2[:5]}")

p3 = re.findall(r'"price":\s*(\d+)', resp.text)
print(f"price JSON: {p3[:5]}")

# Try Naver Shopping API
print("\n=== NAVER SHOPPING ===")
resp2 = httpx.get(
    "https://search.shopping.naver.com/search/all",
    params={"query": keyword, "sort": "price_asc"},
    headers=HEADERS_PC,
    follow_redirects=True,
    timeout=10,
)
print(f"Status: {resp2.status_code}, URL: {resp2.url}")
print(f"Content length: {len(resp2.text)}")

with open("/tmp/naver_search.html", "w", encoding="utf-8") as f:
    f.write(resp2.text)

p4 = re.findall(r'"price":\s*"?(\d+)"?', resp2.text)
print(f"price pattern: {p4[:10]}")

p5 = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp2.text)
print(f"lowPrice pattern: {p5[:10]}")

p6 = re.findall(r'"productPrice":\s*(\d+)', resp2.text)
print(f"productPrice: {p6[:10]}")

# Try Naver Shopping API (openapi-like endpoint)
print("\n=== NAVER SHOPPING RENDER API ===")
resp3 = httpx.get(
    "https://search.shopping.naver.com/api/search/all",
    params={"query": keyword, "sort": "price_asc", "pagingIndex": 1, "pagingSize": 5},
    headers={**HEADERS_PC, "Referer": "https://search.shopping.naver.com/"},
    follow_redirects=True,
    timeout=10,
)
print(f"Status: {resp3.status_code}")
if resp3.status_code == 200:
    try:
        data = resp3.json()
        items = data.get("shoppingResult", {}).get("products", [])
        for it in items[:5]:
            print(f"  {it.get('productTitle','')[:40]} -> {it.get('lowPrice', 'N/A')}원")
    except Exception as e:
        print(f"JSON parse error: {e}")
        p7 = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp3.text[:3000])
        print(f"lowPrice in text: {p7[:5]}")
