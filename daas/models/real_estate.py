"""Real Estate property listing model for DaaS Engine."""

from typing import Any, Optional

from pydantic import Field, field_validator

from daas.models.base import BaseRecord, parse_numeric_price, strip_and_validate_non_empty
from daas.models.enums import VerticalEnum


class RealEstateRecord(BaseRecord):
    """Structured record representing a real estate property listing."""

    vertical: VerticalEnum = Field(default=VerticalEnum.REAL_ESTATE)
    title: str = Field(..., min_length=1, max_length=255, description="Listing headline/title")
    price: float = Field(..., gt=0.0, description="Listing price, strictly positive")
    location: str = Field(..., min_length=1, max_length=255, description="City, address, or neighborhood")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO currency code")
    bedrooms: Optional[int] = Field(default=None, ge=0, description="Number of bedrooms")
    bathrooms: Optional[float] = Field(default=None, ge=0.0, description="Number of bathrooms")
    area_sqm: Optional[float] = Field(default=None, gt=0.0, description="Surface area in square meters")
    property_type: Optional[str] = Field(default=None, max_length=50, description="Property type (e.g. apartment, house)")
    listing_type: Optional[str] = Field(default="sale", max_length=20, description="Listing type (sale or rent)")

    @field_validator("title", "location", mode="before")
    @classmethod
    def validate_strings(cls, v: Any) -> str:
        return strip_and_validate_non_empty(v)

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: Any) -> float:
        return parse_numeric_price(v)
