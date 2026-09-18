"""E-commerce product record model for DaaS Engine."""

from typing import Any, Optional

from pydantic import Field, field_validator

from daas.models.base import BaseRecord, parse_numeric_price, strip_and_validate_non_empty
from daas.models.enums import VerticalEnum


class EcommerceRecord(BaseRecord):
    """Structured record representing an e-commerce catalog product."""

    vertical: VerticalEnum = Field(default=VerticalEnum.ECOMMERCE)
    title: str = Field(..., min_length=1, max_length=255, description="Product title")
    price: float = Field(..., ge=0.0, description="Product price, non-negative")
    sku: str = Field(..., min_length=1, max_length=100, description="Stock keeping unit or product ID")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO currency code")
    brand: Optional[str] = Field(default=None, max_length=100, description="Product brand name")
    category: Optional[str] = Field(default=None, max_length=100, description="Product category / taxonomy")
    availability: bool = Field(default=True, description="True if item is in stock")
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0, description="Customer review rating [0.0-5.0]")
    review_count: Optional[int] = Field(default=None, ge=0, description="Total review count")
    description: Optional[str] = Field(default=None, description="Detailed product description")

    @field_validator("title", "sku", mode="before")
    @classmethod
    def validate_strings(cls, v: Any) -> str:
        return strip_and_validate_non_empty(v)

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: Any) -> float:
        return parse_numeric_price(v)
