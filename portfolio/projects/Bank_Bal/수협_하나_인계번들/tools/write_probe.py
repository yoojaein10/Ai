"""쓰기 능력 프로브 — 열린 담보폼의 빈 텍스트칸에 시험값을 쓰고 되읽은 뒤 복원한다.

Medium 세션에선 UIPI 로 막히고(EM_REPLACESEL 권한없음), 관리자(High)로 실행하면 통과한다.
데이터는 안 남긴다(원래값으로 복원). 은행 무관.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bankon.ui import driver  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def _integrity() -> str:
    from ctypes import wintypes as wt, POINTER, c_void_p, c_ubyte
    k = ctypes.windll.kernel32; a = ctypes.windll.advapi32
    a.GetSidSubAuthorityCount.restype = POINTER(c_ubyte); a.GetSidSubAuthorityCount.argtypes = [c_void_p]
    a.GetSidSubAuthority.restype = POINTER(wt.DWORD); a.GetSidSubAuthority.argtypes = [c_void_p, wt.DWORD]
    hp = k.OpenProcess(0x1000, False, os.getpid()); htok = wt.HANDLE()
    a.OpenProcessToken(hp, 0x8, ctypes.byref(htok)); sz = wt.DWORD()
    a.GetTokenInformation(htok, 25, None, 0, ctypes.byref(sz))
    buf = ctypes.create_string_buffer(sz.value)
    a.GetTokenInformation(htok, 25, buf, sz.value, ctypes.byref(sz))
    psid = ctypes.cast(buf, POINTER(c_void_p))[0]; cnt = a.GetSidSubAuthorityCount(psid)[0]
    rid = a.GetSidSubAuthority(psid, cnt - 1)[0]
    return {0x2000: "Medium(일반)", 0x3000: "High(관리자)"}.get(rid, hex(rid))


def main() -> int:
    print("이 프로세스 권한:", _integrity())
    forms = driver.find_windows(driver.FORM_CLASS_PREFIX)
    if not forms:
        print("담보폼 안 열림"); return 1
    form = forms[0]
    print("대상 폼:", form.class_name, hex(form.handle))
    edits = [c for c in driver.descendants(form.handle)
             if "TcxDBTextEdit" in (c.element_info.class_name or "")]
    target, orig = None, None
    for c in edits:
        v = driver.read(c)
        if not (v or "").strip():
            target, orig = c, v; break
    if target is None:
        target, orig = edits[-1], driver.read(edits[-1])
    print(f"테스트칸 {hex(target.handle)} 원래값={orig!r}")
    try:
        driver.set_text(target, "ZZ쓰기확인")
        print("✅ 쓰기 성공! 되읽기 =", repr(driver.read(target)))
        ok = True
    except Exception as e:
        print("❌ 쓰기 실패:", type(e).__name__, str(e)[:80]); ok = False
    try:
        driver.editable(target).set_edit_text(orig or "")
        print("복원 완료 =", repr(driver.read(target)))
    except Exception as e:
        print("복원 오류:", str(e)[:50])
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
