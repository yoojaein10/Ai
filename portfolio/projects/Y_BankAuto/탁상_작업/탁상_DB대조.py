# -*- coding: utf-8 -*-
"""
탁상자문의뢰서(우리은행) PDF 파싱 ↔ APW_TS_Master DB 대조 스크립트
== 주인님 PC(사내망)에서 실행하세요. (이 폴더의 ts_woori.py 필요) ==

흐름:
  1) 탁상 폴더의 PDF를 fitz(PyMuPDF)로 텍스트 추출 → ts_woori.parse_woori_ts 로 파싱
  2) 파싱된 의뢰번호(T...) / 자문번호(01-...)를 각각 MasterID 후보로
     APW_TS_Master 를 조회(SELECT *)
  3) 어느 후보가 MasterID와 매칭되는지, DB 실제값 전체를 엑셀로 덤프
     → PDF 파싱값과 DB값을 한눈에 대조

사용법:
  python 탁상_DB대조.py                 # 기본: 탁상 폴더 전체
  python 탁상_DB대조.py --pdf-dir "경로"
  python 탁상_DB대조.py --dump-text 1   # 1.pdf 추출 텍스트만 출력(파싱 점검용)

DB 접속정보는 C:\Bank24Extractor\settings.ini [database] 를 우선 사용,
없으면 아래 DEFAULT_DB 사용.
"""
import os, sys, re, argparse, configparser, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ts_woori import parse_woori_ts, FIELDS

DEFAULT_PDF_DIR = r"D:\AI\Claude\Y_BankAuto\탁상"
SETTINGS_INI = r"C:\Bank24Extractor\settings.ini"
DEFAULT_DB = {
    "server": '192.0.2.10', "port": "1433", "database": "apworksdw",
    "username": "dh", "password": 'REDACTED_CONFIGURE_LOCALLY',
    "driver": "ODBC Driver 17 for SQL Server", "trust_server_certificate": "true",
}
TABLE = "APW_TS_Master"

# 우리은행 PDF 번호 (필요시 조정). 빈 리스트면 폴더 전체 스캔.
WOORI_FILES = []  # 예: [1,3,6,...]  비우면 전체


# ---------------- 텍스트 추출 ----------------
def extract_text(pdf_path):
    """fitz words를 좌표로 재구성해 'pdftotext -layout' 유사 라인 생성."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return _extract_with_pdftotext(pdf_path)
    doc = fitz.open(pdf_path)
    out_lines = []
    for page in doc:
        words = page.get_text("words")  # (x0,y0,x1,y1, text, block,line,word)
        if not words:
            continue
        # y 기준 라인 그룹화 (tolerance)
        words.sort(key=lambda w: (round(w[1] / 3.0), w[0]))
        groups = {}
        for w in words:
            key = round(w[1] / 3.0)
            groups.setdefault(key, []).append(w)
        for key in sorted(groups):
            ws = sorted(groups[key], key=lambda w: w[0])
            s, prev_x1 = "", None
            for w in ws:
                x0, x1, txt = w[0], w[2], w[4]
                cw = (x1 - x0) / max(len(txt), 1)
                if prev_x1 is None:
                    s = txt
                else:
                    gap = x0 - prev_x1
                    nsp = max(1, int(round(gap / max(cw, 3.0))))
                    s += " " * nsp + txt
                prev_x1 = x1
            out_lines.append(s)
    doc.close()
    return "\n".join(out_lines)


def _extract_with_pdftotext(pdf_path):
    import subprocess
    return subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                          capture_output=True).stdout.decode("utf-8", "ignore")


# ---------------- DB ----------------
def load_db_cfg():
    cfg = configparser.ConfigParser()
    db = dict(DEFAULT_DB)
    if os.path.exists(SETTINGS_INI):
        cfg.read(SETTINGS_INI, encoding="utf-8")
        if cfg.has_section("database"):
            for k in db:
                if cfg.has_option("database", k):
                    db[k] = cfg.get("database", k)
    return db


def connect(db):
    import pyodbc
    cs = (
        f"DRIVER={{{db['driver']}}};SERVER={db['server']},{db['port']};"
        f"DATABASE={db['database']};UID={db['username']};PWD={db['password']};"
    )
    if str(db.get("trust_server_certificate", "true")).lower() in ("1", "true", "yes"):
        cs += "TrustServerCertificate=yes;"
    return pyodbc.connect(cs, timeout=10)


def query_master(cur, master_id):
    """MasterID = master_id 행 전체를 [(col,val),...] 리스트로. 없으면 None."""
    cur.execute(f"SELECT * FROM {TABLE} WHERE MasterID = ?", (master_id,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return list(zip(cols, [("" if v is None else str(v)) for v in row]))


# ---------------- 메인 ----------------
def collect_pdfs(pdf_dir):
    nums = WOORI_FILES or sorted(
        int(m.group(1)) for f in os.listdir(pdf_dir)
        if (m := re.match(r"(\d+)\.pdf$", f, re.I))
    )
    return [(n, os.path.join(pdf_dir, f"{n}.pdf")) for n in nums
            if os.path.exists(os.path.join(pdf_dir, f"{n}.pdf"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=DEFAULT_PDF_DIR)
    ap.add_argument("--dump-text", type=int, default=0, help="해당 번호 PDF 텍스트만 출력")
    ap.add_argument("--no-db", action="store_true", help="DB 조회 생략(파싱만)")
    args = ap.parse_args()

    if args.dump_text:
        p = os.path.join(args.pdf_dir, f"{args.dump_text}.pdf")
        print(extract_text(p))
        return

    pdfs = collect_pdfs(args.pdf_dir)
    print(f"[*] 대상 PDF {len(pdfs)}건  /  DB조회={'생략' if args.no_db else 'ON'}")

    cur = conn = None
    if not args.no_db:
        try:
            conn = connect(load_db_cfg())
            cur = conn.cursor()
            print("[*] DB 접속 성공")
        except Exception as e:
            print(f"[!] DB 접속 실패 → 파싱만 진행: {e}")

    rows = []          # 파싱 결과
    db_dump = []       # 매칭된 DB 행
    schema_printed = False
    for n, path in pdfs:
        try:
            parsed = parse_woori_ts(extract_text(path))
        except Exception as e:
            print(f"  {n}.pdf 파싱오류: {e}")
            continue
        rec = {"파일": f"{n}.pdf", **{k: parsed.get(k, "") for k in FIELDS}}
        matched_key, db_row = "", None
        if cur:
            for cand_label in ("의뢰번호", "자문번호"):
                cand = parsed.get(cand_label, "")
                if not cand:
                    continue
                try:
                    db_row = query_master(cur, cand)
                except Exception as e:
                    print(f"  {n}.pdf DB조회오류({cand_label}={cand}): {e}")
                    db_row = None
                if db_row:
                    matched_key = cand_label
                    if not schema_printed:
                        print("  [APW_TS_Master 컬럼]", ", ".join(c for c, _ in db_row))
                        schema_printed = True
                    break
        rec["DB매칭키"] = matched_key
        rows.append(rec)
        print(f"  {n}.pdf  의뢰={parsed.get('의뢰번호')}  자문={parsed.get('자문번호')}  "
              f"→ 매칭={matched_key or '없음'}")
        if db_row:
            d = {"파일": f"{n}.pdf", "매칭키": matched_key}
            d.update(dict(db_row))
            db_dump.append(d)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_xlsx = os.path.join(HERE, f"탁상_DB대조_{ts}.xlsx")
    try:
        _write_xlsx(out_xlsx, rows, db_dump)
        print(f"[완료] 엑셀 저장: {out_xlsx}")
    except Exception as e:
        out_csv = os.path.join(HERE, f"탁상_DB대조_{ts}.csv")
        _write_csv(out_csv, rows)
        print(f"[완료] (엑셀 실패:{e}) CSV 저장: {out_csv}")

    if conn:
        conn.close()


def _write_xlsx(path, rows, db_dump):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "파싱결과"
    cols = ["파일"] + [k for k in FIELDS if k != "문서종류"] + ["DB매칭키"]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c, "") for c in cols])
    # DB 덤프 시트
    ws2 = wb.create_sheet("DB원본(APW_TS_Master)")
    if db_dump:
        allcols = ["파일", "매칭키"]
        for d in db_dump:
            for k in d:
                if k not in allcols:
                    allcols.append(k)
        ws2.append(allcols)
        for d in db_dump:
            ws2.append([d.get(c, "") for c in allcols])
    else:
        ws2.append(["(매칭된 DB 행 없음 — MasterID 후보가 맞는지 확인 필요)"])
    wb.save(path)


def _write_csv(path, rows):
    import csv
    cols = ["파일"] + [k for k in FIELDS if k != "문서종류"] + ["DB매칭키"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


if __name__ == "__main__":
    main()
