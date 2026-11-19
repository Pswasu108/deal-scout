"""
Tata CLiQ scraper.

TataCliq's internal API requires session cookies. We:
1. First visit the homepage to get a session + Cloudflare cookies.
2. Then hit the search API.
"""
from __future__ import annotations
import re
import time
import json

from bs4 import BeautifulSoup

from .base import BaseScraper, Deal
from .http_client import make_client

HOME_URL = "https://www.tatacliq.com/"
API_URL = (
    "https://www.tatacliq.com/api/v1/page/search/"
    "?isCategoryPage=true&pageNo={page}&pageSize=40"
    "&searchText={query}&sortBy=discount_desc"
)
LISTING_URL = "https://www.tatacliq.com/search/?text={query}&sort=discount_desc"

API_EXTRA_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "channel": "WEB",
    "Origin": "https://www.tatacliq.com",
    "Referer": "https://www.tatacliq.com/",
}


class TataCliqScraper(BaseScraper):
    name = "tatacliq"

    def __init__(self, delay: float = 2.0, timeout: int = 15, max_retries: int = 3, pincode: str = "110009"):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.pincode = str(pincode or "110009").strip()

    def scrape(self, query: str, max_products: int = 40, max_pages: int | None = None) -> list[Deal]:
        if max_pages is None:
            max_pages = max(1, (max_products + 39) // 40)

        headers = dict(API_EXTRA_HEADERS)
        if self.pincode:
            headers["Cookie"] = f"pincode={self.pincode}"
            headers["x-pincode"] = self.pincode

        # Use persistent client to share cookies across requests
        with make_client(extra_headers=headers, timeout=self.timeout) as client:
            # Step 1: warm up session
            try:
                client.get(HOME_URL)
                time.sleep(1)
            except Exception:
                pass

            # Step 2: try JSON API across pages
            all_deals: list[Deal] = []
            encoded = query.replace(" ", "%20")
            for page in range(1, max_pages + 1):
                api_url = API_URL.format(page=page, query=encoded)
                data = self._fetch_json(client, api_url)
                if data:
                    deals = self._parse_json(data)
                    if deals:
                        all_deals.extend(deals)
                        if len(all_deals) >= max_products:
                            break
                        continue
                break

            # Step 3: fallback to HTML listing
            listing_url = LISTING_URL.format(query=query.replace(" ", "+"))
            html = self._fetch_html(client, listing_url)
            parsed_html = self._parse_html(html)[:max_products] if html else []

            out_deals = (all_deals[:max_products]) if all_deals else parsed_html
            if out_deals:
                from concurrent.futures import ThreadPoolExecutor
                from scrapers.playwright_scraper import fetch_tatacliq_sizes

                def _enrich(d: Deal):
                    if not d.available_sizes and "/p-" in d.product_url:
                        slug = d.product_url.strip("/").split("/p-")[-1].split("?")[0].split("#")[0].strip("/")
                        if slug:
                            extracted = fetch_tatacliq_sizes(slug)
                            if extracted:
                                d.available_sizes = extracted

                with ThreadPoolExecutor(max_workers=8) as pool:
                    list(pool.map(_enrich, out_deals))

            return out_deals

        return []

    def _fetch_json(self, client, url: str) -> dict | None:
        for attempt in range(self.max_retries):
            try:
                resp = client.get(url)
                if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/json"):
                    return resp.json()
                elif resp.status_code == 200:
                    # Returned HTML — API requires more auth
                    return None
                print(f"  [tatacliq] API HTTP {resp.status_code}")
            except Exception as e:
                print(f"  [tatacliq] attempt {attempt+1} error: {e}")
            time.sleep(self.delay)
        return None

    def _fetch_html(self, client, url: str) -> str | None:
        for attempt in range(self.max_retries):
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.text
                print(f"  [tatacliq] HTML HTTP {resp.status_code}")
            except Exception as e:
                print(f"  [tatacliq] attempt {attempt+1} error: {e}")
            time.sleep(self.delay)
        return None

    def _parse_json(self, data: dict) -> list[Deal]:
        deals: list[Deal] = []
        products = (
            data.get("searchData", {})
            .get("clpProuductResponse", {})
            .get("products", [])
        ) or data.get("products", [])

        for p in products:
            try:
                d = self._product_to_deal(p)
                if d:
                    deals.append(d)
            except Exception:
                continue
        return deals

    def _parse_html(self, html: str) -> list[Deal]:
        """Parse TataCliq HTML listing page. Data may be in a JSON script tag."""
        deals: list[Deal] = []
        soup = BeautifulSoup(html, "lxml")

        # TataCliq embeds state in <script id="__NEXT_DATA__"> (Next.js)
        next_data = soup.find("script", id="__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                data = json.loads(next_data.string)
                # Walk the props tree to find products
                products = self._walk_nextdata(data)
                for p in products:
                    d = self._product_to_deal(p)
                    if d:
                        deals.append(d)
                if deals:
                    return deals
            except Exception:
                pass

        # Card-based DOM fallback
        for card in soup.select("div.ProductModule__container, div[class*='ProductModule']"):
            try:
                d = self._card_to_deal(card)
                if d:
                    deals.append(d)
            except Exception:
                continue

        if not deals:
            print("  [tatacliq] Note: TataCliq requires session/cookies — consider enabling Playwright.")
        return deals

    def _walk_nextdata(self, data: dict, depth: int = 0) -> list[dict]:
        """Recursively find a list that looks like product objects."""
        if depth > 8:
            return []
        if isinstance(data, list):
            if data and isinstance(data[0], dict) and "productName" in data[0]:
                return data
            for item in data:
                r = self._walk_nextdata(item, depth + 1)
                if r:
                    return r
        elif isinstance(data, dict):
            for v in data.values():
                r = self._walk_nextdata(v, depth + 1)
                if r:
                    return r
        return []

    def _product_to_deal(self, p: dict) -> Deal | None:
        title = p.get("productName", "")
        brand = p.get("brandName", "")
        mrp = float(p.get("mrp", 0))
        price = float(p.get("sellingPrice", mrp))
        discount = p.get("discount", 0)
        if isinstance(discount, str):
            discount = float(re.sub(r"[^\d.]", "", discount) or 0)
        else:
            discount = float(discount)
        if discount == 0 and mrp and price:
            discount = round((mrp - price) / mrp * 100, 1)

        slug = p.get("productUrl", "") or p.get("url", "")
        url = slug if slug.startswith("http") else f"https://www.tatacliq.com{slug}"

        sizes_raw = p.get("sizes", []) or []
        sizes = []
        for s in sizes_raw:
            if isinstance(s, dict) and s.get("available", True):
                sizes.append(s.get("scaleValue", s.get("label", "")))
            elif isinstance(s, str):
                sizes.append(s)

        imgs = p.get("images", [])
        img_url = imgs[0].get("imageURL", "") if imgs and isinstance(imgs[0], dict) else ""

        # CLIQDEAL coupon (10% off for >= 2000) + 10% NeuCoins
        wow_price = None
        wow_disc = None
        if price > 0:
            cliq_price = round(price * 0.90) if price >= 2000 else price
            wow_price = round(cliq_price * 0.90)
            if mrp and mrp > wow_price:
                wow_disc = round((mrp - wow_price) / mrp * 100, 1)

        return Deal(
            title=title, brand=brand,
            original_price=mrp, sale_price=price, discount_pct=discount,
            available_sizes=sizes,
            product_url=url, source="tatacliq", image_url=img_url,
            wow_price=wow_price, wow_discount_pct=wow_disc,
        )

    def _card_to_deal(self, card) -> Deal | None:
        title_el = card.select_one("[class*='product-title'], [class*='productName']")
        brand_el = card.select_one("[class*='brand-name'], [class*='brandName']")
        price_el = card.select_one("[class*='selling-price'], [class*='sellingPrice']")
        mrp_el = card.select_one("[class*='original-price'], [class*='mrp'], s")
        url_el = card.select_one("a[href]")

        if not title_el or not price_el:
            return None

        title = title_el.get_text(strip=True)
        brand = brand_el.get_text(strip=True) if brand_el else title.split()[0]

        def to_float(el) -> float:
            if not el:
                return 0.0
            t = re.sub(r"[^\d.]", "", el.get_text(strip=True))
            return float(t) if t else 0.0

        price = to_float(price_el)
        mrp = to_float(mrp_el) if mrp_el else price
        discount = round((mrp - price) / mrp * 100, 1) if mrp and price and mrp > price else 0.0

        href = url_el["href"] if url_el else ""
        full_url = href if href.startswith("http") else f"https://www.tatacliq.com{href}"

        # CLIQDEAL coupon (10% off for >= 2000) + 10% NeuCoins
        card_text = card.get_text()
        m_offer = re.search(r"Offer\s*Price[^\d]*₹?\s*([\d,]+)", card_text, re.IGNORECASE)
        offer_price = float(m_offer.group(1).replace(",", "")) if m_offer else None

        wow_price = None
        wow_disc = None
        if price > 0:
            if offer_price and 0 < offer_price < price:
                cliq_price = offer_price
            elif "CLIQDEAL" in card_text or price >= 2000:
                cliq_price = round(price * 0.90)
            else:
                cliq_price = price
            wow_price = round(cliq_price * 0.90)
            if mrp and mrp > wow_price:
                wow_disc = round((mrp - wow_price) / mrp * 100, 1)

        return Deal(
            title=f"{brand} {title}".strip(), brand=brand,
            original_price=mrp, sale_price=price, discount_pct=discount,
            available_sizes=[], product_url=full_url, source="tatacliq",
            wow_price=wow_price, wow_discount_pct=wow_disc,
        )
