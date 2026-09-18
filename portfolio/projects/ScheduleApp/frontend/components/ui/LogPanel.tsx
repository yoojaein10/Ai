"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface LogEntry {
  time: string;
  type: "error" | "warn" | "info";
  msg: string;
}

export default function LogPanel() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [open, setOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const addLog = useCallback((type: LogEntry["type"], ...args: unknown[]) => {
    const msg = args.map((a) => {
      if (typeof a === "string") return a;
      try { return JSON.stringify(a, null, 2); } catch { return String(a); }
    }).join(" ");
    const time = new Date().toLocaleTimeString("ko-KR");
    setLogs((prev) => [...prev.slice(-199), { time, type, msg }]);
  }, []);

  useEffect(() => {
    const origError = console.error.bind(console);
    const origWarn = console.warn.bind(console);
    const origLog = console.log.bind(console);

    console.error = (...args) => { origError(...args); addLog("error", ...args); };
    console.warn = (...args) => { origWarn(...args); addLog("warn", ...args); };
    console.log = (...args) => { origLog(...args); addLog("info", ...args); };

    const onUnhandled = (e: PromiseRejectionEvent) => addLog("error", "[Unhandled]", e.reason);
    const onError = (e: ErrorEvent) => addLog("error", "[JS Error]", e.message, e.filename, `line ${e.lineno}`);

    window.addEventListener("unhandledrejection", onUnhandled);
    window.addEventListener("error", onError);

    return () => {
      console.error = origError;
      console.warn = origWarn;
      console.log = origLog;
      window.removeEventListener("unhandledrejection", onUnhandled);
      window.removeEventListener("error", onError);
    };
  }, [addLog]);

  // textarea 자동 스크롤
  useEffect(() => {
    if (open && textareaRef.current) {
      textareaRef.current.scrollTop = textareaRef.current.scrollHeight;
    }
  }, [logs, open]);

  const text = logs.map((l) => `[${l.time}][${l.type.toUpperCase()}] ${l.msg}`).join("\n");
  const errorCount = logs.filter((l) => l.type === "error").length;

  return (
    <div className="fixed bottom-4 left-4 z-[9999] flex flex-col items-start gap-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono shadow-lg border"
        style={{
          background: errorCount > 0 ? "#ff4444" : "#1e1e1e",
          color: "#fff",
          borderColor: errorCount > 0 ? "#ff2222" : "#444",
        }}
      >
        <span>🖥 로그</span>
        {errorCount > 0 && <span className="bg-white text-red-600 rounded-full px-1.5 text-[10px] font-bold">{errorCount}</span>}
      </button>

      {open && (
        <div className="flex flex-col gap-1 w-[480px]" style={{ maxHeight: "340px" }}>
          <div className="flex gap-1">
            <button
              onClick={() => {
                if (textareaRef.current) {
                  textareaRef.current.select();
                  document.execCommand("copy");
                }
              }}
              className="text-[10px] px-2 py-0.5 rounded bg-[#333] text-white border border-[#555] hover:bg-[#444]"
            >
              전체 복사
            </button>
            <button
              onClick={() => setLogs([])}
              className="text-[10px] px-2 py-0.5 rounded bg-[#333] text-white border border-[#555] hover:bg-[#444]"
            >
              지우기
            </button>
          </div>
          <textarea
            ref={textareaRef}
            readOnly
            value={text}
            className="w-full rounded text-[11px] font-mono p-2 resize-none border border-[#444]"
            style={{ height: "300px", background: "#1e1e1e", color: "#d4d4d4" }}
          />
        </div>
      )}
    </div>
  );
}
