"""시장 최저가 크롤링 테스트 - 대안 접근"""
import re
import json
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        'Chrome/192.0.2.10 Safari/537.36'
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

keyword = "물티슈"

# --- 1. 쿠팡 API endpoint ---
print("=== 1. COUPANG API ===")
try:
    resp = httpx.get(
        "https://www.coupang.com/np/search",
        params={"q": keyword, "channel": "user"},
        headers={**HEADERS, "Accept": "application/json, text/plain, */*"},
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    # Check if it contains price data
    prices = re.findall(r'"salePrice":(\d+)', resp.text)
    if prices:
        print(f"salePrices: {sorted(set(prices))[:10]}")
    else:
        prices = re.findall(r'(\d{3,7})<', resp.text[:20000])
        print(f"Number patterns: {prices[:10]}")
except Exception as e:
    print(f"Error: {e}")

# --- 2. 다나와 ---
print("\n=== 2. DANAWA ===")
try:
    resp = httpx.get(
        "https://search.danawa.com/dsearch.php",
        params={"query": keyword, "sort": "priceASC"},
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    # 다나와 가격 패턴
    prices = re.findall(r'class="price_sect"[^>]*>.*?<em[^>]*>([\d,]+)</em>', resp.text, re.S)
    if not prices:
        prices = re.findall(r'<em class="num">([\d,]+)</em>', resp.text)
    if not prices:
        prices = re.findall(r'class="[^"]*price[^"]*"[^>]*>\s*(?:<[^>]+>)?\s*([\d,]+)\s*원', resp.text)
    print(f"Prices found: {prices[:10]}")
except Exception as e:
    print(f"Error: {e}")

# --- 3. 네이버 쇼핑 (다른 경로) ---
print("\n=== 3. NAVER CATALOG API ===")
try:
    resp = httpx.get(
        "https://shopping.naver.com/api/search/all",
        params={"query": keyword, "sort": "price_asc", "pagingSize": 5},
        headers={
            **HEADERS,
            "Referer": "https://shopping.naver.com/",
        },
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code == 200:
        data = resp.json()
        print(json.dumps(list(data.keys()), ensure_ascii=False))
except Exception as e:
    print(f"Error: {e}")

# --- 4. Google Shopping ---
print("\n=== 4. GOOGLE SHOPPING ===")
try:
    resp = httpx.get(
        "https://www.google.com/search",
        params={"q": f"{keyword} 가격", "tbm": "shop", "hl": "ko"},
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    prices = re.findall(r'([\d,]+)\s*원', resp.text)
    if prices:
        int_prices = [int(p.replace(",", "")) for p in prices]
        int_prices = [p for p in int_prices if p >= 100]
        if int_prices:
            print(f"Min: {min(int_prices):,}원, Prices: {sorted(set(int_prices))[:10]}")
    else:
        print("No prices found")
except Exception as e:
    print(f"Error: {e}")

# --- 5. 에누리 ---
print("\n=== 5. ENURI ===")
try:
    resp = httpx.get(
        "https://www.enuri.com/search/list.php",
        params={"keyword": keyword},
        headers=HEADERS,
        follow_redirects=True,
        timeout=10,
    )
    print(f"Status: {resp.status_code}, Length: {len(resp.text)}")
    prices = re.findall(r'<em[^>]*>([\d,]+)</em>\s*원', resp.text)
    if not prices:
        prices = re.findall(r'([\d,]+)\s*원', resp.text[:20000])
    print(f"Prices: {prices[:10]}")
except Exception as e:
    print(f"Error: {e}")
