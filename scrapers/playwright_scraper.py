"""
Playwright-based scraper for SPAs (Myntra, TataCliq).

Usage: set config.json → scraper.use_playwright = true
Requires: pip install playwright && playwright install chromium
"""
from __future__ import annotations
import json
import re
import time

from .base import BaseScraper, Deal

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


class PlaywrightMyntraScraper(BaseScraper):
    name = "myntra"

    def __init__(self, delay: float = 2.0, pincode: str = "110009", **kwargs):
        self.delay = delay
        self.pincode = str(pincode or "110009").strip()

    def scrape(self, query: str, max_products: int = 40, max_pages: int | None = None, **kwargs) -> list[Deal]:
        # Fast HTTP path: Myntra embeds full state in window.__myx, bypassing Akamai browser blocks
        try:
            from .myntra import MyntraScraper
            deals = MyntraScraper(**self.__dict__).scrape(
                query,
                max_products=max_products,
                max_pages=max_pages,
                brands=kwargs.get("brands"),
            )
            if deals:
                return deals
        except Exception:
            pass

        if not _PLAYWRIGHT_AVAILABLE:
            print("  [playwright/myntra] playwright not installed. Run: pip install playwright && playwright install chromium")
            return []
        slug = query.strip().lower().replace(" ", "-")
        url = f"https://www.myntra.com/{slug}"
        return self._scrape_with_browser(url)[:max_products]

    def _scrape_with_browser(self, url: str) -> list[Deal]:
        deals: list[Deal] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-IN",
            )
            if self.pincode:
                try:
                    ctx.add_cookies([{"name": "pincode", "value": self.pincode, "domain": ".myntra.com", "path": "/"}])
                except Exception:
                    pass
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=30000)
                # Scroll to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                time.sleep(2)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

                cards = page.query_selector_all("li.product-base")
                for card in cards:
                    try:
                        brand = card.query_selector("h3.product-brand")
                        title = card.query_selector("h4.product-product")
                        price_el = card.query_selector("div.product-price span")
                        mrp_el = card.query_selector("span.product-strike")
                        disc_el = card.query_selector("span.product-discountPercentage")
                        url_el = card.query_selector("a")

                        brand_t = brand.inner_text().strip() if brand else ""
                        title_t = title.inner_text().strip() if title else ""

                        def to_f(el, default=0.0):
                            if not el:
                                return default
                            t = re.sub(r"[^\d.]", "", el.inner_text())
                            return float(t) if t else default

                        price = to_f(price_el)
                        mrp = to_f(mrp_el) or price
                        disc = to_f(disc_el) or (round((mrp - price) / mrp * 100, 1) if mrp and price else 0)

                        href = url_el.get_attribute("href") if url_el else ""
                        full_url = href if href.startswith("http") else f"https://www.myntra.com{href}"

                        deals.append(Deal(
                            title=f"{brand_t} {title_t}".strip(),
                            brand=brand_t,
                            original_price=mrp, sale_price=price, discount_pct=disc,
                            available_sizes=[],
                            product_url=full_url, source="myntra",
                        ))
                    except Exception:
                        continue
            except PWTimeout:
                print("  [playwright/myntra] page load timed out")
            finally:
                browser.close()
        return deals


class PlaywrightTataCliqScraper(BaseScraper):
    name = "tatacliq"

    def __init__(self, delay: float = 2.0, pincode: str = "110009", **kwargs):
        self.delay = delay
        self.pincode = str(pincode or "110009").strip()

    def scrape(self, query: str, max_products: int = 40, max_pages: int | None = None) -> list[Deal]:
        if not _PLAYWRIGHT_AVAILABLE:
            print("  [playwright/tatacliq] playwright not installed.")
            return []
        url = f"https://www.tatacliq.com/search/?text={query.replace(' ', '+')}&sort=discount_desc"
        return self._scrape_with_browser(url, max_products=max_products)

    def _scrape_with_browser(self, url: str, max_products: int = 40) -> list[Deal]:
        deals: list[Deal] = []
        api_data: dict = {}  # webURL slug -> {sizes, gender, ...}

        def _on_response(res):
            if "searchbff.tatacliq.com/products" in res.url:
                try:
                    body = res.body()
                    data = json.loads(body)
                    sr = data.get("searchresult", {})
                    products = sr if isinstance(sr, list) else sr.get("products", [])
                    for p in products:
                        webURL = p.get("webURL", "")
                        slug = webURL.strip("/").split("/p-")[-1]
                        if not slug:
                            continue
                        pname = (p.get("productname") or p.get("productTitle", "")).lower()
                        if "women" in pname or "girl" in pname or "ladies" in pname:
                            gender = "women"
                        elif "men" in pname or "boy" in pname:
                            gender = "men"
                        elif "unisex" in pname or "kids" in pname or "child" in pname:
                            gender = "unisex"
                        else:
                            gender = None
                        api_data[slug] = {
                            "gender": gender,
                            "sizes": [],
                        }
                except Exception:
                    pass

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="en-IN",
            )
            if self.pincode:
                try:
                    ctx.add_cookies([{"name": "pincode", "value": self.pincode, "domain": ".tatacliq.com", "path": "/"}])
                except Exception:
                    pass
            page = ctx.new_page()
            page.on("response", _on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector("[class*='ProductModule__base']", timeout=15000)
                except Exception:
                    pass

                # Paginate by clicking 'Show More Products' if needed
                prev_count = 0
                max_clicks = 4
                clicks = 0
                while clicks < max_clicks:
                    cards = page.query_selector_all("[class*='ProductModule__base']")
                    if len(cards) >= max_products:
                        break
                    if len(cards) <= prev_count and clicks > 0:
                        break
                    prev_count = len(cards)

                    show_more_btn = page.query_selector("[class*='ShowMoreButtonPlp__button']")
                    if not show_more_btn or not show_more_btn.is_visible():
                        break
                    try:
                        show_more_btn.click()
                        clicks += 1
                        time.sleep(1.5)
                    except Exception:
                        break

                cards = page.query_selector_all("[class*='ProductModule__base']")
                for card in cards:
                    try:
                        # Scroll card into viewport so React mounts the lazy <img> element
                        try:
                            card.scroll_into_view_if_needed(timeout=1000)
                        except Exception:
                            pass

                        brand_el = card.query_selector("[class*='ProductDescription__header'], h3")
                        title_el = card.query_selector("h2, [class*='ProductDescription__description']")
                        price_el = card.query_selector(
                            "[class*='ProductDescription__discount'], [class*='ProductDescription__priceHolder'], [class*='selling-price']"
                        )
                        mrp_el = card.query_selector(
                            "[class*='ProductDescription__priceCancelled'], s, [class*='mrp']"
                        )
                        disc_el = card.query_selector(
                            "[class*='ProductDescription__newDiscountPercent'], [class*='discountPercent']"
                        )
                        url_el = card.query_selector("a[href]")
                        img_el = card.query_selector("img[class*='Image__actual'], img[src*='tatacliq'], img")

                        def to_f(el, default=0.0):
                            if not el:
                                return default
                            t = re.sub(r"[^\d.]", "", el.inner_text())
                            return float(t) if t else default

                        brand = brand_el.inner_text().strip() if brand_el else "TataCliq"
                        title = title_el.inner_text().strip() if title_el else ""
                        if not title:
                            continue

                        price = to_f(price_el)
                        mrp = to_f(mrp_el) or price
                        disc = round((mrp - price) / mrp * 100, 1) if mrp and price and mrp > price else 0.0
                        if disc == 0.0 and disc_el:
                            raw_disc = to_f(disc_el)
                            if 0 < raw_disc <= 100:
                                disc = raw_disc

                        # CLIQDEAL coupon (10% off, min purchase ₹2000) + 10% NeuCoins on Tata Neu card
                        wow_price = None
                        wow_disc = None
                        if price > 0:
                            card_text = card.inner_text()
                            m_offer = re.search(r"Offer\s*Price[^\d]*₹?\s*([\d,]+)", card_text, re.IGNORECASE)
                            offer_price = float(m_offer.group(1).replace(",", "")) if m_offer else None

                            if offer_price and 0 < offer_price < price:
                                cliq_price = offer_price
                            elif "CLIQDEAL" in card_text or price >= 2000:
                                cliq_price = round(price * 0.90)
                            else:
                                cliq_price = price

                            wow_price = round(cliq_price * 0.90)
                            if mrp and mrp > wow_price:
                                wow_disc = round((mrp - wow_price) / mrp * 100, 1)

                        href = url_el.get_attribute("href") if url_el else ""
                        full_url = href if href.startswith("http") else f"https://www.tatacliq.com{href}"

                        img_src = ""
                        if img_el:
                            raw_src = img_el.get_attribute("src") or img_el.get_attribute("data-src") or ""
                            if raw_src and not raw_src.endswith(".svg"):
                                img_src = f"https:{raw_src}" if raw_src.startswith("//") else raw_src

                        # Match with intercepted API data for gender (sizes are on PDP only)
                        gender = None
                        sizes: list[str] = []
                        slug = href.strip("/").split("/p-")[-1] if href else ""
                        if slug and slug in api_data:
                            gender = api_data[slug].get("gender")
                            sizes = api_data[slug].get("sizes", [])

                        # Gender fallback from title text
                        if not gender:
                            tl = title.lower()
                            if "women" in tl or "girl" in tl or "ladies" in tl:
                                gender = "women"
                            elif "men" in tl or "boy" in tl:
                                gender = "men"
                            elif "unisex" in tl or "kids" in tl:
                                gender = "unisex"

                        deals.append(Deal(
                            title=title,
                            brand=brand,
                            original_price=mrp,
                            sale_price=price,
                            discount_pct=disc,
                            available_sizes=sizes,
                            product_url=full_url,
                            source="tatacliq",
                            image_url=img_src,
                            wow_price=wow_price,
                            wow_discount_pct=wow_disc,
                            gender=gender,
                        ))
                        if len(deals) >= max_products:
                            break
                    except Exception:
                        continue
            except PWTimeout:
                print("  [playwright/tatacliq] page load timed out")
            finally:
                browser.close()

        # Enrich deals with real-time in-stock sizes from TataCLiQ productDetails API
        if deals:
            from concurrent.futures import ThreadPoolExecutor

            def _enrich_sizes(d: Deal):
                if "/p-" in d.product_url:
                    slug = d.product_url.strip("/").split("/p-")[-1].split("?")[0].split("#")[0].strip("/")
                    if slug:
                        extracted = fetch_tatacliq_sizes(slug)
                        if extracted:
                            d.available_sizes = extracted

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(_enrich_sizes, deals))

        return deals


def fetch_tatacliq_sizes(product_id: str, pincode: str = "110009") -> list[str]:
    """Fetch exact live in-stock sizes for a TataCLiQ product via productDetails API."""
    clean_id = product_id.split("?")[0].split("#")[0].strip("/")
    if "/p-" in clean_id:
        clean_id = clean_id.split("/p-")[-1]
    api_url = f"https://www.tatacliq.com/marketplacewebservices/v2/mpl/products/productDetails/{clean_id}?isPwa=true&isMDE=true&isDynamicVar=true"
    try:
        from scrapers.http_client import make_client
        extra_headers = {"channel": "WEB", "Referer": "https://www.tatacliq.com/"}
        if pincode:
            extra_headers["Cookie"] = f"pincode={pincode}"
            extra_headers["x-pincode"] = pincode
        with make_client(extra_headers=extra_headers, timeout=8) as client:
            r = client.get(api_url)
            if r.status_code == 200:
                data = r.json()
                sizes = []
                for vo in data.get("variantOptions", []):
                    sl = vo.get("sizelink", {})
                    if sl and sl.get("isAvailable"):
                        sz = sl.get("brandSize") or sl.get("size")
                        if sz and sz not in sizes:
                            sizes.append(sz)
                return sizes
    except Exception:
        pass
    return []

