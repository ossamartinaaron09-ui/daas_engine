"""Web scraping modules and vertical registry for DaaS Engine."""

from daas.scrapers.base import BaseScraper, ScraperFetchError
from daas.scrapers.ecommerce import EcommerceScraper
from daas.scrapers.local_business import LocalBusinessScraper
from daas.scrapers.real_estate import RealEstateScraper
from daas.scrapers.registry import (
    ScraperRegistry,
    default_registry,
    get_scraper,
    register_scraper,
)

__all__ = [
    "BaseScraper",
    "ScraperFetchError",
    "LocalBusinessScraper",
    "RealEstateScraper",
    "EcommerceScraper",
    "ScraperRegistry",
    "default_registry",
    "get_scraper",
    "register_scraper",
]
