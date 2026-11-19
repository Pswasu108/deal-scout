"""Database operations and SQLite storage for Deal Scout."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from core.models import DealRecord, PriceSnapshot, WatchProfile, UserFeedbackRecord, PriceTracker
from scrapers.base import Deal

DB_PATH = Path(__file__).resolve().parent.parent / "deal_scout.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialize database tables."""
    with get_connection(db_path) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS deals (
            deal_id             TEXT PRIMARY KEY,
            source              TEXT NOT NULL,
            title               TEXT NOT NULL,
            brand               TEXT NOT NULL,
            original_price      REAL NOT NULL DEFAULT 0.0,
            sale_price          REAL NOT NULL DEFAULT 0.0,
            discount_pct        REAL NOT NULL DEFAULT 0.0,
            wow_price           REAL,
            wow_discount_pct    REAL,
            available_sizes     TEXT NOT NULL DEFAULT '[]',
            product_url         TEXT NOT NULL DEFAULT '',
            image_url           TEXT,
            gender              TEXT,
            score               REAL,
            verdict             TEXT,
            reason              TEXT,
            first_seen          TEXT NOT NULL,
            last_seen           TEXT NOT NULL,
            last_price          REAL,
            price_trend         TEXT NOT NULL DEFAULT 'STABLE',
            notified            INTEGER NOT NULL DEFAULT 0,
            ignored             INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_deals_verdict ON deals(verdict);
        CREATE INDEX IF NOT EXISTS idx_deals_source ON deals(source);
        CREATE INDEX IF NOT EXISTS idx_deals_notified ON deals(notified);
        CREATE INDEX IF NOT EXISTS idx_deals_last_seen ON deals(last_seen);

        CREATE TABLE IF NOT EXISTS price_history (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id             TEXT NOT NULL,
            sale_price          REAL NOT NULL,
            wow_price           REAL,
            recorded_at         TEXT NOT NULL,
            FOREIGN KEY (deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_price_history_deal ON price_history(deal_id);

        CREATE TABLE IF NOT EXISTS watch_profiles (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT NOT NULL,
            queries             TEXT NOT NULL DEFAULT '[]',
            brands              TEXT NOT NULL DEFAULT '[]',
            target_sizes        TEXT NOT NULL DEFAULT '[]',
            min_discount_pct    REAL NOT NULL DEFAULT 0.0,
            min_price           REAL NOT NULL DEFAULT 0.0,
            max_price           REAL NOT NULL DEFAULT 999999.0,
            scrapers            TEXT,
            schedule_minutes    INTEGER NOT NULL DEFAULT 30,
            enabled             INTEGER NOT NULL DEFAULT 1,
            created_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_feedback (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id             TEXT NOT NULL,
            action              TEXT NOT NULL,
            created_at          TEXT NOT NULL,
            FOREIGN KEY (deal_id) REFERENCES deals(deal_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_deal ON user_feedback(deal_id);

        CREATE TABLE IF NOT EXISTS price_trackers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            product_url         TEXT,
            search_keyword      TEXT,
            matched_deal_id     TEXT,
            source              TEXT,
            target_price        REAL NOT NULL,
            target_type         TEXT NOT NULL DEFAULT 'ANY',
            target_size         TEXT,
            title               TEXT,
            brand               TEXT,
            image_url           TEXT,
            initial_price       REAL,
            lowest_price        REAL,
            current_price       REAL,
            status              TEXT NOT NULL DEFAULT 'ACTIVE',
            check_interval      INTEGER NOT NULL DEFAULT 30,
            last_checked        TEXT,
            times_checked       INTEGER NOT NULL DEFAULT 0,
            alert_count         INTEGER NOT NULL DEFAULT 0,
            expires_at          TEXT,
            notify_channels     TEXT NOT NULL DEFAULT '["telegram","macos"]',
            created_at          TEXT NOT NULL,
            triggered_at        TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_trackers_status ON price_trackers(status);
        """)


def row_to_deal_record(row: sqlite3.Row) -> DealRecord:
    data = dict(row)
    data["available_sizes"] = json.loads(data["available_sizes"] or "[]")
    data["notified"] = bool(data["notified"])
    data["ignored"] = bool(data["ignored"])
    return DealRecord(**data)


def upsert_scraped_deal(deal: Deal, db_path: Path = DB_PATH) -> Tuple[DealRecord, bool]:
    """
    Insert or update a scraped deal.
    Returns (DealRecord, is_new: bool).
    Detects price drop/increase and logs to price_history.
    """
    now_iso = datetime.now().isoformat()
    deal_id = deal.deal_id

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,))
        existing_row = cursor.fetchone()

        if existing_row:
            existing = row_to_deal_record(existing_row)
            is_new = False
            last_price = existing.sale_price
            price_trend = existing.price_trend

            effective_old = existing.wow_price if existing.wow_price else existing.sale_price
            effective_new = deal.wow_price if deal.wow_price else deal.sale_price

            if effective_new < effective_old:
                price_trend = "DROPPING"
            elif effective_new > effective_old:
                price_trend = "RISING"

            cursor.execute("""
                UPDATE deals SET
                    title = ?,
                    brand = ?,
                    original_price = ?,
                    sale_price = ?,
                    discount_pct = ?,
                    wow_price = ?,
                    wow_discount_pct = ?,
                    available_sizes = ?,
                    product_url = ?,
                    image_url = ?,
                    gender = ?,
                    last_seen = ?,
                    last_price = ?,
                    price_trend = ?
                WHERE deal_id = ?
            """, (
                deal.title,
                deal.brand,
                deal.original_price,
                deal.sale_price,
                deal.discount_pct,
                deal.wow_price,
                deal.wow_discount_pct,
                json.dumps(deal.available_sizes or []),
                deal.product_url,
                deal.image_url,
                deal.gender,
                now_iso,
                last_price,
                price_trend,
                deal_id
            ))

            # Record price history if price changed
            if effective_new != effective_old:
                cursor.execute("""
                    INSERT INTO price_history (deal_id, sale_price, wow_price, recorded_at)
                    VALUES (?, ?, ?, ?)
                """, (deal_id, deal.sale_price, deal.wow_price, now_iso))

            cursor.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,))
            return row_to_deal_record(cursor.fetchone()), False

        else:
            is_new = True
            cursor.execute("""
                INSERT INTO deals (
                    deal_id, source, title, brand, original_price, sale_price,
                    discount_pct, wow_price, wow_discount_pct, available_sizes,
                    product_url, image_url, gender, first_seen, last_seen,
                    last_price, price_trend, notified, ignored
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            """, (
                deal_id,
                deal.source,
                deal.title,
                deal.brand,
                deal.original_price,
                deal.sale_price,
                deal.discount_pct,
                deal.wow_price,
                deal.wow_discount_pct,
                json.dumps(deal.available_sizes or []),
                deal.product_url,
                deal.image_url,
                deal.gender,
                now_iso,
                now_iso,
                deal.sale_price,
                "STABLE"
            ))

            cursor.execute("""
                INSERT INTO price_history (deal_id, sale_price, wow_price, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (deal_id, deal.sale_price, deal.wow_price, now_iso))

            cursor.execute("SELECT * FROM deals WHERE deal_id = ?", (deal_id,))
            return row_to_deal_record(cursor.fetchone()), True


def update_deal_verdict(
    deal_id: str,
    score: float,
    verdict: str,
    reason: str,
    db_path: Path = DB_PATH
) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
            UPDATE deals SET
                score = ?,
                verdict = ?,
                reason = ?
            WHERE deal_id = ?
        """, (score, verdict, reason, deal_id))


def mark_deal_notified(deal_id: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE deals SET notified = 1 WHERE deal_id = ?", (deal_id,))


def set_deal_ignored(deal_id: str, ignored: bool = True, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE deals SET ignored = ? WHERE deal_id = ?", (1 if ignored else 0, deal_id))


def save_user_feedback(deal_id: str, action: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO user_feedback (deal_id, action, created_at)
            VALUES (?, ?, ?)
        """, (deal_id, action.upper(), datetime.now().isoformat()))


def get_user_feedback_map(db_path: Path = DB_PATH) -> dict[str, str]:
    """Returns mapping of deal_id -> most recent action ('LIKED', 'DISLIKED', etc.)."""
    with get_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT deal_id, action FROM user_feedback ORDER BY id ASC
        """).fetchall()
        # Newer entries overwrite older ones
        return {r["deal_id"]: r["action"] for r in rows}


def clear_deals(keep_ignored: bool = True, db_path: Path = DB_PATH) -> int:
    """Clear deals from database. If keep_ignored is True, retains deals flagged ignored=1."""
    legacy_json = Path(__file__).resolve().parent.parent / "seen_deals.json"
    if legacy_json.exists():
        try:
            legacy_json.write_text(json.dumps({"ids": [], "deals": []}, indent=2))
        except Exception:
            pass

    with get_connection(db_path) as conn:
        if keep_ignored:
            conn.execute("""
                DELETE FROM price_history 
                WHERE deal_id IN (SELECT deal_id FROM deals WHERE ignored = 0)
            """)
            cursor = conn.execute("DELETE FROM deals WHERE ignored = 0")
        else:
            conn.execute("DELETE FROM price_history")
            cursor = conn.execute("DELETE FROM deals")
        return cursor.rowcount


def clear_ignored_deals(db_path: Path = DB_PATH) -> int:
    """Unmark all ignored deals so they can appear in scans again."""
    with get_connection(db_path) as conn:
        cursor = conn.execute("UPDATE deals SET ignored = 0 WHERE ignored = 1")
        return cursor.rowcount


def get_all_deals(
    verdict: Optional[str] = None,
    include_ignored: bool = False,
    min_score: Optional[float] = None,
    limit: int = 100,
    db_path: Path = DB_PATH
) -> List[DealRecord]:
    query = "SELECT * FROM deals WHERE 1=1"
    params: List[Any] = []

    if not include_ignored:
        query += " AND ignored = 0"
    if verdict:
        query += " AND verdict = ?"
        params.append(verdict)
    if min_score is not None:
        query += " AND score >= ?"
        params.append(min_score)

    query += " ORDER BY score DESC NULLS LAST, last_seen DESC LIMIT ?"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [row_to_deal_record(r) for r in rows]


def get_price_history(deal_id: str, db_path: Path = DB_PATH) -> List[PriceSnapshot]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM price_history WHERE deal_id = ? ORDER BY recorded_at ASC",
            (deal_id,)
        ).fetchall()
        return [PriceSnapshot(**dict(r)) for r in rows]


def import_legacy_seen_deals(json_path: Optional[Path] = None, db_path: Path = DB_PATH) -> int:
    """Import existing deals from seen_deals.json into SQLite."""
    if json_path is None:
        json_path = Path(__file__).resolve().parent.parent / "seen_deals.json"
    if not json_path.exists():
        return 0

    try:
        data = json.loads(json_path.read_text())
    except Exception:
        return 0

    deals_list = data.get("deals", [])
    imported = 0
    now_iso = datetime.now().isoformat()

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        for d in deals_list:
            if not isinstance(d, dict):
                continue
            deal_id = d.get("deal_id") or f"{d.get('source', 'unknown')}::{d.get('product_url', '')}"
            if not deal_id:
                continue

            sizes = d.get("available_sizes") or []
            if isinstance(sizes, str):
                sizes = [s.strip() for s in sizes.split(",") if s.strip()]

            cursor.execute("SELECT 1 FROM deals WHERE deal_id = ?", (deal_id,))
            if cursor.fetchone():
                continue

            cursor.execute("""
                INSERT INTO deals (
                    deal_id, source, title, brand, original_price, sale_price,
                    discount_pct, wow_price, wow_discount_pct, available_sizes,
                    product_url, image_url, gender, score, verdict, reason,
                    first_seen, last_seen, last_price, price_trend, notified, ignored
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                deal_id,
                d.get("source", "unknown"),
                d.get("title", ""),
                d.get("brand", ""),
                float(d.get("original_price") or 0.0),
                float(d.get("sale_price") or 0.0),
                float(d.get("discount_pct") or 0.0),
                float(d.get("wow_price")) if d.get("wow_price") is not None else None,
                float(d.get("wow_discount_pct")) if d.get("wow_discount_pct") is not None else None,
                json.dumps(sizes),
                d.get("product_url", ""),
                d.get("image_url"),
                d.get("gender"),
                float(d.get("score")) if d.get("score") is not None else (
                    9.0 if d.get("agent_verdict") == "STEAL" else (
                        6.5 if d.get("agent_verdict") == "WORTH_IT" else None
                    )
                ),
                d.get("agent_verdict") or d.get("verdict"),
                d.get("agent_reason") or d.get("reason"),
                d.get("scraped_at") or now_iso,
                now_iso,
                float(d.get("sale_price") or 0.0),
                "STABLE",
                1,
                0
            ))
            imported += 1

    return imported

    query = "SELECT * FROM watch_profiles"
    if enabled_only:
        query += " WHERE enabled = 1"

    with get_connection(db_path) as conn:
        rows = conn.execute(query).fetchall()
        profiles = []
        for r in rows:
            d = dict(r)
            d["queries"] = json.loads(d["queries"] or "[]")
            d["brands"] = json.loads(d["brands"] or "[]")
            d["target_sizes"] = json.loads(d["target_sizes"] or "[]")
            d["scrapers"] = json.loads(d["scrapers"]) if d["scrapers"] else None
            d["enabled"] = bool(d["enabled"])
            profiles.append(WatchProfile(**d))
        return profiles


def upsert_watch_profile(profile: WatchProfile, db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        if profile.id:
            cursor.execute("""
                UPDATE watch_profiles SET
                    name = ?,
                    queries = ?,
                    brands = ?,
                    target_sizes = ?,
                    min_discount_pct = ?,
                    min_price = ?,
                    max_price = ?,
                    scrapers = ?,
                    schedule_minutes = ?,
                    enabled = ?
                WHERE id = ?
            """, (
                profile.name,
                json.dumps(profile.queries),
                json.dumps(profile.brands),
                json.dumps(profile.target_sizes),
                profile.min_discount_pct,
                profile.min_price,
                profile.max_price,
                json.dumps(profile.scrapers) if profile.scrapers else None,
                profile.schedule_minutes,
                1 if profile.enabled else 0,
                profile.id
            ))
            return profile.id
        else:
            cursor.execute("""
                INSERT INTO watch_profiles (
                    name, queries, brands, target_sizes, min_discount_pct,
                    min_price, max_price, scrapers, schedule_minutes, enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                profile.name,
                json.dumps(profile.queries),
                json.dumps(profile.brands),
                json.dumps(profile.target_sizes),
                profile.min_discount_pct,
                profile.min_price,
                profile.max_price,
                json.dumps(profile.scrapers) if profile.scrapers else None,
                profile.schedule_minutes,
                1 if profile.enabled else 0,
                profile.created_at
            ))
            return cursor.lastrowid


# ── Price Trackers CRUD ────────────────────────────────────────────────────────

def _row_to_tracker(row: sqlite3.Row) -> PriceTracker:
    d = dict(row)
    d["notify_channels"] = json.loads(d["notify_channels"] or '["telegram","macos"]')
    return PriceTracker(**d)


def create_price_tracker(tracker: PriceTracker, db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO price_trackers (
                product_url, search_keyword, matched_deal_id, source,
                target_price, target_type, target_size,
                title, brand, image_url, initial_price, lowest_price, current_price,
                status, check_interval, last_checked, times_checked, alert_count,
                expires_at, notify_channels, created_at, triggered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tracker.product_url,
            tracker.search_keyword,
            tracker.matched_deal_id,
            tracker.source,
            tracker.target_price,
            tracker.target_type,
            tracker.target_size,
            tracker.title,
            tracker.brand,
            tracker.image_url,
            tracker.initial_price,
            tracker.lowest_price,
            tracker.current_price,
            tracker.status,
            tracker.check_interval,
            tracker.last_checked,
            tracker.times_checked,
            tracker.alert_count,
            tracker.expires_at,
            json.dumps(tracker.notify_channels),
            tracker.created_at,
            tracker.triggered_at,
        ))
        return cursor.lastrowid


def get_price_trackers(status: Optional[str] = None, db_path: Path = DB_PATH) -> List[PriceTracker]:
    query = "SELECT * FROM price_trackers"
    params: List[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC"
    with get_connection(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_tracker(r) for r in rows]


def get_price_tracker(tracker_id: int, db_path: Path = DB_PATH) -> Optional[PriceTracker]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM price_trackers WHERE id = ?", (tracker_id,)).fetchone()
        return _row_to_tracker(row) if row else None


def update_price_tracker(tracker: PriceTracker, db_path: Path = DB_PATH) -> None:
    if not tracker.id:
        return
    with get_connection(db_path) as conn:
        conn.execute("""
            UPDATE price_trackers SET
                matched_deal_id = ?,
                source = ?,
                target_price = ?,
                target_type = ?,
                target_size = ?,
                title = ?,
                brand = ?,
                image_url = ?,
                initial_price = ?,
                lowest_price = ?,
                current_price = ?,
                status = ?,
                check_interval = ?,
                last_checked = ?,
                times_checked = ?,
                alert_count = ?,
                triggered_at = ?
            WHERE id = ?
        """, (
            tracker.matched_deal_id,
            tracker.source,
            tracker.target_price,
            tracker.target_type,
            tracker.target_size,
            tracker.title,
            tracker.brand,
            tracker.image_url,
            tracker.initial_price,
            tracker.lowest_price,
            tracker.current_price,
            tracker.status,
            tracker.check_interval,
            tracker.last_checked,
            tracker.times_checked,
            tracker.alert_count,
            tracker.triggered_at,
            tracker.id,
        ))


def set_tracker_status(tracker_id: int, status: str, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("UPDATE price_trackers SET status = ? WHERE id = ?", (status, tracker_id))


def delete_price_tracker(tracker_id: int, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM price_trackers WHERE id = ?", (tracker_id,))

