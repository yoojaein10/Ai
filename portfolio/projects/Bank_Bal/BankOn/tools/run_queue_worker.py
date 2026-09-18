"""Apw_YJI_Send 큐 워커 — 발송 요청이 들어온 신한·국민·기업 감정서를 Bank24 에 자동 작성한다. (gui_bankon.py 가 import 해서 씀)

    Apw_YJI_Send(발송팀 운영 큐, **읽기만**) → 은행 판별(apw_masterex.CustName) → 신한/국민 담보 건
    → run_shinhan_full.py / run_kb_full.py 한 건 실행(작성·저장·PDF·현장조사서, 발송은 안 함)
    → 결과를 dbo.Apw_YJI_BankAuto 에 기록(Send_Seq 당 1행, 상태 처리중→완료/실패/제외)

모드 (기본은 계획만 — 화면·DB 어느 쪽도 건드리지 않는다):
    (없음)       후보 목록만 출력
    --dry        후보마다 러너를 --dry 로 돌린다(화면 열어 계획만, 저장·PDF 없음). --record 면 이력도 남김
    --live       ★실서버 쓰기★ 실제 입력·저장·PDF등록 + 이력 기록. 관리자 권한 필수
    --once       한 바퀴만 돌고 종료(기본은 --interval 초마다 반복)
    --interval N 반복 주기(초, 기본 600)          --since YYYY-MM-DD  이 날짜 이후 요청만(기본 오늘)
    --max N      한 바퀴에 최대 N건               --no-pdf            PDF등록 건너뜀
    --seq N      특정 Send.Seq 한 건만(디버그)
정지: reports/STOP_WORKER 파일을 만들면 현재 건을 마치고 멈춘다.

    Start-Process python -ArgumentList '"...\\tools\\run_queue_worker.py" --live' -Verb RunAs -WindowStyle Hidden

안전:
  - 같은 감정서가 이미 완료/처리중이면 새 요청은 '제외'로만 기록(중복 저장 방지). 자동 재시도 없음.
  - .gam 이 아직 FTP 에 없으면(요청이 감정서 완성 전에 들어오기도 함 — 실측) 기록하지 않고 다음 바퀴로 미룬다.
  - 담보(감정서번호 업무구분 3)만 처리 — 러너가 작성 탭을 '담보'로 조회하기 때문. 나머지는 보류.
  - 캐시된 .gam 은 지우고 매번 새로 받는다(담당자가 의견서를 고쳐 재업로드하는 경우 실측 2026-08-26).
  - 러너 exit≠0(행 못 찾음·로그인 실패 등)이면 저장하지 않은 채 '실패' + 사유 기록.
  - 입력 거부 칸이 있어도 그 칸만 비운 채(콤보는 원래 값) 저장하고 계속 → '완료' + 비고 '입력 거부(빈칸 저장, 담당자 확인): 라벨=값'
    (사용자 결정 2026-09-03: 담당자가 한 번 더 보므로 건 전체를 실패로 돌리지 않는다. 종전엔 거부 1칸이라도 있으면 저장 안 하고 실패).
  - PDF(감정서·현장조사·국민 수수료/공부)를 전례 폴더에서 못 찾으면 그 PDF 등록만 건너뛰고 입력·저장은 해서 '완료' —
    비고에 'PDF 건너뜀(종류)' 표시, 사람이 확인해 Bank24 에서 수동 등록(사용자 결정 2026-09-03).
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from bankon import paths as _paths          # noqa: E402
ROOT = _paths.APP_ROOT                       # exe 면 exe 폴더(.env·work·reports), 소스면 저장소 루트
_paths.ensure_dirs()
os.chdir(ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from bankon.config import load_config      # noqa: E402
from bankon.db import connect              # noqa: E402
from bankon.resolver import resolve_document  # noqa: E402

RUNNERS = {"신한": "run_shinhan_full", "국민": "run_kb_full", "기업": "run_ibk_full", "농협": "run_nh_full",
           "수협": "run_ssb_full", "하나": "run_hnb_full", "우리": "run_wrb_full", "새마을": "run_mgb_full"}   # tools/ 모듈명 — exe 는 `BankOn.exe --runner <모듈>` 로 자기 재호출
STOP_FILE = ROOT / "reports" / "STOP_WORKER"
SUPPORTED = {"신한": "신한은행", "국민": "국민은행", "기업": "기업은행", "농협": "농협은행",
             "수협": "수협", "하나": "하나은행", "우리": "우리은행", "새마을": "새마을금고"}
# 국민 2026-08-26 검증(450칸) · 기업 2026-09-01 발송완료 7건 대조+2706 LIVE · 농협 2026-09-07 이식(발송완료 5건 드라이런)
# 수협·하나·우리·새마을 2026-09-10 인계본 이식(작성 폼 매핑 라이브 대조만, 빈 폼 LIVE·현장조사서 정찰 미실시) — 전부 ini banks 에 넣어야 돈다
DAMBO_DOC = re.compile(r"^\d{2}-\d{4}-3-\d{4}$")   # 01-2608-3-2676 (업무구분 3=담보)


def python_exe() -> str:
    """러너를 띄울 python. exe(frozen)에서는 sys.executable 이 BankOn.exe 라 진짜 python 을 찾는다
    (BANKON_PYTHON 환경변수 → PATH 의 python → 설치 기본 경로)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for cand in (os.environ.get("BANKON_PYTHON"), shutil.which("python"),
                 str(Path.home() / "AppData/Local/Programs/Python/Python312/python.exe")):
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("python.exe 를 찾지 못했습니다(BANKON_PYTHON 환경변수로 지정).")


def bank_of(cust_name: str | None) -> str | None:
    name = cust_name or ""
    if "신한은행" in name:
        return "신한"
    if "국민은행" in name:
        return "국민"
    if "기업은행" in name:
        return "기업"
    if name.startswith("농협은행"):        # 농협은행(중앙회)만. 지역·품목농협('군자농협 …')은 폼 변형(수수료 할인 블록·현장조사서 비용 칸)이라 보류
        return "농협"
    # 아래 4개는 2026-09-10 인계본 이식. APW CustName 실측(2025~26 담보):
    #   하나 = 'KEB하나은행 …'·'㈜하나은행 …'·'하나은행 …'(그냥 '하나' 는 하나새마을금고·하나자산신탁 등이라 안 됨)
    #   우리 = '우리은행 여신업무센터장'·'(주)우리은행…'(우리새마을금고·우리신협은 '우리은행' 이 안 들어간다)
    #   수협 = 지역·업종수협('삼천포수협 북부지점장'·'경남정치망수협 …')이 대부분, 중앙 수협은행도 같은 폼(인계본: 수수료 규칙 동일)
    #   새마을 = '…새마을금고 이사장'
    if "하나은행" in name:
        return "하나"
    if "우리은행" in name:
        return "우리"
    if "새마을금고" in name:
        return "새마을"
    if "수협" in name or "수산업협동조합" in name:
        return "수협"
    return None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ── DB ─────────────────────────────────────────────────────────────
# 큐 Status 허용값 — 사용자 확정 2026-09-03: '대기' 건만(종전 '진행', 2026-08-31)
DEFAULT_STATUSES = ("대기",)


def candidates(conn, since: str, seq: int | None, limit: int,
               statuses: tuple[str, ...] = DEFAULT_STATUSES, only_doc: str | None = None) -> list[dict]:
    """statuses: Apw_YJI_Send.Status 허용값. only_doc: 이 감정서번호 1건만(테스트용, since 무시)."""
    statuses = tuple(statuses) or DEFAULT_STATUSES
    sql = f"""
        SELECT TOP (?) s.Seq, s.Docid, s.Insert_Date, s.Emp_Regi, m.CustName, m.RequestDate, m.LStatus, m.Result
        FROM dbo.Apw_YJI_Send s
        JOIN dbo.apw_masterex m ON m.DocID = s.Docid
        WHERE s.Status IN ({", ".join("?" * len(statuses))})
          AND NOT EXISTS (SELECT 1 FROM dbo.Apw_YJI_BankAuto b
                          WHERE b.Send_Seq = s.Seq AND b.Status IN (N'완료', N'처리중', N'제외'))
          AND (m.CustName LIKE '%신한은행%' OR m.CustName LIKE '%국민은행%' OR m.CustName LIKE '%기업은행%'
               OR m.CustName LIKE N'농협은행%'
               OR m.CustName LIKE N'%하나은행%' OR m.CustName LIKE N'%우리은행%'
               OR m.CustName LIKE N'%새마을금고%' OR m.CustName LIKE N'%수협%' OR m.CustName LIKE N'%수산업협동조합%')
          -- 이미 발송한 건(재전송 요청)은 제외 — Bank24 에 사람이 작성한 내용이 이미 있다(2418 실측 2026-09-10)
          AND NOT (m.Status = ? AND m.Result = ?)
    """
    params: list = [limit, *statuses, SENT_STATUS, SENT_RESULT]
    if only_doc:
        sql += " AND s.Docid = ?"
        params.append(only_doc)
    else:
        sql += " AND s.Insert_Date >= ?"
        params.append(since)
    if seq is not None:
        sql += " AND s.Seq = ?"
        params.append(seq)
    sql += " ORDER BY s.Seq"
    cur = conn.cursor()
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def doc_switch(raw, only_doc: str | None) -> bool:
    """번호를 콕 집었을 때만 켜지는 ini 스위치 — `true` 또는 감정서번호 목록.

      값 = 01-2608-3-2513   ← 그 감정서번호일 때만(쉼표로 여러 개). 시연용으로 권장.
      값 = true             ← 번호 칸에 적은 아무 건이나.
    감시 모드는 only_doc 이 없으므로 어느 쪽이든 절대 안 켜진다.
    """
    if not raw or not only_doc:
        return False
    if isinstance(raw, str):
        text = raw.strip()
        if text.lower() in ("1", "true", "yes", "on"):
            return True
        if text.lower() in ("0", "false", "no", "off", ""):
            return False
        return only_doc in {x.strip() for x in text.split(",") if x.strip()}
    return True


def force_for(opt, only_doc: str | None) -> bool:
    """사람 작성 가드를 뚫을지 — ini `[run] force` (사용자 요청 2026-09-17)."""
    return doc_switch(getattr(opt, "force", False), only_doc)


def no_pdf_for(opt, only_doc: str | None) -> bool:
    """PDF 탐색·등록을 통째로 건너뛸지 — ini `[run] no_pdf_docs` (사용자 요청 2026-09-17).

    전례 폴더가 없는 건(2513)은 감정서·수수료·공부·현장조사 4번을 네트워크 공유에서 헛찾느라
    폼을 열기까지 3분을 쓴다(실측 10:47:54~10:50:48). 그 건만 탐색 자체를 안 하게 한다.
    """
    return doc_switch(getattr(opt, "no_pdf_docs", ""), only_doc)


def unqueued_candidate(conn, doc_id: str) -> list[dict]:
    """발송 요청 큐에 없는 감정서를 only_doc 으로 콕 집었을 때의 후보 1건(시연·수동 실행용).

    큐(Apw_YJI_Send)에 행이 없으면 후보 SQL 이 JOIN 에서 0건이라 '1회 처리'가 아무것도 못 한다.
    사람이 번호를 직접 적어 누른 경우에 한해 apw_masterex 만으로 후보를 만든다 —
    Send 행이 없으니 Seq=None 이고, 이력(Apw_YJI_BankAuto.Send_Seq 필수·유니크)은 남기지 않는다.
    은행·담보·.gam·사람작성 가드는 큐 건과 똑같이 그대로 탄다.
    """
    cur = conn.cursor()
    cur.execute("""SELECT TOP 1 m.DocID, m.CustName, m.RequestDate, m.LStatus, m.Result
                   FROM dbo.apw_masterex m WHERE m.DocID = ?""", doc_id)
    row = cur.fetchone()
    if row is None:
        return []
    cols = [d[0] for d in cur.description]
    m = dict(zip(cols, row))
    return [{"Seq": None, "Docid": m["DocID"], "Insert_Date": dt.datetime.now(), "Emp_Regi": "(큐 없음·수동)",
             "CustName": m["CustName"], "RequestDate": m["RequestDate"],
             "LStatus": m["LStatus"], "Result": m["Result"]}]


def history(conn, since: str, limit: int = 300) -> list[dict]:
    """Apw_YJI_BankAuto 이력(조회일자 이후) — GUI 처리 목록용."""
    cur = conn.cursor()
    cur.execute("""SELECT TOP (?) Seq, Send_Seq, Docid, Bank, Status, Msg, LogPath, Start_Date, End_Date
                   FROM dbo.Apw_YJI_BankAuto WHERE Start_Date >= ? ORDER BY Seq""", limit, since)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


_REASONS = (
    ("행을 목록에서 찾지 못했습니다", "작성 탭에 없음(이미 발송된 건이거나 조회기간 밖)"),
    (".gam 없음", "감정서 파일(.gam) 아직 없음 — 감정서 완성 후 재처리"),
    ("PDF 가 비정상적으로 작습니다", "감정서 PDF 파일 이상(크기)"),
    ("를 못 찾았습니다. 기대 위치", "감정서 PDF 를 전례 폴더에서 못 찾음"),
    ("거부가 있어 저장하지 않습니다", "입력 거부 칸이 있어 저장 안 함"),
    ("현장조사서 입력 거부", "현장조사서 입력 거부 — 저장 안 함"),
    ("국민 폼이 아닙니다", "열린 폼이 국민 폼이 아님(은행 판별 확인)"),
    ("폼이 아닙니다", "열린 폼이 해당 은행 폼이 아님(은행 판별 확인)"),
    ("다물건 정합 불명확", "다물건 정합 불명확 — 입력·저장 안 함(담당자 수동)"),
    ("미지원 물건", "미지원 물건(선박·어업권·집계형 등) — 입력·저장 안 함(담당자 수동)"),
    ("앞 문서의 작성 폼이 닫히지 않았습니다", "앞 문서 폼이 안 닫혀 열지 않음(Bank24 화면 정리 후 재처리)"),
    ("작성 폼이 닫히지 않았습니다", "작성 폼이 안 닫힘 — 다음 단계 중단(화면 확인)"),
    ("안에 열리지 않았습니다", "작성 폼이 안 열림(화면 상태 확인)"),
    ("컨텍스트 메뉴가 열리지 않았습니다", "Bank24 우클릭 메뉴가 안 열림(화면 상태 확인)"),
    ("로그인", "Bank24 로그인 실패(.env ID/PW 확인)"),
    ("python.exe 를 찾지 못했습니다", "python 경로 없음(BANKON_PYTHON 설정)"),
)


def humanize(msg: str | None) -> str:
    """러너 요약/예외 문자열 → 비고용 짧은 문장. 거부 칸은 '입력 거부: 라벨=값'으로."""
    text = msg or ""
    if not text:
        return ""
    rejects = re.findall(r"\[거부[^\]]*\]\s*(\S+)\s+넣을값=(\S+)", text)
    rej = ("입력 거부(빈칸 저장, 담당자 확인): " + ", ".join(f"{a}={b}" for a, b in rejects[:5])) if rejects else ""
    for key, human in _REASONS:
        if key in text:
            return human + (("; 거부: " + ", ".join(f"{a}={b}" for a, b in rejects[:3])) if rejects else "")
    m = re.search(r"error=(\w+Error)\((.*?)\)", text)
    if m:
        return "; ".join(x for x in (f"{m.group(1)}: {m.group(2)[:120]}", rej) if x)
    if "error=" in text:
        return text[:200]
    m = re.search(r"pdf_skipped=([^|]+)", text)     # 러너가 PDF 를 못 찾아 등록만 건너뛴 건(완료) — 사람이 수동 등록
    skipped = f"PDF 건너뜀({m.group(1).strip()}) — 수동 등록 필요" if m else ""
    # 다물건 결과. 하나·수협·우리·새마을은 2026-09-16 부터 화면 행을 늘려 전 물건을 채운다 —
    # '(전부)' 면 그대로 알리고, 못 채운 게 있으면 담당자가 볼 수 있게 사유까지 남긴다(농협은 종전대로 슬롯 하나).
    m = re.search(r"multi_object=([^|]+)", text)
    detail_text = m.group(1).strip() if m else ""
    multi = ("" if not m else
             f"다물건 {detail_text}" if "(전부)" in detail_text else
             f"다물건 일부만 입력({detail_text})")
    m = re.search(r"MISSED=(\d+)", text)             # 라벨을 못 짚어 안 채운 칸 — 저장은 됐지만 그 칸은 빈 채다(담당자 확인)
    names = re.findall(r"\[미발견\s*\]\s*(.+?)\s+넣을값", text)
    missed = (f"칸못찾음 {m.group(1)}개(그 칸은 빈 채 저장 — 담당자 확인"
              + (": " + ", ".join(dict.fromkeys(n.strip() for n in names))[:80] if names else "") + ")") \
        if (m and m.group(1) != "0") else ""
    m = re.search(r"survey=([^|]+)", text)          # 현장조사서 폼 미정찰 은행: 입력 칸이 있으면 사람이 채운다
    survey = f"현장조사서 {m.group(1).strip()}" if (m and "미매핑" in m.group(1) or (m and "수동" in m.group(1))) else ""
    if rej or skipped or multi or survey or missed:
        return "; ".join(x for x in (rej, missed, skipped, multi, survey) if x)
    return "정상 처리" if "[요약]" in text else text[:200]


SENT_STATUS, SENT_RESULT = "72", "10"     # apw_Master '완료처리(발송)' — 이미 발송한 건(사용자 확정 2026-09-10)


def sent_already(conn, doc_id: str) -> bool:
    """APW 가 **이미 발송 완료**로 잡은 건인가 — 그렇다면 자동 작성 대상이 아니다.

    발송팀이 이미 보낸 건에 다시 발송 요청이 들어오는 일이 있다(재전송). 그런 건은 Bank24 에 사람이 작성한
    내용이 이미 있으므로 손대면 안 된다(실측 2418: 8월에 세 번 발송한 건에 09-10 재요청 → 자동 작성됨).
    상태 72 라도 Result 가 다르면 '완료처리(조사전반려)' 같은 다른 상태라 Result 까지 함께 본다.
    """
    cur = conn.cursor()
    cur.execute("SELECT Status, Result FROM dbo.apw_Master WHERE DocID = ?", doc_id)
    row = cur.fetchone()
    if not row:
        return False
    return (str(row[0] or "").strip(), str(row[1] or "").strip()) == (SENT_STATUS, SENT_RESULT)


def send_status(conn, seq: int) -> str | None:
    """지금 이 발송 요청의 Status — 후보를 뽑은 뒤 사람이 먼저 처리했는지 보려고 **실행 직전에** 다시 읽는다."""
    cur = conn.cursor()
    cur.execute("SELECT Status FROM dbo.Apw_YJI_Send WHERE Seq = ?", seq)
    row = cur.fetchone()
    return (str(row[0]).strip() if row and row[0] is not None else None)


def prior_state(conn, doc_id: str) -> str | None:
    cur = conn.cursor()
    cur.execute("SELECT TOP 1 Status FROM dbo.Apw_YJI_BankAuto WHERE Docid = ? AND Status IN ('완료','처리중') ORDER BY Seq DESC", doc_id)
    row = cur.fetchone()
    return row[0] if row else None


def record(conn, send_seq: int, doc_id: str, bank: str, status: str, msg: str | None = None) -> int:
    cur = conn.cursor()
    # Send_Seq 유니크(UX_BankAuto_Send): 실패 뒤 재시도는 기존 행을 되살린다(INSERT 불가).
    cur.execute("SELECT Seq FROM dbo.Apw_YJI_BankAuto WHERE Send_Seq = ?", send_seq)
    prior = cur.fetchone()
    if prior:
        cur.execute(
            "UPDATE dbo.Apw_YJI_BankAuto SET Docid = ?, Bank = ?, Status = ?, Msg = ?, LogPath = NULL, "
            "Start_Date = GETDATE(), End_Date = NULL WHERE Seq = ?",
            doc_id, bank, status, (msg or "")[:500], int(prior[0]))
        return int(prior[0])
    # SCOPE_IDENTITY() 를 따로 실행하면 다른 배치라 NULL — OUTPUT 으로 같은 문장에서 받는다.
    cur.execute(
        "INSERT INTO dbo.Apw_YJI_BankAuto (Send_Seq, Docid, Bank, Status, Msg, Start_Date) "
        "OUTPUT INSERTED.Seq VALUES (?, ?, ?, ?, ?, GETDATE())",
        send_seq, doc_id, bank, status, fit_bytes(msg, 500))
    row = cur.fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("Apw_YJI_BankAuto INSERT 뒤 Seq 를 받지 못함")
    return int(row[0])


def fit_bytes(text: str | None, limit: int, encoding: str = "cp949") -> str:
    """varchar(N) 컬럼용 — 한글은 2바이트라 글자수[:N] 로는 넘친다(2754 완료 기록이 8152 잘림 오류로 '처리중'에 멈춤, 2026-09-03).
    바이트 기준으로 자르되 글자 중간에서 끊지 않는다."""
    raw = (text or "").encode(encoding, errors="replace")
    if len(raw) <= limit:
        return text or ""
    return raw[:limit].decode(encoding, errors="ignore")


def finish(conn, seq: int, status: str, msg: str | None, log_path: str | None) -> None:
    conn.cursor().execute(
        "UPDATE dbo.Apw_YJI_BankAuto SET Status = ?, Msg = ?, LogPath = ?, End_Date = GETDATE() WHERE Seq = ?",
        status, fit_bytes(msg, 500), fit_bytes(log_path, 300), seq)


# ── 한 건 실행 ──────────────────────────────────────────────────────
QUERY_DAYS_BEFORE = 3    # BANK24 조회기간(의뢰일자 기준) — APW 의뢰일 앞뒤 여유
QUERY_DAYS_AFTER = 1
# 1차 기간에 없으면 한 번 더 넓게(2701 실측: APW 의뢰일 08-25 / Bank24 의뢰일 09-03 = +9일).
QUERY_WIDE_BEFORE = 10
QUERY_WIDE_AFTER = 14
NOT_IN_LIST = "행을 목록에서 찾지 못했습니다"     # navigate.ensure_row 의 실패 문구(재시도 판별 키)
EXIT_EXCLUDED = 3                                  # 러너 exit 3 = '제외'(사람 작성·이미 발송완료, human_guard)


def status_for(rc: int) -> str:
    """러너 exit → 이력 Status. 0 완료 · 3 제외(재시도 없음) · 그 외 실패(다음 라운드 재시도)."""
    if rc == 0:
        return "완료"
    if rc == EXIT_EXCLUDED:
        return "제외"
    return "실패"


def query_window(req_date: dt.date, *, before: int = QUERY_DAYS_BEFORE, after: int = QUERY_DAYS_AFTER) -> tuple[str, str]:
    """러너에 넘길 BANK24 조회기간 (YYYY-MM-DD, YYYY-MM-DD).

    BANK24 목록 조회는 **의뢰일자(은행이 보낸 시각)** 기준인데 APW RequestDate 는 우리가 접수한 날이라
    하루 어긋날 수 있다(실측 2026-09-08: 2780 의뢰일자 09-03 18:23 / APW 의뢰일 09-04 → 하루짜리 조회로
    "행을 목록에서 찾지 못했습니다"). 행 매칭은 감정서번호 문자열이라 기간을 넓혀도 오탐은 없다.
    """
    start = req_date - dt.timedelta(days=before)
    end = req_date + dt.timedelta(days=after)
    return f"{start:%Y-%m-%d}", f"{end:%Y-%m-%d}"


def run_one(doc_id: str, req_date: dt.date, *, live: bool, no_pdf: bool, bank: str = "신한",
            on_line=None, window: tuple[str, str] | None = None, force: bool = False) -> tuple[int, str | None, str]:
    """러너를 자식 프로세스로 돌린다 → (exit, 로그파일명, 요약 한 줄). on_line(줄) 로 출력을 실시간 전달.

    window: BANK24 조회기간(생략 시 query_window(req_date)). 목록에 없어 실패하면 호출측이 넓은 기간으로 한 번 더 부른다.
    """
    cache = ROOT / "work" / doc_id
    if cache.exists():
        shutil.rmtree(cache, ignore_errors=True)     # 항상 새 .gam
    date_from, date_to = window or query_window(req_date)
    runner = RUNNERS[bank]
    tail = [date_from, date_to, doc_id] + ([] if live else ["--dry"]) + (["--no-pdf"] if no_pdf else []) \
        + (["--force"] if force else [])
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--runner", runner] + tail            # 단일 exe: 러너도 번들 안(자기 재호출, 관리자 상속)
    else:
        args = [python_exe(), str(_paths._REPO / "tools" / f"{runner}.py")] + tail
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", env=env, cwd=str(ROOT), creationflags=creation)
    lines: list[str] = []
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        lines.append(line)
        if on_line:
            try:
                on_line(line)
            except Exception:  # noqa: BLE001
                pass
    proc.wait()
    out = "\n".join(lines)
    m = re.search(r"\[runner\] start (\d{8}_\d{6})", out)
    log_name = f"reports/full_{m.group(1)}.log" if m else None
    summary = next((ln.strip() for ln in reversed(lines) if ln.startswith("[요약]")), "")
    rejected = [ln.strip() for ln in lines if "[거부" in ln]
    # 라벨을 못 짚어 그냥 넘어간 칸('미발견')은 종전엔 러너 로그에만 남아 아무도 몰랐다 — 거부와 달리 exit 코드도 0 이라
    # '완료'로 기록됐다(2804 구분건물 층수 누락 제보, 2026-09-10). 한 칸이라도 있으면 비고에 남겨 담당자가 확인하게 한다.
    missed = [ln.strip() for ln in lines if "[미발견" in ln]
    total_missed = sum(int(x) for x in re.findall(r"칸못찾음 (\d+)", out))
    if proc.returncode != 0:
        err = next((ln.strip() for ln in reversed(lines) if "[runner] 실패" in ln), "")
        summary = " / ".join(x for x in [err, *rejected[:5], summary] if x)
    elif rejected or total_missed:   # 완료지만 거부·미발견 칸이 있으면 비고에 남긴다(2026-09-03·09-10)
        head = f"MISSED={total_missed}" if total_missed else ""
        summary = " / ".join(x for x in [head, *rejected[:5], *missed[:5], summary] if x)
    return proc.returncode, log_name, summary or out[-300:]


def one_round(cfg, opt, *, emit=None, on_item=None, should_stop=None, on_line=None) -> int:
    """한 바퀴. emit(문자열)=로그, on_item(dict)=건별 상태(GUI 표), should_stop()=중단 신호, on_line=러너 출력 줄."""
    log_fn = emit or log
    banks = set(getattr(opt, "banks", None) or SUPPORTED)
    since = opt.since or f"{dt.date.today():%Y-%m-%d}"
    handled = 0
    statuses = tuple(getattr(opt, "statuses", None) or DEFAULT_STATUSES)
    only_doc = (getattr(opt, "only_doc", None) or "").strip() or None
    # 사람이 작성한 폼이어도 진행 — 번호를 콕 집었을 때만 열리는 탈출구(시연·재작성). 감시 모드는 절대 안 켠다.
    force = force_for(opt, only_doc)
    if force:
        log_fn(f"★--force: {only_doc} 은 사람이 작성한 폼이어도 진행한다(사람이 쓴 값에 덮어쓸 수 있음)")
    elif getattr(opt, "force", False) and only_doc:
        log_fn(f"force 설정이 있지만 {only_doc} 은 대상이 아니라 가드 그대로(사람 작성 폼이면 제외)")
    # 전례 PDF 가 아예 없는 건은 탐색(네트워크 공유 4회)만 3분 걸린다 — 그 건만 통째로 건너뛴다.
    skip_pdf = no_pdf_for(opt, only_doc)
    if skip_pdf:
        log_fn(f"★{only_doc} 은 PDF 탐색·등록을 건너뛴다(no_pdf_docs) — 바로 Bank24 입력으로 간다")
    with connect(cfg.source_sql, readonly=True) as ro:
        rows = candidates(ro, since, opt.seq, opt.max, statuses=statuses, only_doc=only_doc)
    if only_doc:
        log_fn(f"★테스트 대상 1건만: {only_doc} (Status IN {statuses}, since 무시)")
        if not rows:
            # 발송 요청이 아예 없는 건(옛 건·시연용). 사람이 번호를 적어 누른 경우만 — 이력은 남기지 않는다.
            with connect(cfg.source_sql, readonly=True) as ro:
                rows = unqueued_candidate(ro, only_doc)
            if rows:
                log_fn(f"★{only_doc} 은 발송 요청 큐에 없음 — apw_masterex 로 직접 실행(이력 기록 안 함)")
    if not rows:
        log_fn(f"후보 없음 (Status IN {statuses}, " + (f"Docid={only_doc})" if only_doc else f"Insert_Date >= {since})"))
        return 0
    for r in rows:
        if STOP_FILE.exists() or (should_stop and should_stop()):
            log_fn("중단 신호 — 남은 건은 다음에")
            break
        doc, seq, bank = r["Docid"], r["Seq"], bank_of(r["CustName"])
        item = {"seq": seq, "doc": doc, "bank": bank, "req": f"{r['Insert_Date']:%m-%d %H:%M}", "emp": r["Emp_Regi"],
                "apw": f"{r['LStatus']}/{r['Result']}", "status": "", "msg": ""}

        def show(status, msg=""):
            item["status"], item["msg"] = status, msg
            if on_item:
                on_item(dict(item))
        head = f"Send#{seq if seq is not None else '-'} {doc} [{bank}] 의뢰 {r['RequestDate']:%Y-%m-%d} 요청 {r['Insert_Date']:%m-%d %H:%M} ({r['Emp_Regi']}) APW={r['LStatus']}/{r['Result']}"
        # 큐에 없는 건(seq None)은 Send_Seq 가 없어 이력을 남길 수 없다 — 입력·저장은 하되 기록만 건너뛴다.
        writing = (opt.live or (opt.dry and opt.record)) and seq is not None
        if bank not in SUPPORTED or bank not in banks:
            log_fn(f"{head} → 보류({bank} 미지원/미선택, 기록 안 함)")
            show("보류", f"{bank} 미지원/미선택")
            continue
        if not DAMBO_DOC.match(doc):
            log_fn(f"{head} → 보류(담보 아님, 기록 안 함)")
            show("보류", "담보 아님")
            continue
        with connect(cfg.source_sql, readonly=True) as ro:
            prior = prior_state(ro, doc)
            try:
                has_gam = bool(resolve_document(ro, doc).remote("gam"))
            except Exception as error:  # noqa: BLE001
                has_gam, gam_err = False, repr(error)
            else:
                gam_err = ""
        if prior:
            log_fn(f"{head} → 제외(이미 {prior})")
            show("제외", f"이미 {prior}")
            if writing:
                with connect(cfg.source_sql) as rw:
                    record(rw, seq, doc, bank, "제외", f"같은 감정서가 이미 {prior}")
            continue
        if not has_gam:
            log_fn(f"{head} → .gam 없음 {gam_err}→ 다음 바퀴로 미룸")
            show("대기", ".gam 없음(감정서 미완성)")
            continue
        if not (opt.live or opt.dry):
            log_fn(f"{head} → 후보(계획만)")
            show("후보", "계획만")
            continue

        # 후보는 바퀴 시작에 한 번 뽑는데 한 바퀴가 수십 분이라, 그 사이 **사람이 먼저 작성·발송**해 버릴 수 있다
        # (실측 2787: 13:54 요청 → 14:34 사람이 처리해 Status '완료' → 14:59 우리 차례, 작성 탭에 없어 '실패'로 남음).
        # 실행 직전에 요청 상태를 다시 읽어 그런 건은 건드리지 않는다.
        with connect(cfg.source_sql, readonly=True) as ro:
            now_status = send_status(ro, seq) if seq is not None else None
            already_sent = sent_already(ro, doc)
        if seq is not None and now_status not in statuses:
            log_fn(f"{head} → 제외(발송 요청 상태가 '{now_status}' 로 바뀜 — 사람이 처리)")
            show("제외", f"요청 상태 '{now_status}'(사람이 처리)")
            if writing:
                with connect(cfg.source_sql) as rw:
                    record(rw, seq, doc, bank, "제외", f"발송 요청 상태가 '{now_status}' 로 바뀜(사람이 먼저 처리)")
            continue
        if already_sent:
            # 후보 SQL 에서도 거르지만, 한 바퀴 도는 사이에 발송될 수 있어 실행 직전에 다시 본다(2787 처럼).
            log_fn(f"{head} → 제외(APW 이미 발송 완료 — 재전송 요청은 자동 작성 안 함)")
            show("제외", "이미 발송 완료(재전송)")
            if writing:
                with connect(cfg.source_sql) as rw:
                    record(rw, seq, doc, bank, "제외", "APW 이미 발송 완료(Status 72/Result 10) — 재전송 요청이라 자동 작성 안 함")
            continue

        log_fn(f"{head} → 실행 {'LIVE' if opt.live else 'DRY'}")
        show("처리중", "LIVE" if opt.live else "DRY")
        rec = None
        if writing:
            with connect(cfg.source_sql) as rw:
                rec = record(rw, seq, doc, bank, "처리중", "DRY" if not opt.live else None)
        req_date = r["RequestDate"].date()
        rc, log_name, summary = run_one(doc, req_date, live=opt.live, no_pdf=opt.no_pdf or skip_pdf,
                                        bank=bank, on_line=on_line, force=force)
        if rc not in (0, EXIT_EXCLUDED) and NOT_IN_LIST in summary:
            # Bank24 의뢰일자가 APW 의뢰일과 많이 다른 건(2701: +9일) — 넓은 기간으로 한 번만 더.
            wide = query_window(req_date, before=QUERY_WIDE_BEFORE, after=QUERY_WIDE_AFTER)
            log_fn(f"{head} → 목록에 없음(1차 {query_window(req_date)}) → 조회기간 {wide} 로 재시도")
            rc, log_name, summary = run_one(doc, req_date, live=opt.live, no_pdf=opt.no_pdf or skip_pdf,
                                            bank=bank, on_line=on_line, window=wide, force=force)
            if rc != 0 and rc != EXIT_EXCLUDED and NOT_IN_LIST in summary:
                summary = f"{summary} / 조회기간 {wide} 로 재시도해도 목록에 없음(미접수·동산담보·탭 확인)"
        status = status_for(rc)
        log_fn(f"{head} → {status} exit={rc} {log_name or ''}\n    {summary[:400]}")
        show(status, summary[:300])
        if rec is not None:
            with connect(cfg.source_sql) as rw:
                finish(rw, rec, status, ("DRY " if not opt.live else "") + summary, log_name)
        handled += 1
    return handled


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="run_queue_worker")
    p.add_argument("--live", action="store_true")
    p.add_argument("--dry", action="store_true")
    p.add_argument("--record", action="store_true", help="--dry 에서도 이력 기록")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=int, default=600)
    p.add_argument("--since", default=None)
    p.add_argument("--max", type=int, default=20)
    p.add_argument("--seq", type=int, default=None)
    p.add_argument("--no-pdf", action="store_true")
    p.add_argument("--banks", default=None, help="쉼표 구분(예: 신한,국민). 기본 전부")
    p.add_argument("--doc", dest="only_doc", default=None, help="테스트용: 이 감정서번호 1건만(since 무시)")
    p.add_argument("--statuses", default=None, help="Apw_YJI_Send.Status 허용값, 쉼표 구분(기본 대기)")
    p.add_argument("--no-pdf-docs", dest="no_pdf_docs", default="",
                   help="이 감정서번호(쉼표 구분)는 PDF 탐색·등록을 건너뛴다(전례 폴더가 없는 건)")
    p.add_argument("--force", nargs="?", const=True, default=False,
                   help="--doc 와 함께: 사람이 작성한 폼이어도 진행(시연·재작성, 덮어쓸 수 있음). "
                        "감정서번호를 주면 그 건에만 걸린다(--force 01-2608-3-2513)")
    p.add_argument("--env", default=None)
    opt = p.parse_args(argv)
    opt.banks = set(opt.banks.split(",")) if opt.banks else None
    opt.statuses = tuple(x.strip() for x in opt.statuses.split(",") if x.strip()) if opt.statuses else None
    if opt.live and opt.dry:
        p.error("--live 와 --dry 는 같이 못 씁니다")
    if (opt.live or opt.dry) and not is_admin():
        print("관리자 권한이 아닙니다 — Bank24 가 elevated 라 입력이 막힙니다(UIPI). -Verb RunAs 로 띄우세요.", file=sys.stderr)
        return 2
    cfg = load_config(opt.env)
    (ROOT / "reports").mkdir(exist_ok=True)
    if STOP_FILE.exists():
        STOP_FILE.unlink()
    mode = "LIVE" if opt.live else ("DRY" if opt.dry else "PLAN")
    log(f"워커 시작 모드={mode} since={opt.since or '오늘'} interval={opt.interval}s once={opt.once} 지원={list(SUPPORTED)}")
    while True:
        try:
            one_round(cfg, opt)
        except Exception as error:  # noqa: BLE001
            log(f"바퀴 실패 {error!r}")
        if opt.once or STOP_FILE.exists():
            break
        time.sleep(opt.interval)
    log("워커 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
