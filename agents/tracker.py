"""
Tracker Agent — Price Target Monitor
Tracks specific products by direct URL or search keyword,
monitors price changes over time, and alerts when target price is hit.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich import box

from agents.notifier import NotifierAgent
from agents.scout import ScoutAgent
from core.config import load_config
from core.db import (
    create_price_tracker,
    get_price_trackers,
    get_price_tracker,
    update_price_tracker,
    upsert_scraped_deal,
    get_all_deals,
    get_connection,
)
from core.models import DealRecord, PriceTracker
from scrapers.base import Deal
from scrapers.http_client import make_client

console = Console()


def _norm_size(sz: Any) -> str:
    s = re.sub(r"^(UK|US|EU|IND|[\/\s\-])+", "", str(sz).upper(), flags=re.I)
    s = re.sub(r"[\/\s\-]+", "", s).strip()
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else f"{f:.1f}"
    except ValueError:
        return s


def detect_source_from_url(url: str) -> Optional[str]:
    low = url.lower()
    if "flipkart.com" in low:
        return "flipkart"
    if "myntra.com" in low:
        return "myntra"
    if "tatacliq.com" in low:
        return "tatacliq"
    if "amazon.in" in low or "amazon.com" in low:
        return "amazon"
    return None


class TrackerAgent:
    """Monitors individual product price targets."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.scout = ScoutAgent(self.config)
        self.notifier = NotifierAgent(self.config)

    # ── Single-PDP URL Scraper ────────────────────────────────────────────────

    def fetch_url_deal(self, url: str) -> Optional[DealRecord]:
        """Scrape a single product URL and persist/update in deals table."""
        source = detect_source_from_url(url)
        clean_url = url.split("?")[0].split("#")[0]

        if source == "flipkart" and "flipkart" in self.scout.scrapers:
            fk = self.scout.scrapers["flipkart"]
            deal = Deal(
                title="Flipkart Product",
                brand="",
                original_price=0.0,
                sale_price=0.0,
                discount_pct=0.0,
                available_sizes=[],
                product_url=clean_url,
                source="flipkart",
            )
            html = fk._fetch(url, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            if html:
                m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>", html, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1))
                        slots = data.get("multiWidgetState", {}).get("widgetsData", {}).get("slots", [])
                        for slot in slots:
                            w = slot.get("slotData", {}).get("widget", {})
                            w_type = str(w.get("type", "")).lower()
                            v_type = str(w.get("viewType", "")).lower()
                            w_data = w.get("data", {})
                            dls = w_data.get("dlsData", {})

                            # Title & Brand
                            if "producttitle" in v_type or "title" in w_type:
                                tc = w_data.get("titleComponent", {}).get("value", {})
                                if tc:
                                    deal.brand = tc.get("superTitle", "") or deal.brand
                                    deal.title = f"{deal.brand} {tc.get('title', '')}".strip() or deal.title
                                if deal.title in ("Flipkart Product", "") and "customEllipsisData_0" in dls:
                                    cand = dls["customEllipsisData_0"].get("value", {}).get("prependingText", "")
                                    if cand:
                                        deal.title = cand.strip()
                                        deal.brand = deal.title.split()[0]
                            elif deal.title in ("Flipkart Product", "") and v_type == "breadcrumb":
                                b_title = dls.get("label_2", {}).get("value", {}).get("text", "")
                                if b_title:
                                    deal.title = b_title.strip()
                                    deal.brand = b_title.split()[0]

                            # Pricing from ATLAS_NEP_V2 or legacy pricing component
                            if "nep" in w_type:
                                col_title = w_data.get("collapseTitle", "")
                                p_m = re.search(r"₹([\d,]+)", col_title)
                                if p_m:
                                    deal.wow_price = float(p_m.group(1).replace(",", ""))
                                nep_ctx_str = w_data.get("nepContext")
                                if nep_ctx_str:
                                    try:
                                        nep_ctx = json.loads(nep_ctx_str)
                                        if nep_ctx.get("lp"):
                                            deal.sale_price = float(nep_ctx["lp"])
                                        if nep_ctx.get("mrp"):
                                            deal.original_price = float(nep_ctx["mrp"])
                                    except Exception:
                                        pass

                            if "pricing" in w_type:
                                price_comp = w_data.get("priceComponent", {}).get("value", {})
                                final_p = price_comp.get("finalPrice", {}).get("value")
                                mrp_p = price_comp.get("mrp", {}).get("value")
                                if final_p:
                                    deal.sale_price = float(final_p)
                                if mrp_p:
                                    deal.original_price = float(mrp_p)

                            if deal.sale_price == 0.0 and "productActionButtonData_1" in dls:
                                act = dls["productActionButtonData_1"].get("action", {}).get("params", {})
                                if act.get("primaryProductPrice"):
                                    deal.sale_price = float(act["primaryProductPrice"])

                            # Image
                            if not deal.image_url:
                                w_str = str(w_data)
                                img_m = re.search(r'(https://rukminim\d*\.flixcart\.com/image/[^\'\"]+)', w_str)
                                if img_m:
                                    deal.image_url = img_m.group(1).replace("{@width}", "400").replace("{@height}", "400")

                        fk.enrich_deal(deal)
                    except Exception:
                        pass

                if deal.sale_price > 0:
                    if deal.original_price > deal.sale_price:
                        deal.discount_pct = round((deal.original_price - deal.sale_price) / deal.original_price * 100, 1)
                    rec, _ = upsert_scraped_deal(deal)
                    return rec

        elif source == "myntra":
            try:
                headers = {"Referer": "https://www.myntra.com/"}
                pincode = str(self.config.get("pincode", "110009")).strip()
                if pincode:
                    headers["Cookie"] = f"pincode={pincode}"
                    headers["x-pincode"] = pincode
                with make_client(extra_headers=headers, timeout=15) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        m = re.search(r"window\.__myx\s*=\s*({.*?})\s*(?:;|</script>|$)", resp.text, re.DOTALL)
                        if m:
                            data = json.loads(m.group(1))
                            pdp = data.get("pdpData", {})
                            if pdp:
                                price_info = pdp.get("price", {})
                                mrp = float(price_info.get("mrp", 0))
                                sale = float(price_info.get("discounted", mrp))
                                disc = round((mrp - sale) / mrp * 100, 1) if mrp and mrp > sale else 0.0
                                sizes = [
                                    str(sz.get("label", ""))
                                    for sz in pdp.get("sizes", [])
                                    if sz.get("available")
                                    ]
                                deal = Deal(
                                    title=pdp.get("name", "Myntra Product"),
                                    brand=pdp.get("brand", {}).get("name", ""),
                                    original_price=mrp,
                                    sale_price=sale,
                                    discount_pct=disc,
                                    available_sizes=sizes,
                                    product_url=clean_url,
                                    source="myntra",
                                )
                                rec, _ = upsert_scraped_deal(deal)
                                return rec
            except Exception as e:
                console.print(f"[dim][tracker] Myntra PDP fetch error: {e}[/]")

        elif source == "tatacliq":
            try:
                slug = clean_url.strip("/").split("/p-")[-1]
                slug = slug.split("?")[0].split("#")[0].strip("/")
                if slug:
                    api_url = f"https://www.tatacliq.com/marketplacewebservices/v2/mpl/products/productDetails/{slug}?isPwa=true&isMDE=true&isDynamicVar=true"
                    headers = {"channel": "WEB", "Referer": "https://www.tatacliq.com/"}
                    pincode = str(self.config.get("pincode", "110009")).strip()
                    if pincode:
                        headers["Cookie"] = f"pincode={pincode}"
                        headers["x-pincode"] = pincode
                    with make_client(extra_headers=headers, timeout=10) as client:
                        resp = client.get(api_url)
                        if resp.status_code == 200:
                            data = resp.json()
                            title = data.get("productName", "")
                            brand = data.get("brandName", "")
                            mrp_info = data.get("mrpPrice", {})
                            mrp = float(mrp_info.get("doubleValue", 0)) if mrp_info else 0.0
                            sell_info = data.get("winningSellerPrice", {})
                            sale = float(sell_info.get("doubleValue", mrp)) if sell_info else mrp
                            disc = float(data.get("discount", 0) or 0)
                            if disc == 0 and mrp and sale and mrp > sale:
                                disc = round((mrp - sale) / mrp * 100, 1)

                            img_url = ""
                            gallery = data.get("galleryImagesList", [])
                            if gallery and isinstance(gallery, list) and gallery[0].get("galleryImages"):
                                raw_img = gallery[0]["galleryImages"][0].get("value", "")
                                if raw_img:
                                    img_url = f"https:{raw_img}" if raw_img.startswith("//") else raw_img

                            sizes = []
                            for vo in data.get("variantOptions", []):
                                sl = vo.get("sizelink", {})
                                if sl and sl.get("isAvailable"):
                                    sz = sl.get("brandSize") or sl.get("size")
                                    if sz and sz not in sizes:
                                        sizes.append(sz)

                            if sale > 0:
                                deal = Deal(
                                    title=title or "TataCLiQ Product",
                                    brand=brand,
                                    original_price=mrp,
                                    sale_price=sale,
                                    discount_pct=disc,
                                    available_sizes=sizes,
                                    product_url=clean_url,
                                    image_url=img_url,
                                    source="tatacliq",
                                )
                                rec, _ = upsert_scraped_deal(deal)
                                return rec
            except Exception as e:
                console.print(f"[dim][tracker] TataCLiQ PDP fetch error: {e}[/]")

        elif source == "amazon":
            try:
                with make_client(timeout=15) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        title_el = soup.find(id="productTitle")
                        title = title_el.get_text(strip=True) if title_el else "Amazon Product"

                        sale_price = 0.0
                        price_whole = soup.find("span", class_="a-price-whole")
                        if price_whole:
                            p_str = re.sub(r"[^\d.]", "", price_whole.get_text(strip=True))
                            try:
                                sale_price = float(p_str)
                            except ValueError:
                                pass
                        if not sale_price:
                            for sel in ["#priceblock_ourprice", "#priceblock_dealprice", ".a-price .a-offscreen"]:
                                el = soup.select_one(sel)
                                if el:
                                    p_str = re.sub(r"[^\d.]", "", el.get_text(strip=True))
                                    try:
                                        sale_price = float(p_str)
                                        if sale_price > 0:
                                            break
                                    except ValueError:
                                        pass

                        mrp = sale_price
                        mrp_el = soup.find("span", class_="a-text-price")
                        if mrp_el:
                            offscreen = mrp_el.find("span", class_="a-offscreen")
                            raw_mrp = offscreen.get_text(strip=True) if offscreen else mrp_el.get_text(strip=True)
                            try:
                                mrp_val = float(re.sub(r"[^\d.]", "", raw_mrp))
                                if mrp_val > 0:
                                    mrp = mrp_val
                            except ValueError:
                                pass

                        brand = ""
                        brand_el = soup.find("a", id="bylineInfo")
                        if brand_el:
                            b_text = brand_el.get_text(strip=True)
                            brand = re.sub(r"^(Visit the|Brand:)\s*", "", b_text, flags=re.I).replace(" Store", "").strip()

                        img_url = None
                        img_el = soup.find(id="landingImage")
                        if img_el:
                            img_url = img_el.get("src") or img_el.get("data-old-hires")

                        if sale_price > 0:
                            disc = round((mrp - sale_price) / mrp * 100, 1) if mrp and mrp > sale_price else 0.0
                            deal = Deal(
                                title=title,
                                brand=brand,
                                original_price=mrp,
                                sale_price=sale_price,
                                discount_pct=disc,
                                available_sizes=[],
                                product_url=clean_url,
                                image_url=img_url,
                                source="amazon",
                            )
                            rec, _ = upsert_scraped_deal(deal)
                            return rec
            except Exception as e:
                console.print(f"[dim][tracker] Amazon PDP fetch error: {e}[/]")

        # Fallback: check if URL already exists in deals DB
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM deals WHERE product_url = ? OR product_url = ? LIMIT 1",
                (url, clean_url),
            ).fetchone()
            if row:
                from core.db import row_to_deal_record
                return row_to_deal_record(row)

        return None

    # ── Keyword Resolver ──────────────────────────────────────────────────────

    def search_keyword_candidates(
        self,
        keyword: str,
        limit: int = 20,
        force_scrape: bool = True,
    ) -> List[DealRecord]:
        """Return top matching deals for a keyword without polluting the main deals table."""
        from scrapers.base import Deal
        clean_kw = keyword.strip()
        if not clean_kw:
            return []

        stopwords = {"for", "in", "and", "the", "with", "a", "an", "to", "of", "on", "at", "by", "from"}
        raw_tokens = [t.lower() for t in re.split(r"[\s,\-_/]+", clean_kw) if len(t) > 1]
        tokens = [t for t in raw_tokens if t not in stopwords]
        if not tokens:
            tokens = raw_tokens

        is_women = any(w in clean_kw.lower() for w in ("women", "woman", "ladies", "girl", "female"))
        is_men = any(w in clean_kw.lower() for w in ("men", "man", "gents", "boy", "male")) and not is_women
        model_tokens = [t for t in tokens if any(c.isdigit() for c in t)]

        candidate_records: List[DealRecord] = []

        # If force_scrape=False, try DB first with high threshold
        if not force_scrape:
            existing = get_all_deals(include_ignored=False, limit=500)
            if existing:
                candidate_records = existing

        # Live scrape directly into memory (NO upsert to deals table)
        if not candidate_records or force_scrape:
            raw_deals: List[Deal] = []
            for name, scraper in self.scout.scrapers.items():
                try:
                    scraped = scraper.scrape(clean_kw, max_products=max(40, limit * 2))
                    raw_deals.extend(scraped)
                except Exception as e:
                    console.print(f"[dim][tracker] Scraper {name} search error: {e}[/]")

            seen_ids = set()
            for d in raw_deals:
                if d.deal_id in seen_ids:
                    continue
                seen_ids.add(d.deal_id)
                candidate_records.append(
                    DealRecord(
                        deal_id=d.deal_id,
                        source=d.source,
                        title=d.title,
                        brand=d.brand,
                        original_price=d.original_price,
                        sale_price=d.sale_price,
                        discount_pct=d.discount_pct,
                        wow_price=d.wow_price,
                        wow_discount_pct=d.wow_discount_pct,
                        available_sizes=d.available_sizes or [],
                        product_url=d.product_url,
                        image_url=d.image_url,
                        gender=d.gender,
                    )
                )

        if not candidate_records:
            return []

        def _score(deal: DealRecord) -> float:
            title_lower = (deal.title or "").lower()
            brand_lower = (deal.brand or "").lower()
            text = f"{brand_lower} {title_lower}"

            # Strict gender conflict check
            if is_women and any(m in text for m in ("for men", "men fob", "men's", "gents")):
                if not any(w in text for w in ("for women", "women's", "women")):
                    return -100.0
            if is_men and any(w in text for w in ("for women", "women's", "ladies")):
                if not any(m in text for m in ("for men", "men's", "men")):
                    return -100.0

            score = 0.0
            for t in tokens:
                if t in brand_lower:
                    score += 20.0
                elif t in title_lower:
                    score += 5.0

            for m in model_tokens:
                clean_m = re.sub(r"[^a-z0-9]", "", m)
                clean_text = re.sub(r"[^a-z0-9]", "", text)
                if clean_m and clean_m in clean_text:
                    score += 50.0

            if is_women and any(w in text for w in ("women", "women's", "ladies")):
                score += 10.0
            if is_men and any(m in text for m in ("men", "men's", "gents")):
                score += 10.0

            return score

        scored = [(d, _score(d)) for d in candidate_records]
        valid = [(d, s) for d, s in scored if s > 0]
        # Sort by relevance score descending, then by price/discount
        valid.sort(key=lambda x: (x[1], x[0].discount_pct or 0.0), reverse=True)
        return [d for d, _ in valid[:limit]]

    def resolve_keyword_deal(self, keyword: str, force_scrape: bool = False) -> Optional[DealRecord]:
        """Find best single matching deal for a keyword."""
        matches = self.search_keyword_candidates(keyword, limit=1, force_scrape=force_scrape)
        return matches[0] if matches else None

    def _prompt_candidate_selection(self, candidates: List[DealRecord], keyword: str) -> List[DealRecord]:
        """Display up to 10 candidate products and let user pick which ones to track."""
        table = Table(
            title=f"🔍 Top Matches for '{keyword}'",
            box=box.ROUNDED,
            show_lines=True,
            header_style="bold cyan",
        )
        table.add_column("#", justify="right", style="bold yellow", no_wrap=True)
        table.add_column("Source", style="cyan", no_wrap=True)
        table.add_column("Brand", style="bold white", max_width=14)
        table.add_column("Title", min_width=20, max_width=36)
        table.add_column("Sale", justify="right", no_wrap=True)
        table.add_column("WOW", justify="right", style="bold green", no_wrap=True)
        table.add_column("Disc", justify="right", style="red", no_wrap=True)
        table.add_column("Sizes", max_width=18)

        for idx, d in enumerate(candidates, start=1):
            wow_str = f"₹{d.wow_price:.0f}" if d.wow_price else "—"
            disc = d.wow_discount_pct or d.discount_pct or 0.0
            sizes_str = ", ".join(d.available_sizes[:5]) if d.available_sizes else "—"
            table.add_row(
                str(idx),
                d.source.title(),
                (d.brand or "—")[:12],
                d.title[:32],
                f"₹{d.sale_price:.0f}",
                wow_str,
                f"{disc:.0f}%",
                sizes_str,
            )

        console.print(table)
        raw = console.input(
            "[bold cyan]Pick # to track[/] [dim](e.g. 1 or 1,3,5 or 'all' or 'q' to cancel)[/] [1]: "
        ).strip().lower()

        if raw in ("q", "quit", "cancel", "n"):
            return []
        if raw == "all":
            return candidates
        if not raw:
            return [candidates[0]]

        chosen: List[DealRecord] = []
        seen_idx = set()
        for part in raw.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    a, b = [int(x) for x in part.split("-", 1)]
                    for i in range(a, b + 1):
                        if 1 <= i <= len(candidates) and i not in seen_idx:
                            seen_idx.add(i)
                            chosen.append(candidates[i - 1])
                except ValueError:
                    continue
            else:
                try:
                    i = int(part)
                    if 1 <= i <= len(candidates) and i not in seen_idx:
                        seen_idx.add(i)
                        chosen.append(candidates[i - 1])
                except ValueError:
                    continue
        return chosen

    # ── Tracker Creation ──────────────────────────────────────────────────────

    def _save_tracker_record(
        self,
        matched_deal: Optional[DealRecord],
        product_url: Optional[str],
        search_keyword: Optional[str],
        source: Optional[str],
        target_price: float,
        target_size: Optional[str],
        target_type: str,
        check_interval: int,
    ) -> PriceTracker:
        initial_price = None
        if matched_deal:
            initial_price = matched_deal.wow_price if (target_type == "WOW" and matched_deal.wow_price) else (
                matched_deal.sale_price if target_type == "SALE" else (matched_deal.wow_price or matched_deal.sale_price)
            )
            source = matched_deal.source
            product_url = product_url or matched_deal.product_url

        tracker = PriceTracker(
            product_url=product_url,
            search_keyword=search_keyword,
            matched_deal_id=matched_deal.deal_id if matched_deal else None,
            source=source,
            target_price=target_price,
            target_type=target_type.upper(),
            target_size=target_size,
            title=matched_deal.title if matched_deal else (search_keyword or "Unknown Product"),
            brand=matched_deal.brand if matched_deal else None,
            image_url=matched_deal.image_url if matched_deal else None,
            initial_price=initial_price,
            lowest_price=initial_price,
            current_price=initial_price,
            status="ACTIVE",
            check_interval=check_interval,
            last_checked=datetime.now().isoformat() if matched_deal else None,
            times_checked=1 if matched_deal else 0,
        )

        tracker_id = create_price_tracker(tracker)
        tracker.id = tracker_id

        if initial_price:
            gap = initial_price - target_price
            gap_pct = round(gap / initial_price * 100) if initial_price > 0 else 0
            console.print(
                f"[bold green]✓ Tracker #{tracker_id} created:[/] {tracker.title} ({(tracker.source or 'store').title()})\n"
                f"  Current: ₹{initial_price:.0f} | Target: ₹{target_price:.0f} | "
                f"{'Target already met!' if gap <= 0 else f'Gap: ₹{gap:.0f} ({gap_pct}% away)'}"
            )
        else:
            console.print(
                f"[bold yellow]✓ Tracker #{tracker_id} created (pending first price fetch):[/] "
                f"{tracker.title} | Target: ₹{target_price:.0f}"
            )

        return tracker

    def create_tracker(
        self,
        target_input: str,
        target_price: float,
        target_size: Optional[str] = None,
        target_type: str = "ANY",
        check_interval: int = 30,
        interactive: bool = False,
        force_scrape: bool = False,
    ) -> List[PriceTracker]:
        """Create and resolve new price tracker(s) from URL or keyword."""
        is_url = target_input.strip().startswith(("http://", "https://"))

        if is_url:
            product_url = target_input.strip()
            source = detect_source_from_url(product_url)
            console.print(f"[dim]🔗 Resolving product URL ({source or 'unknown'})...[/]")
            matched_deal = self.fetch_url_deal(product_url)
            tracker = self._save_tracker_record(
                matched_deal=matched_deal,
                product_url=product_url,
                search_keyword=None,
                source=source,
                target_price=target_price,
                target_size=target_size,
                target_type=target_type,
                check_interval=check_interval,
            )
            return [tracker]

        search_keyword = target_input.strip()
        console.print(f"[dim]🔍 Searching products for '{search_keyword}'...[/]")
        candidates = self.search_keyword_candidates(search_keyword, limit=10, force_scrape=force_scrape)

        if not candidates:
            tracker = self._save_tracker_record(
                matched_deal=None,
                product_url=None,
                search_keyword=search_keyword,
                source=None,
                target_price=target_price,
                target_size=target_size,
                target_type=target_type,
                check_interval=check_interval,
            )
            return [tracker]

        selected = (
            self._prompt_candidate_selection(candidates, search_keyword)
            if interactive
            else [candidates[0]]
        )
        if not selected:
            console.print("[yellow]Tracker creation cancelled.[/]")
            return []

        created: List[PriceTracker] = []
        for deal in selected:
            t = self._save_tracker_record(
                matched_deal=deal,
                product_url=deal.product_url,
                search_keyword=search_keyword,
                source=deal.source,
                target_price=target_price,
                target_size=target_size,
                target_type=target_type,
                check_interval=check_interval,
            )
            created.append(t)
        return created

    # ── Price Check & Alerting ────────────────────────────────────────────────

    def _effective_price(self, deal: DealRecord, target_type: str) -> Optional[float]:
        if target_type == "WOW":
            return deal.wow_price
        if target_type == "SALE":
            return deal.sale_price if deal.sale_price > 0 else None
        candidates = [p for p in (deal.sale_price, deal.wow_price) if p and p > 0]
        return min(candidates) if candidates else None

    def _size_matches(self, deal: DealRecord, target_size: Optional[str]) -> bool:
        if not target_size or not deal.available_sizes:
            return True
        req = _norm_size(target_size)
        avail = {_norm_size(s) for s in deal.available_sizes}
        return req in avail

    def check_tracker(self, tracker: PriceTracker, dry_run: bool = False, force: bool = False) -> bool:
        """Check a single tracker, update prices, and fire alert if target is hit. Returns True if alerted."""
        if tracker.status not in ("ACTIVE", "TRIGGERED"):
            return False

        now = datetime.now()
        if not force and tracker.last_checked:
            try:
                last_dt = datetime.fromisoformat(tracker.last_checked)
                if now - last_dt < timedelta(minutes=tracker.check_interval):
                    return False
            except ValueError:
                pass

        deal: Optional[DealRecord] = None
        if tracker.product_url:
            deal = self.fetch_url_deal(tracker.product_url)
            if deal and (not tracker.matched_deal_id or tracker.title in ("Unknown Product", None)):
                tracker.matched_deal_id = deal.deal_id
                tracker.title = deal.title
                tracker.brand = deal.brand
                tracker.source = deal.source
                tracker.image_url = deal.image_url
        elif tracker.search_keyword:
            deal = self.resolve_keyword_deal(tracker.search_keyword, force_scrape=True)
            if deal and not tracker.matched_deal_id:
                tracker.matched_deal_id = deal.deal_id
                tracker.product_url = deal.product_url
                tracker.title = deal.title
                tracker.brand = deal.brand
                tracker.source = deal.source
                tracker.image_url = deal.image_url

        tracker.last_checked = now.isoformat()
        tracker.times_checked += 1

        if not deal:
            update_price_tracker(tracker)
            return False

        eff_price = self._effective_price(deal, tracker.target_type)
        if eff_price is None:
            update_price_tracker(tracker)
            return False

        prev_price = tracker.current_price
        tracker.current_price = eff_price
        if tracker.initial_price is None:
            tracker.initial_price = eff_price
        if tracker.lowest_price is None or eff_price < tracker.lowest_price:
            tracker.lowest_price = eff_price

        alerted = False
        if eff_price <= tracker.target_price and self._size_matches(deal, tracker.target_size):
            should_alert = (
                tracker.status == "ACTIVE"
                or (tracker.status == "TRIGGERED" and prev_price is not None and eff_price < prev_price)
            )
            if should_alert:
                tracker.status = "TRIGGERED"
                if not tracker.triggered_at:
                    tracker.triggered_at = now.isoformat()
                tracker.alert_count += 1
                alerted = True
                if not dry_run:
                    self.notifier.notify_tracker_hit(tracker, deal)
                else:
                    console.print(
                        f"[bold green]🎯 [DRY RUN] Target hit for #{tracker.id}:[/] "
                        f"{tracker.title} ₹{eff_price:.0f} <= ₹{tracker.target_price:.0f}"
                    )

        update_price_tracker(tracker)
        return alerted

    def check_all_trackers(self, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
        """Check all ACTIVE and TRIGGERED trackers."""
        active = get_price_trackers(status="ACTIVE") + get_price_trackers(status="TRIGGERED")
        if not active:
            return {"checked": 0, "alerts": 0}

        console.print(f"[bold cyan]🎯 Tracker Agent: checking {len(active)} active trackers...[/]")
        alerts = 0
        for t in active:
            if self.check_tracker(t, dry_run=dry_run, force=force):
                alerts += 1

        return {"checked": len(active), "alerts": alerts}

    def print_trackers_table(self) -> None:
        """Render Rich table of all price trackers."""
        trackers = get_price_trackers()
        if not trackers:
            console.print("[yellow]No price trackers configured.[/]")
            return

        table = Table(
            title="🎯 Price Trackers",
            box=box.ROUNDED,
            show_lines=True,
            header_style="bold cyan",
        )
        table.add_column("ID", justify="right", width=4)
        table.add_column("Product", width=30)
        table.add_column("Source", width=10)
        table.add_column("Current", justify="right", width=9)
        table.add_column("Target", justify="right", style="bold green", width=9)
        table.add_column("Gap", justify="right", width=8)
        table.add_column("Size", width=6)
        table.add_column("Status", width=12)

        for t in trackers:
            cur_str = f"₹{t.current_price:.0f}" if t.current_price else "—"
            tgt_str = f"₹{t.target_price:.0f}"
            if t.current_price and t.current_price > 0:
                gap_pct = round((t.target_price - t.current_price) / t.current_price * 100)
                gap_str = f"{gap_pct:+}%"
            else:
                gap_str = "—"

            st_style = {
                "ACTIVE": "cyan",
                "TRIGGERED": "bold green",
                "PAUSED": "yellow",
                "EXPIRED": "dim",
            }.get(t.status, "white")

            table.add_row(
                str(t.id),
                (t.title or t.search_keyword or "")[:30],
                (t.source or "auto").title(),
                cur_str,
                tgt_str,
                gap_str,
                t.target_size or "Any",
                f"[{st_style}]{t.status}[/]",
            )

        console.print(table)
