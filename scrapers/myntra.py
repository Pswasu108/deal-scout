"""
Myntra scraper.

Myntra is a React SPA. The listing page serves an HTML shell; actual
product data is loaded client-side. We extract what's embedded in the
initial HTML (a JSON blob in window.__PRELOADED_STATE__ or a meta tag),
then fall back to visible card DOM elements.
"""
from __future__ import annotations
import json
import re
import time

from bs4 import BeautifulSoup

from .base import BaseScraper, Deal
from .http_client import make_client

SEARCH_URL = "https://www.myntra.com/{slug}"
HEADERS_EXTRA = {"Referer": "https://www.myntra.com/"}


class MyntraScraper(BaseScraper):
    name = "myntra"

    def __init__(self, delay: float = 2.0, timeout: int = 15, max_retries: int = 3, pincode: str = "110009", **kwargs):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.pincode = str(pincode or "110009").strip()

    def scrape(
        self,
        query: str,
        max_products: int = 40,
        max_pages: int | None = None,
        brands: list[str] | None = None,
    ) -> list[Deal]:
        import urllib.parse
        if max_pages is None:
            max_pages = max(2, (max_products + 31) // 32)
        slug = query.strip().lower().replace(" ", "-")

        all_deals: list[Deal] = []
        for page in range(1, max_pages + 1):
            url = f"{SEARCH_URL.format(slug=slug)}?p={page}"
            html = self._fetch(url)
            if not html:
                break
            deals = self._parse(html, url)
            if not deals:
                break
            all_deals.extend(deals)
            if len(all_deals) >= max_products:
                break
        return all_deals[:max_products]

    def _fetch(self, url: str) -> str | None:
        headers = dict(HEADERS_EXTRA)
        if self.pincode:
            headers["Cookie"] = f"pincode={self.pincode}"
            headers["x-pincode"] = self.pincode
        for attempt in range(self.max_retries):
            try:
                with make_client(extra_headers=headers, timeout=self.timeout) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        return resp.text
                    print(f"  [myntra] HTTP {resp.status_code}")
            except Exception as e:
                print(f"  [myntra] attempt {attempt+1} error: {e}")
            time.sleep(self.delay)
        return None

    def _parse(self, html: str, base_url: str) -> list[Deal]:
        soup = BeautifulSoup(html, "lxml")
        deals: list[Deal] = []

        # 1. Try embedded JSON blob (window.__myx or window.__PRELOADED_STATE__)
        m = re.search(r"window\.(?:__myx|__PRELOADED_STATE__)\s*=\s*({.*?})\s*(?:;|</script>|$)", html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                products = (
                    data.get("searchData", {}).get("results", {}).get("products", [])
                    or data.get("pageData", {}).get("data", {}).get("searchData", {}).get("results", [])
                )
                for p in products:
                    d = self._product_to_deal(p)
                    if d:
                        deals.append(d)
                if deals:
                    return deals
            except Exception:
                pass

        # DOM fallback: product-base list items
        for card in soup.select("li.product-base"):
            try:
                d = self._card_to_deal(card)
                if d:
                    deals.append(d)
            except Exception:
                continue

        if not deals:
            print("  [myntra] Note: Myntra is a SPA — static HTML may not contain products. Consider enabling Playwright.")

        return deals

    def _product_to_deal(self, p: dict) -> Deal | None:
        try:
            title = p.get("productName", "")
            brand = p.get("brand", "")
            mrp = float(p.get("mrp", 0))
            price = float(p.get("price", mrp))
            discount = round((mrp - price) / mrp * 100, 1) if mrp else 0.0
            sizes_raw = p.get("sizes", "") or ""
            sizes = [s.strip() for s in sizes_raw.split(",") if s.strip()]
            url = f"https://www.myntra.com/{p.get('landingPageUrl', '')}"

            # Extract Myntra "Best Price" with coupon into wow_price
            wow_price = None
            wow_discount_pct = None
            coupon_data = p.get("couponData") or {}
            if isinstance(coupon_data, dict):
                coupon_desc = coupon_data.get("couponDescription") or {}
                raw_best = coupon_desc.get("bestPrice") or coupon_data.get("bestPrice")
                if raw_best is not None:
                    try:
                        wow_price = float(raw_best)
                    except (ValueError, TypeError):
                        pass
                elif coupon_data.get("couponDiscount"):
                    try:
                        wow_price = price - float(coupon_data["couponDiscount"])
                    except (ValueError, TypeError):
                        pass

            if wow_price and 0 < wow_price < price:
                wow_discount_pct = round((mrp - wow_price) / mrp * 100, 1) if mrp and mrp > wow_price else None
            else:
                wow_price = None

            image_url = p.get("searchImage", "") or p.get("imageUrls", {}).get("default", "")

            return Deal(
                title=title, brand=brand,
                original_price=mrp, sale_price=price, discount_pct=discount,
                available_sizes=sizes, product_url=url, source="myntra",
                image_url=image_url,
                wow_price=wow_price,
                wow_discount_pct=wow_discount_pct,
            )
        except Exception:
            return None

    def _card_to_deal(self, card) -> Deal | None:
        brand_el = card.select_one("h3.product-brand")
        title_el = card.select_one("h4.product-product")
        mrp_el = card.select_one("span.product-strike")
        price_el = card.select_one("div.product-price span")
        disc_el = card.select_one("span.product-discountPercentage")
        url_el = card.select_one("a")

        brand = brand_el.get_text(strip=True) if brand_el else ""
        title = title_el.get_text(strip=True) if title_el else ""

        def clean(el, default="0"):
            if not el:
                return default
            return re.sub(r"[^\d.]", "", el.get_text(strip=True)) or default

        mrp = float(clean(mrp_el))
        price = float(clean(price_el))
        disc_raw = clean(disc_el)
        discount = float(disc_raw) if disc_raw else (round((mrp - price) / mrp * 100, 1) if mrp and price else 0)

        # Check DOM for "Best Price" text
        wow_price = None
        wow_discount_pct = None
        for el in card.select("[class*='coupon'], [class*='bestPrice'], span, div"):
            t = el.get_text(strip=True)
            if "Best Price" in t:
                m_bp = re.search(r"Best\s*Price.*?₹?\s*(\d[\d,]*)", t, re.IGNORECASE)
                if m_bp:
                    try:
                        raw_bp = float(m_bp.group(1).replace(",", ""))
                        if 0 < raw_bp < price:
                            wow_price = raw_bp
                            wow_discount_pct = round((mrp - wow_price) / mrp * 100, 1) if mrp and mrp > wow_price else None
                            break
                    except (ValueError, TypeError):
                        pass

        href = url_el["href"] if url_el and url_el.get("href") else ""
        full_url = href if href.startswith("http") else f"https://www.myntra.com{href}"

        return Deal(
            title=f"{brand} {title}".strip(),
            brand=brand,
            original_price=mrp, sale_price=price, discount_pct=discount,
            available_sizes=[],
            product_url=full_url, source="myntra",
            wow_price=wow_price,
            wow_discount_pct=wow_discount_pct,
        )
