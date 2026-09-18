"""문서번호 → FTP 원격 경로 조회.

원천 시스템(Down_PDF/Down_Gam)과 동일하게:
  1) apw_Master 에서 Docid → Masterid
  2) SP_APW_PDFPATH(@Masterid, @Gubun) → 'PATH' (예: '2026/06/17/01-2606-3-1953.pdf')
실제 FTP 원격 경로는 '/Gam/' + PATH 이며, 내용은 zlib 압축본이다.
"""
from __future__ import annotations

from dataclasses import dataclass


class ResolveError(Exception):
    """경로 조회 실패."""


@dataclass(frozen=True)
class ResolvedPaths:
    doc_id: str
    masterid: int
    pdf_path: str | None  # SP 가 돌려준 상대경로(PATH). 없으면 None
    gam_path: str | None

    def remote(self, kind: str) -> str | None:
        """FTP 원격 절대경로('/Gam/...'). kind: 'pdf'|'gam'."""
        path = self.pdf_path if kind == "pdf" else self.gam_path
        return f"/Gam/{path.lstrip('/')}" if path else None


def _master_id(conn, doc_id: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT Masterid FROM apw_Master WHERE Docid = ?", doc_id)
    row = cur.fetchone()
    if row is None or row.Masterid is None:
        raise ResolveError(f"Masterid 없음: doc_id={doc_id}")
    return int(row.Masterid)


def _pdfpath(conn, masterid: int, gubun: str) -> str | None:
    cur = conn.cursor()
    cur.execute("{CALL SP_APW_PDFPATH (?, ?)}", masterid, gubun)
    row = cur.fetchone()
    if row is None:
        return None
    columns = [d[0].lower() for d in cur.description]
    values = dict(zip(columns, row))
    path = values.get("path")
    return str(path).strip() if path else None


def resolve_document(conn, doc_id: str) -> ResolvedPaths:
    """doc_id 에 대한 PDF/.gam 원격 경로를 조회한다.

    Raises:
        ResolveError: Masterid 를 찾지 못한 경우.
    """
    masterid = _master_id(conn, doc_id)
    return ResolvedPaths(
        doc_id=doc_id,
        masterid=masterid,
        pdf_path=_pdfpath(conn, masterid, "pdf"),
        gam_path=_pdfpath(conn, masterid, "GAM"),
    )
