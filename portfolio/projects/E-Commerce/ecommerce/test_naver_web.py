"""네이버 웹검색 결과에서 쇼핑 가격 추출"""
import httpx
import re

resp = httpx.get(
    "https://search.naver.com/search.naver",
    params={"where": "nexearch", "query": "물티슈 최저가"},
    headers={
        "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
        "Accept-Language": "ko-KR,ko;q=0.9",
    },
    follow_redirects=True,
    timeout=10,
)

html = resp.text
with open("/tmp/naver_web.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"Status: {resp.status_code}, Length: {len(html)}")

# Search for shopping-related sections
shopping_idx = html.find("쇼핑")
if shopping_idx > 0:
    print(f"'쇼핑' found at index {shopping_idx}")

# Look for number patterns that look like prices
# Korean won prices: 3-7 digits with commas
prices = []
for m in re.finditer(r'(\d{1,3}(?:,\d{3})+)', html):
    val = int(m.group(1).replace(",", ""))
    if 500 <= val <= 500000:  # reasonable price range
        prices.append(val)

unique_prices = sorted(set(prices))
print(f"Potential prices ({len(unique_prices)}): {unique_prices[:20]}")

# Find "data-*" attributes with price info
data_attrs = re.findall(r'data-[a-z-]*price[^=]*="([^"]+)"', html, re.I)
print(f"data-*price attrs: {data_attrs[:10]}")

# Search for JSON-LD structured data (schema.org Product)
ld_json = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
print(f"LD+JSON blocks: {len(ld_json)}")
for block in ld_json[:3]:
    if "price" in block.lower():
        print(f"  Price in LD: {block[:200]}")

# Try "where=shopping" query
print("\n=== NAVER where=shopping ===")
resp2 = httpx.get(
    "https://search.naver.com/search.naver",
    params={"where": "shopping", "query": "물티슈"},
    headers={
        "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
        "Accept-Language": "ko-KR,ko;q=0.9",
    },
    follow_redirects=True,
    timeout=10,
)
print(f"Status: {resp2.status_code}, Length: {len(resp2.text)}, URL: {resp2.url}")

if resp2.status_code == 200 and len(resp2.text) > 10000:
    with open("/tmp/naver_shopping2.html", "w", encoding="utf-8") as f:
        f.write(resp2.text)

    prices2 = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp2.text)
    print(f"lowPrice: {prices2[:10]}")

    # __NEXT_DATA__
    m = re.search(r'__NEXT_DATA__[^>]*>(.*?)</script>', resp2.text, re.S)
    if m:
        import json
        try:
            data = json.loads(m.group(1))
            print(f"Keys: {list(data.get('props', {}).get('pageProps', {}).keys())[:10]}")
        except:
            print("JSON parse failed")
