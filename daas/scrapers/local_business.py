"""Local Business web directory scraper."""

import logging
import re
from typing import Any, Dict, List, Optional

import lxml.html

from daas.models.enums import VerticalEnum
from daas.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class LocalBusinessScraper(BaseScraper):
    """Scraper implementation for local business directories."""

    vertical = VerticalEnum.LOCAL_BUSINESS

    # Card container selectors in order of preference
    CARD_XPATHS = [
        "//div[contains(@class, 'business-card')]",
        "//article[contains(@class, 'business-card')]",
        "//div[contains(@class, 'directory-item')]",
        "//article[contains(@class, 'directory-item')]",
        "//div[@data-biz-id]",
        "//div[contains(@class, 'listing-item') and .//*[contains(@class, 'business-name')]]",
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

    def parse(self, html_content: str) -> List[Dict[str, Any]]:
        """Parse local business directory HTML content into list of raw dictionaries."""
        root = self._parse_html_root(html_content)
        if root is None:
            return []

        # Find all card elements across known container selectors
        cards: List[lxml.html.HtmlElement] = []
        for xpath in self.CARD_XPATHS:
            found = root.xpath(xpath)
            if found:
                cards = found
                break

        # Fallback: if no specific container matches, search for any element containing business-name
        if not cards:
            name_nodes = root.xpath("//*[contains(@class, 'business-name')]")
            cards = [node.getparent() for node in name_nodes if node.getparent() is not None]

        results: List[Dict[str, Any]] = []

        for card in cards:
            try:
                # 1. Name
                name = (
                    self._extract_text(card, ".//*[contains(@class, 'business-name')]//a")
                    or self._extract_text(card, ".//*[contains(@class, 'business-name')]")
                    or self._extract_text(card, ".//h2//a")
                    or self._extract_text(card, ".//h2")
                    or self._extract_text(card, ".//h3")
                )

                # 2. Category
                category = (
                    self._extract_text(card, ".//*[contains(@class, 'business-category')]")
                    or self._extract_text(card, ".//*[contains(@class, 'category')]")
                    or self._extract_text(card, ".//*[contains(@class, 'niche')]")
                )

                # If missing both primary identifiers, card is malformed/irrelevant
                if not name and not category:
                    continue

                # 3. Phone
                phone = (
                    self._extract_text(card, ".//*[contains(@class, 'business-phone')]")
                    or self._extract_text(card, ".//*[contains(@class, 'phone')]")
                    or self._extract_text(card, ".//a[starts-with(@href, 'tel:')]")
                )

                # 4. Address, City, Postal Code
                address = (
                    self._extract_text(card, ".//*[contains(@class, 'business-address')]")
                    or self._extract_text(card, ".//*[contains(@class, 'address')]")
                    or self._extract_text(card, ".//address")
                )
                city = (
                    self._extract_text(card, ".//*[contains(@class, 'business-city')]")
                    or self._extract_text(card, ".//*[contains(@class, 'city')]")
                )
                postal_code = (
                    self._extract_text(card, ".//*[contains(@class, 'business-postal')]")
                    or self._extract_text(card, ".//*[contains(@class, 'postal')]")
                    or self._extract_text(card, ".//*[contains(@class, 'zip')]")
                )

                # 5. Website
                website = (
                    self._extract_attr(card, ".//*[contains(@class, 'business-website')]", "href")
                    or self._extract_attr(card, ".//a[contains(@class, 'website')]", "href")
                    or self._extract_text(card, ".//*[contains(@class, 'business-website')]")
                    or self._extract_attr(card, ".//a[starts-with(@href, 'http') and not(contains(@class, 'business-name'))]", "href")
                )

                # 6. Rating
                rating_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'rating-value')]")
                    or self._extract_text(card, ".//*[contains(@class, 'rating')]")
                    or self._extract_text(card, ".//*[contains(@class, 'score')]")
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

                # 7. Review count
                reviews_raw = (
                    self._extract_text(card, ".//*[contains(@class, 'review-count')]")
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

                # 8. Source URL
                source_url = (
                    self._extract_attr(card, ".//*[contains(@class, 'business-name')]//a", "href")
                    or self._extract_attr(card, ".//h2//a", "href")
                )

                record: Dict[str, Any] = {
                    "vertical": self.vertical.value,
                    "name": name,
                    "category": category,
                    "phone": phone,
                    "address": address,
                    "city": city,
                    "postal_code": postal_code,
                    "website": website,
                    "rating": rating,
                    "review_count": review_count,
                    "source_url": source_url,
                }
                results.append(record)
            except Exception as exc:
                logger.warning("Error parsing business card element: %s", exc)
                continue

        return results
