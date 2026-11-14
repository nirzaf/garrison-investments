from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

BusinessCurrency = Literal["USD", "LKR", "QAR"]
DEFAULT_BUSINESS_CURRENCY: BusinessCurrency = "USD"
SUPPORTED_BUSINESS_CURRENCIES: tuple[BusinessCurrency, ...] = ("USD", "LKR", "QAR")
MAX_MONEY = Decimal("999999999999.99")


class BusinessPolicy(BaseModel):
    """Shared validation for application settings and proposed CLI configuration."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    business_currency: BusinessCurrency = DEFAULT_BUSINESS_CURRENCY
    business_timezone: str = "Asia/Qatar"
    material_approval_threshold: Decimal = Field(
        default=Decimal("1000.00"), ge=0, le=MAX_MONEY, max_digits=14, decimal_places=2
    )

    @field_validator("business_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if value in {"Factory", "localtime", "posixrules"} or value.startswith(
            ("posix/", "right/")
        ):
            raise ValueError("Use an IANA timezone such as Asia/Qatar or Etc/UTC.")
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("Use an IANA timezone such as Asia/Qatar or Etc/UTC.") from error
        return value

    @field_validator("material_approval_threshold", mode="before")
    @classmethod
    def validate_threshold_input(cls, value: object) -> object:
        if isinstance(value, float | bool):
            raise ValueError("Supply the approval threshold as an exact decimal string.")
        return value


class BusinessPolicyResponse(BusinessPolicy):
    threshold_comparison: Literal["greater_than"] = "greater_than"
    invoice_tax_mode: Literal["explicit_amount"] = "explicit_amount"
    money_decimal_places: Literal[2] = 2
    supported_business_currencies: tuple[BusinessCurrency, ...] = SUPPORTED_BUSINESS_CURRENCIES
