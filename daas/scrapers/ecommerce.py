"""E-commerce product catalog web scraper."""

import logging
import re
from typing import Any, Dict, List, Optional

import lxml.html

from daas.models.enums import VerticalEnum
from daas.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class EcommerceScraper(BaseScraper):
    """Scraper implementation for e-commerce stores and product catalogs."""

    vertical = VerticalEnum.ECOMMERCE

    CARD_XPATHS = [
        "//div[contains(@class, 'product-card')]",
        "//article[contains(@class, 'product-card')]",
        "//div[contains(@class, 'catalog-item')]",
        "//article[contains(@class, 'catalog-item')]",
        "//div[@data-sku]",
        "//article[@data-sku]",
        "//div[contains(@class, 'product-item')]",
        "//article[contains(@class, 'product-item')]",
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
        """Parse e-commerce catalog HTML content into list of raw dictionaries."""
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
            title_nodes = root.xpath("//*[contains(@class, 'product-title')]")
            cards = [node.getparent() for node in title_nodes if node.getparent() is not None]

        results: List[Dict[str, Any]] = []

        for card in cards:
            try:
                # 1. Title
                title = (
                    self._extract_text(card, ".//*[contains(@class, 'product-title')]//a")
                    or self._extract_text(card, ".//*[contains(@class, 'product-title')]")
                    or self._extract_text(card, ".//h2//a")
                    or self._extract_text(card, ".//h2")
                    or self._extract_text(card, ".//h3")
                )

                # 2. SKU
                sku_raw = (
                    (card.attrib.get("data-sku") if hasattr(card, "attrib") else None)
                    or self._extract_text(card, ".//*[contains(@class, 'product-sku')]")
                    or self._extract_text(card, ".//*[contains(@class, 'sku')]")
                )
                sku: Optional[str] = None
                if sku_raw:
                    sku = re.sub(r"^sku\s*[:#-]?\s*", "", sku_raw, flags=re.IGNORECASE).strip()

                # 3. Price
                price_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'product-price')]")
                    or self._extract_text(card, ".//*[contains(@class, 'price')]")
                )

                # If missing mandatory elements, skip malformed card
                if not title or not sku or not price_raw:
                    continue

                # 4. Currency
                currency_raw = self._extract_text(card, ".//*[contains(@class, 'currency')]")
                currency = currency_raw.upper() if currency_raw and len(currency_raw) == 3 else self._detect_currency(price_raw)

                # 5. Brand
                brand = (
                    self._extract_text(card, ".//*[contains(@class, 'brand-name')]")
                    or self._extract_text(card, ".//*[contains(@class, 'product-brand')]")
                    or self._extract_text(card, ".//*[contains(@class, 'brand')]")
                )

                # 6. Category
                category = (
                    self._extract_text(card, ".//*[contains(@class, 'category-name')]")
                    or self._extract_text(card, ".//*[contains(@class, 'product-category')]")
                    or self._extract_text(card, ".//*[contains(@class, 'category')]")
                )

                # 7. Availability / Stock
                avail_text = (
                    self._extract_text(card, ".//*[contains(@class, 'stock-status')]")
                    or self._extract_text(card, ".//*[contains(@class, 'product-availability')]")
                    or self._extract_text(card, ".//*[contains(@class, 'availability')]")
                )
                availability = True
                if avail_text:
                    lower = avail_text.lower()
                    if "out of stock" in lower or "unavailable" in lower or "sold out" in lower:
                        availability = False
                    elif "in stock" in lower or "available" in lower:
                        availability = True

                # 8. Rating
                rating_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'rating-score')]")
                    or self._extract_text(card, ".//*[contains(@class, 'product-rating')]")
                    or self._extract_text(card, ".//*[contains(@class, 'rating')]")
                )
                rating: Optional[float] = None
                if rating_raw:
                    match = re.search(r"\b([0-5](?:\.\d+)?)\b", rating_raw)
                    if match:
                        try:
                            val = float(match.group(1))
                            if 0.0 <= val <= 5.0:
                                rating = val
                        except ValueError:
                            pass

                # 9. Review count
                reviews_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'review-total')]")
                    or self._extract_text(card, ".//*[contains(@class, 'review-count')]")
                    or self._extract_text(card, ".//*[contains(@class, 'reviews')]")
                )
                review_count: Optional[int] = None
                if reviews_raw:
                    match = re.search(r"(\d+)", reviews_raw.replace(",", ""))
                    if match:
                        try:
                            review_count = int(match.group(1))
                        except ValueError:
                            pass

                # 10. Description
                description = (
                    self._extract_text(card, ".//*[contains(@class, 'product-description')]")
                    or self._extract_text(card, ".//*[contains(@class, 'description')]")
                    or self._extract_text(card, ".//p[contains(@class, 'desc')]")
                )

                # 11. Source URL
                source_url = (
                    self._extract_attr(card, ".//*[contains(@class, 'product-title')]//a", "href")
                    or self._extract_attr(card, ".//h2//a", "href")
                )

                record: Dict[str, Any] = {
                    "vertical": self.vertical.value,
                    "title": title,
                    "sku": sku,
                    "price": price_raw,
                    "currency": currency,
                    "brand": brand,
                    "category": category,
                    "availability": availability,
                    "rating": rating,
                    "review_count": review_count,
                    "description": description,
                    "source_url": source_url,
                }
                results.append(record)
            except Exception as exc:
                logger.warning("Error parsing e-commerce card element: %s", exc)
                continue

        return results
