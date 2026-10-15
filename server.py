#!/usr/bin/env python3
"""
Deal Scanner Web Server (Sanic)
--------------------------------
Serves minimal interactive UI and REST API:
1. View deals from seen_deals.json
2. Edit config.json
3. Trigger pipeline runs on demand
4. Schedule pipeline every X minutes
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sanic import Sanic, Request, json as sanic_json, text as sanic_text
from sanic.response import file as sanic_file

from pipeline import (
    ignore_deal,
    unignore_deal,
    load_ignored,
    load_ignored_data,
    clear_ignored_deals,
)

ROOT = Path(__file__).parent.resolve()
CONFIG_PATH = ROOT / "config.json"
SEEN_DEALS_PATH = ROOT / "seen_deals.json"
IGNORED_DEALS_PATH = ROOT / "ignored_deals.json"
SCHEDULE_PATH = ROOT / "schedule.json"
FRONTEND_DIR = ROOT / "frontend"

app = Sanic("deal_scanner_frontend")
app.config.RESPONSE_TIMEOUT = 600
app.config.REQUEST_TIMEOUT = 600
app.config.KEEP_ALIVE_TIMEOUT = 600

# Serve static directory
app.static("/static", str(FRONTEND_DIR), name="static")

# Shared state
class AppState:
    def __init__(self):
        self.is_running: bool = False
        self.current_process: asyncio.subprocess.Process | None = None
        self.last_run_time: str | None = None
        self.last_duration_sec: float | None = None
        self.last_exit_code: int | None = None
        self.logs: list[str] = []
        self.max_logs: int = 2000

        # Scheduler
        self.schedule_enabled: bool = False
        self.schedule_interval_min: int = 15
        self.schedule_next_run_ts: float | None = None
        self.load_schedule_config()

    def load_schedule_config(self):
        if SCHEDULE_PATH.exists():
            try:
                data = json.loads(SCHEDULE_PATH.read_text())
                self.schedule_enabled = bool(data.get("enabled", False))
                self.schedule_interval_min = max(1, int(data.get("interval_minutes", 15)))
                if self.schedule_enabled:
                    self.schedule_next_run_ts = time.time() + (self.schedule_interval_min * 60)
            except Exception:
                pass

    def save_schedule_config(self):
        SCHEDULE_PATH.write_text(
            json.dumps({
                "enabled": self.schedule_enabled,
                "interval_minutes": self.schedule_interval_min,
            }, indent=2)
        )

    def append_log(self, line: str):
        self.logs.append(line)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]


state = AppState()


async def run_pipeline_task(dry_run: bool = False, query: str | None = None, scrapers: list[str] | str | None = None):
    if state.is_running:
        return

    state.is_running = True
    start_ts = time.time()
    state.last_run_time = datetime.now().isoformat()
    state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ▶ Starting scanner run (dry_run={dry_run}, scrapers={scrapers or 'all'})...")

    cmd = [sys.executable, "-u", str(ROOT / "pipeline.py")]
    if dry_run:
        cmd.append("--dry-run")
    if query:
        cmd.extend(["--query", query])
    if scrapers:
        if isinstance(scrapers, list):
            cmd.extend(["--scraper", *scrapers])
        else:
            cmd.extend(["--scraper", str(scrapers)])

    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["FORCE_COLOR"] = "1"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(ROOT),
            env=env,
        )
        state.current_process = proc

        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip()
            state.append_log(line)

        await proc.wait()
        state.last_exit_code = proc.returncode
        duration = round(time.time() - start_ts, 1)
        state.last_duration_sec = duration
        status_msg = "SUCCESS" if proc.returncode == 0 else f"FAILED (code {proc.returncode})"
        state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ■ Run finished: {status_msg} in {duration}s")
    except Exception as exc:
        state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ✖ Error running pipeline: {exc}")
        state.last_exit_code = -1
    finally:
        state.is_running = False
        state.current_process = None


async def scheduler_daemon():
    while True:
        try:
            if state.schedule_enabled and not state.is_running:
                now = time.time()
                if state.schedule_next_run_ts is None:
                    state.schedule_next_run_ts = now + (state.schedule_interval_min * 60)
                elif now >= state.schedule_next_run_ts:
                    state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ⏱ Scheduled trigger fired")
                    asyncio.create_task(run_pipeline_task(dry_run=False))
                    state.schedule_next_run_ts = time.time() + (state.schedule_interval_min * 60)
        except Exception as e:
            state.append_log(f"Scheduler exception: {e}")
        await asyncio.sleep(2)


@app.before_server_start
async def setup_background_tasks(app: Sanic, loop):
    app.add_task(scheduler_daemon())


# ── Frontend Routes ────────────────────────────────────────────────────────────

@app.route("/")
async def serve_index(request: Request):
    index_file = FRONTEND_DIR / "index.html"
    return await sanic_file(str(index_file))


# ── API: Deals ─────────────────────────────────────────────────────────────────

@app.route("/api/deals", methods=["GET"])
async def get_deals(request: Request):
    if not SEEN_DEALS_PATH.exists():
        return sanic_json({"total": 0, "total_ids": 0, "deals": [], "ignored_count": 0})

    try:
        data = json.loads(SEEN_DEALS_PATH.read_text())
    except Exception as e:
        return sanic_json({"error": f"Failed to read seen_deals.json: {e}"}, status=500)

    ids = data.get("ids", [])
    deals = data.get("deals", [])
    ignored_ids = load_ignored()
    include_ignored = request.args.get("include_ignored", "0") in ("1", "true", "yes")

    # If some IDs don't have rich deal objects yet, create fallback descriptors
    known_deal_ids = {d.get("deal_id") for d in deals if isinstance(d, dict)}
    for raw_id in ids:
        if raw_id not in known_deal_ids:
            source = "flipkart" if "flipkart.com" in raw_id else ("myntra" if "myntra.com" in raw_id else "other")
            url = raw_id.split("::", 1)[1] if "::" in raw_id else raw_id
            deals.append({
                "deal_id": raw_id,
                "title": url.split("/")[-1].replace("-", " ").title(),
                "brand": source.title(),
                "original_price": 0,
                "sale_price": 0,
                "discount_pct": 0,
                "available_sizes": [],
                "product_url": url,
                "source": source,
                "image_url": None,
                "wow_price": None,
                "wow_discount_pct": None,
                "gender": None,
                "scraped_at": None,
                "is_placeholder": True,
            })

    if not include_ignored:
        active_deals = []
        for d in deals:
            did = d.get("deal_id", "")
            purl = d.get("product_url", "")
            clean_url = purl.split("?")[0].split("#")[0] if purl else ""
            if did in ignored_ids or purl in ignored_ids or clean_url in ignored_ids:
                continue
            active_deals.append(d)
        deals = active_deals

    return sanic_json({
        "total": len(deals),
        "total_ids": len(ids),
        "ignored_count": len(ignored_ids),
        "deals": deals,
    })


@app.route("/api/deals/ignore", methods=["POST"])
async def api_ignore_deal(request: Request):
    payload = request.json or {}
    deal_id = payload.get("deal_id") or payload.get("url") or payload.get("product_url")
    if not deal_id:
        return sanic_json({"error": "deal_id or url is required"}, status=400)

    try:
        ignore_deal(deal_id, payload)
        return sanic_json({"status": "ok", "message": "Deal ignored", "deal_id": deal_id})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/deals/unignore", methods=["POST"])
async def api_unignore_deal(request: Request):
    payload = request.json or {}
    deal_id = payload.get("deal_id") or payload.get("url") or payload.get("product_url")
    if not deal_id:
        return sanic_json({"error": "deal_id or url is required"}, status=400)

    try:
        unignore_deal(deal_id)
        return sanic_json({"status": "ok", "message": "Deal unignored", "deal_id": deal_id})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/deals/ignored", methods=["GET"])
async def api_get_ignored_deals(request: Request):
    try:
        data = load_ignored_data()
        ignored_deals = data.get("deals", [])
        return sanic_json({"total": len(ignored_deals), "deals": ignored_deals})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/deals/ignored", methods=["DELETE"])
async def api_clear_ignored_deals(request: Request):
    try:
        clear_ignored_deals()
        return sanic_json({"status": "ok", "message": "Ignored listings cleared"})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/deals", methods=["DELETE"])
async def clear_deals(request: Request):
    try:
        SEEN_DEALS_PATH.write_text(json.dumps({"ids": [], "deals": []}, indent=2))
        return sanic_json({"status": "ok", "message": "Seen deals cleared"})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


# ── API: Config ────────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET"])
async def get_config(request: Request):
    if not CONFIG_PATH.exists():
        return sanic_json({"error": "config.json not found"}, status=404)

    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        return sanic_json(cfg)
    except Exception as e:
        return sanic_json({"error": f"Invalid config.json: {e}"}, status=500)


@app.route("/api/config", methods=["POST"])
async def save_config(request: Request):
    try:
        new_cfg = request.json
        if not isinstance(new_cfg, dict):
            return sanic_json({"error": "Config payload must be a JSON object"}, status=400)

        # Basic validations
        for key in ["min_discount_pct", "min_price", "max_price", "watchlist", "search_queries"]:
            if key not in new_cfg:
                return sanic_json({"error": f"Missing required config key: {key}"}, status=400)

        CONFIG_PATH.write_text(json.dumps(new_cfg, indent=2))
        return sanic_json({"status": "ok", "message": "Config saved successfully"})
    except Exception as e:
        return sanic_json({"error": f"Failed to save config: {e}"}, status=500)


# ── API: Runner & Status ───────────────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
async def get_status(request: Request):
    next_in_sec = None
    if state.schedule_enabled and state.schedule_next_run_ts:
        next_in_sec = max(0, int(state.schedule_next_run_ts - time.time()))

    return sanic_json({
        "is_running": state.is_running,
        "last_run_time": state.last_run_time,
        "last_duration_sec": state.last_duration_sec,
        "last_exit_code": state.last_exit_code,
        "logs": state.logs[-200:],  # return recent logs
        "scheduler": {
            "enabled": state.schedule_enabled,
            "interval_minutes": state.schedule_interval_min,
            "next_run_in_seconds": next_in_sec,
        },
    })


@app.route("/api/run", methods=["POST"])
async def trigger_run(request: Request):
    if state.is_running:
        return sanic_json({"error": "A pipeline run is already in progress"}, status=409)

    payload = request.json or {}
    dry_run = bool(payload.get("dry_run", False))
    query = payload.get("query")
    scrapers = payload.get("scrapers") or payload.get("scraper")

    asyncio.create_task(run_pipeline_task(dry_run=dry_run, query=query, scrapers=scrapers))
    return sanic_json({"status": "started", "dry_run": dry_run, "scrapers": scrapers})


@app.route("/api/agent/search", methods=["POST"])
async def api_agent_search(request: Request):
    payload = request.json or {}
    query = (payload.get("query") or payload.get("prompt") or "").strip()
    if not query:
        return sanic_json({"error": "Query or prompt is required"}, status=400)

    state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 AI Agent Search requested: '{query}'")
    try:
        from agent import search_and_judge
        res = await asyncio.to_thread(search_and_judge, query)
        state.append_log(
            f"[{datetime.now().strftime('%H:%M:%S')}] 🤖 AI Agent Search complete: {res.get('total_deals', 0)} deals judged"
        )
        return sanic_json(res)
    except Exception as e:
        state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ✖ AI Agent Search error: {e}")
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/stop", methods=["POST"])
async def stop_run(request: Request):
    if not state.is_running or not state.current_process:
        return sanic_json({"message": "No pipeline run in progress"})

    try:
        state.current_process.terminate()
        state.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠ Pipeline run stopped by user")
        return sanic_json({"status": "stopped"})
    except Exception as e:
        return sanic_json({"error": str(e)}, status=500)


@app.route("/api/logs/clear", methods=["POST"])
async def clear_logs(request: Request):
    state.logs.clear()
    return sanic_json({"status": "cleared"})


# ── API: Scheduler ─────────────────────────────────────────────────────────────

@app.route("/api/schedule", methods=["POST"])
async def set_schedule(request: Request):
    payload = request.json or {}
    if "enabled" in payload:
        state.schedule_enabled = bool(payload["enabled"])
    if "interval_minutes" in payload:
        val = int(payload["interval_minutes"])
        if val < 1:
            return sanic_json({"error": "Interval must be >= 1 minute"}, status=400)
        state.schedule_interval_min = val

    if state.schedule_enabled:
        state.schedule_next_run_ts = time.time() + (state.schedule_interval_min * 60)
    else:
        state.schedule_next_run_ts = None

    state.save_schedule_config()
    return sanic_json({
        "status": "ok",
        "scheduler": {
            "enabled": state.schedule_enabled,
            "interval_minutes": state.schedule_interval_min,
            "next_run_in_seconds": state.schedule_interval_min * 60 if state.schedule_enabled else None,
        }
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting Deal Scanner Web Server on http://{host}:{port}")
    app.run(host=host, port=port, auto_reload=False, access_log=False)
