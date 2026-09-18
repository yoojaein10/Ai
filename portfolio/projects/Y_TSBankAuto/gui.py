# -*- coding: utf-8 -*-
"""Y_TSBankAuto 탁상감정 테스트판 GUI (tkinter). 지시 §11.

- 화면 명칭은 모두 탁상감정 기준.
- Bank24 상태, 탁상 조회, 의뢰 선택, PDF 다운로드/직접 선택, 처리 시작, 긴급 중지.
- Customer/RegHist/중복/메타데이터 상태와 처리 불가 사유, 대표 물건 정책 표시.
- 실제 자동화 시작 전 세션 확인문구 요구(파일·레지스트리 미저장). DB 저장 버튼 비활성.
- "테스트판 — DB 저장 없음" 명확 표시.
- 메인 스레드에서 자동화·PDF 파싱·DB 미실행(워커 스레드). 큐에는 마스킹 DTO만.
- 자격증명·서버명·로그인명·상세주소·원문 업무번호·연결문자열 미표시.

import 만으로 창을 띄우지 않는다. main() 호출 시에만 실행한다.
format_report_for_gui() 는 tkinter 없이 단위 테스트 가능한 순수 함수다.
"""
from __future__ import annotations

import os
import queue
import threading

TEST_BANNER = (
    "테스트판 — DB 저장 없음. 실제 SP 실행/COMMIT/데이터 변경을 하지 않습니다. "
    "SP 정의는 provisional 이며 실행 경로에 연결되지 않습니다."
)


def format_report_for_gui(report) -> list[str]:
    """오케스트레이터 RunReport → 마스킹 표시 라인. 원문 PII/자격증명 미포함.

    report.customer_dtos/reghist_dtos 는 이미 마스킹 DTO 다.
    """
    lines: list[str] = []
    for step, ok, note in report.steps:
        mark = "OK" if ok else "실패"
        lines.append(f"[{mark}] {step}" + (f" — {note}" if note else ""))
    if report.failed_step:
        lines.append(f"※ 중단 단계: {report.failed_step}")

    pm = report.parse_masked or {}
    if pm:
        if pm.get("multi_unit"):
            lines.append("· 다물건: 첫 대표 물건만 사용(정책)")
        lines.append(f"· 파싱 상태: {pm.get('status')} / 은행: {pm.get('bank', '?')}")

    if report.customer_status:
        lines.append(f"· Customer: {report.customer_status} "
                     f"(후보 {len(report.customer_dtos)})")
    if report.reghist_status:
        lines.append(f"· RegHist: {report.reghist_status} "
                     f"(후보 {len(report.reghist_dtos)})")
    if report.duplicate_status:
        lines.append(f"· 중복: {report.duplicate_status}")
    if report.metadata_status:
        lines.append(f"· SP 메타데이터: {report.metadata_status} "
                     f"(fingerprint: {report.fingerprint_status})")
    if report.decision:
        d = report.decision
        lines.append(f"· 처리 결정: {d['status']}")
        for r in d.get("reasons", []):
            lines.append(f"    - 처리불가 사유: {r}")
    lines.append(f"· DB 연결: {report.db_connected} / COMMIT: {report.committed} "
                 f"/ SP 실행: {report.executed_sp}")
    return lines


class _Worker(threading.Thread):
    """탁상 처리 워커. fake adapter 로 전체 흐름을 실행하고 마스킹 리포트를 큐로 전달."""

    def __init__(self, out_q: queue.Queue, stop_ev: threading.Event,
                 pdf_root: str, allowed_roots: list[str]):
        super().__init__(daemon=True)
        self.out_q = out_q
        self.stop_ev = stop_ev
        self.pdf_root = pdf_root
        self.allowed_roots = allowed_roots

    def run(self):
        # 레거시 tkinter 데모는 비활성화됐다(제품 진입점은 app_gui, §100/§101).
        # 제거된 select_adapter/fake 흐름을 실행하지 않는다.
        self.out_q.put(("error", ["레거시 GUI 는 비활성화됨(안전코드: LEGACY_DISABLED)"]))
        self.out_q.put(("done", None))


def main():  # pragma: no cover - GUI
    import tkinter as tk
    from tkinter import scrolledtext

    import config
    import settings_integrity

    # 고정 경로(C:\Bank24Extractor\settings.ini) 사용 + 없으면 시크릿 없는 기본본 자동 생성.
    settings_integrity.ensure_settings_file()
    ini = settings_integrity.resolve_settings_path()
    pdf_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdf_test")
    try:
        app_cfg = config.load_app_config(ini)
        if app_cfg.paths.pdf_root:
            pdf_root = app_cfg.paths.pdf_root
    except Exception:
        pass
    os.makedirs(pdf_root, exist_ok=True)

    root = tk.Tk()
    root.title("Y_TSBankAuto 탁상감정 (테스트판 — DB 저장 없음)")
    root.geometry("880x620")

    tk.Label(root, text=TEST_BANNER, fg="white", bg="#9c2b2b",
             wraplength=860, justify="left").pack(fill="x")

    log = scrolledtext.ScrolledText(root, height=26)
    log.pack(fill="both", expand=True, padx=6, pady=6)

    out_q: queue.Queue = queue.Queue()
    stop_ev = threading.Event()

    def append(line: str):
        log.insert("end", line + "\n")
        log.see("end")

    def poll():
        try:
            while True:
                kind, payload = out_q.get_nowait()
                if kind in ("report", "error"):
                    for ln in payload:
                        append(ln)
                elif kind == "done":
                    append("== 처리 완료 (실제 저장 없음) ==")
        except queue.Empty:
            pass
        root.after(150, poll)

    def start():
        stop_ev.clear()
        append("== 레거시 데모는 비활성화됨 — 제품 GUI(app_gui)를 사용하세요 ==")
        _Worker(out_q, stop_ev, pdf_root, [pdf_root]).start()

    bar = tk.Frame(root)
    bar.pack(fill="x", padx=6, pady=4)
    tk.Button(bar, text="탁상 조회·처리 시작", command=start).pack(side="left")
    tk.Button(bar, text="긴급 중지", fg="red",
              command=lambda: stop_ev.set()).pack(side="left", padx=6)
    tk.Label(bar, text="실제 자동화 확인문구:").pack(side="left", padx=(20, 2))
    tk.Entry(bar, width=22).pack(side="left")
    save_btn = tk.Button(bar, text="DB 저장", state="disabled")
    save_btn.pack(side="left", padx=(20, 2))
    tk.Label(bar, text="※ 비활성(테스트판)").pack(side="left")

    poll()
    root.mainloop()


if __name__ == "__main__":
    main()
