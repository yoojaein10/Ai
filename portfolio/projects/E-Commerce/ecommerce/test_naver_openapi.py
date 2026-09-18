"""네이버 Open API 없이 가능한 방법 + 쿠팡 시도"""
import httpx
import re
import json

# 1. 네이버 검색 (일반 웹검색 -> 쇼핑 탭 결과에 가격 포함)
print("=== NAVER WEB SEARCH (shopping info) ===")
try:
    resp = httpx.get(
        "https://search.naver.com/search.naver",
        params={"where": "nexearch", "query": "물티슈 가격비교"},
        headers={
            "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
            "Accept-Language": "ko-KR,ko;q=0.9",
        },
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

    # 네이버 통합검색에서 쇼핑 섹션의 가격
    prices = re.findall(r'"price":\s*"?(\d+)"?', resp.text)
    print(f"price JSON: {prices[:10]}")

    prices2 = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp.text)
    print(f"lowPrice: {prices2[:10]}")

    # 일반 가격 패턴
    prices3 = re.findall(r'(\d{1,3}(?:,\d{3})+)원', resp.text[:100000])
    int_prices = sorted(set(int(p.replace(",", "")) for p in prices3 if int(p.replace(",", "")) >= 500))
    print(f"원 prices (sorted): {int_prices[:15]}")

except Exception as e:
    print(f"Error: {e}")

# 2. 네이버 쇼핑 with cookie & realistic headers
print("\n=== NAVER SHOPPING (realistic) ===")
try:
    client = httpx.Client(
        headers={
            "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        },
        follow_redirects=True,
        timeout=10,
    )
    # First visit main to get cookies
    client.get("https://search.shopping.naver.com/")
    # Then search
    resp = client.get(
        "https://search.shopping.naver.com/search/all",
        params={"query": "물티슈", "sort": "price_asc"},
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")

    if resp.status_code == 200:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
        if m:
            data = json.loads(m.group(1))
            products = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("products", {}).get("list", [])
            print(f"Products found: {len(products)}")
            for p in products[:5]:
                item = p.get("item", p)
                print(f"  {item.get('productTitle', '')[:40]} -> {item.get('lowPrice', 'N/A')}원")
        else:
            prices = re.findall(r'"lowPrice":\s*"?(\d+)"?', resp.text)
            print(f"lowPrice in raw: {prices[:10]}")
    client.close()
except Exception as e:
    print(f"Error: {e}")
