"""Data models and vertical registry for DaaS Engine."""

from typing import Any, Dict, Type, Union

from daas.models.base import BaseRecord, parse_numeric_price, strip_and_validate_non_empty
from daas.models.ecommerce import EcommerceRecord
from daas.models.enums import VerticalEnum
from daas.models.local_business import LocalBusinessRecord
from daas.models.real_estate import RealEstateRecord

VERTICAL_MODEL_MAP: Dict[VerticalEnum, Type[BaseRecord]] = {
    VerticalEnum.LOCAL_BUSINESS: LocalBusinessRecord,
    VerticalEnum.REAL_ESTATE: RealEstateRecord,
    VerticalEnum.ECOMMERCE: EcommerceRecord,
}


def get_model_for_vertical(vertical: Union[str, VerticalEnum]) -> Type[BaseRecord]:
    """Retrieve the Pydantic model class for a specific vertical.
    
    Args:
        vertical: VerticalEnum instance or case-insensitive string name.
        
    Returns:
        The concrete Pydantic model class (LocalBusinessRecord, RealEstateRecord, EcommerceRecord).
        
    Raises:
        ValueError: If vertical is unknown or unsupported.
    """
    if isinstance(vertical, VerticalEnum):
        key = vertical
    elif isinstance(vertical, str):
        cleaned = vertical.strip().lower()
        try:
            key = VerticalEnum(cleaned)
        except ValueError:
            valid_values = [v.value for v in VerticalEnum]
            raise ValueError(f"Unknown vertical '{vertical}'. Must be one of: {valid_values}")
    else:
        raise ValueError(f"Invalid vertical type: {type(vertical)}")

    if key in VERTICAL_MODEL_MAP:
        return VERTICAL_MODEL_MAP[key]
    raise ValueError(f"No model registered for vertical: '{key}'")


def create_record(data: Dict[str, Any]) -> BaseRecord:
    """Validate and instantiate a concrete record model based on the 'vertical' field."""
    vertical_raw = data.get("vertical")
    if not vertical_raw:
        raise ValueError("Missing mandatory 'vertical' field in record payload")
    model_cls = get_model_for_vertical(vertical_raw)
    return model_cls(**data)


__all__ = [
    "VerticalEnum",
    "BaseRecord",
    "LocalBusinessRecord",
    "RealEstateRecord",
    "EcommerceRecord",
    "VERTICAL_MODEL_MAP",
    "get_model_for_vertical",
    "create_record",
    "strip_and_validate_non_empty",
    "parse_numeric_price",
]
