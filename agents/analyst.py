"""
Analyst Agent — Evaluator
Filters deals with fast deterministic rules,
evaluates price drop trends, and uses LLM
for semantic scoring and verdict assignment.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set

from rich.console import Console

from core.config import load_config
from core.db import (
    update_deal_verdict,
    get_connection,
    get_price_history,
)
from core.llm import call_llm
from core.models import DealRecord, WatchProfile

console = Console()


@dataclass
class DealEvaluation:
    deal_id: str
    score: float
    verdict: str  # STEAL, WORTH_IT, SKIP
    reason: str


def _norm_size(sz: Any) -> str:
    s = re.sub(r"^(UK|US|EU|IND|[\/\s\-])+", "", str(sz).upper(), flags=re.I)
    s = re.sub(r"[\/\s\-]+", "", s).strip()
    try:
        f = float(s)
        return str(int(f)) if f.is_integer() else f"{f:.1f}"
    except ValueError:
        return s


class AnalystAgent:
    """Evaluates deals against watchlists, historical trends, and LLM scoring."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or load_config()

    # ── Rule Engine ────────────────────────────────────────────────────────────

    def passes_rules(self, deal: DealRecord, criteria: Optional[Dict[str, Any]] = None) -> bool:
        """Deterministic filtering before LLM."""
        crit = criteria or {}
        wl = self.config.get("watchlist", {})

        brands = crit.get("brands")
        if not brands:
            wl_brands = wl.get("brands", [])
            matching = [b for b in wl_brands if b.lower() in (deal.title or "").lower() or b.lower() in (deal.brand or "").lower()]
            brands = matching if matching else ([deal.brand] if deal.brand else [])
        brands_lower = [b.lower() for b in brands]
        target_sizes = crit["target_sizes"] if "target_sizes" in crit else wl.get("target_sizes", [])

        min_disc = crit.get("min_discount_pct", self.config.get("min_discount_pct", wl.get("min_discount_pct", 0)))
        max_price = crit.get("max_price", self.config.get("max_price", wl.get("max_price", 999999)))
        min_price = crit.get("min_price", self.config.get("min_price", wl.get("min_price", 0)))

        # 1. Price band
        effective_price = deal.wow_price if deal.wow_price else deal.sale_price
        if effective_price < min_price or effective_price > max_price:
            return False

        # 2. Discount threshold
        effective_disc = max(deal.discount_pct or 0.0, deal.wow_discount_pct or 0.0)
        if effective_disc < min_disc:
            return False

        # 3. Brand match
        if brands_lower:
            brand_in_field = deal.brand.lower() in brands_lower
            brand_in_title = any(b in deal.title.lower() for b in brands_lower)
            if not (brand_in_field or brand_in_title):
                return False

        # 4. Strict target size filtering (if sizes available on product)
        if target_sizes and deal.available_sizes:
            is_onesize = any(
                str(s).upper().strip() in {"ONESIZE", "ONE SIZE", "FREE SIZE", "FS", "OS", "STANDARD", "ALL SIZES", "ALL SIZES / GENERAL"}
                for s in deal.available_sizes
            )
            if not is_onesize:
                deal_sizes = {_norm_size(s) for s in deal.available_sizes}
                req_sizes = {_norm_size(s) for s in target_sizes}
                if not deal_sizes.intersection(req_sizes):
                    return False

        return True

    # ── Historical Price Trends ───────────────────────────────────────────────

    def check_price_trend(self, deal_id: str, current_price: float) -> str:
        """Returns context string if deal is at all-time-low or recently dropped."""
        history = get_price_history(deal_id)
        if len(history) <= 1:
            return ""

        prices = [h.wow_price if h.wow_price else h.sale_price for h in history]
        min_past = min(prices)
        if current_price < min_past:
            drop_pct = round((min_past - current_price) / min_past * 100)
            return f"All-time low (dropped {drop_pct}% from prev low ₹{min_past:.0f})"
        elif current_price == min_past and len(prices) > 2:
            return f"Matching all-time low ₹{current_price:.0f}"

        return ""

    # ── Feedback Context ───────────────────────────────────────────────────────

    def _get_user_feedback_summary(self) -> str:
        """Summarize user thumbs up / down for prompt conditioning."""
        try:
            with get_connection() as conn:
                rows = conn.execute("""
                    SELECT uf.action, d.brand, d.title
                    FROM user_feedback uf
                    JOIN deals d ON uf.deal_id = d.deal_id
                    ORDER BY uf.created_at DESC LIMIT 20
                """).fetchall()

            if not rows:
                return ""

            likes = [f"{r['brand']} - {r['title'][:25]}" for r in rows if r['action'] == 'LIKED']
            dislikes = [f"{r['brand']} - {r['title'][:25]}" for r in rows if r['action'] == 'DISLIKED']

            summary = []
            if likes:
                summary.append(f"User previously LIKED: {', '.join(likes[:4])}")
            if dislikes:
                summary.append(f"User previously DISLIKED: {', '.join(dislikes[:4])}")
            return "\n".join(summary)
        except Exception:
            return ""

    # ── Scoring & Evaluation ──────────────────────────────────────────────────

    def evaluate_deals(
        self,
        deals: List[DealRecord],
        user_query_context: str = "",
        criteria: Optional[Dict[str, Any]] = None
    ) -> List[DealEvaluation]:
        """Filter and score deals using rules + LLM."""
        passed_deals = [d for d in deals if self.passes_rules(d, criteria)]
        if not passed_deals:
            return []

        evaluations: List[DealEvaluation] = []
        eval_map: Dict[str, DealEvaluation] = {}
        batch_size = 40

        # Prepare payload for LLM
        deals_payload = []
        for d in passed_deals:
            effective_price = d.wow_price if d.wow_price else d.sale_price
            trend_note = self.check_price_trend(d.deal_id, effective_price)
            deals_payload.append({
                "id": d.deal_id,
                "title": d.title,
                "brand": d.brand,
                "sale_price": d.sale_price,
                "original_price": d.original_price,
                "discount_pct": round(d.discount_pct, 1),
                "wow_price": d.wow_price,
                "wow_discount_pct": round(d.wow_discount_pct, 1) if d.wow_discount_pct else None,
                "sizes": d.available_sizes,
                "source": d.source,
                "price_trend": trend_note or d.price_trend,
            })

        feedback_ctx = self._get_user_feedback_summary()
        total_batches = max(1, (len(deals_payload) + batch_size - 1) // batch_size)

        for b_idx in range(0, len(deals_payload), batch_size):
            batch_slice = deals_payload[b_idx:b_idx + batch_size]
            batch_num = (b_idx // batch_size) + 1

            prompt = f"""You are an expert deal analyst for Indian e-commerce (Myntra, Flipkart, TataCLiQ).
User preference context:
{user_query_context or "Looking for best value, authentic branded fashion & footwear at genuine discounts."}

{feedback_ctx}

Rate each deal below (Batch {batch_num} of {total_batches}, containing {len(batch_slice)} deals).
Return ONLY a valid JSON array of objects:
[
  {{"id": "<deal_id>", "verdict": "STEAL|WORTH_IT|SKIP", "score": <number 1.0 to 10.0>, "reason": "<max 12 words>"}}
]

Verdict guidelines:
- STEAL (Score 8.0-10.0): Exceptional discount, WOW price, high-demand item, verified brand, price drop.
- WORTH_IT (Score 5.0-7.9): Solid price match, reliable brand, decent discount.
- SKIP (Score 1.0-4.9): Mediocre discount, unknown generic brand, or inflated MRP.

Deals to evaluate:
{json.dumps(batch_slice, indent=2)}
"""

            try:
                raw_llm = call_llm(prompt)
                if raw_llm.startswith("```"):
                    raw_llm = raw_llm.split("```")[1]
                    if raw_llm.startswith("json"):
                        raw_llm = raw_llm[4:]
                    raw_llm = raw_llm.strip()

                parsed = json.loads(raw_llm)
                for item in parsed:
                    eval_map[item["id"]] = DealEvaluation(
                        deal_id=item["id"],
                        score=float(item.get("score", 7.0)),
                        verdict=item.get("verdict", "WORTH_IT"),
                        reason=item.get("reason", "Solid deal matching criteria"),
                    )
            except Exception as e:
                console.print(f"[yellow]LLM batch {batch_num}/{total_batches} failed ({e}). Using rule fallback.[/]")
                for d in passed_deals[b_idx:b_idx + batch_size]:
                    eff_disc = max(d.discount_pct or 0.0, d.wow_discount_pct or 0.0)
                    if eff_disc >= 60 or (d.wow_price and eff_disc >= 50):
                        verdict = "STEAL"
                        score = 8.5
                        reason = f"Huge {eff_disc:.0f}% savings with WOW price"
                    elif eff_disc >= 35:
                        verdict = "WORTH_IT"
                        score = 6.8
                        reason = f"Good discount of {eff_disc:.0f}% off"
                    else:
                        verdict = "SKIP"
                        score = 4.0
                        reason = "Discount below high-value threshold"

                    eval_map[d.deal_id] = DealEvaluation(
                        deal_id=d.deal_id,
                        score=score,
                        verdict=verdict,
                        reason=reason
                    )

        evaluations = list(eval_map.values())

        # Update database with scores & verdicts
        for ev in evaluations:
            update_deal_verdict(ev.deal_id, ev.score, ev.verdict, ev.reason)

        return evaluations
