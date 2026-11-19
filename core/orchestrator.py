"""
Orchestrator
Coordinates the Scout, Analyst, and Notifier agents
into a continuous, autonomous pipeline.
"""
from __future__ import annotations
import re
from typing import List, Optional, Dict, Any

from rich.console import Console
from rich.table import Table
from rich import box

from agents.scout import ScoutAgent, ScoutReport
from agents.analyst import AnalystAgent
from agents.notifier import NotifierAgent
from agents.tracker import TrackerAgent
from core.config import load_config
from core.db import get_all_deals
from core.models import DealRecord, WatchProfile

console = Console()


class DealScoutOrchestrator:
    """Master controller orchestrating all agents."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()
        self.scout = ScoutAgent(self.config)
        self.analyst = AnalystAgent(self.config)
        self.notifier = NotifierAgent(self.config)
        self.tracker = TrackerAgent(self.config)

    def run_cycle(
        self,
        queries: Optional[List[str | Dict[str, Any]]] = None,
        scraper_names: Optional[List[str]] = None,
        dry_run: bool = False,
        criteria: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute one full multi-agent cycle:
        1. Scout harvests & deduplicates deals into SQLite
        2. Analyst filters & evaluates deals
        3. Notifier alerts user of top-ranked steals
        """
        console.rule("[bold cyan]🤖 Deal Scout Multi-Agent Cycle Started[/]")

        target_queries = queries or self.config.get("search_queries", [])
        if not target_queries:
            console.print("[yellow]No queries provided or configured in config.yaml[/]")
            return {"status": "no_queries"}

        # Step 1: Scout collects deals
        scout_report: ScoutReport = self.scout.collect(target_queries, scraper_names)

        rejections_summary = ""
        if scout_report.rejections:
            sorted_reasons = sorted(scout_report.rejections.items(), key=lambda x: x[1], reverse=True)
            rejections_summary = ", ".join(f"{cnt}x {r}" for r, cnt in sorted_reasons[:3])
            if len(scout_report.new_deals) == 0:
                console.print(f"  [dim yellow]ℹ️ Why raw items were dropped: {rejections_summary}[/]")

        # Candidate deals to analyze
        if queries is not None:
            # For ad-hoc search queries, analyze all products returned in this scrape
            candidates = scout_report.new_deals + scout_report.updated_deals
        else:
            candidates = scout_report.new_deals + scout_report.price_drops

        if not candidates:
            # If no deals scraped, evaluate existing unjudged or unnotified matching deals
            candidates = [
                d for d in get_all_deals(include_ignored=False, limit=50)
                if not d.verdict or not d.score or not d.notified
            ]

        console.print(f"[bold magenta]🧠 Analyst: evaluating {len(candidates)} candidate deals...[/]")

        # Step 2: Analyst scores & judges
        query_context = ", ".join([
            q.get("query", "") if isinstance(q, dict) else str(q)
            for q in target_queries
        ])
        # Build deterministic eval criteria respecting watchlist and query overrides
        eval_criteria = criteria
        if eval_criteria is None:
            wl = self.config.get("watchlist", {})
            eval_criteria = {
                "brands": wl.get("brands", []),
                "target_sizes": wl.get("target_sizes", []),
                "min_discount_pct": self.config.get("min_discount_pct", wl.get("min_discount_pct", 0)),
                "min_price": self.config.get("min_price", wl.get("min_price", 0)),
                "max_price": self.config.get("max_price", wl.get("max_price", 999999)),
            }
            # Merge per-query overrides if specified
            for q in target_queries:
                if isinstance(q, dict):
                    for k in ("brands", "target_sizes", "min_discount_pct", "min_price", "max_price"):
                        if k in q:
                            eval_criteria[k] = q[k]

        evaluations = self.analyst.evaluate_deals(
            candidates,
            user_query_context=query_context,
            criteria=eval_criteria,
        )

        # Refresh candidate deal objects from DB with new verdicts
        evaluated_deals = get_all_deals(include_ignored=False, limit=len(evaluations) + 10)
        eval_map = {e.deal_id: e for e in evaluations}
        active_steals_worth = [d for d in evaluated_deals if d.deal_id in eval_map and d.verdict in ("STEAL", "WORTH_IT")]

        # Step 3: Print summary table
        display_deals = active_steals_worth
        if queries is not None:
            # Prioritize deals matching query keywords
            q_str = " ".join([q.get("query", "") if isinstance(q, dict) else str(q) for q in target_queries]).lower()
            q_tokens = [t for t in re.split(r"\s+", q_str) if len(t) > 2]
            def _query_relevance(d: DealRecord) -> int:
                text = f"{d.brand} {d.title}".lower()
                return sum(1 for t in q_tokens if t in text)

            pool = active_steals_worth or candidates
            matching = [d for d in pool if _query_relevance(d) > 0]
            if matching:
                display_deals = sorted(
                    matching,
                    key=lambda d: (_query_relevance(d), max(d.wow_discount_pct or 0.0, d.discount_pct or 0.0)),
                    reverse=True
                )[:15]
        elif not display_deals and candidates:
            display_deals = sorted(
                candidates,
                key=lambda d: max(d.discount_pct or 0.0, d.wow_discount_pct or 0.0),
                reverse=True
            )[:15]

        if display_deals:
            self._print_cycle_table(display_deals)
        else:
            recent = get_all_deals(include_ignored=False, limit=15)
            if recent:
                self._print_cycle_table(recent)

        # Step 4: Notifier alerts
        alert_count = 0
        if not dry_run and active_steals_worth:
            console.print(f"[bold cyan]📢 Notifier: dispatching alerts...[/]")
            alert_count = self.notifier.dispatch_batch(active_steals_worth)

        # Step 5: Price Trackers
        tracker_stats = self.tracker.check_all_trackers(dry_run=dry_run)

        console.rule("[bold green]Cycle Complete[/]")
        return {
            "status": "success",
            "total_scraped": scout_report.total_scraped,
            "new_deals": len(scout_report.new_deals),
            "price_drops": len(scout_report.price_drops),
            "rejections_summary": rejections_summary,
            "evaluated": len(evaluations),
            "steals_found": len([e for e in evaluations if e.verdict == "STEAL"]),
            "worth_it_found": len([e for e in evaluations if e.verdict == "WORTH_IT"]),
            "alerts_sent": alert_count,
            "trackers_checked": tracker_stats.get("checked", 0),
            "tracker_alerts": tracker_stats.get("alerts", 0),
        }

    def _print_cycle_table(self, deals: List[DealRecord]) -> None:
        table = Table(
            title="🎯 Evaluated Deals Feed",
            box=box.ROUNDED,
            show_lines=True,
            header_style="bold magenta",
        )
        table.add_column("Verdict", width=12)
        table.add_column("Score", justify="right", width=6)
        table.add_column("Store", style="cyan", width=9)
        table.add_column("Brand", style="bold white", width=12)
        table.add_column("Title", width=26)
        table.add_column("Price", justify="right", style="bold green", width=9)
        table.add_column("Disc %", justify="right", style="red", width=7)
        table.add_column("Reason", width=28)

        for d in deals[:15]:
            if d.verdict == "STEAL":
                verdict_style = "bold green"
                icon = "🔥 "
            elif d.verdict == "WORTH_IT":
                verdict_style = "yellow"
                icon = "✓ "
            else:
                verdict_style = "dim"
                icon = "· "

            price = d.wow_price if d.wow_price else d.sale_price
            disc = d.wow_discount_pct if d.wow_discount_pct else d.discount_pct

            table.add_row(
                f"[{verdict_style}]{icon}{d.verdict or 'MONITORED'}[/]",
                f"{d.score:.1f}" if d.score else "—",
                d.source.title(),
                d.brand,
                d.title[:26],
                f"₹{price:.0f}",
                f"{disc:.0f}%",
                f"[{verdict_style}]{d.reason or 'Added to database'}[/]",
            )

        console.print(table)
