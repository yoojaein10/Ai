# -*- coding: utf-8 -*-
"""탁상 PDF 파싱 → SP_I_APW_TS_Master 최대 2건 트랜잭션 저장."""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import re

import config
import address_mapper
import parsers
import pipeline
import sp_spec
import ts_db_writer
import ro_lookups
from parsers import base

class SaveError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


# 담당자(Manager) 기반 저장 제외 규칙 (코드 상수 allowlist — 런타임/사용자 입력 아님).
# CustID 의 '재직' 담당자 목록에 아래가 '포함'되면 해당 의뢰의 PDF/DB 저장을 건너뛴다
# (EXCLUDED_MANAGER). 담당자 코드는 int/char 컬럼 어느 쪽이어도 매칭되도록 문자열 비교.
#   - 1927: 모든 은행에서 제외
#   - 1115: 기업은행 의뢰만 제외
EXCLUDED_MANAGERS_ALL_BANKS = frozenset({"1927"})
EXCLUDED_MANAGERS_BY_BANK = {"기업은행": frozenset({"1115"})}


def manager_exclusion_applies(bank: str, managers) -> bool:
    """재직 담당자 목록과 은행으로 저장 제외 여부 판정(순수 함수)."""
    pool = EXCLUDED_MANAGERS_ALL_BANKS | EXCLUDED_MANAGERS_BY_BANK.get(
        bank or "", frozenset())
    return any(m in pool for m in managers)


@dataclass
class SaveResult:
    count: int
    outputs: list


def _dbdiag_write(stage: str, exc) -> None:
    """DB 연결/검증 실패 원인을 %TEMP%\\Y_TSBankAuto_dbdiag.txt 에 append(로컬 진단 전용).

    예외 클래스 + SQLSTATE(범주) + 메시지(따옴표 안=사용자/객체명은 *** 로 마스킹)만 남긴다.
    시크릿/비밀번호는 포함하지 않는다(pyodbc 오류는 PWD 를 echo 하지 않음).
    """
    try:
        import os
        import re
        import tempfile
        sqlstate = ""
        try:
            a0 = exc.args[0] if getattr(exc, "args", None) else ""
            if isinstance(a0, str) and len(a0) <= 8:
                sqlstate = a0
        except Exception:
            pass
        # 사용자명만 마스킹(user '...'), provider/오류 텍스트(TCP/SSL Provider 등)는 유지.
        msg = re.sub(r"(?i)(user\s+)'[^']*'", r"\1'***'", str(exc))[:400]
        line = "stage=%s type=%s sqlstate=%s msg=%s" % (
            stage, type(exc).__name__, sqlstate, msg)
        path = os.path.join(tempfile.gettempdir(), "Y_TSBankAuto_dbdiag.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n----\n")
    except Exception:
        pass


def _connect(app: config.AppConfig, connector=None):
    db = app.db
    if not db.enabled:
        raise SaveError("DB_DISABLED")
    if not all((db.server, db.database, db.username, db.password)):
        raise SaveError("DB_CONFIG_MISSING")
    if connector is None:
        import pyodbc
        connector = pyodbc.connect
    # 설정에 encrypt 가 명시돼 있으면 그대로, 없으면 yes→no 폴백(대상 PC TLS 미지원 대응).
    attempts = [None] if str(db.encrypt).strip() else ["yes", "no"]
    last_exc = None
    for enc in attempts:
        cs = ts_db_writer.build_connection_string(
            db, db.username, db.password, encrypt=enc)
        try:
            return connector(cs, timeout=10, autocommit=False)
        except TypeError:  # mock connector
            return connector(cs)
        except Exception as exc:
            last_exc = exc
            _dbdiag_write("connect(enc=%s)" % (enc or "cfg"), exc)
    raise SaveError("DB_CONNECT_FAILED") from last_exc


def _connect_lookup(app: config.AppConfig, connector=None):
    """APW_RegHist/APW_Customer 전용 읽기 연결."""
    db = app.db
    # lookup_server 미설정 시 쓰기 서버(server)로 폴백 — 같은 DB 에서 읽기 조회(별도 조회
    # 서버가 필요하면 settings.ini [database] lookup_server 로 지정).
    lookup_server = db.lookup_server or db.server
    if not lookup_server:
        raise SaveError("LOOKUP_DB_CONFIG_MISSING")
    lookup_db = replace(db, server=lookup_server)
    if connector is None:
        import pyodbc
        connector = pyodbc.connect
    attempts = [None] if str(db.encrypt).strip() else ["yes", "no"]
    last_exc = None
    for enc in attempts:
        cs = ts_db_writer.build_connection_string(
            lookup_db, lookup_db.username, lookup_db.password, encrypt=enc)
        cs += "ApplicationIntent=ReadOnly;"
        try:
            return connector(cs, timeout=10, autocommit=False)
        except TypeError:
            return connector(cs)
        except Exception as exc:
            last_exc = exc
            _dbdiag_write("connect_lookup(enc=%s)" % (enc or "cfg"), exc)
    raise SaveError("LOOKUP_DB_CONNECT_FAILED") from last_exc


def _verify_target_and_metadata(conn, app: config.AppConfig) -> None:
    cur = conn.cursor()
    try:
        cur.execute("SELECT @@SERVERNAME, DB_NAME()")
        row = cur.fetchone()
        actual_db = str(row[1] or "").strip() if row else ""
        # server는 INI에 IP/별칭/인스턴스명으로 지정될 수 있어 @@SERVERNAME과 문자열이
        # 다를 수 있다. 실제 연결 대상 DB명은 반드시 일치시킨다.
        if actual_db.casefold() != app.db.database.strip().casefold():
            raise SaveError("DB_TARGET_MISMATCH")

        cur.execute(
            "SELECT p.name FROM sys.parameters p "
            "WHERE p.object_id=OBJECT_ID(?) ORDER BY p.parameter_id",
            sp_spec.SP_NAME,
        )
        names = [str(r[0] or "").lstrip("@") for r in cur.fetchall()]
        required = sp_spec.INPUT_PARAM_NAMES + [p.name for p in sp_spec.OUTPUT_PARAM_SPECS]
        if names != required:
            raise SaveError("SP_METADATA_MISMATCH")
    except SaveError:
        raise
    except Exception as exc:
        _dbdiag_write("verify", exc)
        raise SaveError("DB_VERIFY_FAILED") from exc


def _eligibility_reason_code(item) -> str:
    """부적격 사유를 PII-없는 짧은 안전코드로 조립.

    필드명(영문 식별자)·범주 텍스트·길이 숫자만 포함하며 주소/이름 등 원문은
    절대 넣지 않는다. GUI 안전코드/진단파일 노출용.
    """
    parts = []
    m = getattr(item, "model", None)
    if m is not None:
        try:
            ok, missing = m.has_required()
            if not ok:
                parts.append("MISSING[" + ",".join(missing) + "]")
        except Exception:
            pass
        if not getattr(m, "request_datetime", ""):
            parts.append("NO_DATETIME")
    alc = getattr(item, "addr_len_check", None) or {}
    if alc and not alc.get("ok"):
        parts.append("ADDR_LEN[%s>%s]" % (alc.get("char_len"), alc.get("max_len")))
    if getattr(item, "params", "x") is None and not parts:
        parts.append("PARAMS_NONE")
    return ";".join(parts) or "UNKNOWN"


def _eligdiag_write(item, code: str) -> None:
    """부적격 판정 원인을 %TEMP%\\Y_TSBankAuto_eligdiag.txt 에 기록(로컬 진단 전용).

    마스킹된 모델 요약(bank/의뢰일시 유무/branch 유무/주소길이/물건수)만 남긴다.
    PII 원문(채무자/소유자/주소 원문/이름)은 포함하지 않는다.
    """
    try:
        import os
        import tempfile
        m = getattr(item, "model", None)
        summary = {}
        if m is not None:
            try:
                summary = m.safe_log_dict()
            except Exception:
                summary = {"bank": getattr(m, "bank", "")}
        line = "reason=%s bank=%s datetime=%r branch_present=%s addr_len=%s units=%s" % (
            code, summary.get("bank", ""), summary.get("request_datetime", ""),
            bool(summary.get("branch")), (item.addr_len_check or {}).get("char_len"),
            summary.get("unit_count"))
        path = os.path.join(tempfile.gettempdir(), "Y_TSBankAuto_eligdiag.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n----\n")
    except Exception:
        pass


def prepare_pdfs(paths: list[str], allowed_roots: list[str]):
    if not paths:
        raise SaveError("SAVE_COUNT_INVALID")
    prepared = []
    for path in paths:
        try:
            # 프로즌 EXE의 sys.executable 재호출은 GUI를 한 개 더 띄우므로 저장
            # 파이프라인에서는 검증된 로컬 PDF를 현재 프로세스에서 추출한다.
            lines = base.extract_lines(
                path, allowed_roots=allowed_roots, use_worker=False)
            item = pipeline.prepare(lines)
        except parsers.ExcludedRequest:
            # 의뢰기관 제외 건은 일반 파싱 실패로 감싸지 않고 그대로 전파해
            # 이후 DB 연결·조회·SP·COMMIT·PDF 재출력을 수행하지 않는다(§14-15).
            raise
        except Exception as exc:
            raise SaveError("PDF_PARSE_FAILED") from exc
        if not item.eligible or item.params is None:
            code = _eligibility_reason_code(item)
            _eligdiag_write(item, code)
            raise SaveError("PDF_NOT_ELIGIBLE:" + code)
        prepared.append(item)
    return prepared


def _enrich_from_db(cur, item) -> dict:
    """Reg/Eub/CustID 조회 및 다중 호수 조립."""
    params = dict(item.params)
    structured = item.structured
    reg_raw = _lookup_reg_eub_ybankauto(cur, structured.admin_addr)
    if not reg_raw:
        for raw_addr in getattr(item.model, "fallback_addresses", []) or []:
            fallback = address_mapper.structure_address(raw_addr)
            reg_raw = _lookup_reg_eub_ybankauto(cur, fallback.admin_addr)
            if reg_raw:
                structured = fallback
                for key, attr in (
                    ("SAN", "san"), ("Addr", "admin_addr"), ("BUN1", "bun1"),
                    ("BUN2", "bun2"), ("Building", "building"),
                    ("Building_Nm", "building_nm"), ("Dong", "dong"),
                    ("Ho", "ho"), ("AddrEtc", "addr_etc"),
                ):
                    params[key] = getattr(fallback, attr)
                break
    cust = ro_lookups.lookup_customer_exact(cur, item.custname)
    if not cust._raw_selected:
        cust = ro_lookups.lookup_customer(cur, item.model.bank, item.model.branch)
    if not reg_raw:
        raise SaveError("REG_EUB_NOT_RESOLVED")
    if not cust._raw_selected and cust.status != ro_lookups.NO_RESULT:
        raise SaveError("CUSTID_NOT_RESOLVED")
    params["Reg"] = reg_raw["Reg"]
    params["Eub"] = reg_raw["Eub"]
    params["CustID"] = (cust._raw_selected["CustID"]
                        if cust._raw_selected else None)
    # 담당자(Manager) 기반 저장 제외: CustID 의 '재직' 담당자 목록에 제외 대상이
    # '포함'되면 이 의뢰를 저장하지 않는다(1927=전 은행, 1115=기업은행만).
    # 퇴사자는 조회 단계에서 이미 제외됨. 담당자 0명/조회 실패는 저장 진행
    # (fail-open — 제외는 확실할 때만). Manager 값은 로그로 남기지 않는다.
    _cid = params["CustID"]
    if _cid:
        _managers = ro_lookups.lookup_managers(cur, _cid)
        if manager_exclusion_applies(item.model.bank, _managers):
            raise parsers.ExcludedRequest("EXCLUDED_MANAGER")
    params["Consult_Charge"] = None
    params["Manager"] = None
    params["CustFAX"] = "온"
    params["DongHo"] = None
    params["Guid"] = None
    params["Build_Struct"] = None
    params["Remodel_Date"] = None
    params["Bigo"] = None
    params["HFDocid"] = (item.model.request_no or None
                         if item.model.bank == "우리은행" else None)

    unit_text = " ".join(
        item.model.addresses + item.model.extra_units + ([item.model.remarks]
                                                         if item.model.remarks else []))
    preserve_alpha_multi_ho = bool(re.search(
        r"\b[A-Za-z가-힣]\d+(?:-\d+)?\s*호\s*,\s*[A-Za-z가-힣]?\d+(?:-\d+)?\s*호",
        unit_text,
    ))
    prefixed_ho_values = re.findall(r"(?:제\s*)?(?!제)([A-Za-z가-힣]\d+(?:-\d+)?)\s*호", unit_text)
    if len(set(prefixed_ho_values)) >= 2:
        preserve_alpha_multi_ho = True
    preserve_range_ho = bool(re.search(
        r"\b\d+(?:-\d+)?\s*호\s*~\s*\d+(?:-\d+)?\s*호",
        unit_text,
    ))
    units = []
    woori_shifted_units = False
    for group in re.findall(r"((?:\d{1,5}\s*,\s*)+\d{1,5})\s*호", unit_text):
        for value in re.findall(r"\d{1,5}", group):
            if value not in units:
                units.append(value)
    for value in re.findall(r"(?<!\d)(\d{1,5})\s*호", unit_text):
        if value not in units:
            units.append(value)
    if (item.model.bank == "우리은행"
            and str(params.get("Dong") or "").isdigit()
            and str(params.get("Ho") or "") == "1"):
        # `218동 1호, 건물명,219,220`처럼 우리은행 원문에서 첫 호수가
        # 동 칸에 붙어 인쇄된 다중 호수 양식.
        tails = re.findall(r",\s*(\d{2,5})(?!\s*동)", unit_text)
        if tails:
            units = [str(params["Dong"])] + [x for x in tails if x != params["Dong"]]
            woori_shifted_units = True
    # 참고사항에 별도 호수가 있거나 실제 다중 호수일 때만 주소 구조화값을 집계값으로
    # 덮어쓴다. 단일 주소의 명확한 건물명·동·호는 그대로 보존한다.
    if units and not preserve_alpha_multi_ho and not preserve_range_ho and (bool(item.model.remarks) or len(units) > 1):
        nums = [int(u) for u in units]
        if item.model.bank == "수협은행" and len(units) > 1:
            params["Building"] = f"{units[0]}호 외"
            # 대표 주소에서 구조화한 Dong/Ho를 유지한다.
        elif item.model.bank == "새마을금고" and len(units) > 1:
            unit_display = ",".join(units) + "호"
            pieces = [params.get("Building_Nm")]
            if params.get("Dong"):
                pieces.append(f"{params['Dong']}동")
            pieces.append(unit_display)
            params["Building"] = " ".join(p for p in pieces if p)
            params["Ho"] = ",".join(units)
        elif item.model.bank == "우리은행" and len(units) > 1:
            # 운영 DB의 우리은행 다중 호수 표기 규칙.
            bname = params.get("Building_Nm") or ""
            if (str(getattr(item.structured, "dong", "")).isdigit()
                    and str(getattr(item.structured, "ho", "")) == "1"):
                bname = ""
            if (not woori_shifted_units
                    and nums == list(range(nums[0], nums[-1] + 1))):
                unit_display = f"{nums[0]}~{nums[-1]}호"
                params["Ho"] = f"{nums[0]}~{nums[-1]}"
            else:
                unit_display = ",".join(units) + "호"
                params["Ho"] = "".join(units)
            params["Building"] = " ".join(
                p for p in (bname, unit_display) if p)
            params["Dong"] = None
            params["Building_Nm"] = None
        elif len(nums) > 1 and nums == list(range(nums[0], nums[-1] + 1)):
            params["Building"] = f"{nums[0]}호~{nums[-1]}호"
        else:
            params["Building"] = ",".join(f"{u}호" for u in units)
        # DongHo는 SP가 담당자 코드로 채우는 컬럼이므로 호수로 덮어쓰지 않는다.
        if item.model.bank not in ("수협은행", "새마을금고"):
            if item.model.bank != "우리은행":
                params["Dong"] = units[0]
                params["Ho"] = None

    if item.model.bank == "우리은행":
        # 우리은행은 Building에 상세를 합치고 Building_Nm/Dong은 사용하지 않는다.
        params["Dong"] = None
        raw_building = params.get("Building") or ""
        floor_unit = re.search(r"((?:지하|지상)?\d+층\s*[가-힣]?\d+)호", raw_building)
        if floor_unit:
            params["Ho"] = floor_unit.group(1)
        if (not params.get("Ho") and
                re.match(r"^(?:주식회사|\(주\))", raw_building.strip())):
            params["Building"] = None
        params["Building_Nm"] = None
    elif item.model.bank == "기업은행" and params.get("Building") and params.get("Ho"):
        params["Building"] = " ".join(
            p for p in (params.get("Building_Nm"), f"{params['Ho']}호") if p)
    elif item.model.bank == "아이엠뱅크" and params.get("Building_Nm") and params.get("Ho"):
        im_units = []
        for value in [str(params.get("Ho") or "")]:
            if value and value not in im_units:
                im_units.append(value)
        for value in re.findall(r"(?:제\s*)?(?!제)([가-힣A-Za-z]?\d+(?:-\d+)?)\s*호", item.model.remarks or ""):
            if value and value not in im_units:
                im_units.append(value)
        if im_units:
            params["Ho"] = ",".join(im_units)
            params["Building"] = f"{params['Building_Nm']}  {params['Ho']}호"
        params["Dong"] = None
    params["DongHo"] = None
    return {name: params.get(name) for name in sp_spec.INPUT_PARAM_NAMES}


def _lookup_reg_eub_ybankauto(cur, admin_addr: str) -> dict | None:
    """Y_BankAuto lookup_reg_eub의 상세 주소 우선 전략."""
    tokens = [t for t in (admin_addr or "").split() if t]
    if not tokens:
        return None
    # LIKE '당산동%'가 당산동1가를 먼저 잡는 문제를 막기 위해 정확 법정동을 우선한다.
    if len(tokens) >= 3:
        cur.execute(
            "SELECT TOP 1 REG,EUB FROM apworksdw.dbo.APW_RegHist "
            "WHERE FUSE='1' AND AS1=? AND AS2=? AND AS4=? "
            "ORDER BY REG,EUB",
            (tokens[0], tokens[1], tokens[-1]),
        )
        row = cur.fetchone()
        if row:
            return {"Reg": str(row[0] or "").strip(),
                    "Eub": str(row[1] or "").strip()}
    strategies = []
    if len(tokens) >= 4:
        strategies.extend([
            (("AS1", "AS2", "AS3", "AS4"), tokens[:4]),
            (("AS1", "AS2", "AS4"), (tokens[0], tokens[1], tokens[-1])),
            (("AS1", "AS2", "AS4"), (tokens[0], tokens[2], tokens[-1])),
        ])
    if len(tokens) >= 3:
        strategies.append((("AS1", "AS2", "AS4"), tokens[:3]))
    if len(tokens) >= 2:
        strategies.append((("AS1", "AS2"), tokens[:2]))
    strategies.append((("AS1",), tokens[:1]))
    for columns, values in strategies:
        where = " AND ".join(f"{c} LIKE ?" for c in columns)
        cur.execute(
            "SELECT TOP 5 REG,EUB FROM apworksdw.dbo.APW_RegHist "
            f"WHERE FUSE='1' AND {where}",
            [f"{v}%" for v in values],
        )
        row = cur.fetchone()
        if row:
            return {"Reg": str(row[0] or "").strip(),
                    "Eub": str(row[1] or "").strip()}
    return None


def _next_reg_charge(cur) -> int:
    """최신 저장값을 잠금 조회해 899/1729를 교대로 선택한다."""
    cur.execute(
        "SELECT TOP 1 Reg_Charge FROM dbo.APW_TS_Master WITH (UPDLOCK,HOLDLOCK) "
        "WHERE Reg_Charge IN (?,?) ORDER BY TS_SEQ DESC", (899, 1729))
    row = cur.fetchone()
    return 1729 if row and int(row[0] or 0) == 899 else 899


def save_pdf_batch(paths: list[str], app: config.AppConfig, *, allowed_roots: list[str],
                   connector=None, lookup_connector=None) -> SaveResult:
    """두 PDF를 모두 파싱한 뒤 한 트랜잭션으로 저장한다. 하나라도 실패하면 전체 rollback."""
    prepared = prepare_pdfs(paths, allowed_roots)
    conn = _connect(app, connector)
    lookup_conn = None
    outputs = []
    try:
        _verify_target_and_metadata(conn, app)
        lookup_conn = _connect_lookup(app, lookup_connector or connector)
        for item in prepared:
            cur = conn.cursor()
            params = _enrich_from_db(lookup_conn.cursor(), item)
            params["Reg_Charge"] = _next_reg_charge(cur)
            cur.execute(sp_spec.build_wrapper_sql(), sp_spec.params_in_order(params))
            output = ts_db_writer.fetch_output_and_drain(cur) or {}
            model = getattr(item, "model", None)
            output.update({
                "RequestNo": getattr(model, "request_no", None),
                "Bank": getattr(model, "bank", None),
                "CustName": params.get("CustName"),
                "RegCharge": params.get("Reg_Charge"),
            })
            outputs.append(output)
        conn.commit()
        return SaveResult(len(prepared), outputs)
    except SaveError:
        try: conn.rollback()
        except Exception: pass
        raise
    except parsers.ExcludedRequest:
        # 담당자 제외 등: SP 실패로 감싸지 않고 그대로 전파(호출자가 '저장 제외' 처리).
        # 아직 어떤 행도 commit 되지 않았으므로 rollback.
        try: conn.rollback()
        except Exception: pass
        raise
    except Exception as exc:
        try: conn.rollback()
        except Exception: pass
        _dbdiag_write("sp_execute", exc)
        raise SaveError("SP_EXECUTE_FAILED") from exc
    finally:
        try:
            if lookup_conn is not None:
                lookup_conn.rollback()
                lookup_conn.close()
        except Exception:
            pass
        try: conn.close()
        except Exception: pass
