"""Local Business record model for DaaS Engine."""

from typing import Any, Optional

from pydantic import Field, field_validator

from daas.models.base import BaseRecord, strip_and_validate_non_empty
from daas.models.enums import VerticalEnum


class LocalBusinessRecord(BaseRecord):
    """Structured record representing a local directory business listing."""

    vertical: VerticalEnum = Field(default=VerticalEnum.LOCAL_BUSINESS)
    name: str = Field(..., min_length=1, max_length=255, description="Business name")
    category: str = Field(..., min_length=1, max_length=100, description="Business industry category")
    phone: Optional[str] = Field(default=None, max_length=50, description="Contact phone number")
    address: Optional[str] = Field(default=None, max_length=500, description="Physical street address")
    city: Optional[str] = Field(default=None, max_length=100, description="City name")
    postal_code: Optional[str] = Field(default=None, max_length=20, description="Postal / ZIP code")
    website: Optional[str] = Field(default=None, max_length=500, description="Website URL or domain")
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0, description="Aggregate user rating [0.0-5.0]")
    review_count: Optional[int] = Field(default=None, ge=0, description="Total number of reviews")

    @field_validator("name", "category", mode="before")
    @classmethod
    def validate_strings(cls, v: Any) -> str:
        return strip_and_validate_non_empty(v)
