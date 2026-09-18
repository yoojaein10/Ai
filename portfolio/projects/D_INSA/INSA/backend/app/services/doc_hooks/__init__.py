"""Approval doc post-action hooks (PHASE 15).

Dispatcher wires approval state transitions back to the originating
business domain (leave, travel, contract, ...) without forcing
`approval_service` to import every domain.

Hooks are resolved by the doc-type `code` string. A hook module
may define any subset of:

- `on_approved(db, doc)`  — called after final-step APPROVED
- `on_rejected(db, doc)`  — called after REJECTED
- `on_recalled(db, doc)`  — called after RECALLED

All hook functions are called within the same DB session as the
approval transition, but AFTER `db.commit()` of the state change.
Hooks are expected to commit their own side effects.

Failures inside a hook are logged but never raised — approval state
must not roll back if, say, calendar creation fails.
"""

from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.db.models import ApprovalDoc, ApprovalDocType
from app.services.doc_hooks import leave_hook, travel_hook

log = logging.getLogger(__name__)


# code → module mapping. Extend here as new doc types gain hooks.
_HOOKS: dict[str, object] = {
    "ATT_LEAVE": leave_hook,
    "TRAVEL_ORDER": travel_hook,
    "TRAVEL_REPORT": travel_hook,
}


def _doc_type_code(db: Session, doc: ApprovalDoc) -> str | None:
    dt = (
        db.query(ApprovalDocType)
        .filter(ApprovalDocType.id == doc.doc_type_id)
        .first()
    )
    return dt.code if dt else None


def _run(hook_fn: Callable[[Session, ApprovalDoc], None], db: Session, doc: ApprovalDoc) -> None:
    try:
        hook_fn(db, doc)
    except Exception as exc:  # never let a hook break approval state
        log.exception("doc_hook failed for doc %s: %s", doc.id, exc)


def dispatch(db: Session, doc: ApprovalDoc, event: str) -> None:
    """Run the matching post-action hook for `event`.

    `event` ∈ {"approved", "rejected", "recalled"}.
    """
    code = _doc_type_code(db, doc)
    if code is None:
        return
    module = _HOOKS.get(code)
    if module is None:
        return
    fn = getattr(module, f"on_{event}", None)
    if fn is None:
        return
    _run(fn, db, doc)
