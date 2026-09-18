# -*- coding: utf-8 -*-
"""SP 파라미터 스펙 · 빌더 (쓰기 실행 모듈과 import 단위로 분리; 지시 §13).

이 모듈은 순수 변환만 한다:
- SP 파라미터 스펙(이름/타입/길이/필수/OUTPUT)
- RequestModel + 구조화주소 → 파라미터 dict 조립
- 바인딩 순서 리스트, OUTPUT 래퍼 SQL 생성

★ 여기에는 execute_sp / commit / DB 연결이 없다. 미리보기·파싱 경로가 이 모듈만
  import 하면 실행/저장 경로를 끌어들이지 않는다(ts_db_writer 는 이 모듈을 재사용).
★ SP 정의는 PROVISIONAL 이다. 실쓰기 전 DB 메타데이터 검증 필요(SP_DEFINITION_SOURCE).

값 바인딩: 모든 입력은 pyodbc `?` 로 바인딩(호출부). 데이터값을 SQL 에 문자열로 넣지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import config


def strip_bigo_leading_name(text):
    """참고사항(ToJiBIGO)에서 선두 '이름. ' (한글 2~4자 + 마침표) 를 제거한다.

    예: '이영준. 매매예정' → '매매예정'. '이름. 내용' 형식이 아니면 원문을 그대로 둔다.
    """
    if not text:
        return text
    m = re.match(r"^\s*[가-힣]{2,4}\s*\.\s*(.+)$", str(text))
    return m.group(1).strip() if m else text

SP_NAME = "dbo.SP_I_APW_TS_Master"           # 고정 상수 (allowlist)
SP_DEFINITION_SOURCE = "metadata"
REGHIST_NOT_QUERIED = True                     # 이번 작업에서 Reg/Eub 미조회


@dataclass
class ParamSpec:
    name: str
    sqltype: str
    length: str          # 길이/정밀도 (provisional)
    required: bool       # 파라미터 필수 여부(보고서 기준 provisional)
    is_output: bool = False
    forced: str = ""     # SP 내부 강제값 설명


# 실제 DB sys.parameters 기준 입력 파라미터(순서·타입·길이 고정).
INPUT_PARAM_SPECS: list[ParamSpec] = [
    ParamSpec("MasterID", "varchar", "30", False),
    ParamSpec("Office", "char", "2", True),
    ParamSpec("Reg_DateTime", "varchar", "25", True),
    ParamSpec("Reg_Charge", "int", "4", False),
    ParamSpec("Consult_Charge", "int", "4", False),
    ParamSpec("CustName", "varchar", "50", True),
    ParamSpec("CustPhone", "varchar", "20", True),
    ParamSpec("CustCharge", "varchar", "30", True),
    ParamSpec("CustFAX", "varchar", "20", False),
    ParamSpec("Reg", "varchar", "5", True),
    ParamSpec("Eub", "varchar", "5", True),
    ParamSpec("SAN", "varchar", "4", True),
    ParamSpec("Addr", "varchar", "40", True),
    ParamSpec("BUN1", "char", "4", True),
    ParamSpec("BUN2", "char", "4", True),
    ParamSpec("Building", "varchar", "200", False),
    ParamSpec("DongHo", "varchar", "22", False),
    ParamSpec("Pyoung", "varchar", "10", False),
    ParamSpec("Category", "char", "2", False),
    ParamSpec("ToJiBIGO", "varchar", "3000", False),
    ParamSpec("Build_Struct", "varchar", "500", False),
    ParamSpec("Remodel_Date", "varchar", "20", False),
    ParamSpec("ToJi_Build_Total", "money", "8", False),
    ParamSpec("AdjPrice", "money", "8", False),
    ParamSpec("DocID", "varchar", "30", False),
    ParamSpec("Bigo", "varchar", "5000", False),
    ParamSpec("Jun_Master", "int", "4", False, forced="SP 가 항상 0 저장"),
    ParamSpec("MinPrice", "money", "8", False),
    ParamSpec("MaxPrice", "money", "8", False),
    ParamSpec("CustID", "char", "6", False),
    ParamSpec("Toji_Total", "money", "8", False),
    ParamSpec("Build_Total", "money", "8", False),
    ParamSpec("Bigo_In", "varchar", "4096", False),
    ParamSpec("Manager", "int", "4", False),
    ParamSpec("AppCode", "char", "6", True),
    ParamSpec("Guid", "varchar", "40", False),
    ParamSpec("AddrEtc", "char", "1", False),
    ParamSpec("Score", "int", "4", False, forced="SP 가 항상 1 저장"),
    ParamSpec("HFDocid", "varchar", "20", False),
    ParamSpec("HFOwnername", "varchar", "20", False),
    ParamSpec("HFOwnerPhone", "varchar", "20", False),
    ParamSpec("HFOwnerTel", "varchar", "20", False),
    ParamSpec("HFGubun", "int", "4", False),
    ParamSpec("HFWorkYN", "varchar", "2", False),
    ParamSpec("Dong", "varchar", "30", False),
    ParamSpec("Ho", "varchar", "20", False),
    ParamSpec("Building_Nm", "varchar", "200", False),
]

OUTPUT_PARAM_SPECS: list[ParamSpec] = [
    ParamSpec("NewMasterID", "varchar", "30", False, is_output=True),
    ParamSpec("NewSEQ", "int", "-", False, is_output=True),
]

INPUT_PARAM_NAMES = [p.name for p in INPUT_PARAM_SPECS]
# Reg_DateTime은 DB 서버 시간(GETDATE())을 사용하므로 바인딩하지 않는다.
EXEC_BIND_PARAM_NAMES = [n for n in INPUT_PARAM_NAMES if n != "Reg_DateTime"]

# 값의 출처 분류(미리보기용). 나머지 present 값은 PDF 파생으로 본다.
FIXED_PARAMS = {"Office", "AppCode", "Jun_Master", "Score"}
DB_DERIVED_PARAMS = {"CustID", "Reg", "Eub"}


# ───────────────────────────── 파라미터 조립 ─────────────────────────────
def build_sp_params(model, *, custname: str, custphone: str, custcharge: str,
                    addr, reg: str | None, eub: str | None) -> dict:
    """RequestModel + 구조화주소 → SP 입력 파라미터 dict (이름→값).

    PDF 파싱/파생값만 채우고 나머지는 명시적으로 None(NULL).
    PII(debtor/owner/owner_phone)는 절대 포함하지 않는다. HFDocid 는 항상 None.
    """
    def nv(s):  # 빈 문자열은 NULL 로
        return s if (s is not None and s != "") else None

    params = {
        "MasterID": None,                       # 신규 발번
        "Office": config.SP_OFFICE,             # '10'
        "AppCode": config.SP_APP_CODE,          # '300611'
        "Reg_DateTime": None,                    # wrapper SQL이 DB GETDATE() 사용
        "Reg_Charge": None,
        "Consult_Charge": None,
        "CustID": None,
        "CustName": nv(custname),
        "CustPhone": nv(custphone),
        "CustCharge": nv(custcharge),
        "CustFAX": "온",                       # 운영 DB 기본값
        "Reg": nv(reg),                          # RegHist 조회 결과(이번 미조회→None)
        "Eub": nv(eub),
        "SAN": nv(addr.san),
        "Addr": nv(addr.admin_addr),
        "BUN1": nv(addr.bun1),
        "BUN2": nv(addr.bun2),
        "Building": nv(addr.building),
        "Building_Nm": nv(addr.building_nm),
        "Dong": nv(addr.dong),
        "Ho": nv(addr.ho),
        "DongHo": None,                          # 주소 컬럼으로 사용 안 함
        "AddrEtc": nv(addr.addr_etc),
        "Build_Struct": None,
        "Remodel_Date": None,
        "Category": None,
        "Pyoung": None,
        "ToJiBIGO": nv(strip_bigo_leading_name(model.remarks)),
        "Bigo": None,
        "Manager": None,
        "Guid": None,
        "DocID": None,
        "AdjPrice": None,
        "MinPrice": None,
        "MaxPrice": None,
        "Toji_Total": None,
        "Build_Total": None,
        "ToJi_Build_Total": None,
        # 운영 DB 규칙: 우리은행 T문서만 HFDocid를 사용한다.
        "HFDocid": nv(model.request_no) if model.bank == "우리은행" else None,
        "HFOwnername": None,
        "HFOwnerPhone": None,
        "HFOwnerTel": None,
        "HFWorkYN": None,
        "HFGubun": None,                         # 기본 NULL
        "Jun_Master": 0,                         # SP 가 0 강제(전달은 0)
        "Score": 1,                              # SP 가 1 강제(전달은 1)
        "Bigo_In": None,                         # 실제 SP 메타데이터 항목; 용도 미확정
    }
    # 실제 sys.parameters 순서로 재배열한다. 누락 키는 즉시 실패한다.
    assert set(params.keys()) == set(INPUT_PARAM_NAMES), "파라미터 이름 불일치"
    return {name: params[name] for name in INPUT_PARAM_NAMES}


def params_in_order(params: dict) -> list:
    """DB GETDATE 항목을 제외한 실제 바인딩 순서."""
    return [params[name] for name in EXEC_BIND_PARAM_NAMES]


# ───────────────────────────── 래퍼 SQL ─────────────────────────────
def build_wrapper_sql() -> str:
    """OUTPUT 래퍼. 입력은 모두 ?, OUTPUT 은 로컬 변수. 데이터값 미삽입."""
    lines = []
    for p in INPUT_PARAM_SPECS:
        if p.name == "Reg_DateTime":
            lines.append("    @Reg_DateTime=@DbNow")
        else:
            lines.append(f"    @{p.name}=?")
    lines.append("    @NewMasterID=@OutMasterID OUTPUT")
    lines.append("    @NewSEQ=@OutSEQ OUTPUT")
    body = ",\n".join(lines)
    return (
        "SET NOCOUNT ON;\n"
        "DECLARE\n"
        "    @OutMasterID varchar(30),\n"
        "    @OutSEQ int,\n"
        "    @DbNow varchar(25)=CONVERT(varchar(25), GETDATE(), 121);\n\n"
        f"EXEC {SP_NAME}\n"
        f"{body};\n\n"
        "SELECT\n"
        "    @OutMasterID AS NewMasterID,\n"
        "    @OutSEQ AS NewSEQ;"
    )


def count_placeholders(sql: str) -> int:
    return sql.count("?")
