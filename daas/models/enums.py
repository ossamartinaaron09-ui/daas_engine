"""Vertical enumerations for DaaS Engine."""

from enum import Enum


class VerticalEnum(str, Enum):
    """Supported industry niches / verticals."""
    LOCAL_BUSINESS = "local_business"
    REAL_ESTATE = "real_estate"
    ECOMMERCE = "ecommerce"
