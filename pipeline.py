#!/usr/bin/env python3
"""
Deal Scanner Pipeline
---------------------
Runs all scrapers → filters by watchlist → deduplicates → prints table → notifies.

Usage:
    python pipeline.py
    python pipeline.py --query "women kurta" --scraper myntra
    python pipeline.py --dry-run      # skip notifications
"""
from __future__ import annotations
import argparse
import json
import os
import signal
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box

from scrapers import MyntraScraper, FlipkartScraper, TataCliqScraper
from scrapers.base import Deal, BaseScraper
from notifier import notify_macos, notify_telegram

from core.config import load_config as _load_core_config

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
SEEN_DEALS_PATH = ROOT / "seen_deals.json"
IGNORED_DEALS_PATH = ROOT / "ignored_deals.json"

console = Console()


# ── Config ─────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    return _load_core_config()


# ── Ignored-deals store ────────────────────────────────────────────────────────
def load_ignored_data() -> dict:
    if IGNORED_DEALS_PATH.exists():
        try:
            return json.loads(IGNORED_DEALS_PATH.read_text())
        except Exception:
            return {"ids": [], "deals": []}

    # Migrate any legacy ignored data from seen_deals.json
    legacy_ids = []
    legacy_deals = []
    if SEEN_DEALS_PATH.exists():
        try:
            s_data = json.loads(SEEN_DEALS_PATH.read_text())
            legacy_ids = s_data.get("ignored_ids", [])
            legacy_deals = s_data.get("ignored_deals", [])
        except Exception:
            pass

    data = {"ids": legacy_ids, "deals": legacy_deals}
    IGNORED_DEALS_PATH.write_text(json.dumps(data, indent=2))
    return data


def load_ignored() -> set[str]:
    data = load_ignored_data()
    ignored = set(data.get("ids", []))
    try:
        cfg = load_config()
        for item in cfg.get("ignored_deals", []) + cfg.get("ignore_list", []):
            if isinstance(item, str):
                ignored.add(item)
            elif isinstance(item, dict) and "url" in item:
                ignored.add(item["url"])
            elif isinstance(item, dict) and "deal_id" in item:
                ignored.add(item["deal_id"])
    except Exception:
        pass
    return ignored


def is_ignored(deal: Deal, ignored: set[str]) -> bool:
    if not ignored:
        return False
    if deal.deal_id in ignored or deal.product_url in ignored:
        return True
    clean_url = deal.product_url.split("?")[0].split("#")[0]
    if clean_url in ignored or f"{deal.source}::{clean_url}" in ignored:
        return True
    return False


def ignore_deal(deal_id_or_url: str, deal_meta: dict | None = None) -> None:
    ign_data = load_ignored_data()
    ignored_ids = set(ign_data.get("ids", []))
    ignored_ids.add(deal_id_or_url)
    if "://" in deal_id_or_url:
        clean = deal_id_or_url.split("?")[0].split("#")[0]
        ignored_ids.add(clean)

    ignored_deals = ign_data.get("deals", [])
    existing_meta = next(
        (d for d in ignored_deals if d.get("deal_id") == deal_id_or_url or d.get("product_url") == deal_id_or_url),
        None
    )
    if not existing_meta and deal_meta:
        meta = dict(deal_meta)
        meta.setdefault("deal_id", deal_id_or_url)
        meta.setdefault("ignored_at", datetime.now().isoformat())
        ignored_deals.append(meta)
    elif not existing_meta:
        ignored_deals.append({
            "deal_id": deal_id_or_url,
            "product_url": deal_id_or_url if "://" in deal_id_or_url else "",
            "ignored_at": datetime.now().isoformat(),
        })

    IGNORED_DEALS_PATH.write_text(
        json.dumps({
            "ids": list(ignored_ids),
            "deals": ignored_deals,
        }, indent=2)
    )

    # Remove from active seen deals
    seen_data = load_seen_data()
    active_deals = [
        d for d in seen_data.get("deals", [])
        if d.get("deal_id") not in ignored_ids and d.get("product_url") not in ignored_ids
    ]
    SEEN_DEALS_PATH.write_text(
        json.dumps({
            "ids": seen_data.get("ids", []),
            "deals": active_deals,
        }, indent=2)
    )


def unignore_deal(deal_id_or_url: str) -> None:
    ign_data = load_ignored_data()
    clean_url = deal_id_or_url.split("?")[0].split("#")[0] if "://" in deal_id_or_url else deal_id_or_url
    ignored_ids = {
        x for x in ign_data.get("ids", [])
        if x != deal_id_or_url and x != clean_url
    }
    ignored_deals = [
        d for d in ign_data.get("deals", [])
        if d.get("deal_id") != deal_id_or_url
        and d.get("product_url") != deal_id_or_url
        and d.get("product_url") != clean_url
    ]

    IGNORED_DEALS_PATH.write_text(
        json.dumps({
            "ids": list(ignored_ids),
            "deals": ignored_deals,
        }, indent=2)
    )


def clear_ignored_deals() -> None:
    IGNORED_DEALS_PATH.write_text(
        json.dumps({
            "ids": [],
            "deals": [],
        }, indent=2)
    )


# ── Seen-deals store ───────────────────────────────────────────────────────────
def load_seen_data() -> dict:
    if SEEN_DEALS_PATH.exists():
        try:
            return json.loads(SEEN_DEALS_PATH.read_text())
        except Exception:
            return {"ids": [], "deals": []}
    return {"ids": [], "deals": []}


def load_seen() -> set[str]:
    data = load_seen_data()
    return set(data.get("ids", []))


def save_seen_deals(seen: set[str], matched_deals: list[Deal] | None = None) -> None:
    data = load_seen_data()
    ignored_ids = load_ignored()
    existing_deals = {}
    for d in data.get("deals", []):
        if isinstance(d, dict) and "deal_id" in d:
            if d["deal_id"] not in ignored_ids and d.get("product_url") not in ignored_ids:
                existing_deals[d["deal_id"]] = d

    if matched_deals:
        for deal in matched_deals:
            if is_ignored(deal, ignored_ids):
                continue
            deal_dict = asdict(deal)
            deal_dict["deal_id"] = deal.deal_id
            if deal.deal_id not in existing_deals:
                deal_dict["scraped_at"] = datetime.now().isoformat()
            else:
                deal_dict["scraped_at"] = existing_deals[deal.deal_id].get(
                    "scraped_at", datetime.now().isoformat()
                )
            existing_deals[deal.deal_id] = deal_dict
            seen.add(deal.deal_id)

    SEEN_DEALS_PATH.write_text(
        json.dumps({
            "ids": list(seen),
            "deals": list(existing_deals.values()),
        }, indent=2)
    )


def save_seen(seen: set[str]) -> None:
    save_seen_deals(seen, None)


# ── Filter ─────────────────────────────────────────────────────────────────────
def passes_watchlist(deal: Deal, cfg: dict, overrides: dict | None = None) -> bool:
    wl = cfg.get("watchlist", {})
    ovr = overrides or {}

    brands = ovr["brands"] if "brands" in ovr else wl.get("brands", [])
    brands_lower = [b.lower() for b in brands]
    target_sizes = set(str(s).upper() for s in ovr.get("target_sizes", wl.get("target_sizes", [])))

    # Priority: query override -> root level -> watchlist -> fallback
    min_disc  = ovr.get("min_discount_pct", cfg.get("min_discount_pct", wl.get("min_discount_pct", 0)))
    max_price = ovr.get("max_price", cfg.get("max_price", wl.get("max_price", float("inf"))))
    min_price = ovr.get("min_price", cfg.get("min_price", wl.get("min_price", 0)))

    # ── Price band (always checks discounted sale price) ────────────────────
    if deal.sale_price < min_price:
        return False
    if deal.sale_price > max_price:
        return False

    # ── Discount ────────────────────────────────────────────────────────────
    effective_disc = max(deal.discount_pct or 0.0, deal.wow_discount_pct or 0.0)
    if effective_disc < min_disc:
        return False

    # ── Brand ───────────────────────────────────────────────────────────────
    if brands_lower and deal.brand.lower() not in brands_lower:
        if not any(b in deal.title.lower() for b in brands_lower):
            return False

    # ── Size (STRICT) ───────────────────────────────────────────────────────
    # If the scraper returned sizes, at least one must match target_sizes.
    # If no sizes were found (scraper couldn't extract them), we let it through
    # and flag it as "size unknown" in the table.
    if target_sizes and deal.available_sizes:
        def _norm_s(x):
            s = str(x).upper().replace("UK", "").replace("US", "").replace("EU", "").strip()
            try:
                f = float(s)
                return str(int(f)) if f.is_integer() else f"{f:.1f}"
            except ValueError:
                return s

        deal_sizes = {_norm_s(s) for s in deal.available_sizes}
        req_sizes = {_norm_s(s) for s in target_sizes}
        if not deal_sizes.intersection(req_sizes):
            return False  # size definitely not available

    return True


# ── Rich table ─────────────────────────────────────────────────────────────────
def print_table(deals: list[Deal], target_sizes: set[str]) -> None:
    table = Table(
        title=f"🔥 Deal Scanner — {datetime.now().strftime('%d %b %Y %H:%M')}",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("Source",   style="cyan",        width=8)
    table.add_column("Brand",    style="bold white",   width=12)
    table.add_column("Title",                         width=28)
    table.add_column("MRP",      justify="right",      style="dim",         width=8)
    table.add_column("Sale",     justify="right",      style="white",       width=8)
    table.add_column("Disc %",   justify="right",      style="red",         width=7)
    table.add_column("WOW",      justify="right",      style="bold green",  width=8)
    table.add_column("WOW Disc", justify="right",      style="bold green",  width=8)
    table.add_column("Sizes ✓",                       width=18)
    table.add_column("URL",                           width=24)

    for d in deals:
        # Highlight sizes that match user's target
        if d.available_sizes:
            size_parts = []
            for s in d.available_sizes[:6]:
                if str(s).upper() in target_sizes:
                    size_parts.append(f"[bold green]{s}[/]")
                else:
                    size_parts.append(f"[dim]{s}[/]")
            size_str = " ".join(size_parts)
        else:
            size_str = "[yellow]unknown[/]"

        wow_str = f"₹{d.wow_price:.0f}" if d.wow_price else "—"
        wow_disc_str = f"{d.wow_discount_pct:.0f}%" if d.wow_discount_pct else "—"

        table.add_row(
            d.source.title(),
            d.brand or "—",
            d.title[:28],
            f"₹{d.original_price:.0f}",
            f"₹{d.sale_price:.0f}",
            f"{d.discount_pct:.0f}%",
            wow_str,
            wow_disc_str,
            size_str,
            d.product_url[:22] + "…",
        )

    console.print(table)


# ── Main ───────────────────────────────────────────────────────────────────────
def build_scrapers(cfg: dict, names: list[str] | None = None) -> list[BaseScraper]:
    sc = cfg["scraper"]
    opts = dict(
        delay=sc["request_delay_sec"],
        timeout=sc["timeout_sec"],
        max_retries=sc["max_retries"],
        pincode=str(cfg.get("pincode", "110009")).strip(),
    )
    use_pw        = sc.get("use_playwright", False)
    fetch_wow     = sc.get("fetch_wow_price", False)
    pincode       = opts["pincode"]

    fk_cookies = (
        cfg.get("flipkart_cookies")
        or sc.get("flipkart_cookies", "")
    )
    if not fk_cookies:
        import os
        from pathlib import Path
        cookie_file = Path("flipkart_cookies.txt")
        if cookie_file.exists():
            fk_cookies = cookie_file.read_text().strip()
        else:
            fk_cookies = os.getenv("FLIPKART_COOKIES", "")

    if use_pw:
        from scrapers.playwright_scraper import PlaywrightMyntraScraper, PlaywrightTataCliqScraper
        all_scrapers: list[BaseScraper] = [
            PlaywrightMyntraScraper(**opts),
            FlipkartScraper(**opts, fetch_wow_price=fetch_wow, cookies=fk_cookies),
            PlaywrightTataCliqScraper(**opts),
        ]
    else:
        all_scrapers = [
            MyntraScraper(**opts),
            FlipkartScraper(**opts, fetch_wow_price=fetch_wow, cookies=fk_cookies),
            TataCliqScraper(**opts),
        ]

    if names:
        return [s for s in all_scrapers if s.name in names]
    return all_scrapers


# ── Manual deal validator ──────────────────────────────────────────────────────
def validate_manual_deals(cfg: dict, scraped: list[Deal]) -> None:
    """Cross-check manually tracked deals against live scraped data."""
    manual = cfg.get("manually_tracked_deals", [])
    if not manual:
        return

    console.rule("[bold yellow]Manual Deal Validation[/]")
    scraped_index = {d.product_url: d for d in scraped}

    for m in manual:
        title_kw = m["title"].lower()
        brand_kw = m["brand"].lower()
        size_want = str(m.get("size_wanted", "")).upper()
        expected_sale = m["sale_price"]
        expected_wow  = m.get("wow_price")

        # Find matching deal in scraped results (fuzzy title match)
        match = next(
            (d for d in scraped
             if brand_kw in d.brand.lower() or brand_kw in d.title.lower()
             if any(kw in d.title.lower() for kw in title_kw.split()[:3])),
            None
        )

        if not match:
            console.print(f"  [red]✗ NOT FOUND:[/] {m['brand']} — {m['title']}")
            continue

        # Price check (accepts either standard sale price or WOW deal price)
        price_ok = (
            abs(match.sale_price - expected_sale) < 50
            or (expected_wow is not None and abs(match.sale_price - expected_wow) < 50)
        )
        price_sym = "[green]✓[/]" if price_ok else "[red]✗[/]"

        # Size check
        size_ok = not size_want or size_want in {str(s).upper() for s in match.available_sizes}
        size_sym = "[green]✓[/]" if size_ok else (
            "[yellow]?[/]" if not match.available_sizes else "[red]✗[/]"
        )

        console.print(
            f"  {price_sym} [bold]{match.brand}[/] {match.title[:40]}\n"
            f"     Price: scraped=₹{match.sale_price:.0f} expected=₹{expected_sale} {price_sym}\n"
            f"     Disc:  {match.discount_pct:.0f}%   "
            f"WOW: {'₹'+str(expected_wow) if expected_wow else 'PDP only'}\n"
            f"     Size {size_want}: {size_sym}  "
            f"Available: {', '.join(match.available_sizes) or 'not in listing'}"
        )



def run(queries: list[str | dict], scraper_names: list[str] | None, dry_run: bool) -> None:
    cfg = load_config()
    seen = load_seen()
    ignored = load_ignored()
    scrapers = build_scrapers(cfg, scraper_names)
    notif_cfg = cfg["notifications"]
    target_sizes = set(str(s).upper() for s in cfg.get("watchlist", {}).get("target_sizes", []))

    all_deals:   list[Deal] = []
    new_deals:   list[Deal] = []
    all_scraped: list[Deal] = []  # unfiltered, for manual validation

    aborted = False

    def handle_abort(signum=None, frame=None):
        nonlocal aborted
        if aborted:
            return
        aborted = True
        console.print(f"\n[bold yellow]⚠ Abort signal received. Dumping {len(all_deals)} collected deals to seen_deals.json...[/]")
        try:
            save_seen_deals(seen, all_deals)
            console.print(f"[bold green]✓ Successfully dumped {len(all_deals)} deals to seen_deals.json[/]")
        except Exception as e:
            console.print(f"[bold red]Failed to dump deals on abort: {e}[/]")
        sys.stdout.flush()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, handle_abort)
        signal.signal(signal.SIGTERM, handle_abort)
    except (ValueError, AttributeError):
        pass

    try:
        for scraper in scrapers:
            for q_entry in queries:
                if isinstance(q_entry, dict):
                    query = q_entry["query"]
                    q_overrides = {k: v for k, v in q_entry.items() if k != "query"}
                else:
                    query = str(q_entry)
                    q_overrides = {}

                # Filter scrapers per query if specified
                q_scrapers = q_overrides.get("scrapers") or q_overrides.get("scraper")
                if q_scrapers:
                    if isinstance(q_scrapers, str):
                        q_scrapers_list = [s.strip().lower() for s in q_scrapers.split(",") if s.strip()]
                    else:
                        q_scrapers_list = [str(s).strip().lower() for s in q_scrapers if str(s).strip()]
                    if scraper.name.lower() not in q_scrapers_list:
                        continue

                ovr_txt = ""
                if q_overrides:
                    ovr_txt = f" [dim]({', '.join(f'{k}={v}' for k, v in q_overrides.items())})[/]"
                console.rule(f"[bold cyan]{scraper.name.title()}[/] ← '{query}'{ovr_txt}")
                try:
                    max_products = int(q_overrides.get("max_products", cfg.get("max_products", cfg.get("scraper", {}).get("max_products", 40))))
                    max_pages = q_overrides.get("max_pages", cfg.get("max_pages", cfg.get("scraper", {}).get("max_pages", None)))
                    if max_pages is not None:
                        max_pages = int(max_pages)
                    deals = scraper.scrape(query, max_products=max_products, max_pages=max_pages)
                    console.print(f"  Found [yellow]{len(deals)}[/] raw products (limit={max_products})")
                except Exception as e:
                    console.print(f"  [red]Error:[/] {e}")
                    deals = []

                all_scraped.extend(deals)
                for deal in deals:
                    if is_ignored(deal, ignored):
                        continue

                    if not passes_watchlist(deal, cfg, q_overrides):
                        continue

                    # Enrich Flipkart deal with in-stock sizes and exact WOW deal price from PDP (limit to avoid blocking)
                    if scraper.name == "flipkart" and cfg.get("scraper", {}).get("fetch_wow_pdp", False) and len(all_deals) < 5:
                        scraper.enrich_deal(deal)
                        if not passes_watchlist(deal, cfg, q_overrides):
                            continue

                    all_deals.append(deal)
                    if deal.deal_id not in seen:
                        new_deals.append(deal)
                        seen.add(deal.deal_id)

                if all_deals:
                    save_seen_deals(seen, all_deals)

        save_seen_deals(seen, all_deals)
    except (KeyboardInterrupt, SystemExit):
        handle_abort()
        raise

    # ── Manual deal cross-check ──────────────────────────────────────────────
    validate_manual_deals(cfg, all_scraped)

    # ── Results table ────────────────────────────────────────────────────────

    console.rule("[bold green]Matched Deals[/]")
    if not all_deals:
        console.print("[yellow]No deals matched your watchlist.[/]")
        return

    all_deals.sort(key=lambda d: d.discount_pct, reverse=True)
    print_table(all_deals, target_sizes)

    console.print(
        f"\n[bold]Total:[/] {len(all_deals)} deals matched | "
        f"[bold green]{len(new_deals)} new[/] this run"
    )

    if dry_run:
        console.print("[dim]--dry-run: skipping notifications[/]")
        return

    for deal in new_deals:
        if notif_cfg["macos_notify"]["enabled"]:
            notify_macos(deal)
        if notif_cfg["telegram"]["enabled"]:
            notify_telegram(
                deal,
                notif_cfg["telegram"]["bot_token"],
                notif_cfg["telegram"]["chat_id"],
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-retailer deal scanner")
    parser.add_argument("--query", nargs="*", help="Override search queries")
    parser.add_argument(
        "--scraper", nargs="*", choices=["myntra", "flipkart", "tatacliq"],
        help="Limit to specific scrapers",
    )
    parser.add_argument("--dry-run", action="store_true", help="Skip notifications")
    parser.add_argument("--ignore", help="Add a product URL or deal_id to ignore/skip list")
    parser.add_argument("--unignore", help="Remove a product URL or deal_id from ignore/skip list")
    parser.add_argument("--clear-ignored", action="store_true", help="Clear all ignored listings")
    parser.add_argument("--max-products", type=int, help="Override raw product limit per query (e.g. 80, 120)")
    args = parser.parse_args()

    if args.clear_ignored:
        clear_ignored_deals()
        console.print("[bold green]✓ Ignored listings cleared.[/]")
        return

    if args.ignore:
        ignore_deal(args.ignore)
        console.print(f"[bold green]✓ Added to ignore list:[/] {args.ignore}")
        return

    if args.unignore:
        unignore_deal(args.unignore)
        console.print(f"[bold green]✓ Removed from ignore list:[/] {args.unignore}")
        return

    cfg = load_config()
    if args.max_products:
        cfg["max_products"] = args.max_products
    queries = args.query or cfg["search_queries"]
    run(queries, args.scraper, args.dry_run)


if __name__ == "__main__":
    main()
