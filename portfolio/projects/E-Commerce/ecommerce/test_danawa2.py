import httpx
import re

HEADERS = {
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/192.0.2.10 Safari/537.36',
    "Accept-Language": "ko-KR,ko;q=0.9",
}

resp = httpx.get(
    "https://search.danawa.com/dsearch.php",
    params={"query": "물티슈", "sort": "priceASC"},
    headers=HEADERS,
    follow_redirects=True,
    timeout=10,
)
html = resp.text

# Find all price_sect blocks
for i, m in enumerate(re.finditer(r'price_sect">(.*?)</div>', html, re.S)):
    block = m.group(1)
    # Find prices in this block
    prices = re.findall(r'>([\d,]+)<', block)
    if prices and i < 5:
        print(f"Product {i}: prices={prices}")

# Try the Ajax API that Danawa uses
print("\n=== DANAWA AJAX API ===")
resp2 = httpx.post(
    "https://search.danawa.com/dsearch.php",
    data={
        "query": "물티슈",
        "originalQuery": "물티슈",
        "previousKeyword": "",
        "volumeType": "allvs",
        "page": "1",
        "limit": "5",
        "sort": "priceASC",
        "list": "list",
        "boost": "true",
        "addDelivery": "N",
        "tab": "goods",
    },
    headers={
        **HEADERS,
        "Referer": "https://search.danawa.com/dsearch.php?query=%EB%AC%BC%ED%8B%B0%EC%8A%88",
        "X-Requested-With": "XMLHttpRequest",
    },
    follow_redirects=True,
    timeout=10,
)
print(f"Status: {resp2.status_code}, Length: {len(resp2.text)}")

# Look for price in ajax response
ajax_prices = re.findall(r'>([\d,]{4,})<', resp2.text[:50000])
print(f"Ajax prices: {ajax_prices[:20]}")

# Another pattern - danawa uses specific class
ajax_prices2 = re.findall(r'price_TT">\s*([\d,]+)', resp2.text[:50000])
print(f"price_TT: {ajax_prices2[:10]}")

# Look around price text
for label in ["최저", "price"]:
    idx = resp2.text.find(label)
    if idx > 0:
        print(f"\n'{label}' context: {resp2.text[idx:idx+200]}")
        break
