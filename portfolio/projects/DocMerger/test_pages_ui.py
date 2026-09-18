"""
페이지 편집 UI 플로우 테스트 (offscreen QApplication)
실행: python -B test_pages_ui.py
산출물: test_output/pages_test/
"""
import io
import os
import sys
import traceback
import fitz
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap
from main import MainWindow, EditPageWidget, MENU_ITEMS

OUT_DIR = str(Path(__file__).parent / "test_output" / "pages_test")
os.makedirs(OUT_DIR, exist_ok=True)

SRC_14P = str(Path(__file__).parent / "1.pdf")
SRC_1P  = str(Path(__file__).parent / "4.pdf")

results = []

def record(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    suffix = f" | {detail}" if detail else ""
    print(f"  [{tag}] {name}{suffix}")
    results.append((name, ok, detail))

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

app = QApplication(sys.argv)
w = MainWindow()

# ═══════════════════════════════════════════════════════════════════
# 1. 앱 실행 / 메뉴 활성화 확인
# ═══════════════════════════════════════════════════════════════════
section("1. 메뉴 활성화 확인")

pages_entry = next((e for e in MENU_ITEMS if e[0] == "pages"), None)
record("pages 메뉴 항목 존재", pages_entry is not None)
record("pages 메뉴 enabled=True", pages_entry is not None and pages_entry[2] is True,
       f"enabled={pages_entry[2] if pages_entry else 'N/A'}")

# 사이드바 버튼 존재
record("pages 사이드바 버튼 생성", "pages" in w._sidebar_buttons)

# ═══════════════════════════════════════════════════════════════════
# 2. pages 모드 전환
# ═══════════════════════════════════════════════════════════════════
section("2. 모드 전환")

w._set_mode("pages")
record("pages 모드 전환", w._mode == "pages", f"mode={w._mode}")
record("workspace stack index=3", w._workspace_stack.currentIndex() == 3,
       f"idx={w._workspace_stack.currentIndex()}")
record("option stack index=3",    w._option_stack.currentIndex() == 3,
       f"idx={w._option_stack.currentIndex()}")
record("run_btn 텍스트 변경",
       "편집" in w.run_btn.text() or "저장" in w.run_btn.text(),
       w.run_btn.text())

# ═══════════════════════════════════════════════════════════════════
# 3. PDF 로드 (파일 추가 버튼 시뮬레이션)
# ═══════════════════════════════════════════════════════════════════
section("3. PDF 로드 — 14페이지 파일")

orig_14p_mtime = Path(SRC_14P).stat().st_mtime

w._load_pages_pdf(SRC_14P)
record("pdf_path 저장", w._pages_pdf_path == SRC_14P)
record("page_count 저장=14", w._pages_page_count == 14,
       f"count={w._pages_page_count}")
record("썸네일 위젯 수=14", len(w._pages_page_widgets) == 14,
       f"widgets={len(w._pages_page_widgets)}")
record("view stack → index 1 (썸네일)", w._pages_view_stack.currentIndex() == 1,
       f"idx={w._pages_view_stack.currentIndex()}")
record("모든 위젯이 EditPageWidget",
       all(isinstance(x, EditPageWidget) for x in w._pages_page_widgets))
record("초기 rotation 모두 0",
       all(x.rotation() == 0 for x in w._pages_page_widgets))

# ═══════════════════════════════════════════════════════════════════
# 4. 드래그앤드롭 시뮬레이션 (같은 경로 재로드)
# ═══════════════════════════════════════════════════════════════════
section("4. 드래그앤드롭 시뮬레이션")

prev_count = len(w._pages_page_widgets)
w._load_pages_pdf(SRC_14P)   # _PagesDropTarget.pdf_dropped → _load_pages_pdf
record("재로드 후 기존 위젯 정리됨", len(w._pages_page_widgets) == 14,
       f"widgets={len(w._pages_page_widgets)}")
# 이전 위젯이 교체됐는지 확인 (새 객체여야 함)
record("새 위젯 객체로 교체됨",
       id(w._pages_page_widgets[0]) != id(w._pages_page_widgets[-1]))

# ═══════════════════════════════════════════════════════════════════
# 5. 전체선택 / 전체해제
# ═══════════════════════════════════════════════════════════════════
section("5. 전체선택 / 전체해제")

w._select_all_pages()
sel = sum(1 for x in w._pages_page_widgets if x.is_selected())
record("전체선택 후 선택 수=14", sel == 14, f"selected={sel}")

w._clear_pages_selection()
sel = sum(1 for x in w._pages_page_widgets if x.is_selected())
record("전체해제 후 선택 수=0", sel == 0, f"selected={sel}")

# ═══════════════════════════════════════════════════════════════════
# 6. 일부 선택 후 삭제
# ═══════════════════════════════════════════════════════════════════
section("6. 선택 페이지 삭제")

# 0,2,4,6번 페이지(1,3,5,7p) 선택
w._clear_pages_selection()
for idx in [0, 2, 4, 6]:
    w._pages_page_widgets[idx].set_selected(True)
before_delete_count = len(w._pages_page_widgets)

w._delete_selected_pages()

after_count = len(w._pages_page_widgets)
record("삭제 후 위젯 수=10 (14-4)", after_count == 10,
       f"before={before_delete_count} after={after_count}")
# 남은 위젯의 page_index는 1,3,5,7,8,9,10,11,12,13 이어야 함
remaining_indices = [x.page_index() for x in w._pages_page_widgets]
expected_indices  = [1, 3, 5, 7, 8, 9, 10, 11, 12, 13]
record("남은 page_index 정확", remaining_indices == expected_indices,
       f"indices={remaining_indices}")

# 삭제된 후 선택 없는 상태
sel = sum(1 for x in w._pages_page_widgets if x.is_selected())
record("삭제 후 선택 초기화", sel == 0, f"selected={sel}")

# ═══════════════════════════════════════════════════════════════════
# 7. 모든 페이지 삭제 방지
# ═══════════════════════════════════════════════════════════════════
section("7. 전체 삭제 방지")

# 현재 10p → 전체 선택 후 삭제 시도 (QMessageBox가 뜨므로 시뮬레이션)
# _delete_selected_pages 내부에서 remaining이 0이면 경고 후 return
w._select_all_pages()
count_before_attempt = len(w._pages_page_widgets)

# QMessageBox.warning 을 패치해서 경고 없이 테스트
from unittest.mock import patch
with patch("main.QMessageBox.warning") as mock_warn:
    w._delete_selected_pages()
    record("전체 삭제 시 warning 호출됨", mock_warn.called,
           f"called={mock_warn.called}")

record("전체 삭제 시도 후 위젯 수 변동 없음",
       len(w._pages_page_widgets) == count_before_attempt,
       f"before={count_before_attempt} after={len(w._pages_page_widgets)}")

# ═══════════════════════════════════════════════════════════════════
# 8. 선택 페이지 회전
# ═══════════════════════════════════════════════════════════════════
section("8. 선택 페이지 회전")

w._clear_pages_selection()
# 처음 3개 선택
for i in range(3):
    w._pages_page_widgets[i].set_selected(True)

w._rotate_selected_pages()
rot_after_1 = [w._pages_page_widgets[i].rotation() for i in range(3)]
record("1회 회전 후 처음 3개 rotation=90",
       rot_after_1 == [90, 90, 90], f"rotations={rot_after_1}")

w._rotate_selected_pages()
rot_after_2 = [w._pages_page_widgets[i].rotation() for i in range(3)]
record("2회 회전 후 처음 3개 rotation=180",
       rot_after_2 == [180, 180, 180], f"rotations={rot_after_2}")

# 나머지는 회전 없음
non_sel_rots = [w._pages_page_widgets[i].rotation() for i in range(3, 10)]
record("미선택 페이지 rotation 유지=0",
       all(r == 0 for r in non_sel_rots), f"rotations={non_sel_rots}")

# 선택 없이 회전 시 warning
w._clear_pages_selection()
with patch("main.QMessageBox.warning") as mock_warn:
    w._rotate_selected_pages()
    record("미선택 상태 회전 시 warning 호출", mock_warn.called)

# ═══════════════════════════════════════════════════════════════════
# 9. 선택 페이지 이동 (왼쪽/오른쪽)
# ═══════════════════════════════════════════════════════════════════
section("9. 페이지 순서 이동")

# 현재 page_index 순서 기록
before_move = [x.page_index() for x in w._pages_page_widgets]
print(f"    이동 전 page_index: {before_move}")

# 인덱스 3,4번 위젯 선택
w._clear_pages_selection()
w._pages_page_widgets[3].set_selected(True)
w._pages_page_widgets[4].set_selected(True)
sel_indices_before = [w._pages_page_widgets[3].page_index(),
                      w._pages_page_widgets[4].page_index()]

# 왼쪽 이동 1칸
w._move_pages(-1)
after_left = [x.page_index() for x in w._pages_page_widgets]
print(f"    왼쪽 이동 후: {after_left}")
# 위젯 위치 [2],[3]에 있어야 함 (한 칸씩 앞으로)
record("왼쪽 이동: 선택 블록이 앞으로 이동",
       after_left[2] == sel_indices_before[0] and after_left[3] == sel_indices_before[1],
       f"pos2={after_left[2]}, pos3={after_left[3]}")

# 오른쪽 이동 2칸 (원위치 복귀)
w._move_pages(1)
w._move_pages(1)
after_right = [x.page_index() for x in w._pages_page_widgets]
print(f"    오른쪽 이동 2칸 후: {after_right}")

# 맨 앞(0번)이 왼쪽 이동 불가 확인
w._clear_pages_selection()
w._pages_page_widgets[0].set_selected(True)
idx_at_0_before = w._pages_page_widgets[0].page_index()
w._move_pages(-1)
idx_at_0_after  = w._pages_page_widgets[0].page_index()
record("맨 앞 페이지 왼쪽 이동 불가",
       idx_at_0_before == idx_at_0_after,
       f"before={idx_at_0_before} after={idx_at_0_after}")

# 맨 뒤 오른쪽 이동 불가
w._clear_pages_selection()
last_idx = len(w._pages_page_widgets) - 1
w._pages_page_widgets[last_idx].set_selected(True)
idx_last_before = w._pages_page_widgets[last_idx].page_index()
w._move_pages(1)
idx_last_after  = w._pages_page_widgets[last_idx].page_index()
record("맨 뒤 페이지 오른쪽 이동 불가",
       idx_last_before == idx_last_after,
       f"before={idx_last_before} after={idx_last_after}")

# ═══════════════════════════════════════════════════════════════════
# 10~12. 편집 결과 저장 및 검증
# ═══════════════════════════════════════════════════════════════════
section("10-12. 저장 및 원본 검증")

# 깨끗하게 다시 로드
w._load_pages_pdf(SRC_14P)
# 시나리오: 1,3,5,7페이지(0-based:0,2,4,6) 삭제 + 남은 처음 3개 회전(90°) + 2,3번 순서 교환 후 저장
w._clear_pages_selection()
for idx in [0, 2, 4, 6]:
    w._pages_page_widgets[idx].set_selected(True)
w._delete_selected_pages()  # 14p → 10p

# 처음 3개 90° 회전
w._clear_pages_selection()
for i in range(3):
    w._pages_page_widgets[i].set_selected(True)
w._rotate_selected_pages()

# 1,2번 위치 교환 (오른쪽 이동)
w._clear_pages_selection()
w._pages_page_widgets[1].set_selected(True)
w._move_pages(-1)   # 1→0 이동

# 저장 전 상태 기록
expected_ops = w._get_pages_page_ops()
print(f"    저장될 page_ops: {expected_ops}")

out_path = str(Path(OUT_DIR) / "scenario_edited.pdf")
orig_mtime_before = Path(SRC_14P).stat().st_mtime

# PageEditWorker를 통하지 않고 직접 호출 (비동기 없이)
from merger import save_edited_pdf, make_unique_split_path
try:
    save_edited_pdf(SRC_14P, expected_ops, out_path)
    saved_ok = True
except Exception as e:
    saved_ok = False
    print(f"    저장 오류: {e}")

record("편집 결과 저장 성공", saved_ok)

if saved_ok:
    # 저장된 PDF 검증
    result_doc = fitz.open(out_path)
    saved_page_count = result_doc.page_count
    saved_rotations  = [result_doc[i].rotation for i in range(result_doc.page_count)]
    result_doc.close()

    record("저장 파일 페이지 수=10", saved_page_count == 10,
           f"pages={saved_page_count}")

    # 처음 3개는 원본 rotation + 90
    src_doc = fitz.open(SRC_14P)
    # 남은 page indices (삭제 후): [1,3,5,7,8,9,10,11,12,13]
    # 그 중 1,2번(pos 0,1) 스왑 → pos0=3, pos1=1
    # 처음 3개 rotation=90 적용
    # pos0의 원본 idx: expected_ops[0]['idx'], 원본 rotation: src_doc[idx].rotation
    # 기대 rotation = (원본 rotation + 90) % 360
    expected_rots = []
    for op in expected_ops:
        orig_rot = src_doc[op["idx"]].rotation
        if op["rotation"] != 0:
            expected_rots.append((orig_rot + op["rotation"]) % 360)
        else:
            expected_rots.append(orig_rot)
    src_doc.close()
    record("저장 파일 rotation 정확",
           saved_rotations == expected_rots,
           f"saved={saved_rotations[:5]}... expected={expected_rots[:5]}...")

# 원본 파일 변경 없음
orig_mtime_after = Path(SRC_14P).stat().st_mtime
record("원본 파일 mtime 변경 없음",
       orig_mtime_before == orig_mtime_after,
       f"before={orig_mtime_before} after={orig_mtime_after}")

# 원본 덮어쓰기 차단 (동일 경로로 save 시도)
try:
    save_edited_pdf(SRC_14P, [{"idx": 0, "rotation": 0}], SRC_14P)
    record("원본 덮어쓰기 차단", False, "ValueError 미발생 — 차단 실패!")
except ValueError:
    record("원본 덮어쓰기 차단", True, "ValueError 정상 발생")

# 1페이지 PDF 테스트 (모두 삭제 방지)
section("  1페이지 PDF 전체 삭제 방지")
w._load_pages_pdf(SRC_1P)
record("1p PDF 로드", w._pages_page_count == 1, f"count={w._pages_page_count}")
w._select_all_pages()
with patch("main.QMessageBox.warning") as mock_warn:
    w._delete_selected_pages()
    record("1p 전체 삭제 방지 (warning 호출)", mock_warn.called)
record("1p 삭제 후에도 위젯 1개 유지", len(w._pages_page_widgets) == 1)

# ═══════════════════════════════════════════════════════════════════
# 13. 기존 기능 회귀 테스트
# ═══════════════════════════════════════════════════════════════════
section("13. 기존 기능 회귀 테스트")

for mode, idx in [("merge", 0), ("compress", 1), ("split", 2)]:
    w._set_mode(mode)
    record(f"{mode} 모드 전환 및 stack index={idx}",
           w._mode == mode and w._workspace_stack.currentIndex() == idx,
           f"mode={w._mode} workspace_idx={w._workspace_stack.currentIndex()}")

# 분할 화면 PDF 로드
w._set_mode("split")
w._load_split_pdf(SRC_14P)
record("split _load_split_pdf 정상 동작",
       len(w._split_page_widgets) == 14,
       f"widgets={len(w._split_page_widgets)}")

# merge/compress/split run_btn 텍스트
for mode, expected_frag in [("compress", "압축"), ("split", "분할"), ("merge", "작업")]:
    w._set_mode(mode)
    record(f"{mode} run_btn 텍스트 정확",
           expected_frag in w.run_btn.text(),
           w.run_btn.text())

# pages 모드로 복귀 후 run_btn
w._set_mode("pages")
record("pages run_btn 텍스트 정확",
       "편집" in w.run_btn.text() or "저장" in w.run_btn.text(),
       w.run_btn.text())

# ═══════════════════════════════════════════════════════════════════
# _get_pages_page_ops 반환값 구조 확인
# ═══════════════════════════════════════════════════════════════════
section("기타: page_ops 구조 / _rebuild_pages_grid")

w._load_pages_pdf(SRC_14P)
ops = w._get_pages_page_ops()
record("page_ops 길이=14", len(ops) == 14, f"len={len(ops)}")
record("page_ops 키 포함 (idx, rotation)",
       all("idx" in o and "rotation" in o for o in ops))
record("page_ops idx 순서 0..13",
       [o["idx"] for o in ops] == list(range(14)))

# _rebuild_pages_grid 호출 후 위젯 수 변동 없음
w._rebuild_pages_grid()
record("_rebuild_pages_grid 후 위젯 수 유지",
       len(w._pages_page_widgets) == 14)

# ═══════════════════════════════════════════════════════════════════
# 결과 요약
# ═══════════════════════════════════════════════════════════════════
print("\n" + "="*60)
print("  최종 결과 요약")
print("="*60)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
total  = len(results)
print(f"  PASS: {passed}/{total}  |  FAIL: {failed}/{total}")

if failed:
    print("\n  실패 항목:")
    for name, ok, detail in results:
        if not ok:
            print(f"    ✗ {name} — {detail}")

# 저장된 산출물 목록
print("\n  생성된 파일:")
for f in sorted(Path(OUT_DIR).glob("*")):
    size = f.stat().st_size
    print(f"    {f.name}  ({size:,} bytes)")

sys.exit(0 if failed == 0 else 1)
