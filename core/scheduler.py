"""Autonomous scheduler using APScheduler for Deal Scout."""
from __future__ import annotations
import logging
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from core.config import load_config
from core.orchestrator import DealScoutOrchestrator

logger = logging.getLogger("deal_scout.scheduler")


class ScoutScheduler:
    """Manages autonomous periodic runs."""

    def __init__(self, orchestrator: Optional[DealScoutOrchestrator] = None):
        self.orchestrator = orchestrator or DealScoutOrchestrator()
        self.scheduler = BackgroundScheduler()
        self._is_running = False

    def schedule_interval(self, minutes: int = 30) -> None:
        """Schedule the full agent cycle every N minutes."""
        self.scheduler.remove_all_jobs()
        self.scheduler.add_job(
            func=self.orchestrator.run_cycle,
            trigger=IntervalTrigger(minutes=max(1, minutes)),
            id="deal_scout_cycle",
            name="Periodic Deal Scout Agent Cycle",
            replace_existing=True,
        )

    def start(self, interval_minutes: Optional[int] = None) -> None:
        if self._is_running:
            return

        cfg = load_config()
        interval = (
            interval_minutes
            or cfg.get("scheduler", {}).get("interval_minutes")
            or cfg.get("schedule_interval_minutes", 30)
        )
        self.schedule_interval(interval)
        self.scheduler.start()
        self._is_running = True

    def stop(self) -> None:
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
