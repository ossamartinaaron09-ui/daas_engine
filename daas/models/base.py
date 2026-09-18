"""Base model and reusable validation helpers for DaaS Engine records."""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field

from daas.models.enums import VerticalEnum


def strip_and_validate_non_empty(v: Any) -> str:
    """Validate that input is a non-empty string after stripping whitespace."""
    if isinstance(v, str):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace-only")
        return cleaned
    raise ValueError("Field must be a string")


def parse_numeric_price(v: Any) -> float:
    """Parse numeric price from float, int, or formatted currency string.
    
    Handles formats such as:
    - 129.99 -> 129.99
    - "$1,299.99" -> 1299.99
    - "€ 450.000" -> 450000.0
    - "€ 1.250.000,00" -> 1250000.0
    - "$450,000 / month" -> 450000.0
    """
    if isinstance(v, bool):
        raise ValueError("Boolean is not a valid price")
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        raise ValueError("Invalid price type: must be float, int, or string")

    text = v.strip()
    if not text:
        raise ValueError("Price string cannot be empty or whitespace-only")

    if not any(c.isdigit() for c in text):
        raise ValueError(f"Cannot parse numeric price from string: '{v}'")

    # Extract numeric substring with commas, dots, and optional sign
    match = re.search(r"[-+]?[\d.,\s]+", text)
    if not match:
        raise ValueError(f"Cannot parse numeric price from string: '{v}'")

    s = match.group(0).strip().replace(" ", "")

    if "," in s and "." in s:
        # Both separators present: check which comes last
        if s.rfind(".") > s.rfind(","):
            # US format: 1,299.99 -> commas are thousand separators
            s = s.replace(",", "")
        else:
            # European format: 1.250.000,00 -> dots are thousand separators, comma is decimal
            s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            # Decimal comma: e.g. 45,50 or 129,99
            s = s.replace(",", ".")
        else:
            # Thousand separator: e.g. 1,000 or 1,250,000
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2:
            # Multiple dots: e.g. 1.250.000 -> thousand separators
            s = s.replace(".", "")
        elif len(parts) == 2 and len(parts[1]) == 3 and ("€" in text or float(parts[0]) >= 10):
            # European thousand separator with single dot: e.g. € 450.000
            s = s.replace(".", "")

    try:
        return float(s)
    except ValueError as exc:
        raise ValueError(f"Cannot parse numeric price from string: '{v}'") from exc


class BaseRecord(BaseModel):
    """Foundational record model with universal fields."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: Optional[int] = Field(default=None, description="Database unique identifier")
    vertical: VerticalEnum = Field(..., description="Industry niche/vertical discriminator")
    source_url: Optional[str] = Field(default=None, description="Source URL of scraped item")
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC ingestion timestamp",
    )
    raw_data: Optional[Dict[str, Any]] = Field(default=None, description="Audit raw extraction dictionary")
