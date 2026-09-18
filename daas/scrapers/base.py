"""Base scraper interface and lifecycle abstractions for DaaS Engine."""

import abc
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

import lxml.etree
import lxml.html

from daas.models import BaseRecord, VerticalEnum, get_model_for_vertical

logger = logging.getLogger(__name__)


class ScraperFetchError(Exception):
    """Raised when an HTTP fetch operation fails."""
    pass


class BaseScraper(abc.ABC):
    """Abstract base scraper defining standard lifecycle methods across verticals."""

    vertical: VerticalEnum

    def __init__(self, default_headers: Optional[Dict[str, str]] = None, timeout: float = 10.0):
        self.default_headers = default_headers or {
            "User-Agent": "Mozilla/5.0 (compatible; DaaSEngine/0.1.0; +https://github.com/daas-engine)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        self.timeout = timeout

    def fetch(self, url: str, headers: Optional[Dict[str, str]] = None, timeout: Optional[float] = None) -> str:
        """Fetch remote HTML content using standard HTTP request.
        
        Args:
            url: Target web address.
            headers: Optional HTTP headers override.
            timeout: Optional request timeout in seconds.
            
        Returns:
            Decoded HTML body as string.
            
        Raises:
            ScraperFetchError: If network error or HTTP error occurs.
        """
        merged_headers = dict(self.default_headers)
        if headers:
            merged_headers.update(headers)

        req = urllib.request.Request(url, headers=merged_headers)
        to = timeout if timeout is not None else self.timeout

        try:
            with urllib.request.urlopen(req, timeout=to) as response:
                content_type = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(content_type, errors="replace")
                return body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            raise ScraperFetchError(f"HTTP fetch error for {url}: {exc}") from exc

    def _parse_html_root(self, html_content: str) -> Optional[lxml.html.HtmlElement]:
        """Safely parse HTML string into an lxml HtmlElement tree.
        
        Returns None if input is empty, whitespace, or unparseable.
        """
        if not html_content or not html_content.strip():
            return None

        try:
            return lxml.html.fromstring(html_content)
        except (lxml.etree.ParserError, lxml.etree.XMLSyntaxError, ValueError) as exc:
            logger.warning("HTML parsing failure: %s", exc)
            return None

    def clean(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and sanitize raw extracted dictionary before Pydantic validation.
        
        Strips leading/trailing whitespace from string values and normalizes whitespace.
        """
        cleaned: Dict[str, Any] = {}
        for key, value in raw_record.items():
            if isinstance(value, str):
                s = " ".join(value.split()).strip()
                cleaned[key] = s if s else None
            elif isinstance(value, dict):
                cleaned[key] = self.clean(value)
            else:
                cleaned[key] = value
        return cleaned

    @abc.abstractmethod
    def parse(self, html_content: str) -> List[Dict[str, Any]]:
        """Parse raw HTML string and return extracted record dictionaries.
        
        Must be implemented by concrete vertical scrapers.
        """
        raise NotImplementedError("Subclasses must implement parse()")

    def extract_all(
        self,
        html_content: str,
        source_url: Optional[str] = None,
        strict: bool = False,
    ) -> List[BaseRecord]:
        """Extract, clean, and validate all records from HTML into Pydantic models.
        
        Args:
            html_content: Raw HTML text to extract from.
            source_url: Optional origin URL to tag records with.
            strict: If True, raises ValidationError on invalid items; if False, skips with warning.
            
        Returns:
            List of validated concrete Pydantic record instances.
        """
        raw_items = self.parse(html_content)
        model_cls = get_model_for_vertical(self.vertical)
        validated_records: List[BaseRecord] = []

        for item in raw_items:
            try:
                cleaned_item = self.clean(item)
                # Ensure vertical is set
                cleaned_item["vertical"] = self.vertical
                if source_url and not cleaned_item.get("source_url"):
                    cleaned_item["source_url"] = source_url
                if "raw_data" not in cleaned_item:
                    cleaned_item["raw_data"] = dict(item)

                record = model_cls(**cleaned_item)
                validated_records.append(record)
            except Exception as exc:
                logger.warning("Record validation failure for vertical %s: %s", self.vertical, exc)
                if strict:
                    raise

        return validated_records
