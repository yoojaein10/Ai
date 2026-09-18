# -*- coding: utf-8 -*-
"""전체 흐름 오케스트레이터 (지시 §10).

순서: 설정·allowlist 검증 → Bank24 fake/real adapter → 탁상 조회·PDF 저장 → PDF 검증 →
격리 파싱 → 필수값·은행·대표물건 검증 → 읽기전용 DB 연결 → 사후 대상·권한 검증 →
Customer 조회 → RegHist 조회 → 중복 조회 → SP 메타데이터/fingerprint 검증 →
SP 파라미터 생성 → 마스킹 DTO 생성 → rollback/close → GUI 상태 전달.

- 단계 실패 시 이후 단계를 호출하지 않는다(fail-closed).
- PDF 파싱 중에는 DB 연결·트랜잭션을 열지 않는다(파싱 완료 후에만 DB 단계 진입).
- DB 저장 adapter 는 제공하지 않는다. 저장 요청은 항상 차단 stub 으로 처리한다.
- ts_db_writer(쓰기 모듈)의 execute_sp/commit 을 import 하거나 호출하지 않는다.
- GUI 로는 마스킹 DTO 만 전달한다(원문 PII/자격증명/연결문자열 미포함).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ro_duplicate
import ro_guards
import ro_lookups
import ro_metadata
import ro_pipeline
import ro_query


class SaveBlocked(Exception):
    """DB 저장 경로는 이 테스트판에서 항상 차단된다."""


def save_to_db_stub(*a, **k):
    """항상 차단되는 저장 stub. 어떤 인자로도 저장하지 않는다."""
    raise SaveBlocked("테스트판 — DB 저장 없음(SP 실행/COMMIT 금지)")


@dataclass
class ParseOutcome:
    status: str
    eligible: bool
    masked: dict                          # GUI 안전
    _raw_keys: dict | None = field(default=None, repr=False)  # 메모리 전용(bank/branch/addr)

    def __repr__(self) -> str:
        return f"ParseOutcome(status={self.status!r}, eligible={self.eligible})"


@dataclass
class RunReport:
    """GUI/보고 전용 마스킹 리포트. 원문 미포함."""
    steps: list = field(default_factory=list)     # [(step, ok, note)]
    failed_step: str | None = None
    parse_masked: dict | None = None
    customer_status: str | None = None
    reghist_status: str | None = None
    duplicate_status: str | None = None
    metadata_status: str | None = None
    fingerprint_status: str | None = None
    metadata_diff: dict | None = None
    decision: dict | None = None
    customer_dtos: list = field(default_factory=list)
    reghist_dtos: list = field(default_factory=list)
    db_connected: bool = False
    committed: bool = False               # 항상 False
    executed_sp: bool = False             # 항상 False

    def add(self, step: str, ok: bool, note: str = ""):
        self.steps.append((step, ok, note))
        if not ok and self.failed_step is None:
            self.failed_step = step


# ───────────────────────────── 파싱 단계 (격리) ─────────────────────────────
def default_parse_stage(path: str, allowed_roots: list[str], *,
                        need_raw_keys: bool) -> ParseOutcome:
    """격리 worker 로 안전 검증·마스킹 요약을 얻고, 필요 시에만 메모리 내 원문 키를 추출.

    원문 키(bank/branch/admin_addr)는 DB 조회 바인딩에만 쓰이며 로그·GUI·영속화 대상이 아니다.
    """
    import pdf_worker
    masked = pdf_worker.run_isolated(path, allowed_roots)
    if masked.get("status") != "parsed":
        return ParseOutcome(masked.get("status", "parse_failed"), False, masked)
    if not masked.get("eligible"):
        return ParseOutcome("ineligible", False, masked)
    raw = None
    if need_raw_keys:
        # DB 단계에서만 원문 키를 메모리로 확보(격리 재파싱의 잔여 위험은 보고에 명시).
        import pipeline
        from parsers import base
        pr = pipeline.prepare(base.extract_lines(path, allowed_roots=allowed_roots))
        raw = {"bank": pr.model.bank, "branch": pr.model.branch,
               "admin_addr": pr.structured.admin_addr}
    return ParseOutcome("parsed", True, masked, _raw_keys=raw)


# ───────────────────────────── DB 단계 ─────────────────────────────
def _run_db_stage(report: RunReport, conn, allowlist, raw_keys: dict, *, stop=None):
    """읽기 전용 DB 단계. 모든 종료 경로에서 rollback/close 보장(context manager)."""
    import ro_connect
    with ro_connect.readonly_transaction(conn, stop_check=(stop.is_stopped if stop else None)) as c:
        report.db_connected = True
        cur = c.cursor()
        ro_query.apply_readonly_session(cur)

        # 사후 대상·권한 검증
        t = ro_query.execute_registered(cur, "VERIFY_TARGET")
        r = ro_query.execute_registered(cur, "VERIFY_ROLES")
        p = ro_query.execute_registered(cur, "VERIFY_PERMISSIONS")
        gate = ro_guards.evaluate_gate(t[0] if t else None, r[0] if r else None,
                                       p[0] if p else None, allowlist)
        report.add("db_post_verify", gate["gate_open"],
                   "" if gate["gate_open"] else "권한/대상 검증 실패")
        if not gate["gate_open"]:
            return   # context 종료 시 rollback/close

        # Customer / RegHist / 중복
        cust = ro_lookups.lookup_customer(cur, raw_keys["bank"], raw_keys["branch"])
        report.customer_status = cust.status
        report.customer_dtos = cust.dtos
        report.add("customer_lookup", cust.status != ro_lookups.QUERY_FAILED, cust.status)

        reg = ro_lookups.lookup_reghist(cur, raw_keys["admin_addr"])
        report.reghist_status = reg.status
        report.reghist_dtos = reg.dtos
        report.add("reghist_lookup", reg.status != ro_lookups.QUERY_FAILED, reg.status)

        dup = ro_duplicate.check_duplicate(cur)
        report.duplicate_status = dup.status
        report.add("duplicate_check", True, dup.status)

        # SP 메타데이터 / fingerprint
        meta = ro_query.execute_registered(cur, "READ_SP_METADATA",
                                           [ro_query.SP_SCHEMA, ro_query.SP_OBJECT])
        norm = ro_metadata.normalize_rows(meta)
        fp = ro_metadata.compute_fingerprint(norm)
        pin = ro_metadata.evaluate_pin(fp, allowlist_target_ok=gate["target_ok"])
        report.metadata_status = pin["status"]
        report.fingerprint_status = pin["status"]
        report.metadata_diff = ro_metadata.structure_diff(norm)
        report.add("sp_metadata", True, pin["status"])

        # 처리 가능 여부 결정 (SP 파라미터 생성까지만; 실행/저장 미연결)
        decision = ro_pipeline.decide(customer=cust, reghist=reg,
                                      metadata_verified=pin["metadata_verified"])
        report.decision = decision
        report.add("decision", True, decision["status"])


# ───────────────────────────── 전체 실행 ─────────────────────────────
def run(*, adapter, request_token: str, pdf_root: str, timestamp: str,
        allowed_roots: list[str], db_provider=None, allowlist=None,
        stop=None, parse_stage=None) -> RunReport:
    """전체 흐름 실행. db_provider 가 없으면 2단계(파싱까지)만 수행한다.

    db_provider: callable() -> conn (읽기전용 연결/또는 fake). allowlist 와 함께 주면 DB 단계 실행.
    parse_stage: 테스트 주입용. 기본은 default_parse_stage.
    """
    report = RunReport()
    parse_stage = parse_stage or default_parse_stage

    def stopped():
        return bool(stop and stop.is_stopped())

    try:
        # Bank24 단계
        adapter.launch_or_attach(); report.add("launch_or_attach", True, "fake" if adapter.is_fake else "real")
        if stopped():
            report.add("stopped", False, "긴급중지"); return report
        adapter.verify_login_screen(); report.add("verify_login_screen", True)
        adapter.login(None); report.add("login", True)
        adapter.select_tabletop_menu(); report.add("select_tabletop_menu", True)
        requests = adapter.query_requests(); report.add("query_requests", True, f"{len(requests)}건")
        path = adapter.download_pdf(request_token, pdf_root, timestamp=timestamp)
        report.add("download_pdf", True, "저장됨")
    except Exception as e:
        report.add("bank24", False, type(e).__name__)
        return report   # 단계 실패 → 이후 미호출

    # 격리 파싱 (이 시점까지 DB 연결 없음)
    need_raw = db_provider is not None and allowlist is not None
    try:
        outcome = parse_stage(path, allowed_roots, need_raw_keys=need_raw)
    except Exception as e:
        report.add("parse", False, type(e).__name__)
        return report
    report.parse_masked = outcome.masked
    report.add("parse", outcome.eligible, outcome.status)

    # 필수값·은행·대표물건 검증
    if not outcome.eligible:
        report.add("required_check", False, "필수값/적격성 미충족 → DB 미연결")
        return report   # 파싱 실패/부적격 → DB 연결 미시도

    # DB 단계 (파싱 완료 후에만)
    if not need_raw:
        report.add("db_stage", True, "DB 미연결(2단계: 파싱까지)")
        return report

    if stopped():
        report.add("stopped", False, "긴급중지"); return report

    try:
        conn = db_provider()
    except Exception as e:
        report.add("db_connect", False, type(e).__name__)
        return report
    try:
        _run_db_stage(report, conn, allowlist, outcome._raw_keys, stop=stop)
    except Exception as e:
        report.add("db_stage", False, type(e).__name__)
    # rollback/close 는 readonly_transaction 이 보장.
    return report
