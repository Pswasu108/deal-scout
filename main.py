#!/usr/bin/env python3
"""
Deal Scout v2 — Autonomous Multi-Agent Deal Engine
-------------------------------------------------
Commands:
  python main.py                     # Run one complete multi-agent cycle
  python main.py --continuous        # Run autonomously on scheduler (every N minutes)
  python main.py --query "nike dunks" # Target specific search
  python main.py --dry-run           # Run without dispatching notifications
  python main.py --web               # Launch FastAPI web dashboard
"""
from __future__ import annotations
import argparse
import sys
import time

from rich.console import Console

from core.db import init_db, import_legacy_seen_deals, set_tracker_status, delete_price_tracker
from core.orchestrator import DealScoutOrchestrator
from core.scheduler import ScoutScheduler
from agents.tracker import TrackerAgent

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Deal Scout v2 — Autonomous Multi-Agent System")
    parser.add_argument("--query", nargs="*", help="Run cycle for specific search query")
    parser.add_argument("--scraper", nargs="*", choices=["myntra", "flipkart", "tatacliq"], help="Limit scrapers")
    parser.add_argument("--continuous", action="store_true", help="Run autonomously in background loop")
    parser.add_argument("--interval", type=int, default=30, help="Interval in minutes for continuous run")
    parser.add_argument("--dry-run", action="store_true", help="Skip sending external notifications")
    parser.add_argument("--min-discount", type=float, default=None, help="Override minimum discount %%")
    parser.add_argument("--no-playwright", action="store_true", help="Disable Playwright browser scraping (faster HTTP)")
    parser.add_argument("--web", action="store_true", help="Launch FastAPI web dashboard")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload in web mode")
    parser.add_argument("--port", type=int, default=8080, help="Web dashboard port")

    # Price tracker flags
    parser.add_argument("--track", help="Product URL or search keyword to track")
    parser.add_argument("--target", type=float, help="Target price in INR for --track")
    parser.add_argument("--size", help="Optional target size for --track")
    parser.add_argument("--target-type", default="ANY", choices=["ANY", "SALE", "WOW"], help="Price type to compare")
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-pick top match without prompt")
    parser.add_argument("--trackers", action="store_true", help="List all configured price trackers")
    parser.add_argument("--check-trackers", action="store_true", help="Force check all active trackers now")
    parser.add_argument("--tracker-pause", type=int, metavar="ID", help="Pause a tracker by ID")
    parser.add_argument("--tracker-resume", type=int, metavar="ID", help="Resume a tracker by ID")
    parser.add_argument("--tracker-delete", type=int, metavar="ID", help="Delete a tracker by ID")
    args = parser.parse_args()

    # 1. Initialize SQLite Database & migrate legacy data if needed
    init_db()
    import_legacy_seen_deals()

    # 1b. Handle price tracker commands
    if args.tracker_pause is not None:
        set_tracker_status(args.tracker_pause, "PAUSED")
        console.print(f"[yellow]⏸ Tracker #{args.tracker_pause} paused.[/]")
        return
    if args.tracker_resume is not None:
        set_tracker_status(args.tracker_resume, "ACTIVE")
        console.print(f"[green]▶ Tracker #{args.tracker_resume} resumed.[/]")
        return
    if args.tracker_delete is not None:
        delete_price_tracker(args.tracker_delete)
        console.print(f"[red]✗ Tracker #{args.tracker_delete} deleted.[/]")
        return
    if args.trackers:
        TrackerAgent().print_trackers_table()
        return
    if args.track:
        if args.target is None:
            console.print("[red]Error: --target <price> is required with --track[/]")
            sys.exit(1)
        TrackerAgent().create_tracker(
            target_input=args.track,
            target_price=args.target,
            target_size=args.size,
            target_type=args.target_type,
            check_interval=args.interval,
            interactive=not args.yes,
        )
        return
    if args.check_trackers:
        TrackerAgent().check_all_trackers(dry_run=args.dry_run, force=True)
        TrackerAgent().print_trackers_table()
        return

    # 2. Web mode
    if args.web:
        import uvicorn
        console.print(f"[bold green]🚀 Launching Deal Scout Web on http://127.0.0.1:{args.port}[/]")
        if args.reload:
            uvicorn.run("web.server:app", host="0.0.0.0", port=args.port, reload=True)
        else:
            from web.server import app
            uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    from core.config import load_config
    cfg = load_config()
    if args.no_playwright:
        cfg.setdefault("scraper", {})["use_playwright"] = False

    orchestrator = DealScoutOrchestrator(config=cfg)

    # 3. Continuous daemon mode
    if args.continuous:
        console.print(f"[bold green]🔄 Deal Scout daemon starting (running every {args.interval} minutes)...[/]")
        scheduler = ScoutScheduler(orchestrator)
        scheduler.start(interval_minutes=args.interval)

        # Run first cycle immediately
        orchestrator.run_cycle(dry_run=args.dry_run)

        try:
            while True:
                time.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            console.print("\n[yellow]Stopping Deal Scout daemon...[/]")
            scheduler.stop()
            sys.exit(0)

    # 4. Single run mode
    queries = args.query if args.query else None
    criteria = None
    if queries is not None or args.min_discount is not None:
        criteria = {
            "brands": [],
            "target_sizes": [],
            "min_price": 0,
            "max_price": 999999,
        }
        if args.min_discount is not None:
            criteria["min_discount_pct"] = args.min_discount

    orchestrator.run_cycle(
        queries=queries,
        scraper_names=args.scraper,
        dry_run=args.dry_run,
        criteria=criteria,
    )


if __name__ == "__main__":
    main()
