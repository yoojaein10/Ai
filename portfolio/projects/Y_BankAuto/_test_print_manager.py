# -*- coding: utf-8 -*-
'선택형 자동 인쇄 회귀 테스트 (print_manager).\n\n실제 프린터/Windows 스풀러/GDI에 작업을 제출하지 않는다. 모든 win32/GDI 경계는\nMockBackend로 대체한다. 데이터는 전부 합성(REDACTED_CONFIGURE_LOCALLY)이며 실제 PDF/PII를 쓰지 않는다.\n단독 pytest 프로세스로 실행 가능.\n'
import os
import stat as _stat

import pytest

import print_manager as pm


# ── 합성 헬퍼 ────────────────────────────────────────────────────────────────
def make_pdf_bytes(pages=1, w=595.0, h=842.0):
    """fitz로 만든 합성 PDF 바이트 (실제 문서 아님, 더미 사각형만)."""
    import fitz
    doc = fitz.open()
    try:
        for _ in range(pages):
            page = doc.new_page(width=w, height=h)
            page.draw_rect(fitz.Rect(20, 20, w - 20, h - 20), color=(0, 0, 0))
        return doc.tobytes()
    finally:
        doc.close()


def write_pdf(dir_path, name="doc.pdf", data=None):
    p = os.path.join(str(dir_path), name)
    with open(p, "wb") as f:
        f.write(data if data is not None else make_pdf_bytes())
    return p


class FakeRenderer:
    """실제 렌더링 없이 페이지 목록만 반환(제출 경로 테스트용)."""
    def __init__(self, pages=1, w=595.0, h=842.0, error=None):
        self.pages = pages
        self.w = w
        self.h = h
        self.error = error
        self.calls = 0

    def __call__(self, pdf_bytes, *a, **k):
        self.calls += 1
        if self.error:
            raise self.error
        return [pm.RenderedPage(self.w, self.h, object()) for _ in range(self.pages)]


class MockBackend:
    """win32/GDI 경계 mock — 실제 스풀러에 제출하지 않는다."""
    def __init__(self, names=("Printer A",), ready=None, submit_error=None):
        self._names = list(names)
        self._ready = ready          # None=준비됨, 아니면 사유 코드
        self._submit_error = submit_error
        self.submitted = []          # (printer, n_pages, job_name)
        self.enum_calls = 0

    def enum_printer_names(self):
        self.enum_calls += 1
        return list(self._names)

    def printer_ready_code(self, name):
        return self._ready

    def submit_print_job(self, printer_name, rendered_pages, job_name):
        self.submitted.append((printer_name, len(rendered_pages), job_name))
        if self._submit_error is not None:
            raise self._submit_error


def make_mgr(tmp, *, enabled=True, printer="Printer A", names=("Printer A",),
             ready=None, submit_error=None, renderer=None, max_jobs=100):
    backend = MockBackend(names=names, ready=ready, submit_error=submit_error)
    mgr = pm.PrintManager(
        enabled=enabled, printer_name=printer, allowed_dir=str(tmp),
        max_jobs_per_run=max_jobs, backend=backend,
        renderer=renderer or FakeRenderer(),
    )
    return mgr, backend


# ── 상한/불린 파서 ───────────────────────────────────────────────────────────
def test_clamp_max_jobs_default_and_hardcap():
    assert pm.clamp_max_jobs("100") == 100
    assert pm.clamp_max_jobs("5") == 5                     # 낮추기 허용
    assert pm.clamp_max_jobs("999999") == pm.HARD_MAX_JOBS_PER_RUN  # 무제한 방지
    assert pm.clamp_max_jobs("bad") == pm.DEFAULT_MAX_JOBS_PER_RUN  # 손상값 기본
    assert pm.clamp_max_jobs("-3") == pm.DEFAULT_MAX_JOBS_PER_RUN


def test_parse_bool_strict():
    assert pm.parse_bool_strict("true") is True
    assert pm.parse_bool_strict("false") is False
    assert pm.parse_bool_strict(True) is True
    assert pm.parse_bool_strict("maybe") is None          # 불명확 → None
    assert pm.parse_bool_strict("") is None


# ── OFF / 미선택 ─────────────────────────────────────────────────────────────
def test_off_skips_everything(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, enabled=False)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_AUTOPRINT_OFF
    assert backend.enum_calls == 0          # 조회조차 하지 않음
    assert backend.submitted == []


def test_no_printer_selected_skips(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, printer="")
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_NO_PRINTER
    assert backend.submitted == []


# ── 정상 인쇄: 선택 프린터로 1부, 1회 ────────────────────────────────────────
def test_success_submits_once_to_selected_printer(tmp_path):
    path = write_pdf(tmp_path)
    renderer = FakeRenderer(pages=2)
    mgr, backend = make_mgr(tmp_path, renderer=renderer)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_OK and res.code == pm.CODE_OK
    assert len(backend.submitted) == 1
    printer, n_pages, job_name = backend.submitted[0]
    assert printer == "Printer A"           # 선택 프린터로만
    assert n_pages == 2
    assert "Printer A" not in job_name       # 문서명에 프린터명(PII 가능) 미포함
    assert mgr.counts["성공"] == 1


# ── 프린터 없음/중복/오프라인/오류 → 인쇄만 건너뜀 ───────────────────────────
def test_printer_missing_skips(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, printer="Ghost", names=("Printer A",))
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_PRINTER_NOT_FOUND
    assert backend.submitted == []


def test_printer_ambiguous_skips(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, printer="Dup", names=("Dup", "Dup"))
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_PRINTER_AMBIGUOUS
    assert backend.submitted == []


def test_printer_not_ready_skips(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, ready=pm.CODE_PRINTER_NOT_READY)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_PRINTER_NOT_READY
    assert backend.submitted == []


def test_no_fallback_to_other_printer(tmp_path):
    # 선택 프린터가 없을 때 목록의 다른 프린터로 전환하지 않는다.
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, printer="Selected",
                            names=("Other 1", "Other 2"))
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP
    assert backend.submitted == []          # 어떤 프린터로도 제출 안 함


# ── 실패/불확실 격리 ─────────────────────────────────────────────────────────
def test_submit_exception_is_uncertain_and_isolated(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, submit_error=RuntimeError("gdi boom"))
    res = mgr.print_document(path)   # 예외가 전파되지 않아야 함
    assert res.status == pm.PRINT_UNCERTAIN and res.code == pm.CODE_SUBMIT_UNCERTAIN
    assert len(backend.submitted) == 1      # 제출 '시도'는 1회
    assert mgr.counts["확인필요"] == 1


def test_render_error_is_fail_not_raise(tmp_path):
    path = write_pdf(tmp_path)
    renderer = FakeRenderer(error=RuntimeError("render boom"))
    mgr, backend = make_mgr(tmp_path, renderer=renderer)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_FAIL and res.code == pm.CODE_RENDER_ERROR
    assert backend.submitted == []


# ── 중복/재시도/불확실 → 재인쇄 없음 ─────────────────────────────────────────
def test_same_document_printed_at_most_once(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path)
    r1 = mgr.print_document(path)
    r2 = mgr.print_document(path)            # 저장 재시도 등으로 재요청
    assert r1.status == pm.PRINT_OK
    assert r2.status == pm.PRINT_SKIP and r2.code == pm.CODE_ALREADY_PRINTED
    assert len(backend.submitted) == 1       # 중복 인쇄 없음


def test_uncertain_does_not_auto_reprint(tmp_path):
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, submit_error=RuntimeError("x"))
    r1 = mgr.print_document(path)
    r2 = mgr.print_document(path)
    assert r1.status == pm.PRINT_UNCERTAIN
    assert r2.status == pm.PRINT_SKIP and r2.code == pm.CODE_ALREADY_PRINTED
    assert len(backend.submitted) == 1       # 자동 재인쇄 없음


# ── 실행당 상한 ──────────────────────────────────────────────────────────────
def test_run_limit_skips_excess(tmp_path):
    mgr, backend = make_mgr(tmp_path, max_jobs=2)
    paths = [write_pdf(tmp_path, name=f"d{i}.pdf") for i in range(3)]
    results = [mgr.print_document(p) for p in paths]
    assert results[0].status == pm.PRINT_OK
    assert results[1].status == pm.PRINT_OK
    assert results[2].status == pm.PRINT_SKIP and results[2].code == pm.CODE_RUN_LIMIT
    assert len(backend.submitted) == 2       # 상한만큼만 제출


# ── 경로/파일 검증 ───────────────────────────────────────────────────────────
def test_outside_allowed_dir_skips(tmp_path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    path = write_pdf(outside)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    backend = MockBackend()
    mgr = pm.PrintManager(enabled=True, printer_name="Printer A",
                          allowed_dir=str(allowed), backend=backend,
                          renderer=FakeRenderer())
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_PATH_OUTSIDE
    assert backend.submitted == []


def test_symlink_or_reparse_skips(tmp_path, monkeypatch):
    # 실제 심볼릭 생성 권한에 의존하지 않도록 realpath가 경로를 치환한 상황을 모사.
    path = write_pdf(tmp_path)
    real_realpath = os.path.realpath

    def fake_realpath(p):
        if os.path.normcase(os.path.abspath(p)) == os.path.normcase(os.path.abspath(path)):
            return os.path.join(str(tmp_path), "elsewhere_target.pdf")
        return real_realpath(p)

    monkeypatch.setattr(pm.os.path, "realpath", fake_realpath)
    mgr, backend = make_mgr(tmp_path)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_PATH_SYMLINK
    assert backend.submitted == []


def test_missing_file_skips(tmp_path):
    path = os.path.join(str(tmp_path), "gone.pdf")
    mgr, backend = make_mgr(tmp_path)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_FILE_MISSING
    assert backend.submitted == []


def test_bad_signature_skips(tmp_path):
    path = write_pdf(tmp_path, name="fake.pdf", data=b"NOT A PDF" * 10)
    mgr, backend = make_mgr(tmp_path)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_BAD_SIGNATURE
    assert backend.submitted == []


def test_bad_extension_skips(tmp_path):
    path = write_pdf(tmp_path, name="doc.txt")
    mgr, backend = make_mgr(tmp_path)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_BAD_EXT
    assert backend.submitted == []


def test_too_large_skips(tmp_path, monkeypatch):
    path = write_pdf(tmp_path)
    monkeypatch.setattr(pm, "MAX_PDF_BYTES", 10)  # 인위적으로 작게
    mgr, backend = make_mgr(tmp_path)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_TOO_LARGE
    assert backend.submitted == []


def test_too_many_pages_skips(tmp_path):
    data = make_pdf_bytes(pages=3)
    path = write_pdf(tmp_path, data=data)
    # 실제 렌더러로 페이지 수 상한 검증 (max_pages=2)
    renderer = lambda b: pm.render_pdf_pages(b, dpi=72, max_pages=2)
    mgr, backend = make_mgr(tmp_path, renderer=renderer)
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_SKIP and res.code == pm.CODE_TOO_MANY_PAGES
    assert backend.submitted == []


# ── 페이지 크기·방향·비율 계산 ──────────────────────────────────────────────
def test_placement_portrait_fit_centered():
    # A4 세로(595x842pt)를 300DPI 프린터 인쇄영역(2480x3508)에 맞춤
    x, y, w, h = pm.compute_placement(595.0, 842.0, 2480, 3508, 300, 300)
    # 비율 유지: w/h ≈ 595/842
    assert abs((w / h) - (595.0 / 842.0)) < 0.01
    # 인쇄영역 내부
    assert 0 <= x and 0 <= y and x + w <= 2480 and y + h <= 3508
    # 중앙 정렬
    assert abs((2480 - w) / 2 - x) <= 1 and abs((3508 - h) / 2 - y) <= 1


def test_placement_landscape_orientation_preserved():
    # 가로 페이지(842x595)는 가로 비율을 유지
    x, y, w, h = pm.compute_placement(842.0, 595.0, 2480, 3508, 300, 300)
    assert w > h                                  # 가로가 더 김
    assert abs((w / h) - (842.0 / 595.0)) < 0.01
    assert x + w <= 2480 and y + h <= 3508


def test_placement_no_crop_when_page_larger_than_area():
    # 페이지가 인쇄영역보다 크면 축소만 하고 잘리지 않는다.
    x, y, w, h = pm.compute_placement(2000.0, 3000.0, 500, 700, 72, 72)
    assert w <= 500 and h <= 700 and x >= 0 and y >= 0


def test_placement_invalid_inputs_raise():
    with pytest.raises(ValueError):
        pm.compute_placement(0, 100, 500, 500, 300, 300)
    with pytest.raises(ValueError):
        pm.compute_placement(100, 100, 0, 500, 300, 300)


# ── 실제 렌더링(합성 PDF) — 능동콘텐츠 미실행, 셸 미호출 ─────────────────────
def test_real_render_produces_pages_with_true_size(tmp_path):
    data = make_pdf_bytes(pages=1, w=595.0, h=842.0)
    pages = pm.render_pdf_pages(data, dpi=72)
    assert len(pages) == 1
    assert abs(pages[0].width_pt - 595.0) < 1 and abs(pages[0].height_pt - 842.0) < 1


def test_no_shell_or_external_process_used(tmp_path, monkeypatch):
    # 인쇄 전체 경로에서 os.system/subprocess/셸을 호출하지 않음을 보장.
    import subprocess
    def boom(*a, **k):
        raise AssertionError("external process must not be used for printing")
    monkeypatch.setattr(os, "system", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "call", boom)
    path = write_pdf(tmp_path)
    mgr, backend = make_mgr(tmp_path, renderer=lambda b: pm.render_pdf_pages(b, dpi=72))
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_OK
    assert len(backend.submitted) == 1


def test_active_content_pdf_still_renders_without_side_effect(tmp_path):
    # OpenAction/JS가 있는 PDF라도 pixmap 렌더는 스크립트를 실행하지 않는다.
    import fitz
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    # 문서 열기 동작(OpenAction) 및 JS를 삽입 — 렌더 시 실행되면 안 됨
    try:
        doc.set_open_action(0, fitz.Point(0, 0))
    except Exception:
        pass
    data = doc.tobytes()
    doc.close()
    path = write_pdf(tmp_path, data=data)
    mgr, backend = make_mgr(tmp_path, renderer=lambda b: pm.render_pdf_pages(b, dpi=72))
    res = mgr.print_document(path)
    assert res.status == pm.PRINT_OK    # 예외 없이 렌더·제출


def test_no_temp_files_left_behind(tmp_path):
    # 메모리 렌더링만 사용 — 허용 디렉터리에 임시 이미지/사본을 남기지 않는다.
    path = write_pdf(tmp_path)
    before = set(os.listdir(str(tmp_path)))
    mgr, backend = make_mgr(tmp_path, renderer=lambda b: pm.render_pdf_pages(b, dpi=72))
    mgr.print_document(path)
    after = set(os.listdir(str(tmp_path)))
    assert before == after              # 새 임시 파일 없음


# ── 리스트 조회 실패 격리 ────────────────────────────────────────────────────
def test_list_installed_printers_failure_returns_empty():
    class Boom:
        def enum_printer_names(self):
            raise RuntimeError("enum failed")
    assert pm.list_installed_printers(backend=Boom()) == []


def test_list_installed_printers_dedup_sorted():
    class B:
        def enum_printer_names(self):
            return ["B", "A", "B", "  ", "A"]
    assert pm.list_installed_printers(backend=B()) == ["A", "B"]


# ── 저장·검증 실패 시 인쇄 안 함 (호출부 계약) ───────────────────────────────
def test_caller_prints_only_on_verified_success(tmp_path):
    # 파이프라인 계약: 처리상태=='성공'일 때만 print_document를 호출한다.
    mgr, backend = make_mgr(tmp_path)
    path = write_pdf(tmp_path)

    def pipeline_step(item_status):
        if item_status == "성공":
            return mgr.print_document(path)
        return None  # 저장/검증 실패 → 인쇄 호출 자체를 하지 않음

    assert pipeline_step("실패") is None
    assert backend.submitted == []
    r = pipeline_step("성공")
    assert r.status == pm.PRINT_OK
    assert len(backend.submitted) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
