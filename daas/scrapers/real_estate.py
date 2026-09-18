"""Real Estate property listings web scraper."""

import logging
import re
from typing import Any, Dict, List, Optional

import lxml.html

from daas.models.enums import VerticalEnum
from daas.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class RealEstateScraper(BaseScraper):
    """Scraper implementation for real estate property portals and listings."""

    vertical = VerticalEnum.REAL_ESTATE

    CARD_XPATHS = [
        "//article[contains(@class, 'property-card')]",
        "//div[contains(@class, 'property-card')]",
        "//article[contains(@class, 'listing-card')]",
        "//div[contains(@class, 'listing-card')]",
        "//article[@data-listing-id]",
        "//div[@data-listing-id]",
        "//article[contains(@class, 'property-item')]",
        "//div[contains(@class, 'property-item')]",
    ]

    def _extract_text(self, element: lxml.html.HtmlElement, xpath_expr: str) -> Optional[str]:
        """Safely extract stripped text content matching an XPath expression."""
        nodes = element.xpath(xpath_expr)
        if not nodes:
            return None
        node = nodes[0]
        if isinstance(node, str):
            text = node.strip()
        elif hasattr(node, "text_content"):
            text = node.text_content().strip()
        else:
            text = str(node).strip()
        return " ".join(text.split()) if text else None

    def _extract_attr(self, element: lxml.html.HtmlElement, xpath_expr: str, attr_name: str) -> Optional[str]:
        """Safely extract an attribute value matching an XPath expression."""
        nodes = element.xpath(xpath_expr)
        if not nodes:
            return None
        node = nodes[0]
        if hasattr(node, "attrib") and attr_name in node.attrib:
            val = node.attrib[attr_name].strip()
            return val if val else None
        return None

    def _detect_currency(self, text: Optional[str], fallback: str = "USD") -> str:
        """Infer 3-letter ISO currency code from symbol or text."""
        if not text:
            return fallback
        if "€" in text or "EUR" in text.upper():
            return "EUR"
        if "£" in text or "GBP" in text.upper():
            return "GBP"
        if "$" in text or "USD" in text.upper():
            return "USD"
        return fallback

    def parse(self, html_content: str) -> List[Dict[str, Any]]:
        """Parse real estate HTML content into list of raw dictionaries."""
        root = self._parse_html_root(html_content)
        if root is None:
            return []

        cards: List[lxml.html.HtmlElement] = []
        for xpath in self.CARD_XPATHS:
            found = root.xpath(xpath)
            if found:
                cards = found
                break

        if not cards:
            title_nodes = root.xpath("//*[contains(@class, 'property-title')]")
            cards = [node.getparent() for node in title_nodes if node.getparent() is not None]

        results: List[Dict[str, Any]] = []

        for card in cards:
            try:
                # 1. Title
                title = (
                    self._extract_text(card, ".//*[contains(@class, 'property-title')]//a")
                    or self._extract_text(card, ".//*[contains(@class, 'property-title')]")
                    or self._extract_text(card, ".//h2//a")
                    or self._extract_text(card, ".//h2")
                    or self._extract_text(card, ".//h3")
                )

                # 2. Price text
                price_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'price-value')]")
                    or self._extract_text(card, ".//*[contains(@class, 'property-price')]")
                    or self._extract_text(card, ".//*[contains(@class, 'price')]")
                )

                # 3. Location
                location = (
                    self._extract_text(card, ".//*[contains(@class, 'location-text')]")
                    or self._extract_text(card, ".//*[contains(@class, 'property-location')]")
                    or self._extract_text(card, ".//*[contains(@class, 'location')]")
                    or self._extract_text(card, ".//address")
                )

                # If missing mandatory elements, skip malformed card
                if not title or not price_raw or not location:
                    continue

                # 4. Currency
                currency_raw = self._extract_text(card, ".//*[contains(@class, 'currency')]")
                currency = currency_raw.upper() if currency_raw and len(currency_raw) == 3 else self._detect_currency(price_raw)

                # 5. Bedrooms
                bedrooms_text = (
                    self._extract_text(card, ".//*[contains(@class, 'spec-bedrooms')]//*[contains(@class, 'value')]")
                    or self._extract_text(card, ".//*[contains(@class, 'spec-bedrooms')]")
                    or self._extract_text(card, ".//*[contains(@class, 'bedrooms')]")
                    or self._extract_text(card, ".//*[contains(@class, 'beds')]")
                )
                bedrooms: Optional[int] = None
                if bedrooms_text:
                    if "studio" in bedrooms_text.lower():
                        bedrooms = 0
                    else:
                        match = re.search(r"(\d+)", bedrooms_text)
                        if match:
                            bedrooms = int(match.group(1))

                # 6. Bathrooms
                bathrooms_text = (
                    self._extract_text(card, ".//*[contains(@class, 'spec-bathrooms')]//*[contains(@class, 'value')]")
                    or self._extract_text(card, ".//*[contains(@class, 'spec-bathrooms')]")
                    or self._extract_text(card, ".//*[contains(@class, 'bathrooms')]")
                    or self._extract_text(card, ".//*[contains(@class, 'baths')]")
                )
                bathrooms: Optional[float] = None
                if bathrooms_text:
                    match = re.search(r"(\d+(?:\.\d+)?)", bathrooms_text)
                    if match:
                        bathrooms = float(match.group(1))

                # 7. Area in sqm
                area_text = (
                    self._extract_text(card, ".//*[contains(@class, 'spec-area')]//*[contains(@class, 'value')]")
                    or self._extract_text(card, ".//*[contains(@class, 'spec-area')]")
                    or self._extract_text(card, ".//*[contains(@class, 'area')]")
                )
                area_sqm: Optional[float] = None
                if area_text:
                    match = re.search(r"(\d+(?:\.\d+)?)", area_text.replace(",", "."))
                    if match:
                        area_sqm = float(match.group(1))

                # 8. Property type
                property_type = (
                    self._extract_text(card, ".//*[contains(@class, 'property-type')]")
                    or self._extract_text(card, ".//*[contains(@class, 'type')]")
                )
                if property_type:
                    property_type = property_type.lower()

                # 9. Listing type
                listing_type = (
                    self._extract_text(card, ".//*[contains(@class, 'listing-type')]")
                )
                if not listing_type:
                    listing_type = "rent" if "month" in price_raw.lower() or "rent" in price_raw.lower() else "sale"
                else:
                    listing_type = listing_type.lower()

                # 10. Source URL
                source_url = (
                    self._extract_attr(card, ".//*[contains(@class, 'property-title')]//a", "href")
                    or self._extract_attr(card, ".//h2//a", "href")
                )

                record: Dict[str, Any] = {
                    "vertical": self.vertical.value,
                    "title": title,
                    "price": price_raw,
                    "location": location,
                    "currency": currency,
                    "bedrooms": bedrooms,
                    "bathrooms": bathrooms,
                    "area_sqm": area_sqm,
                    "property_type": property_type,
                    "listing_type": listing_type,
                    "source_url": source_url,
                }
                results.append(record)
            except Exception as exc:
                logger.warning("Error parsing real estate card element: %s", exc)
                continue

        return results
