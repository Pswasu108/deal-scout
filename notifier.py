"""Notification helpers: Telegram + macOS."""
from __future__ import annotations
import subprocess
import httpx
from scrapers.base import Deal


def notify_macos(deal: Deal) -> None:
    """Send a macOS notification via osascript."""
    title = f"🔥 Deal: {deal.brand} | {deal.discount_pct:.0f}% OFF"
    body = f"₹{deal.sale_price:.0f} (was ₹{deal.original_price:.0f}) — {deal.source.title()}"
    script = (
        f'display notification "{body}" '
        f'with title "{title}" '
        f'sound name "Ping"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
    except Exception as e:
        print(f"  [notify/macos] error: {e}")


def notify_telegram(deal: Deal, bot_token: str, chat_id: str) -> None:
    """Send a Telegram message via Bot API."""
    text = (
        f"🔥 *{deal.brand}* — {deal.discount_pct:.0f}% OFF\n"
        f"📦 {deal.title}\n"
        f"💰 ₹{deal.sale_price:.0f} ~~₹{deal.original_price:.0f}~~\n"
        f"📏 Sizes: {', '.join(deal.available_sizes) or 'N/A'}\n"
        f"🛍 [{deal.source.title()}]({deal.product_url})"
    )
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        with httpx.Client(timeout=10) as client:
            client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            })
    except Exception as e:
        print(f"  [notify/telegram] error: {e}")
