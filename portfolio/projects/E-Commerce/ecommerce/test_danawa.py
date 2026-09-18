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
with open("/tmp/danawa.html", "w", encoding="utf-8") as f:
    f.write(html)

# Various price patterns
print(f"Total length: {len(html)}")

p1 = re.findall(r'class="price_sect"', html)
print(f"price_sect count: {len(p1)}")

p2 = re.findall(r'prc_c">([\d,]+)<', html)
print(f"prc_c: {p2[:10]}")

p3 = re.findall(r'"minPrice":\s*([\d]+)', html)
print(f"minPrice JSON: {p3[:10]}")

p4 = re.findall(r'class="[^"]*num[^"]*">([\d,]+)<', html)
print(f"num class: {p4[:10]}")

# Find all won prices
p5 = re.findall(r'([\d,]+)\s*원', html[:100000])
print(f"원 prices: {p5[:20]}")

# Look at a snippet with price_sect
idx = html.find("price_sect")
if idx > 0:
    snippet = html[idx:idx+500]
    print(f"\nprice_sect snippet:\n{snippet}")

# Find product list items
p6 = re.findall(r'prod_pricelist.*?</li>', html[:100000], re.S)
print(f"\nprod_pricelist items: {len(p6)}")
if p6:
    print(p6[0][:300])
