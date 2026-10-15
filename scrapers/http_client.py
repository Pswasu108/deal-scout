"""Shared httpx client factory with SSL workaround for pyenv/homebrew setups."""
from __future__ import annotations
import warnings
import httpx

# Suppress InsecureRequestWarning for verify=False
warnings.filterwarnings("ignore", message=".*verify=False.*")


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}


def make_client(extra_headers: dict | None = None, timeout: int = 15) -> httpx.Client:
    """Return a configured httpx.Client that works around macOS SSL cert issues."""
    headers = {**BROWSER_HEADERS, **(extra_headers or {})}
    return httpx.Client(
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
        verify=False,  # macOS pyenv+homebrew SSL mismatch workaround
    )
