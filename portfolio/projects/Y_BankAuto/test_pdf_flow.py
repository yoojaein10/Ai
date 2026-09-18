"""
PDF 기반 추출 통합 테스트
1. Bank24 재시작 + 로그인
2. 신한은행 담보 1건 스캔
3. APPS → C → PDF 저장
4. PDF 파싱
5. 결과 출력
"""
import sys, time
from pathlib import Path
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')

from extract_shinhan import (
    kill_existing, launch_and_login, wait_main,
    apply_filter, scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    navigate_and_verify, save_pdf_for_row, PDF_DIR,
    safe_cls, safe_txt, log as es_log,
)
from pdf_parser import parse_bank24_pdf

# 로그를 터미널로
import extract_shinhan as _es
_es._log_callback = print

def run():
    print("=" * 60)
    print("  PDF 기반 추출 테스트")
    print("=" * 60)

    # 1) Bank24 재시작
    kill_existing()
    time.sleep(1)
    launch_and_login('dbwodls00', 'REDACTED_CONFIGURE_LOCALLY')

    main_win = wait_main()
    if not main_win:
        print("[ABORT] 메인창 없음"); return
    time.sleep(2)

    # 2) 조회
    apply_filter(main_win)
    time.sleep(2)

    items = scan_main_grid(main_win)
    rows  = parse_scan_results(items)
    shin  = filter_shinhan_dambo(rows)
    print(f"\n신한은행 담보: {len(shin)}건")
    if not shin:
        print("[ABORT] 데이터 없음"); return

    # 3) 첫 번째 건 PDF 저장
    target = shin[0]
    doc_no = target.get("의뢰번호", "")
    est_no = target.get("감정서번호", "")
    print(f"\n대상: 의뢰번호={doc_no}  감정서번호={est_no}")

    navigate_and_verify(main_win, target)
    time.sleep(0.3)

    # PDF 경로 생성
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{est_no}_{doc_no}".replace('/', '_').replace('\\', '_')
    pdf_path = PDF_DIR / f"{safe_name}.pdf"

    print(f"\n[PDF] 저장 경로: {pdf_path}")
    ok = save_pdf_for_row(main_win, target, str(pdf_path))
    print(f"[PDF] 저장 결과: {'성공' if ok else '실패'}")

    if not ok:
        print("[ABORT] PDF 저장 실패"); return

    # 4) PDF 파싱
    print(f"\n[파싱] {pdf_path.name}  ({pdf_path.stat().st_size:,} bytes)")
    result = parse_bank24_pdf(str(pdf_path))

    print("\n" + "=" * 60)
    print("  파싱 결과")
    print("=" * 60)
    for k, v in result.items():
        if k not in ('_missing',):
            print(f"  {k:<20} = {v!r}")

    print("\n" + "=" * 60)
    print("  검증")
    print("=" * 60)
    pdf_doc = result.get("상세창 의뢰번호", "")
    pdf_est = result.get("상세창 감정서번호", "")
    match = (doc_no and doc_no == pdf_doc) or (est_no and est_no == pdf_est)
    print(f"  그리드 의뢰번호: {doc_no!r}  →  PDF: {pdf_doc!r}  일치: {doc_no == pdf_doc}")
    print(f"  그리드 감정서번호: {est_no!r}  →  PDF: {pdf_est!r}  일치: {est_no == pdf_est}")
    print(f"  최종 검증: {'OK' if match else 'FAIL'}")

    print(f"\n  우편번호주소: {result.get('pdf_우편번호주소')!r}")
    print(f"  소재지:       {result.get('pdf_소재지')!r}")
    print(f"  담보종류:     {result.get('물건종류')!r}")
    print(f"  처리상태:     {result.get('처리상태')!r}")

if __name__ == '__main__':
    run()
