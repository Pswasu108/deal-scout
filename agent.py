#!/usr/bin/env python3
"""
Deal Scout Agent
----------------
Natural-language interface for deal_scrapper.

Stages:
  1. PARSE  — LLM extracts structured search params from user input
  2. SCRAPE — existing pipeline runs with those params
  3. JUDGE  — LLM scores each deal: STEAL / WORTH_IT / SKIP + reason

Usage:
    python agent.py "Nike or Adidas shoes under 5k, size 10, at least 40% off"
    python agent.py  (interactive prompt)
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from google import genai
from google.genai import types

# ── Env & config ───────────────────────────────────────────────────────────────
load_dotenv(Path(__file__).parent / ".env")

_API_KEY = os.getenv("GEMINI_API_KEY")
if not _API_KEY:
    print("[ERROR] GEMINI_API_KEY not set. Add it to .env or export it.")
    sys.exit(1)

_CLIENT = genai.Client(api_key=_API_KEY)
_CANDIDATE_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-pro-latest",
]


def _call_llm(prompt: str) -> str:
    last_err = None
    for model_name in _CANDIDATE_MODELS:
        for attempt in range(2):
            try:
                resp = _CLIENT.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if resp.text and resp.text.strip():
                    return resp.text.strip()
            except Exception as e:
                last_err = e
                time.sleep(1)
    raise RuntimeError(f"All Gemini candidate models failed. Last error: {last_err}")

CONFIG_PATH = Path(__file__).parent / "config.json"
console = Console()


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


# ── Stage 1: PARSE ─────────────────────────────────────────────────────────────
_PARSE_PROMPT = """\
You are a deal-search parameter extractor for an Indian e-commerce deal scanner.

Extract search parameters from the user's natural language input and return ONLY
valid JSON with these fields (omit fields not mentioned):

{{
  "queries": ["<search term>"],          // required — what to search for
  "brands": ["Brand1", "Brand2"],        // optional
  "target_sizes": ["9", "10", "L"],      // optional — shoe sizes or clothing sizes
  "min_discount_pct": 30,               // optional — integer
  "min_price": 1000,                    // optional — INR
  "max_price": 5000,                    // optional — INR
  "scrapers": ["myntra", "flipkart", "tatacliq"]  // optional — subset if user specifies a store
}}

Rules:
- "queries" must always be present with at least one term
- Convert price ranges like "under 5k" to max_price=5000
- If user says "at least 50% off" set min_discount_pct=50
- Infer sizes: if user says "size 10" add "10" to target_sizes
- Return ONLY the JSON object, no markdown, no explanation

User input: {user_input}
"""

def parse_intent(user_input: str) -> dict:
    """Stage 1: LLM → structured search params."""
    cfg = _load_config()
    prompt = _PARSE_PROMPT.format(user_input=user_input)

    console.print("[dim]▸ Stage 1: Parsing intent...[/]")
    raw = _call_llm(prompt)

    # Strip markdown fences if model adds them
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        params = json.loads(raw)
    except json.JSONDecodeError:
        console.print(f"[red]Failed to parse LLM response:[/] {raw}")
        sys.exit(1)

    # Fill defaults from config for anything not mentioned
    wl = cfg.get("watchlist", {})
    params.setdefault("min_discount_pct", cfg.get("min_discount_pct", wl.get("min_discount_pct", 30)))
    params.setdefault("max_price", cfg.get("max_price", wl.get("max_price", 15000)))
    params.setdefault("min_price", cfg.get("min_price", wl.get("min_price", 0)))

    console.print(f"[green]✓ Parsed:[/] {json.dumps(params, indent=2)}")
    return params


# ── Stage 2: SCRAPE ────────────────────────────────────────────────────────────
def run_pipeline(params: dict) -> list:
    """Stage 2: run existing pipeline with extracted params, return matched deals."""
    import pipeline  # local import — keeps agent.py decoupled

    cfg = _load_config()

    # Build query list with per-query overrides
    query_overrides = {
        k: params[k]
        for k in ("brands", "target_sizes", "min_discount_pct", "min_price", "max_price")
        if k in params
    }
    queries = [{"query": q, **query_overrides} for q in params["queries"]]
    scraper_names = params.get("scrapers")  # None = all

    console.print("[dim]▸ Stage 2: Scraping deals...[/]")

    # Capture deals by monkey-patching save — simpler than modifying pipeline.py
    captured: list = []
    _orig_save = pipeline.save_seen_deals

    def _capture(seen, matched_deals=None):
        if matched_deals:
            captured.extend(matched_deals)
        _orig_save(seen, matched_deals)

    pipeline.save_seen_deals = _capture
    try:
        pipeline.run(queries, scraper_names, dry_run=True)
    finally:
        pipeline.save_seen_deals = _orig_save

    # Deduplicate by deal_id
    seen_ids: set = set()
    unique: list = []
    for d in captured:
        if d.deal_id not in seen_ids:
            seen_ids.add(d.deal_id)
            unique.append(d)

    return unique


# ── Stage 3: JUDGE ─────────────────────────────────────────────────────────────
@dataclass
class Judgment:
    deal_id: str
    verdict: str   # STEAL | WORTH_IT | SKIP
    reason: str


_JUDGE_PROMPT = """\
You are a sharp deal analyst for Indian e-commerce (Myntra, Flipkart, TataCLiQ).
The user was looking for: {user_input}

Rate each deal below. Return ONLY a JSON array, one object per deal:
[
  {{"id": "<deal_id>", "verdict": "STEAL|WORTH_IT|SKIP", "reason": "<max 12 words>"}},
  ...
]

Verdict guide:
- STEAL  : exceptional value (WOW price, very high disc, exactly what user wants)
- WORTH_IT: decent deal, matches user criteria
- SKIP   : below expectations or poor fit

Deals:
{deals_json}

Return ONLY the JSON array.
"""

def judge_deals(deals: list, user_input: str) -> list[Judgment]:
    """Stage 3: LLM scores each deal."""
    if not deals:
        return []

    from dataclasses import asdict
    deals_data = []
    for d in deals:
        deals_data.append({
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
        })

    prompt = _JUDGE_PROMPT.format(
        user_input=user_input,
        deals_json=json.dumps(deals_data, indent=2),
    )

    console.print("[dim]▸ Stage 3: Judging deals...[/]")
    raw = _call_llm(prompt)

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        ratings = json.loads(raw)
    except json.JSONDecodeError:
        console.print(f"[yellow]Could not parse judgments, skipping:[/] {raw}")
        return []

    return [Judgment(r["id"], r["verdict"], r["reason"]) for r in ratings]


# ── Output ─────────────────────────────────────────────────────────────────────
_VERDICT_STYLE = {
    "STEAL":    "bold green",
    "WORTH_IT": "yellow",
    "SKIP":     "dim red",
}
_VERDICT_ICON = {"STEAL": "🔥", "WORTH_IT": "✓", "SKIP": "✗"}


def print_judged_table(deals: list, judgments: list[Judgment]) -> None:
    judgment_map = {j.deal_id: j for j in judgments}

    table = Table(
        title="🤖 Deal Scout — Agent Verdict",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("Verdict",  width=10)
    table.add_column("Source",   style="cyan",       width=8)
    table.add_column("Brand",    style="bold white",  width=12)
    table.add_column("Title",                         width=26)
    table.add_column("Sale",     justify="right",     width=8)
    table.add_column("Disc %",   justify="right",     style="red", width=7)
    table.add_column("WOW",      justify="right",     style="bold green", width=8)
    table.add_column("Reason",                        width=28)

    # Sort: STEAL first, then WORTH_IT, then SKIP
    order = {"STEAL": 0, "WORTH_IT": 1, "SKIP": 2}
    deals_sorted = sorted(
        deals,
        key=lambda d: order.get(judgment_map.get(d.deal_id, Judgment("", "SKIP", "")).verdict, 2),
    )

    for d in deals_sorted:
        j = judgment_map.get(d.deal_id)
        verdict = j.verdict if j else "—"
        reason  = j.reason  if j else ""
        style   = _VERDICT_STYLE.get(verdict, "")
        icon    = _VERDICT_ICON.get(verdict, "")
        wow_str = f"₹{d.wow_price:.0f}" if d.wow_price else "—"

        table.add_row(
            f"[{style}]{icon} {verdict}[/]",
            d.source.title(),
            d.brand or "—",
            d.title[:26],
            f"₹{d.sale_price:.0f}",
            f"{d.discount_pct:.0f}%",
            wow_str,
            f"[{style}]{reason}[/]",
        )

    console.print(table)


def search_and_judge(user_input: str) -> dict:
    """Run all 3 stages and return structured dictionary for API/frontend."""
    from dataclasses import asdict

    params = parse_intent(user_input)
    deals = run_pipeline(params)
    judgments = judge_deals(deals, user_input)
    judgment_map = {j.deal_id: j for j in judgments}

    results = []
    for d in deals:
        d_dict = asdict(d)
        d_dict["deal_id"] = d.deal_id
        j = judgment_map.get(d.deal_id)
        d_dict["agent_verdict"] = j.verdict if j else "WORTH_IT"
        d_dict["agent_reason"] = j.reason if j else ""
        results.append(d_dict)

    # Sort: STEAL first, then WORTH_IT, then SKIP
    order = {"STEAL": 0, "WORTH_IT": 1, "SKIP": 2}
    results.sort(key=lambda x: order.get(x.get("agent_verdict", "WORTH_IT"), 1))

    # Persist deals with judgments to seen_deals.json
    try:
        from pipeline import load_seen_data, SEEN_DEALS_PATH
        seen_data = load_seen_data()
        existing = {d.get("deal_id"): d for d in seen_data.get("deals", []) if isinstance(d, dict)}
        for item in results:
            did = item["deal_id"]
            if did in existing:
                existing[did]["agent_verdict"] = item["agent_verdict"]
                existing[did]["agent_reason"] = item["agent_reason"]
            else:
                existing[did] = item
        seen_ids = set(seen_data.get("ids", [])) | {item["deal_id"] for item in results}
        SEEN_DEALS_PATH.write_text(json.dumps({"ids": list(seen_ids), "deals": list(existing.values())}, indent=2))
    except Exception as e:
        console.print(f"[yellow]Warning: Could not update seen_deals with judgments: {e}[/]")

    return {
        "status": "ok",
        "user_input": user_input,
        "params": params,
        "total_deals": len(results),
        "deals": results,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
    else:
        user_input = console.input("[bold cyan]What are you looking for?[/] ")

    console.rule(f"[bold]Deal Scout Agent[/]")
    console.print(f"[dim]Query:[/] {user_input}\n")

    params   = parse_intent(user_input)
    deals    = run_pipeline(params)

    if not deals:
        console.print("[yellow]No deals matched. Try relaxing your filters.[/]")
        return

    console.print(f"\n[bold]{len(deals)} deals found.[/] Asking LLM to judge...\n")
    judgments = judge_deals(deals, user_input)
    print_judged_table(deals, judgments)


if __name__ == "__main__":
    main()
