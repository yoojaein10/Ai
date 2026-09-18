import sys, time
sys.path.insert(0, r'D:\AI\Claude\Y_BankAuto')
from extract_shinhan import (safe_cls, safe_txt, safe_rect, safe_val,
    force_foreground, navigate_and_verify, _get_main_grid,
    scan_main_grid, parse_scan_results, filter_shinhan_dambo,
    snapshot_detail_handles, open_detail_at_current, apply_filter,
    LABEL_CLS, EDIT_CLS)
from pywinauto import Desktop, Application

MAIN_CLS = 'TfrmMain'
main_win = next((w for w in Desktop(backend='win32').windows()
                 if safe_cls(w)==MAIN_CLS and 'BANK24' in safe_txt(w)), None)
force_foreground(main_win.handle, '메인창')
time.sleep(0.5)

print('조회 중...')
apply_filter(main_win)
time.sleep(2)

# 그리드 스캔
items = scan_main_grid(main_win)
rows  = parse_scan_results(items)
shin  = filter_shinhan_dambo(rows)
print(f'신한은행 담보: {len(shin)}건')

target = shin[0]
print(f'대상: {target.get("의뢰번호")} / {target.get("감정서번호")}')
navigate_and_verify(main_win, target)
time.sleep(0.3)

from extract_shinhan import _find_detail
existing = _find_detail()
if existing:
    existing.close(); time.sleep(0.8)

before = snapshot_detail_handles()
detail_win = open_detail_at_current(main_win, before)
if not detail_win:
    print('종합접수 창 미발견'); sys.exit(1)

print(f'종합접수: {safe_txt(detail_win)!r}')
time.sleep(1)

# win32 descendants 전체 스캔
app32 = Application(backend='win32').connect(handle=detail_win.handle)
win32 = app32.top_window()
descs = win32.descendants()

print(f'\n전체 컨트롤: {len(descs)}개')
print('\n=== 라벨 근접 편집 컨트롤 (우편번호/주소 관련) ===')

labels = [(c, safe_txt(c).strip(), safe_rect(c)) for c in descs
          if safe_cls(c) in LABEL_CLS and safe_txt(c).strip()]
edits  = [(c, safe_cls(c), safe_rect(c)) for c in descs
          if safe_cls(c) in EDIT_CLS]

# 우편번호 관련 키워드
keywords = ['우편', '주소', 'zip', 'postal', '번호주소', '소재', '번호', '도로']
for ctrl, ltxt, (lL, lT, lR, lB) in labels:
    if any(k in ltxt for k in keywords):
        # 근접 편집 컨트롤 찾기
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            if abs(eT - lT) <= 15 and eL >= lL:
                d = eL - lR
                if 0 <= d < best_d:
                    best_d, best = d, ec
        val = safe_txt(best).strip() if best else ''
        if not val and best:
            val = safe_val(best)
        print(f'  라벨={ltxt!r:20} → 값={val!r}  (rect={lL},{lT})')

# 모든 라벨 전체 출력
print('\n=== 모든 라벨 텍스트 (물건정보 영역 추정) ===')
sorted_labels = sorted(labels, key=lambda x: x[2][1])  # y 오름차순
for ctrl, ltxt, (lL, lT, lR, lB) in sorted_labels:
    if lT > 400:  # 아래쪽 영역
        best, best_d = None, 9999
        for ec, ec_cls, (eL, eT, eR, eB) in edits:
            if abs(eT - lT) <= 15 and eL >= lL:
                d = eL - lR
                if 0 <= d < best_d:
                    best_d, best = d, ec
        val = safe_txt(best).strip() if best else ''
        print(f'  y={lT:4d} 라벨={ltxt!r:20} → 값={val!r}')

detail_win.close()
print('\n완료')
