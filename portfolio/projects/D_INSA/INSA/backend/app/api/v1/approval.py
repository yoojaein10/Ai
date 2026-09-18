"""API routes for electronic approval (PHASE 12)."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_roles
from app.db.models import User
from app.db.session import get_db
from app.schemas.approval_doc import (
    AttachmentResponse,
    DocActionRequest,
    DocCreate,
    DocDetailResponse,
    DocResponse,
    DocUpdate,
)
from app.schemas.approval_doc_type import (
    ApprovalDocTypeCreate,
    ApprovalDocTypeResponse,
    ApprovalDocTypeUpdate,
)
from app.schemas.approval_line import (
    LineTemplateCreate,
    LineTemplateResponse,
    LineTemplateUpdate,
)
from app.services import approval_service as svc

router = APIRouter(prefix="/approval", tags=["approval"])

_STORAGE_ROOT = Path(os.environ.get("APPROVAL_STORAGE_ROOT", "storage/approval")).resolve()
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-()]")


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.NotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.PermissionDenied):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, svc.InvalidState):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail="internal error")


# ── Doc types ───────────────────────────────────────────────


@router.get("/doc-types", response_model=list[ApprovalDocTypeResponse])
def list_doc_types_route(
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.list_doc_types(db, active_only=active_only)


@router.get("/doc-types/{doc_type_id}", response_model=ApprovalDocTypeResponse)
def get_doc_type_route(
    doc_type_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_doc_type(db, doc_type_id)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post(
    "/doc-types",
    response_model=ApprovalDocTypeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doc_type_route(
    body: ApprovalDocTypeCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_doc_type(
            db,
            code=body.code,
            name=body.name,
            category=body.category,
            description=body.description,
            is_active=body.is_active,
        )
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.put("/doc-types/{doc_type_id}", response_model=ApprovalDocTypeResponse)
def update_doc_type_route(
    doc_type_id: int,
    body: ApprovalDocTypeUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_doc_type(
            db,
            doc_type_id,
            name=body.name,
            category=body.category,
            description=body.description,
            is_active=body.is_active,
        )
    except svc.ApprovalError as e:
        raise _map_error(e)


# ── Line templates ──────────────────────────────────────────


@router.get("/lines", response_model=list[LineTemplateResponse])
def list_lines_route(
    doc_type_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.list_templates(db, doc_type_id=doc_type_id)


@router.get("/lines/{template_id}", response_model=LineTemplateResponse)
def get_line_route(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_template(db, template_id)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post(
    "/lines",
    response_model=LineTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_line_route(
    body: LineTemplateCreate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return svc.create_template(
            db,
            doc_type_id=body.doc_type_id,
            name=body.name,
            scope=body.scope,
            scope_ref=body.scope_ref,
            is_default=body.is_default,
            steps=[s.model_dump() for s in body.steps],
        )
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.put("/lines/{template_id}", response_model=LineTemplateResponse)
def update_line_route(
    template_id: int,
    body: LineTemplateUpdate,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        return svc.update_template(
            db,
            template_id,
            name=body.name,
            scope=body.scope,
            scope_ref=body.scope_ref,
            is_default=body.is_default,
            steps=[s.model_dump() for s in body.steps] if body.steps is not None else None,
        )
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.delete("/lines/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line_route(
    template_id: int,
    current_user: User = Depends(require_roles("SYSTEM_ADMIN", "HR_ADMIN")),
    db: Session = Depends(get_db),
):
    try:
        svc.delete_template(db, template_id)
    except svc.ApprovalError as e:
        raise _map_error(e)


# ── Docs ────────────────────────────────────────────────────


@router.get("/docs/inbox", response_model=list[DocResponse])
def inbox_route(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.get_inbox(db, current_user, status_filter=status_filter)


@router.get("/docs/inbox/count")
def inbox_count_route(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"count": svc.inbox_unread_count(db, current_user)}


@router.get("/docs/drafts", response_model=list[DocResponse])
def drafts_route(
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.get_drafts(db, current_user, status_filter=status_filter)


@router.get("/docs/{doc_id}", response_model=DocDetailResponse)
def doc_detail_route(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_doc_detail(db, doc_id, current_user)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post(
    "/docs", response_model=DocResponse, status_code=status.HTTP_201_CREATED
)
def create_doc_route(
    body: DocCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.create_draft(
            db,
            user=current_user,
            doc_type_id=body.doc_type_id,
            title=body.title,
            content=body.content,
            line_template_id=body.line_template_id,
        )
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.put("/docs/{doc_id}", response_model=DocResponse)
def update_doc_route(
    doc_id: int,
    body: DocUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.update_draft(
            db,
            doc_id,
            user=current_user,
            title=body.title,
            content=body.content,
        )
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post("/docs/{doc_id}/submit", response_model=DocResponse)
def submit_doc_route(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.submit_doc(db, doc_id, current_user)
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post("/docs/{doc_id}/approve", response_model=DocResponse)
def approve_route(
    doc_id: int,
    body: DocActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.approve_step(db, doc_id, current_user, comment=body.comment)
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post("/docs/{doc_id}/reject", response_model=DocResponse)
def reject_route(
    doc_id: int,
    body: DocActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.reject_step(db, doc_id, current_user, comment=body.comment)
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.post("/docs/{doc_id}/recall", response_model=DocResponse)
def recall_route(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc = svc.recall_doc(db, doc_id, current_user)
        return svc._enrich_doc_row(db, doc)
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.get("/docs/{doc_id}/history")
def history_route(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return svc.get_history(db, doc_id, current_user)
    except svc.ApprovalError as e:
        raise _map_error(e)


# ── Attachments ─────────────────────────────────────────────


def _safe_filename(raw: str) -> str:
    base = os.path.basename(raw or "")
    cleaned = _SAFE_NAME_RE.sub("_", base)
    return cleaned or "file"


@router.post(
    "/docs/{doc_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_attachment_route(
    doc_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        doc_dir = (_STORAGE_ROOT / str(doc_id)).resolve()
        # Guard against path traversal via doc_id (int-typed, still resolve-check)
        if not str(doc_dir).startswith(str(_STORAGE_ROOT)):
            raise HTTPException(status_code=400, detail="invalid path")
        doc_dir.mkdir(parents=True, exist_ok=True)

        safe = _safe_filename(file.filename or "file")
        stored_name = f"{uuid.uuid4().hex}_{safe}"
        target = (doc_dir / stored_name).resolve()
        if not str(target).startswith(str(doc_dir)):
            raise HTTPException(status_code=400, detail="invalid path")

        content = file.file.read()
        with open(target, "wb") as fh:
            fh.write(content)

        att = svc.add_attachment(
            db,
            doc_id,
            current_user,
            filename=safe,
            filesize=len(content),
            filepath=str(target),
        )
        return att
    except svc.ApprovalError as e:
        raise _map_error(e)


@router.get("/docs/{doc_id}/attachments", response_model=list[AttachmentResponse])
def list_attachments_route(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Authorization happens inside get_doc_detail; piggyback
    try:
        svc.get_doc_detail(db, doc_id, current_user)
    except svc.ApprovalError as e:
        raise _map_error(e)
    return svc.list_attachments(db, doc_id)
