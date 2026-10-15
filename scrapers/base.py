"""Base scraper contract — all scrapers must inherit this."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Deal:
    title: str
    brand: str
    original_price: float
    sale_price: float
    discount_pct: float
    available_sizes: list[str]
    product_url: str
    source: str
    image_url: Optional[str] = None
    wow_price: Optional[float] = None
    wow_discount_pct: Optional[float] = None
    gender: Optional[str] = None  # e.g. 'men', 'women', 'unisex', 'kids'

    @property
    def deal_id(self) -> str:
        """Stable unique key for deduplication."""
        return f"{self.source}::{self.product_url}"


class BaseScraper(ABC):
    name: str = "base"

    @abstractmethod
    def scrape(self, query: str, max_products: int = 40, max_pages: int | None = None) -> list[Deal]:
        """Scrape deals for the given search query."""
        ...
