# -*- coding: utf-8 -*-
"""KrasFill GUI — 폴더를 지정하고 시작을 누르면 폴더 안의 워크북을 하나씩 기입한다.

- 진행률 바(파일 단위) + 실시간 로그.
- 원본 워크북에 바로 기입한다(복사본 없음). 기입 대상 외 셀·사진·수식은 보존.
- exe 빌드: python -m PyInstaller KrasFill.spec --noconfirm --clean
"""
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


class _QueueWriter:
    """worker 스레드의 print() 출력을 GUI 로그 큐로 넘긴다."""

    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", s))

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.out_dir = None

        root.title("KrasFill — 일사편리 자동 기입")
        root.geometry("760x560")
        root.minsize(560, 400)

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="대상 폴더").pack(side="left")
        self.folder_var = tk.StringVar()
        self.ent_folder = ttk.Entry(top, textvariable=self.folder_var)
        self.ent_folder.pack(side="left", fill="x", expand=True, padx=6)
        self.btn_browse = ttk.Button(top, text="찾아보기…", command=self.browse)
        self.btn_browse.pack(side="left")

        opts = ttk.Frame(root, padding=(10, 0, 10, 6))
        opts.pack(fill="x")
        self.dry_var = tk.BooleanVar(value=False)
        self.chk_dry = ttk.Checkbutton(
            opts, text="대조만 (기입 없이 차이만 보고, dry-run)", variable=self.dry_var)
        self.chk_dry.pack(side="left")

        btns = ttk.Frame(root, padding=(10, 0, 10, 6))
        btns.pack(fill="x")
        self.btn_start = ttk.Button(btns, text="▶ 시작", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="■ 중지", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_open = ttk.Button(btns, text="폴더 열기", command=self.open_out,
                                   state="disabled")
        self.btn_open.pack(side="right")

        prog = ttk.Frame(root, padding=(10, 0, 10, 6))
        prog.pack(fill="x")
        self.bar = ttk.Progressbar(prog, mode="determinate")
        self.bar.pack(fill="x")
        self.status_var = tk.StringVar(value="대기 중")
        ttk.Label(prog, textvariable=self.status_var).pack(anchor="w", pady=(4, 0))

        self.log = scrolledtext.ScrolledText(root, wrap="word", state="disabled",
                                             font=("Malgun Gothic", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        root.after(100, self.poll_queue)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- UI 동작 ----------
    def browse(self):
        d = filedialog.askdirectory(title="워크북(.xlsx)이 들어있는 폴더 선택")
        if d:
            self.folder_var.set(os.path.normpath(d))

    def start(self):
        folder = self.folder_var.get().strip().strip('"')
        if not folder or not Path(folder).is_dir():
            messagebox.showwarning("KrasFill", "먼저 대상 폴더를 지정하세요.")
            return
        self.out_dir = folder  # 원본에 바로 기입하므로 '폴더 열기'는 대상 폴더
        self.stop_event.clear()
        self.bar["value"] = 0
        self.status_var.set("준비 중…")
        self._clear_log()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._worker, args=(folder, self.dry_var.get()), daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
        self.status_var.set("중지 요청됨 — 현재 파일까지 마치고 멈춥니다")

    def open_out(self):
        if self.out_dir and Path(self.out_dir).is_dir():
            os.startfile(self.out_dir)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("KrasFill", "작업이 진행 중입니다. 종료할까요?"):
                return
            self.stop_event.set()
        self.root.destroy()

    def _set_running(self, running):
        state = "disabled" if running else "normal"
        for w in (self.btn_start, self.btn_browse, self.ent_folder, self.chk_dry):
            w.configure(state=state)
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _append_log(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.configure(state="disabled")

    def poll_queue(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "total":
                    self.bar.configure(maximum=payload, value=0)
                elif kind == "progress":
                    i, total, name = payload
                    self.bar["value"] = i - 1
                    self.status_var.set(f"{i}/{total} 처리 중: {name}")
                elif kind == "file_done":
                    self.bar["value"] = payload
                elif kind == "done":
                    ok, fail, note = payload
                    self.bar["value"] = self.bar["maximum"]
                    self.status_var.set(note)
                    self._set_running(False)
                    if not self.dry_var.get() and ok:
                        self.btn_open.configure(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    # ---------- worker (별도 스레드) ----------
    def _worker(self, folder, dry_run):
        q = self.q
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _QueueWriter(q)
        com_init = False
        try:
            import pythoncom
            pythoncom.CoInitialize()  # Excel COM은 스레드별 초기화 필요
            com_init = True

            import main as core
            from fill_excel import ExcelFiller

            files = core.collect_files([folder])
            if not files:
                q.put(("done", (0, 0, "폴더에 처리할 .xlsx가 없습니다.")))
                return
            q.put(("total", len(files)))

            filler = ExcelFiller()
            ok = fail = 0
            stopped = False
            try:
                for i, src in enumerate(files, 1):
                    if self.stop_event.is_set():
                        stopped = True
                        print("\n[중지] 사용자 요청으로 중단")
                        break
                    q.put(("progress", (i, len(files), src.name)))
                    print(f"\n[{i}/{len(files)}] {src.name}")
                    try:
                        result = core.process_file(filler, src, None, dry_run)
                        if result is None:
                            fail += 1
                        else:
                            ok += 1
                    except Exception as e:
                        fail += 1
                        print(f"  [오류] {e}")
                        traceback.print_exc()
                    q.put(("file_done", i))
            finally:
                filler.close()

            print(f"\n===== 총 {len(files)}건: 성공 {ok}, 실패 {fail} =====")
            if not dry_run and ok:
                print("원본 워크북에 직접 기입 완료")
            note = "중지됨" if stopped else "완료"
            q.put(("done", (ok, fail, f"{note} — 성공 {ok}, 실패 {fail}")))
        except Exception as e:
            print(f"[오류] {e}")
            traceback.print_exc()
            q.put(("done", (0, 1, f"오류: {e}")))
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            if com_init:
                import pythoncom
                pythoncom.CoUninitialize()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
