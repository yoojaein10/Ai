"""
의뢰서 미리보기 창 → 캡쳐 + 텍스트 추출 테스트
실행 전: bank24.exe에서 의뢰서 미리보기 창이 열린 상태여야 함
"""
import time
import re
from pathlib import Path

import pyautogui
from PIL import Image, ImageGrab
from pywinauto import Application, Desktop
from pywinauto.findwindows import find_windows

OUTPUT_DIR = Path(r"D:\AI\Claude\BankAuto\output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ── 1. 미리보기 창 찾기 ────────────────────────────────────────────────────────
def find_preview_window():
    print("[1] 미리보기 창 탐색...")
    wins = Desktop(backend="win32").windows()
    for w in wins:
        try:
            title = w.window_text()
            cls   = w.class_name()
            if "미리보기" in title or "Preview" in title.lower():
                print(f"    발견: title='{title}', class='{cls}'")
                return w
        except Exception:
            pass

    # 타이틀 못 찾으면 알려진 클래스로 재시도
    for cls_name in ("TfrmPreview", "TPreviewForm", "TfrxPreview", "TRVPreview"):
        try:
            handles = find_windows(class_name=cls_name)
            if handles:
                app = Application(backend="win32").connect(handle=handles[0])
                win = app.window(handle=handles[0])
                print(f"    발견 (class): class='{cls_name}'")
                return win
        except Exception:
            pass

    print("    !! 미리보기 창을 찾지 못했습니다")
    return None


# ── 2. 창 전체 컨트롤 덤프 (텍스트 추출 시도) ───────────────────────────────
def dump_controls(win):
    print("\n[2] 컨트롤 텍스트 덤프...")
    texts = []
    try:
        for ctrl in win.descendants():
            try:
                t = ctrl.window_text().strip()
                c = ctrl.class_name()
                if t and len(t) > 1:
                    texts.append((c, t))
                    print(f"    [{c}] {t[:80]}")
            except Exception:
                pass
    except Exception as e:
        print(f"    descendants 실패: {e}")
    return texts


# ── 3. 창 영역 캡쳐 (상단 + 스크롤 후 하단) ─────────────────────────────────
def capture_window(win) -> Image.Image:
    print("\n[3] 창 캡쳐 (상단 + 하단)...")
    try:
        r = win.rectangle()
        print(f"    창 rect: {r.left},{r.top},{r.right},{r.bottom}")

        # 상단 캡쳐
        win.set_focus()
        time.sleep(0.3)
        img_top = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
        img_top.save(OUTPUT_DIR / "preview_capture.png")
        print(f"    상단 캡쳐 완료")

        # Page Down x2 으로 스크롤 후 캡쳐
        cx = (r.left + r.right) // 2
        cy = (r.top + r.bottom) // 2
        pyautogui.click(cx, cy)
        time.sleep(0.2)

        captures = [img_top]
        for i in range(4):
            pyautogui.press("pagedown")
            time.sleep(0.8)
            img_s = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom))
            img_s.save(OUTPUT_DIR / f"preview_capture_s{i+1}.png")
            captures.append(img_s)
            print(f"    스크롤 {i+1} 캡쳐 완료")

        # 맨 위로 복귀
        pyautogui.hotkey("ctrl", "home")
        time.sleep(0.3)

        # 세로로 합치기
        total_h = sum(img.height for img in captures)
        combined = Image.new("RGB", (img_top.width, total_h))
        y_offset = 0
        for img in captures:
            combined.paste(img, (0, y_offset))
            y_offset += img.height
        combined.save(OUTPUT_DIR / "preview_capture_full.png")
        print(f"    합친 이미지: {combined.width}x{combined.height} ({len(captures)}장)")
        return combined

    except Exception as e:
        print(f"    캡쳐 실패: {e}")
        return None


# ── 4. 흰 문서 영역 크롭 + 전처리 ──────────────────────────────────────────
def crop_document(img: Image.Image) -> Image.Image:
    print("\n[4] 문서 영역 크롭 + 전처리...")
    try:
        import numpy as np
        import cv2
        from PIL import ImageFilter, ImageEnhance

        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            print(f"    문서 영역: x={x}, y={y}, w={w}, h={h}")
            cropped = img.crop((x, y, x + w, y + h))

            # 전처리: 2배 확대 + 샤프닝 + 대비 강화
            new_w, new_h = cropped.width * 2, cropped.height * 2
            cropped = cropped.resize((new_w, new_h), Image.LANCZOS)
            cropped = cropped.filter(ImageFilter.SHARPEN)
            cropped = ImageEnhance.Contrast(cropped).enhance(1.5)
            print(f"    전처리 완료: {new_w}x{new_h}, 샤프닝+대비강화")

            out = OUTPUT_DIR / "preview_doc_crop.png"
            cropped.save(out)
            print(f"    저장: {out}")
            return cropped
    except Exception as e:
        print(f"    크롭 실패: {e}")
    return img


# ── 5. OCR 시도 (easyocr 우선, Windows OCR fallback) ─────────────────────────
def try_ocr(img: Image.Image) -> str:
    print("\n[5] OCR 시도 (easyocr)...")

    # 5-A: easyocr (한글 정확도 높음)
    try:
        import easyocr
        import numpy as np
        import sys, io as _io
        print("    easyocr 모델 로딩...")
        # verbose=False: 프로그레스바 출력 억제 (cp949 인코딩 에러 방지)
        reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        result = reader.readtext(np.array(img), detail=0, paragraph=False)
        text = "\n".join(result)
        if text.strip():
            print(f"    easyocr 성공 ({len(result)}줄)")
            return text
        print("    easyocr 빈 결과")
    except ImportError:
        print("    easyocr 없음")
    except Exception as e:
        print(f"    easyocr 실패: {e}")

    print("    Windows OCR fallback...")
    try:
        import asyncio
        import io
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.globalization import Language
        from winsdk.windows.graphics.imaging import (
            SoftwareBitmap, BitmapDecoder, BitmapPixelFormat
        )
        from winsdk.windows.storage.streams import InMemoryRandomAccessStream

        async def _run_ocr(pil_img: Image.Image) -> str:
            from winsdk.windows.storage import StorageFile
            from winsdk.windows.graphics.imaging import BitmapAlphaMode

            # 파일로 저장 후 Windows Storage API로 로드 (절대경로 필요)
            tmp_path = OUTPUT_DIR / "_ocr_tmp.png"
            pil_img.convert("RGBA").save(str(tmp_path), format="PNG")

            storage_file = await StorageFile.get_file_from_path_async(str(tmp_path))
            stream = await storage_file.open_async(0)  # FileAccessMode.Read
            decoder = await BitmapDecoder.create_async(stream)
            soft_bmp = await decoder.get_software_bitmap_async()

            # BGRA8 변환
            converted = SoftwareBitmap.convert(
                soft_bmp, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
            )
            if converted is not None:
                soft_bmp = converted

            # 한국어 OCR 엔진
            lang = Language("ko")
            if not OcrEngine.is_language_supported(lang):
                print("    ko 언어 미지원 — en 시도")
                lang = Language("en")
            engine = OcrEngine.try_create_from_language(lang)
            if engine is None:
                return ""

            result = await engine.recognize_async(soft_bmp)
            lines = [line.text for line in result.lines]
            return "\n".join(lines)

        text = asyncio.run(_run_ocr(img))
        if text:
            print(f"    Windows OCR 성공 ({len(text.splitlines())}줄)")
            return text
        print("    Windows OCR 빈 결과")
        return ""

    except ImportError:
        print("    winsdk 없음")
    except Exception as e:
        print(f"    Windows OCR 실패: {e}")

    # fallback: easyocr
    try:
        import easyocr
        import numpy as np
        print("    easyocr 시도...")
        reader = easyocr.Reader(["ko", "en"], gpu=False)
        result = reader.readtext(np.array(img), detail=0)
        return "\n".join(result)
    except Exception:
        pass

    print("    OCR 엔진 없음 - 이미지만 저장됨")
    return ""


# ── 5.5 OCR 숫자 후처리 ───────────────────────────────────────────────────────
def fix_ocr_numbers(text: str) -> str:
    """숫자처럼 보이는 영역에서 흔한 OCR 오인식 교정"""
    import re
    # 숫자가 있는 줄에서만 치환 (한글 줄은 건드리지 않음)
    lines = text.splitlines()
    fixed = []
    for line in lines:
        # 숫자/특수문자 위주 줄이면 교정 적용
        non_alpha = re.sub(r'[0-9\-\(\)\s]', '', line)
        if len(non_alpha) < len(line) * 0.5:  # 절반 이상이 숫자/기호
            line = line.replace('D', '0').replace('U', '0').replace('O', '0')
            line = line.replace('E', '6').replace('G', '6').replace('B', '8')
            line = line.replace('I', '1').replace('l', '1').replace('|', '1')
            line = line.replace('S', '5').replace('Z', '2')
        fixed.append(line)
    return "\n".join(fixed)


# ── 6. 필드 파싱 ──────────────────────────────────────────────────────────────
def parse_fields(text: str) -> dict:
    print("\n[6] 필드 파싱...")
    text = fix_ocr_numbers(text)
    print("--- OCR 결과 ---")
    print(text[:600])
    print("----------------")

    # 숫자/패턴 기반 파싱 (OCR 한글 깨짐에 강함)
    lines = text.splitlines()

    def next_nonempty_lines(keyword, n=3):
        """keyword가 포함된 줄 다음 n개 비어있지 않은 줄 반환"""
        for i, line in enumerate(lines):
            if keyword in line:
                collected = []
                for j in range(i+1, min(i+10, len(lines))):
                    l = lines[j].strip()
                    if l and not re.match(r'^[가-힣]{2,5}$', l):  # 단순 라벨 제외
                        collected.append(l)
                    if len(collected) >= n:
                        break
                return " ".join(collected)
        return ""

    # 1차: 라벨+같은줄 패턴
    inline_patterns = {
        "의뢰번호":   r"(?:의뢰|의회)[^\d:]*:?\s*(\d{14,20})",
    }
    # 2차: 라벨 다음줄 패턴
    nextline_patterns = {
        "감정서번호":   (r"감정\s*서번호",        r"[\d\-\s]{10,20}"),
        "신청번호":     (r"신청번호",              r"\d{8,12}"),
        "채무자명":     (r"신청인명",              r"[가-힣]{2,5}"),
        "채무자전화":   (r"전화번호",              r"0\d{1,2}-\d{3,4}-\d{4}"),
        "산출수수료":   (r"산출수수료",            r"[\d,]{4,10}"),
        "담당자명":     (r"담당\s*자명",            r"[가-힣]{2,4}"),
        "담당자연락처": (r"담당\s*자.{0,3}락처",   r"0\d{1,2}-\d{3,4}-\d{4}"),
        "상품명":       (r"상품명",                r"[가-힣A-Za-z]{4,20}"),
        "소유자명":     (r"[성섬]\s{1,}명",        r"[가-힣]{2,5}"),             # 성→섬 오인식 허용
    }

    result = {}

    for field, pattern in inline_patterns.items():
        m = re.search(pattern, text)
        val = re.sub(r'\s+', '', m.group(1)).strip() if m else ""
        result[field] = val
        print(f"    {field}: {result[field] or '(없음)'}")

    for field, (label, val_pattern) in nextline_patterns.items():
        result[field] = ""
        for i, line in enumerate(lines):
            if re.search(label, line):
                # 같은 줄: 라벨 텍스트 제거 후 값 찾기 (라벨 자체가 매칭되는 것 방지)
                label_removed = re.sub(label, '', line).strip()
                if label_removed:
                    m = re.search(val_pattern, label_removed)
                    if m:
                        result[field] = re.sub(r'\s+', '', m.group(0)).strip()
                        break
                # 다음 몇 줄 체크
                for j in range(i+1, min(i+5, len(lines))):
                    m = re.search(val_pattern, lines[j])
                    if m:
                        val = re.sub(r'\s+', '', m.group(0)).strip()
                        # 감정서번호: 다음 줄이 숫자만 있으면 합치기 ("111 1" → "1111")
                        if field == "감정서번호" and j+1 < len(lines):
                            nxt = lines[j+1].strip()
                            if re.match(r'^\d+$', nxt):
                                val = val + nxt
                        result[field] = val
                        break
                break
        print(f"    {field}: {result[field] or '(없음)'}")

    # 의뢰기관: 라벨 다음줄 (OCR이 의리기관/의로기관으로 읽음)
    result["의뢰기관"] = ""
    for kw in ["의뢰기관", "의리기관", "의로기관"]:
        val = next_nonempty_lines(kw, n=1)
        if val:
            result["의뢰기관"] = val
            break
    print(f"    의뢰기관: {result['의뢰기관'] or '(없음)'}")

    # 주소: 다음 줄 수집 방식
    세부 = next_nonempty_lines("세부주소", n=4)
    전체 = next_nonempty_lines("전체주소", n=1)
    if not 전체:
        전체 = next_nonempty_lines("전체 주소", n=1)
    # 세부주소에 전체주소가 합쳐지지 않도록 정리
    if 전체 and 전체 in 세부:
        세부 = 세부.replace(전체, "").strip()
    result["세부주소"] = 세부
    result["전체주소"] = 전체
    print(f"    세부주소: {세부}")
    print(f"    전체주소: {전체}")

    # fallback: 의뢰번호 14자리 숫자
    if not result.get("의뢰번호"):
        m = re.search(r"\b(\d{14,20})\b", text)
        if m:
            result["의뢰번호"] = m.group(1)
            print(f"    의뢰번호(fallback): {result['의뢰번호']}")

    # fallback: 감정서번호 (공백 포함 패턴도 허용: "01-2604-3-111 1")
    if not result.get("감정서번호"):
        m = re.search(r"\b(\d{2}-\d{4}-\d+[-\s]\d+)\b", text)
        if m:
            val = re.sub(r'\s+', '', m.group(1))  # 공백 제거
            result["감정서번호"] = val
            print(f"    감정서번호(fallback): {val}")

    # fallback: 전화번호
    if not result.get("전화번호"):
        m = re.search(r"\b(01[016789]-\d{3,4}-\d{4})\b", text)
        if m:
            result["전화번호"] = m.group(1)
            print(f"    전화번호(fallback): {result['전화번호']}")

    # fallback: 신청번호
    if not result.get("신청번호"):
        for m in re.finditer(r"\b(\d{10})\b", text):
            val = m.group(1)
            if val != result.get("의뢰번호", ""):
                result["신청번호"] = val
                print(f"    신청번호(fallback): {val}")
                break

    # fallback: 산출수수료
    if not result.get("산출수수료"):
        for m in re.finditer(r"\b(\d{3,3}[,\d]*\d{3})\b", text):
            try:
                val = int(m.group(1).replace(",", ""))
                if 10000 <= val <= 9999999:
                    result["산출수수료"] = m.group(1)
                    print(f"    산출수수료(fallback): {m.group(1)}")
                    break
            except Exception:
                pass

    return result


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("의뢰서 미리보기 파싱 테스트")
    print("=" * 60)

    win = find_preview_window()
    if not win:
        print("\n>> 미리보기 창을 열고 다시 실행하세요")
        return

    # 컨트롤에서 직접 텍스트 추출 시도
    ctrl_texts = dump_controls(win)

    # 창 캡쳐 (상단 + 스크롤)
    img = capture_window(win)
    if img is None:
        return

    # 각 캡쳐 이미지별로 OCR 후 텍스트 합치기
    all_texts = []
    for png in sorted(OUTPUT_DIR.glob("preview_capture*.png")):
        if "full" in png.name:
            continue
        pil = Image.open(png)
        doc = crop_document(pil)
        t = try_ocr(doc)
        if t.strip():
            all_texts.append(t)

    ocr_text = "\n".join(all_texts)

    if ocr_text:
        # 결과 저장
        out_txt = OUTPUT_DIR / "preview_ocr_result.txt"
        out_txt.write_text(ocr_text, encoding="utf-8")
        print(f"\n    OCR 결과 저장: {out_txt}")

        # 필드 파싱
        fields = parse_fields(ocr_text)
        print(f"\n파싱 결과: {fields}")
    else:
        # OCR 없어도 컨트롤 텍스트로 파싱 시도
        if ctrl_texts:
            combined = "\n".join(t for _, t in ctrl_texts)
            fields = parse_fields(combined)
            print(f"\n파싱 결과 (컨트롤 기반): {fields}")

    print("\n완료.")


if __name__ == "__main__":
    main()
