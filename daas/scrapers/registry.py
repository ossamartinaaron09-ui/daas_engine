"""Dynamic plugin registry for vertical web scrapers."""

import logging
from typing import Dict, List, Optional, Type, Union

from daas.models.enums import VerticalEnum
from daas.scrapers.base import BaseScraper
from daas.scrapers.ecommerce import EcommerceScraper
from daas.scrapers.local_business import LocalBusinessScraper
from daas.scrapers.real_estate import RealEstateScraper

logger = logging.getLogger(__name__)


class ScraperRegistry:
    """Registry allowing dynamic registration and resolution of vertical web scrapers."""

    def __init__(self, register_builtins: bool = True):
        self._registry: Dict[str, Type[BaseScraper]] = {}
        if register_builtins:
            self._register_defaults()

    def _normalize_key(self, vertical: Union[str, VerticalEnum]) -> str:
        """Normalize vertical enum or string to lowercase canonical string."""
        if isinstance(vertical, VerticalEnum):
            return vertical.value
        if isinstance(vertical, str):
            cleaned = vertical.strip().lower()
            if not cleaned:
                raise ValueError("Vertical name cannot be empty")
            return cleaned
        raise ValueError(f"Invalid vertical type: {type(vertical)}")

    def _register_defaults(self) -> None:
        """Register the built-in scrapers for standard verticals."""
        self.register(VerticalEnum.LOCAL_BUSINESS, LocalBusinessScraper)
        self.register(VerticalEnum.REAL_ESTATE, RealEstateScraper)
        self.register(VerticalEnum.ECOMMERCE, EcommerceScraper)

    def register(self, vertical: Union[str, VerticalEnum], scraper_cls: Type[BaseScraper]) -> None:
        """Register a scraper class for a vertical key.
        
        Args:
            vertical: Vertical enum or string identifier.
            scraper_cls: Subclass of BaseScraper.
            
        Raises:
            TypeError: If scraper_cls is not a subclass of BaseScraper.
        """
        if not (isinstance(scraper_cls, type) and issubclass(scraper_cls, BaseScraper)):
            raise TypeError(f"scraper_cls must be a subclass of BaseScraper, got {scraper_cls}")

        key = self._normalize_key(vertical)
        self._registry[key] = scraper_cls
        logger.debug("Registered scraper %s for vertical '%s'", scraper_cls.__name__, key)

    def unregister(self, vertical: Union[str, VerticalEnum]) -> bool:
        """Unregister a scraper by vertical key.
        
        Returns True if vertical was registered and removed, False otherwise.
        """
        key = self._normalize_key(vertical)
        if key in self._registry:
            del self._registry[key]
            return True
        return False

    def get_scraper_class(self, vertical: Union[str, VerticalEnum]) -> Type[BaseScraper]:
        """Retrieve the registered scraper class for a vertical.
        
        Args:
            vertical: Vertical enum or string identifier.
            
        Returns:
            Registered BaseScraper subclass.
            
        Raises:
            KeyError: If vertical is not registered.
        """
        key = self._normalize_key(vertical)
        if key not in self._registry:
            valid = list(self._registry.keys())
            raise KeyError(f"No scraper registered for vertical '{vertical}'. Available: {valid}")
        return self._registry[key]

    def get(self, vertical: Union[str, VerticalEnum], **kwargs) -> BaseScraper:
        """Instantiate and return a registered scraper instance.
        
        Args:
            vertical: Vertical enum or string identifier.
            **kwargs: Keyword arguments passed to scraper constructor.
            
        Returns:
            An instantiated BaseScraper object.
        """
        scraper_cls = self.get_scraper_class(vertical)
        return scraper_cls(**kwargs)

    def list_verticals(self) -> List[str]:
        """Return a sorted list of currently registered vertical names."""
        return sorted(list(self._registry.keys()))

    def clear(self) -> None:
        """Clear all registered scrapers."""
        self._registry.clear()


# Default singleton instance
default_registry = ScraperRegistry(register_builtins=True)


def get_scraper(vertical: Union[str, VerticalEnum], **kwargs) -> BaseScraper:
    """Convenience function to get an instantiated scraper from the default registry."""
    return default_registry.get(vertical, **kwargs)


def register_scraper(vertical: Union[str, VerticalEnum], scraper_cls: Type[BaseScraper]) -> None:
    """Convenience function to register a scraper in the default registry."""
    default_registry.register(vertical, scraper_cls)
