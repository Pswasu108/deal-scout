"""
Notifier Agent — Reporter
Dispatches high-value deal alerts (STEAL / WORTH_IT)
to Telegram and macOS system notifications,
and prepares digests.
"""
from __future__ import annotations
import subprocess
from typing import List, Optional, Dict, Any

import httpx
from rich.console import Console

from core.config import load_config
from core.db import mark_deal_notified
from core.models import DealRecord, PriceTracker

console = Console()


class NotifierAgent:
    """Reporter Agent delivering deal alerts across channels."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()

    # ── macOS Notification ─────────────────────────────────────────────────────

    def notify_macos(self, deal: DealRecord) -> bool:
        """Trigger macOS notification banner."""
        notif_cfg = self.config.get("notifications", {}).get("macos_notify", {})
        if not notif_cfg.get("enabled", True):
            return False

        effective_price = deal.wow_price if deal.wow_price else deal.sale_price
        disc = deal.wow_discount_pct if deal.wow_discount_pct else deal.discount_pct

        title = f"🔥 {deal.verdict or 'Deal'}: {deal.brand} | {disc:.0f}% OFF"
        body = f"₹{effective_price:.0f} (was ₹{deal.original_price:.0f}) — {deal.source.title()}"
        script = (
            f'display notification "{body}" '
            f'with title "{title}" '
            f'sound name "Ping"'
        )
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            return True
        except Exception as e:
            console.print(f"[dim][notifier/macos] notice: {e}[/]")
            return False

    # ── Telegram Notification ──────────────────────────────────────────────────

    def notify_telegram(self, deal: DealRecord) -> bool:
        """Send formatted markdown message to Telegram."""
        tg_cfg = self.config.get("notifications", {}).get("telegram", {})
        if not tg_cfg.get("enabled", False):
            return False

        bot_token = tg_cfg.get("bot_token")
        chat_id = tg_cfg.get("chat_id")
        if not bot_token or not chat_id:
            return False

        effective_price = deal.wow_price if deal.wow_price else deal.sale_price
        disc = deal.wow_discount_pct if deal.wow_discount_pct else deal.discount_pct
        verdict_badge = "🔥 *STEAL*" if deal.verdict == "STEAL" else "✨ *WORTH IT*"

        sizes_str = ", ".join(deal.available_sizes) if deal.available_sizes else "N/A"
        reason_str = f"\n💡 _{deal.reason}_" if deal.reason else ""
        wow_note = " *(WOW Deal with Coupon/Bank Offer)*" if deal.wow_price else ""

        text = (
            f"{verdict_badge} — *{deal.brand}* ({disc:.0f}% OFF)\n"
            f"📦 {deal.title}\n"
            f"💰 *₹{effective_price:.0f}* ~₹{deal.original_price:.0f}~{wow_note}\n"
            f"📏 Sizes: {sizes_str}\n"
            f"🛍 [{deal.source.title()} Deal Link]({deal.product_url}){reason_str}"
        )

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": False,
                })
                return resp.status_code == 200
        except Exception as e:
            console.print(f"[dim][notifier/telegram] error: {e}[/]")
            return False

    # ── Dispatch Deal ──────────────────────────────────────────────────────────

    def dispatch_deal(self, deal: DealRecord) -> None:
        """Notify through configured channels and mark as notified."""
        if deal.notified or deal.ignored:
            return

        if deal.verdict in ("STEAL", "WORTH_IT") or (deal.score and deal.score >= 6.0):
            console.print(f"[bold green]📢 Alerting:[/] [{deal.verdict}] {deal.brand} - ₹{deal.sale_price:.0f}")
            self.notify_macos(deal)
            self.notify_telegram(deal)
            mark_deal_notified(deal.deal_id)

    def dispatch_batch(self, deals: List[DealRecord]) -> int:
        """Dispatch notifications for all qualifying unnotified deals."""
        count = 0
        for deal in deals:
            if not deal.notified and deal.verdict in ("STEAL", "WORTH_IT"):
                self.dispatch_deal(deal)
                count += 1
        return count

    # ── Price Tracker Alerts ──────────────────────────────────────────────────

    def notify_tracker_hit(self, tracker: PriceTracker, deal: Optional[DealRecord] = None) -> None:
        """Alert user when a tracked product hits its target price."""
        current = tracker.current_price or 0.0
        target = tracker.target_price
        diff = target - current
        title = tracker.title or tracker.search_keyword or "Tracked Product"
        source = (tracker.source or "store").title()
        url = tracker.product_url or (deal.product_url if deal else "")

        console.print(
            f"[bold green]🎯 PRICE TARGET HIT![/] {title} ({source}) "
            f"₹{current:.0f} <= target ₹{target:.0f}"
        )

        # macOS notification
        if "macos" in tracker.notify_channels:
            notif_cfg = self.config.get("notifications", {}).get("macos_notify", {})
            if notif_cfg.get("enabled", True):
                mac_title = f"🎯 Target Hit: {tracker.brand or source}"
                mac_body = f"{title[:40]} — ₹{current:.0f} (target ₹{target:.0f})"
                script = (
                    f'display notification "{mac_body}" '
                    f'with title "{mac_title}" '
                    f'sound name "Ping"'
                )
                try:
                    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
                except Exception as e:
                    console.print(f"[dim][notifier/macos] notice: {e}[/]")

        # Telegram notification
        if "telegram" in tracker.notify_channels:
            tg_cfg = self.config.get("notifications", {}).get("telegram", {})
            if tg_cfg.get("enabled", False):
                bot_token = tg_cfg.get("bot_token")
                chat_id = tg_cfg.get("chat_id")
                if bot_token and chat_id:
                    below_txt = f" (₹{diff:.0f} below!)" if diff > 0 else ""
                    size_line = f"\n📏 Size {tracker.target_size}: In Stock ✅" if tracker.target_size else ""
                    low_line = f"\n📉 Lowest tracked: ₹{tracker.lowest_price:.0f}" if tracker.lowest_price else ""
                    link_line = f"\n\n🛒 [Buy Now]({url})" if url else ""

                    text = (
                        f"🎯 *PRICE TARGET HIT!*\n\n"
                        f"*{title}* — {source}\n"
                        f"💰 *₹{current:.0f}*\n"
                        f"🎯 Your target: ₹{target:.0f} ✅{below_txt}"
                        f"{low_line}"
                        f"{size_line}"
                        f"{link_line}"
                    )
                    tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    try:
                        with httpx.Client(timeout=10) as client:
                            client.post(tg_url, json={
                                "chat_id": chat_id,
                                "text": text,
                                "parse_mode": "Markdown",
                                "disable_web_page_preview": False,
                            })
                    except Exception as e:
                        console.print(f"[dim][notifier/telegram] error: {e}[/]")

