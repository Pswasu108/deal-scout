"""
Flipkart scraper.

Strategy:
  Desktop SRP  → 40 products per page, full card DOM (brand, title, MRP, sale price)
  mweb SRP     → same page, fewer products BUT includes the WOW/effective price
                 via ctx=<base64> in each product link href.
                 ctx decodes to {"displayPrice": "XXXX"} which is the final price
                 after auto-applied coupons/bank offers shown as WOW DEAL.

We fetch BOTH in one scrape:
  1. Desktop fetch → parse 40 cards → build pid→Deal map
  2. mweb fetch    → parse ctx base64 for each pid → enrich wow_price in place

WOW price is available on the SRP without visiting any PDP.
"""
from __future__ import annotations
import base64
import json
import re
import time
from bs4 import BeautifulSoup

from .base import BaseScraper, Deal
from .http_client import make_client

SEARCH_URL   = "https://www.flipkart.com/search?q={query}&sort=discount_desc&page={page}"

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MWEB_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

DEAL_BADGE_CLS = "MaiFhH"


class FlipkartScraper(BaseScraper):
    name = "flipkart"

    def __init__(
        self,
        delay: float = 2.0,
        timeout: int = 15,
        max_retries: int = 3,
        fetch_wow_price: bool = True,
        cookies: str = "",
    ):
        self.delay       = delay
        self.timeout     = timeout
        self.max_retries = max_retries
        self.fetch_wow   = fetch_wow_price
        self.cookies     = cookies.strip()
        self._clients: dict[str, any] = {}

    def _get_client(self, ua: str):
        if ua not in self._clients:
            headers = {"User-Agent": ua, "Accept-Language": "en-IN,en;q=0.9"}
            if self.cookies:
                headers["Cookie"] = self.cookies
            self._clients[ua] = make_client(extra_headers=headers, timeout=self.timeout)
        return self._clients[ua]

    # ── Public ────────────────────────────────────────────────────────────────

    def scrape(self, query: str, max_products: int = 40, max_pages: int | None = None) -> list[Deal]:
        if max_pages is None:
            max_pages = max(1, (max_products + 39) // 40)

        all_deals: list[Deal] = []
        encoded_query = query.replace(" ", "+")

        for page in range(1, max_pages + 1):
            url = SEARCH_URL.format(query=encoded_query, page=page)

            # Step 1: desktop → product list for this page
            desktop_html = self._fetch(url, DESKTOP_UA)
            if not desktop_html:
                break
            page_deals, pid_map = self._parse_desktop(desktop_html)
            if not page_deals:
                break

            # Step 2: mweb → WOW prices & sizes for this page
            if self.fetch_wow and page_deals:
                mweb_html = self._fetch(url, MWEB_UA)
                if mweb_html:
                    wow_map, size_map = self._parse_mweb(mweb_html)
                    for deal in page_deals:
                        pid = pid_map.get(deal.product_url, "")
                        if pid in size_map and not deal.available_sizes:
                            deal.available_sizes = size_map[pid]
                        wow = wow_map.get(pid)
                        if wow:
                            deal.wow_price = wow
                            if deal.original_price:
                                deal.wow_discount_pct = round(
                                    (deal.original_price - wow) / deal.original_price * 100, 1
                                )

            all_deals.extend(page_deals)
            if len(all_deals) >= max_products:
                break

        return all_deals[:max_products]

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _fetch(self, url: str, ua: str) -> str | None:
        client = self._get_client(ua)
        for attempt in range(self.max_retries):
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.text
                print(f"  [flipkart] HTTP {resp.status_code} (ua={ua[:20]}…)")
            except Exception as e:
                print(f"  [flipkart] attempt {attempt + 1} error: {e}")
            time.sleep(self.delay)
        return None

    # ── Desktop parser ────────────────────────────────────────────────────────

    def _parse_desktop(self, html: str) -> tuple[list[Deal], dict[str, str]]:
        """Returns (deals, url→pid map)."""
        soup  = BeautifulSoup(html, "lxml")
        deals: list[Deal] = []
        pid_map: dict[str, str] = {}  # clean_url → pid

        for card in soup.select("[data-id]"):
            pid = card.get("data-id", "")
            try:
                d = self._card_to_deal(card, pid)
                if d:
                    deals.append(d)
                    pid_map[d.product_url] = pid
            except Exception:
                continue
        return deals, pid_map

    def _card_to_deal(self, card, pid: str) -> Deal | None:
        brand_el = card.select_one("div.Fo1I0b")
        title_el = card.select_one("a[title]")
        price_el = card.select_one("div.hZ3P6w")  # sale price
        mrp_el   = card.select_one("div.kRYCnD")  # struck-through MRP
        disc_el  = card.select_one("div.HQe8jr")  # "60% off"
        url_el   = card.select_one("a[href]")

        if not title_el or not price_el:
            return None

        brand = brand_el.get_text(strip=True) if brand_el else ""
        title = title_el.get("title") or title_el.get_text(strip=True)

        def to_float(el) -> float:
            if not el:
                return 0.0
            raw = el.get_text(separator=" ", strip=True)
            raw = raw.replace("₹", "").replace(",", "").replace("\u20b9", "")
            return float(re.sub(r"[^\d.]", "", raw) or 0)

        sale_price = to_float(price_el)
        mrp        = to_float(mrp_el) if mrp_el else sale_price

        disc_txt = disc_el.get_text(strip=True) if disc_el else ""
        disc_num = float(re.sub(r"[^\d.]", "", disc_txt) or 0)
        if not disc_num and mrp and sale_price and mrp > sale_price:
            disc_num = round((mrp - sale_price) / mrp * 100, 1)

        href      = url_el["href"] if url_el else f"/product/p/{pid}"
        clean_url = href if href.startswith("http") else f"https://www.flipkart.com{href}"
        clean_url = clean_url.split("?")[0]

        sizes = self._extract_sizes_from_card(card)
        img_el = card.select_one("img")
        img_url = (img_el.get("src") or img_el.get("data-src")) if img_el else None

        return Deal(
            title=f"{brand} {title}".strip(),
            brand=brand,
            original_price=mrp,
            sale_price=sale_price,
            discount_pct=disc_num,
            available_sizes=sizes,
            product_url=clean_url,
            source="flipkart",
            image_url=img_url,
        )

    # ── mweb WOW price & size parser ──────────────────────────────────────────

    def _parse_mweb(self, html: str) -> tuple[dict[str, float], dict[str, list[str]]]:
        """
        Parse mweb SRP HTML and return:
          - {pid: wow_price}
          - {pid: [sizes]}
        From window.__INITIAL_STATE__ (slotWiseSnippets bank offers + variants),
        with fallback to ctx=<base64> in links.
        """
        wow_map: dict[str, float] = {}
        size_map: dict[str, list[str]] = {}

        # 1. State JSON extraction (highest precision for WOW bank offers + sizes)
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                slots = data.get("multiWidgetState", {}).get("widgetsData", {}).get("slots", [])
                for slot in slots:
                    products = slot.get("slotData", {}).get("widget", {}).get("data", {}).get("products", [])
                    for p in products:
                        val = p.get("value", {})
                        pid = (
                            p.get("action", {}).get("params", {}).get("productId")
                            or val.get("productMeta", {}).get("productId")
                        )
                        if not pid:
                            continue

                        # Extract WOW / bank offer price
                        snippets = val.get("slotWiseSnippets", {})
                        for _, snips in snippets.items():
                            for s in snips:
                                for d in s.get("data", []):
                                    txt = d.get("value", {}).get("text", "")
                                    if "₹" in txt:
                                        p_clean = re.sub(r"[^\d.]", "", txt)
                                        if p_clean:
                                            wow_map[pid] = float(p_clean)

                        # Extract size
                        sizes: list[str] = []
                        sub = val.get("titles", {}).get("subtitle", "")
                        if "," in sub:
                            parts = [x.strip() for x in sub.split(",")]
                            if len(parts) >= 2 and re.match(r"^[\dA-Za-z.]+$", parts[-1]):
                                sizes.append(parts[-1])
                        cosub = val.get("titles", {}).get("coSubtitle", "")
                        m_sz = re.search(r"Size:\s*([\dA-Za-z.]+)", cosub)
                        if m_sz:
                            sizes.append(m_sz.group(1))
                        swatch_opts = val.get("textSwatch", {}).get("value", {}).get("attributeOptions", [])
                        for opt in swatch_opts:
                            v = opt.get("value")
                            if v and re.match(r"^[\dA-Za-z.]+$", str(v)):
                                sizes.append(str(v))
                        if sizes:
                            size_map[pid] = list(dict.fromkeys(sizes))
            except Exception:
                pass

        # 2. Fallback to ctx base64 param in links
        soup = BeautifulSoup(html, "lxml")
        for link in soup.find_all("a", href=re.compile(r"pid=")):
            href = link.get("href", "")
            pid_m = re.search(r"pid=([A-Z0-9]+)", href)
            ctx_m = re.search(r"ctx=([A-Za-z0-9+/=]+)", href)
            if not pid_m or not ctx_m:
                continue
            pid = pid_m.group(1)
            if pid in wow_map:
                continue
            try:
                b64 = ctx_m.group(1)
                b64 += "=" * (4 - len(b64) % 4)
                ctx_data = json.loads(base64.b64decode(b64).decode("utf-8", errors="ignore"))
                display_price = ctx_data.get("displayPrice", "")
                if display_price:
                    wow_map[pid] = float(display_price)
            except Exception:
                continue

        return wow_map, size_map

    # ── Size extraction ───────────────────────────────────────────────────────

    def _extract_sizes_from_card(self, card) -> list[str]:
        sizes: list[str] = []

        # Pattern 1: size bubble containers
        for size_container in card.select(
            "div._1fGeJ5, div._2ZW3or, div.yiggsN, "
            "div[class*='size'], ul[class*='size']"
        ):
            for item in size_container.find_all(["span", "li", "div"]):
                txt = item.get_text(strip=True)
                if txt and len(txt) <= 6 and re.match(r"^[\dA-Za-z.]+$", txt):
                    sizes.append(txt)

        # Pattern 2: pipe-separated numeric sequence in card text
        if not sizes:
            full_text = card.get_text(separator="|", strip=True)
            m = re.search(r"((?:\d{1,2}(?:\.\d)?)\|){2,}", full_text)
            if m:
                raw = m.group(0).strip("|")
                sizes = [s.strip() for s in raw.split("|") if s.strip()]

        return list(dict.fromkeys(sizes))

    # ── PDP enrichment (in-stock sizes + exact WOW deal price) ────────────────

    def enrich_deal(self, deal: Deal) -> bool:
        """
        Enrich a matched deal by fetching its PDP:
          - Extract real in-stock sizes (filters out OutOfStock variants)
          - Extract real WOW deal price from ATLAS_NEP_V2 (Buy at ₹... with offers)
        """
        html = self._fetch(deal.product_url, DESKTOP_UA)
        if not html:
            return False

        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
        if not m:
            return False

        try:
            data = json.loads(m.group(1))
            slots = data.get("multiWidgetState", {}).get("widgetsData", {}).get("slots", [])
            pdp_sizes: list[str] = []
            pdp_wow: float | None = None

            for slot in slots:
                w = slot.get("slotData", {}).get("widget", {})
                w_type = w.get("type", "")
                dls = w.get("data", {}).get("dlsData", {})

                # 1. Available in-stock sizes
                if "size-selector-view_0" in dls:
                    items = dls["size-selector-view_0"].get("value", {}).get("scrollToListData_0", {}).get("value", [])
                    for it in items:
                        track = it.get("value", {}).get("trackerData_0", {}).get("tracking", {})
                        c_type = track.get("contentType", "").lower()
                        sz = track.get("contentTitle")
                        if sz and ("instock" in c_type or "scarcity" in c_type):
                            pdp_sizes.append(str(sz).strip())

                # 2. WOW deal price
                if "nep" in str(w_type).lower():
                    col_title = w.get("data", {}).get("collapseTitle", "")
                    p_m = re.search(r"₹([\d,]+)", col_title)
                    if p_m:
                        pdp_wow = float(p_m.group(1).replace(",", ""))

            if pdp_sizes:
                deal.available_sizes = pdp_sizes

            if pdp_wow:
                deal.wow_price = pdp_wow
                if deal.original_price:
                    deal.wow_discount_pct = round((deal.original_price - pdp_wow) / deal.original_price * 100, 1)

            return True
        except Exception:
            return False

    def _fetch_wow_price(self, pdp_url: str) -> float | None:
        """Legacy fallback — try to parse WOW price from PDP static HTML."""
        html = self._fetch(pdp_url, DESKTOP_UA)
        if not html:
            return None
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                slots = data.get("multiWidgetState", {}).get("widgetsData", {}).get("slots", [])
                for slot in slots:
                    w = slot.get("slotData", {}).get("widget", {})
                    if "nep" in str(w.get("type", "")).lower():
                        col_title = w.get("data", {}).get("collapseTitle", "")
                        p_m = re.search(r"₹([\d,]+)", col_title)
                        if p_m:
                            return float(p_m.group(1).replace(",", ""))
            except Exception:
                pass
        return None
