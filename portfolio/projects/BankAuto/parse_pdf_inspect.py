import fitz
import os

pdf_dir = r"D:\AI\Claude\BankAuto\output\bank"
pdfs = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]

for pdf_name in sorted(pdfs):
    path = os.path.join(pdf_dir, pdf_name)
    doc = fitz.open(path)
    print(f"\n{'='*60}")
    print(f"[{pdf_name}]")
    for i, page in enumerate(doc):
        text = page.get_text()
        print(f"--- 페이지 {i+1} ---")
        print(text)
    doc.close()
