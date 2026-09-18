import sys
sys.path.insert(0, "D:/AI/Claude/Y_BankAuto")
from pdf_parser import parse_bank24_pdf
from db_writer import parse_building_detail, _supplement_building_detail

r1 = parse_bank24_pdf(r"C:\Bank24Extractor\pdf\202606100000136_20260612_093543.pdf")
print("=== 202606100000136 ===")
print("  채무자  :", r1["채무자"])
print("  소유자  :", r1["소유자"])
print("  물건종류:", r1["물건종류"])
print("  처리상태:", r1["처리상태"])
print()

r2 = parse_bank24_pdf(r"C:\Bank24Extractor\pdf\202606100000106_20260612_093721.pdf")
print("=== 202606100000106 ===")
print("  채무자        :", r2["채무자"])
print("  pdf_우편번호주소:", r2["pdf_우편번호주소"])
print("  처리상태      :", r2["처리상태"])

# FIX-3 직접 검증: "건물" blocking
empty_bld = {"building": "", "dong": "", "floor": "", "ho": ""}
item_106 = {"pdf_우편번호주소": "서울 관악구 봉천동 649-36번지 건물"}
result = _supplement_building_detail(empty_bld, item_106)
print()
print("=== FIX-3 _supplement_building_detail ===")
print("  building:", repr(result["building"]))
print("  dong    :", repr(result["dong"]))
print("  ho      :", repr(result["ho"]))
ok = result["building"] == "" and result["dong"] == "" and result["ho"] == ""
print("  결과:", "OK" if ok else "FAIL")
