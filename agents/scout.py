"""
Scout Agent — Collector
Continuously fetches deals across multiple retailers,
deduplicates and persists records into SQLite,
and tracks price movements over time.
"""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from rich.console import Console

from core.config import load_config
from core.db import upsert_scraped_deal, get_connection
from core.models import DealRecord, WatchProfile
from scrapers import MyntraScraper, FlipkartScraper, TataCliqScraper
from scrapers.base import BaseScraper, Deal

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

console = Console()


@dataclass
class ScoutReport:
    total_scraped: int = 0
    new_deals: List[DealRecord] = field(default_factory=list)
    updated_deals: List[DealRecord] = field(default_factory=list)
    price_drops: List[DealRecord] = field(default_factory=list)
    rejections: Dict[str, int] = field(default_factory=dict)


GENERIC_QUERY_WORDS = {
    "shoe", "shoes", "sneaker", "sneakers", "men", "mens", "women", "womens",
    "watch", "watches", "unisex", "casual", "sport", "sports", "running",
    "training", "footwear", "original", "originals", "for", "in", "and", "or",
    "the", "a", "an", "under", "size", "with", "pair", "all", "best"
}

DEFAULT_NEGATIVE_KEYWORDS = [
    "socks", "sock", "shoelace", "shoe lace", "shoelaces",
    "cleaning kit", "shoe care", "deodorizer", "insole", "insoles",
    "strap only", "case only", "crease protector", "shoe tree",
    "shoe horn", "shoe bag"
]


def check_scout_filter(deal: Deal, cfg: Dict[str, Any], query_overrides: Optional[Dict[str, Any]] = None) -> tuple[bool, Optional[str]]:
    """Deterministic pre-filter with detailed rejection reason."""
    ovr = query_overrides or {}
    wl = cfg.get("watchlist", {})
    deal_title = (deal.title or "").strip()
    deal_brand = (deal.brand or "").strip()
    title_lower = deal_title.lower()
    brand_lower = deal_brand.lower()
    query_str = (ovr.get("query") or "").lower()

    # 1. Price band
    effective_price = deal.wow_price if deal.wow_price else deal.sale_price
    min_price = float(ovr.get("min_price", cfg.get("min_price", wl.get("min_price", 0))))
    max_price = float(ovr.get("max_price", cfg.get("max_price", wl.get("max_price", 999999))))
    if effective_price < min_price:
        return False, f"price below min (₹{effective_price:.0f} < ₹{min_price:.0f})"
    if effective_price > max_price:
        return False, f"price above max (₹{effective_price:.0f} > ₹{max_price:.0f})"

    # 2. Minimum discount %
    effective_disc = max(deal.discount_pct or 0.0, deal.wow_discount_pct or 0.0)
    min_disc = float(ovr.get("min_discount_pct", cfg.get("min_discount_pct", wl.get("min_discount_pct", 0))))
    if effective_disc < min_disc:
        return False, f"discount below target (<{min_disc:.0f}%)"

    # 3. Negative keyword blocklist (accessories & clutter)
    neg_keywords = cfg.get("negative_keywords") or DEFAULT_NEGATIVE_KEYWORDS
    for nk in neg_keywords:
        nk_clean = nk.strip().lower()
        if nk_clean and re.search(r"\b" + re.escape(nk_clean) + r"\b", title_lower):
            return False, f"matched negative keyword '{nk_clean}'"

    # 4. Brand whitelist with regex word boundaries (avoids 'asics' matching 'basics')
    brands = ovr["brands"] if "brands" in ovr else wl.get("brands", [])
    if brands:
        full_brand_text = f"{brand_lower} {title_lower}"
        matched_any_brand = False
        # If product brand is explicitly part of the search query itself, allow it
        if brand_lower and re.search(r"\b" + re.escape(brand_lower) + r"\b", query_str):
            matched_any_brand = True
        else:
            for b in brands:
                b_clean = b.strip().lower()
                if b_clean and re.search(r"\b" + re.escape(b_clean) + r"\b", full_brand_text):
                    matched_any_brand = True
                    break
        if not matched_any_brand:
            return False, "unmatched brand"

    # 5. Gender alignment check (default is 'na' = no gender filtering)
    target_gender = str(ovr.get("gender", "na")).lower().strip()
    if target_gender not in ("na", "all", "", "none"):
        product_gender = (deal.gender or "").lower()

        # Strict men's query check: drop women-only products
        if target_gender in ("men", "male"):
            if "unisex" not in title_lower and "unisex" not in product_gender:
                if re.search(r"\b(women|womens|ladies|female)\b", title_lower) or product_gender in ("women", "female"):
                    if not re.search(r"\b(men|mens|male|gents)\b", title_lower):
                        return False, "women's product in men's query"

        # Strict women's query check: drop men-only products
        elif target_gender in ("women", "female"):
            if "unisex" not in title_lower and "unisex" not in product_gender:
                if re.search(r"\b(men|mens|gents|male)\b", title_lower) or product_gender in ("men", "male"):
                    if not re.search(r"\b(women|womens|ladies|female)\b", title_lower):
                        return False, "men's product in women's query"

        # Strict kids query check
        elif target_gender in ("kids", "boy", "boys", "girl", "girls"):
            if not any(k in title_lower or k in product_gender for k in ("kid", "boy", "girl", "junior", "infant")):
                return False, "adult product in kids query"

    # 6. Specific model token matching (e.g. 'adidas sl 72' -> requires 'sl' and '72')
    if query_str:
        known_brands = brands if brands else []
        q_clean = query_str
        for b in known_brands:
            q_clean = re.sub(r"\b" + re.escape(b.lower().strip()) + r"\b", " ", q_clean)
        model_tokens = [
            t for t in re.findall(r"[a-z0-9]+", q_clean)
            if t not in GENERIC_QUERY_WORDS and len(t) > 0
        ]
        if model_tokens:
            full_text = f"{brand_lower} {title_lower}"
            text_alphanum = re.sub(r"[^a-z0-9]", "", full_text)
            joined = "".join(model_tokens)
            tokens_in_text = set(re.findall(r"[a-z0-9]+", full_text))
            has_joined = bool(joined and joined in text_alphanum)
            has_all_tokens = all(tok in tokens_in_text for tok in model_tokens)
            if not (has_joined or has_all_tokens):
                return False, "model mismatch with query"

    # 7. Target sizes (if scraper extracted sizes; keep lenient if sizes unknown)
    target_sizes = ovr["target_sizes"] if "target_sizes" in ovr else wl.get("target_sizes", [])
    if target_sizes and deal.available_sizes:
        # Onesize / Free Size / Standard products (watches, accessories, bags) pass size filter
        is_onesize = any(
            str(s).upper().strip() in {"ONESIZE", "ONE SIZE", "FREE SIZE", "FS", "OS", "STANDARD", "ALL SIZES", "ALL SIZES / GENERAL"}
            for s in deal.available_sizes
        )
        if not is_onesize:
            def _norm_s(x):
                s = re.sub(r"^(UK|US|EU|IND|[\/\s\-])+", "", str(x).upper(), flags=re.I)
                s = re.sub(r"[\/\s\-]+", "", s).strip()
                try:
                    f = float(s)
                    return str(int(f)) if f.is_integer() else f"{f:.1f}"
                except ValueError:
                    return s

            deal_sizes = {_norm_s(s) for s in deal.available_sizes if str(s).strip()}
            req_sizes = {_norm_s(s) for s in target_sizes if str(s).strip()}
            if deal_sizes and req_sizes and not deal_sizes.intersection(req_sizes):
                return False, f"target sizes not in stock (stock: {', '.join(deal.available_sizes[:3])})"

    return True, None


def passes_scout_filter(deal: Deal, cfg: Dict[str, Any], query_overrides: Optional[Dict[str, Any]] = None) -> bool:
    """Deterministic pre-filter: drops ~70-95% of noise before DB persistence or LLM calls."""
    passed, _ = check_scout_filter(deal, cfg, query_overrides)
    return passed


class ScoutAgent:
    """Collector Agent responsible for harvesting deals and updating the DB."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.scrapers: Dict[str, BaseScraper] = {}
        self._init_scrapers()

    def _init_scrapers(self) -> None:
        sc = self.config.get("scraper", {})
        pincode = str(self.config.get("pincode", "110009")).strip()
        opts = dict(
            delay=sc.get("request_delay_sec", 2.0),
            timeout=sc.get("timeout_sec", 20),
            max_retries=sc.get("max_retries", 3),
            pincode=pincode,
        )
        use_pw = sc.get("use_playwright", False)
        fetch_wow = sc.get("fetch_wow_price", True)

        fk_cookies = self.config.get("flipkart_cookies") or sc.get("flipkart_cookies", "")
        if not fk_cookies:
            cookie_file = Path("flipkart_cookies.txt")
            if cookie_file.exists():
                fk_cookies = cookie_file.read_text().strip()
            else:
                fk_cookies = os.getenv("FLIPKART_COOKIES", "")

        if use_pw:
            try:
                from scrapers.playwright_scraper import PlaywrightMyntraScraper, PlaywrightTataCliqScraper
                self.scrapers["myntra"] = PlaywrightMyntraScraper(**opts)
                self.scrapers["tatacliq"] = PlaywrightTataCliqScraper(**opts)
            except Exception as e:
                console.print(f"[yellow]Warning initializing Playwright scrapers: {e}. Falling back to HTTP.[/]")
                self.scrapers["myntra"] = MyntraScraper(**opts)
                self.scrapers["tatacliq"] = TataCliqScraper(**opts)
        else:
            self.scrapers["myntra"] = MyntraScraper(**opts)
            self.scrapers["tatacliq"] = TataCliqScraper(**opts)

        self.scrapers["flipkart"] = FlipkartScraper(
            **opts,
            fetch_wow_price=fetch_wow,
            cookies=fk_cookies,
        )

    def collect(
        self,
        queries: List[str | Dict[str, Any]],
        scraper_names: Optional[List[str]] = None
    ) -> ScoutReport:
        """Run collection across queries with live progress bar, deduplicate, and persist to SQLite."""
        report = ScoutReport()
        default_max_products = self.config.get("max_products", 40)

        active_scrapers = [
            (name, s) for name, s in self.scrapers.items()
            if not scraper_names or name.lower() in [n.lower() for n in scraper_names]
        ]

        total_steps = len(queries) * len(active_scrapers)
        if total_steps == 0:
            return report

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}[/]"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            overall_task = progress.add_task("Harvesting deals across retailers", total=total_steps)

            for q_entry in queries:
                if isinstance(q_entry, dict):
                    query = q_entry.get("query", "")
                    q_scrapers = q_entry.get("scrapers")
                    max_prod = q_entry.get("max_products", default_max_products)
                    max_pg = q_entry.get("max_pages")
                else:
                    query = str(q_entry)
                    q_scrapers = scraper_names
                    max_prod = default_max_products
                    max_pg = None

                if not query:
                    continue

                for s_name, s in active_scrapers:
                    if q_scrapers and s_name.lower() not in [n.lower() for n in q_scrapers]:
                        progress.advance(overall_task)
                        continue

                    progress.update(overall_task, description=f"Scouting [yellow]{s_name.title()}[/] for '[green]{query}[/]'")
                    try:
                        q_ovr = q_entry if isinstance(q_entry, dict) else {"query": query}
                        target_brands = q_ovr.get("brands")
                        if not target_brands:
                            wl_brands = self.config.get("watchlist", {}).get("brands", [])
                            matching = [b for b in wl_brands if re.search(r"\b" + re.escape(b.lower()) + r"\b", query.lower())]
                            target_brands = matching if matching else []

                        import inspect
                        sig = inspect.signature(s.scrape)
                        scrape_kwargs = {"max_products": max_prod, "max_pages": max_pg}
                        if target_brands and ("brands" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())):
                            scrape_kwargs["brands"] = target_brands

                        deals = s.scrape(query, **scrape_kwargs)
                        report.total_scraped += len(deals)
                        console.print(f"  [dim]• {s_name.title()}: {len(deals)} items harvested[/]")

                        for deal in deals:
                            # Apply deterministic pre-filter: drops ~70-90% noise before DB & LLM
                            passed, reason = check_scout_filter(deal, self.config, q_ovr)
                            if not passed:
                                if reason:
                                    report.rejections[reason] = report.rejections.get(reason, 0) + 1
                                continue

                            record, is_new = upsert_scraped_deal(deal)
                            if is_new:
                                report.new_deals.append(record)
                            else:
                                report.updated_deals.append(record)
                                if record.price_trend == "DROPPING":
                                    report.price_drops.append(record)
                    except Exception as e:
                        console.print(f"[red]Scraper {s_name} notice: {e}[/]")
                    finally:
                        progress.advance(overall_task)

            progress.update(overall_task, description="[bold green]Harvesting complete[/]")

        console.print(
            f"[bold green]✓ Scout collection finished:[/] {report.total_scraped} raw scraped | "
            f"[green]{len(report.new_deals)} new[/] | "
            f"[cyan]{len(report.updated_deals)} updated[/] | "
            f"[yellow]{len(report.price_drops)} price drops[/]"
        )
        if report.rejections and len(report.new_deals) == 0 and len(report.updated_deals) == 0:
            sorted_reasons = sorted(report.rejections.items(), key=lambda x: x[1], reverse=True)
            summary_items = [f"{cnt}x {r}" for r, cnt in sorted_reasons[:3]]
            console.print(f"  [dim yellow]ℹ️ Why raw items were dropped: {', '.join(summary_items)}[/]")
        return report

    def collect_from_profile(self, profile: WatchProfile) -> ScoutReport:
        """Run collection using a WatchProfile."""
        return self.collect(
            queries=profile.queries,
            scraper_names=profile.scrapers
        )
