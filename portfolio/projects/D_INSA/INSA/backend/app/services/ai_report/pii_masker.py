"""PII 마스킹 / 언마스킹 — Gemini 호출 전후 변환.

마스킹 대상:
- 직원 식별자(사번 + 이름) → `__INSA_EMP_NNN__` / `__INSA_RATER_NNN__`
- 코멘트 본문 내 등록 직원 이름 → 식별자와 동일 placeholder

부서명·직급명은 원문 유지 (코칭 품질 위해).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


RestoreMap = dict[str, str]
Role = Literal["employee", "rater"]


@dataclass
class PiiMasker:
    employee_names: list[str]
    _emp_counter: int = 0
    _rater_counter: int = 0
    _emp_id_to_placeholder: dict[tuple[Role, int], str] = field(default_factory=dict)
    _name_to_placeholder: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._sorted_names = sorted(set(self.employee_names), key=len, reverse=True)

    def mask_identifier(
        self,
        emp_id: int,
        name: str,
        role: Role,
    ) -> tuple[str, RestoreMap]:
        key = (role, emp_id)
        if key in self._emp_id_to_placeholder:
            placeholder = self._emp_id_to_placeholder[key]
        else:
            if role == "employee":
                self._emp_counter += 1
                placeholder = f"__INSA_EMP_{self._emp_counter:03d}__"
            else:
                self._rater_counter += 1
                placeholder = f"__INSA_RATER_{self._rater_counter:03d}__"
            self._emp_id_to_placeholder[key] = placeholder
            self._name_to_placeholder[name] = placeholder
        restore = {placeholder: f"{name}(E{emp_id:03d})"}
        return placeholder, restore

    def mask_text(
        self,
        text: str | None,
        existing_restore: RestoreMap | None = None,
    ) -> tuple[str, RestoreMap]:
        if not text:
            return text or "", existing_restore or {}
        restore: RestoreMap = dict(existing_restore or {})
        masked = text
        for name in self._sorted_names:
            if name not in masked:
                continue
            if name in self._name_to_placeholder:
                placeholder = self._name_to_placeholder[name]
            else:
                self._emp_counter += 1
                placeholder = f"__INSA_EMP_{self._emp_counter:03d}__"
                self._name_to_placeholder[name] = placeholder
            masked = masked.replace(name, placeholder)
            if placeholder not in restore:
                restore[placeholder] = name
        return masked, restore

    @staticmethod
    def unmask(text: str, restore: RestoreMap) -> str:
        if not text:
            return text or ""
        result = text
        for placeholder in sorted(restore.keys(), key=len, reverse=True):
            result = result.replace(placeholder, restore[placeholder])
        return result
