"""Data models for Deal Scout."""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class DealRecord(BaseModel):
    deal_id: str
    source: str
    title: str
    brand: str
    original_price: float = 0.0
    sale_price: float = 0.0
    discount_pct: float = 0.0
    wow_price: Optional[float] = None
    wow_discount_pct: Optional[float] = None
    available_sizes: List[str] = Field(default_factory=list)
    product_url: str = ""
    image_url: Optional[str] = None
    gender: Optional[str] = None

    # Agent evaluation fields
    score: Optional[float] = None  # 1.0 to 10.0
    verdict: Optional[str] = None  # STEAL, WORTH_IT, SKIP
    reason: Optional[str] = None

    # Metadata & Tracking
    first_seen: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_seen: str = Field(default_factory=lambda: datetime.now().isoformat())
    last_price: Optional[float] = None
    price_trend: str = "STABLE"  # DROPPING, STABLE, RISING
    notified: bool = False
    ignored: bool = False


class PriceSnapshot(BaseModel):
    id: Optional[int] = None
    deal_id: str
    sale_price: float
    wow_price: Optional[float] = None
    recorded_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class WatchProfile(BaseModel):
    id: Optional[int] = None
    name: str = "Default Watchlist"
    queries: List[str] = Field(default_factory=list)
    brands: List[str] = Field(default_factory=list)
    target_sizes: List[str] = Field(default_factory=list)
    min_discount_pct: float = 0.0
    min_price: float = 0.0
    max_price: float = 999999.0
    scrapers: Optional[List[str]] = None  # None means all scrapers
    schedule_minutes: int = 30
    enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class UserFeedbackRecord(BaseModel):
    id: Optional[int] = None
    deal_id: str
    action: str  # LIKED, DISLIKED, BOUGHT, IGNORED
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class PriceTracker(BaseModel):
    id: Optional[int] = None
    product_url: Optional[str] = None
    search_keyword: Optional[str] = None
    matched_deal_id: Optional[str] = None
    source: Optional[str] = None

    target_price: float
    target_type: str = "ANY"  # ANY, SALE, WOW
    target_size: Optional[str] = None

    title: Optional[str] = None
    brand: Optional[str] = None
    image_url: Optional[str] = None
    initial_price: Optional[float] = None
    lowest_price: Optional[float] = None
    current_price: Optional[float] = None

    status: str = "ACTIVE"  # ACTIVE, PAUSED, TRIGGERED, EXPIRED
    check_interval: int = 30
    last_checked: Optional[str] = None
    times_checked: int = 0
    alert_count: int = 0
    expires_at: Optional[str] = None
    notify_channels: List[str] = Field(default_factory=lambda: ["telegram", "macos"])

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    triggered_at: Optional[str] = None

