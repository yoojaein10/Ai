from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PartnerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company_code: str = Field(min_length=4, max_length=4)
    business_no: str
    name: str = Field(min_length=1, max_length=60)
    short_name: str | None = Field(default=None, max_length=60)
    representative: str | None = Field(default=None, max_length=30)
    business_type: str | None = Field(default=None, max_length=40)
    business_item: str | None = Field(default=None, max_length=40)
    postal_code: str | None = Field(default=None, max_length=7)
    address1: str | None = Field(default=None, max_length=150)
    address2: str | None = Field(default=None, max_length=150)
    telephone: str | None = Field(default=None, max_length=20)
    fax: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=80)
    partner_type: Literal["1", "2", "4"] = "1"
    partner_code: str | None = Field(default=None, max_length=10)
    insert_id: str | None = Field(default=None, max_length=30)

    @field_validator("business_no", mode="before")
    @classmethod
    def normalize_business_no(cls, value: object) -> str:
        normalized = "".join(character for character in str(value) if character.isdigit())
        if not is_valid_business_number(normalized):
            raise ValueError("올바른 10자리 사업자등록번호가 아닙니다.")
        return normalized

    @model_validator(mode="after")
    def validate_manual_partner_code(self) -> "PartnerCreate":
        if self.partner_code is not None and not self.partner_code:
            self.partner_code = None
        return self

    def to_amaranth_item(self) -> dict[str, str]:
        item: dict[str, str] = {
            "coCd": self.company_code,
            "trNm": self.name,
            "attrNm": self.short_name or self.name,
            "trFg": self.partner_type,
            "regNb": self.business_no,
            "inputFg": "1" if self.partner_code else "0",
        }
        optional_fields = {
            "trCd": self.partner_code,
            "ceoNm": self.representative,
            "business": self.business_type,
            "jongmok": self.business_item,
            "zip": self.postal_code,
            "divAddr1": self.address1,
            "addr2": self.address2,
            "tel": self.telephone,
            "fax": self.fax,
            "email": self.email,
        }
        item.update({key: value for key, value in optional_fields.items() if value})
        return item


def is_valid_business_number(value: str) -> bool:
    """국세청 사업자등록번호 체크섬을 검증한다."""

    if len(value) != 10 or not value.isdigit():
        return False
    digits = [int(character) for character in value]
    weights = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    total = sum(digit * weight for digit, weight in zip(digits[:9], weights))
    total += (digits[8] * 5) // 10
    check_digit = (10 - (total % 10)) % 10
    return check_digit == digits[9]

