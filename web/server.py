"""
FastAPI Web Dashboard & REST API for Deal Scout v2.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
from contextlib import asynccontextmanager
from datetime import datetime
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import load_config, save_config_yaml
from core.db import (
    get_all_deals,
    set_deal_ignored,
    save_user_feedback,
    get_user_feedback_map,
    get_price_history,
    get_price_trackers,
    set_tracker_status,
    delete_price_tracker,
    clear_deals,
    clear_ignored_deals,
    upsert_scraped_deal,
    init_db
)
from core.orchestrator import DealScoutOrchestrator
from agents.tracker import TrackerAgent

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    _start_scheduler_task()
    yield
    _stop_scheduler_task()


app = FastAPI(title="Deal Scout v2", version="2.0.0", lifespan=lifespan)

# Mount frontend static files
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

init_db()
orchestrator = DealScoutOrchestrator()
_is_running_cycle = False
_last_run_stats: Dict[str, Any] = {}
_last_run_time: Optional[str] = None
_next_run_timestamp: Optional[float] = None
_scheduler_task: Optional[asyncio.Task] = None

_logs: List[str] = []


def _append_log(line: str):
    clean = line.strip()
    if clean:
        _logs.append(clean)
        if len(_logs) > 2000:
            _logs.pop(0)


async def _scheduler_loop():
    global _next_run_timestamp, _last_run_time
    while True:
        try:
            cfg = load_config()
            sched = cfg.get("scheduler", {})
            if not sched.get("enabled", False):
                _append_log("ℹ️ Background scheduler paused (disabled in config).")
                break

            interval_mins = max(1, int(sched.get("interval_minutes", 15)))
            interval_secs = interval_mins * 60
            _next_run_timestamp = time.time() + interval_secs
            _append_log(f"⏰ Scheduler active. Next scan scheduled in {interval_mins}m.")

            await asyncio.sleep(interval_secs)

            if _is_running_cycle:
                _append_log("⏳ Scheduled run deferred: an active scan is already in progress.")
                continue

            _append_log("⏰ Scheduled trigger: running periodic deal radar cycle...")
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _run_cycle_worker, False, None, None)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _append_log(f"⚠️ Scheduler background error: {e}")
            await asyncio.sleep(30)


def _start_scheduler_task():
    global _scheduler_task
    cfg = load_config()
    sched = cfg.get("scheduler", {})
    if sched.get("enabled", False):
        if _scheduler_task is None or _scheduler_task.done():
            _scheduler_task = asyncio.create_task(_scheduler_loop())


def _stop_scheduler_task():
    global _scheduler_task, _next_run_timestamp
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
    _scheduler_task = None
    _next_run_timestamp = None


class LogCapture:
    def __init__(self, stream):
        self.stream = stream

    def write(self, s):
        self.stream.write(s)
        if s:
            for l in s.splitlines():
                if l.strip():
                    _append_log(l)

    def flush(self):
        self.stream.flush()

    def fileno(self):
        return self.stream.fileno()


if not isinstance(sys.stdout, LogCapture):
    sys.stdout = LogCapture(sys.stdout)
    sys.stderr = LogCapture(sys.stderr)


class FeedbackRequest(BaseModel):
    deal_id: str
    action: str  # LIKED, DISLIKED, BOUGHT, IGNORED


class IgnoreRequest(BaseModel):
    deal_id: str
    ignored: bool = True


class RunRequest(BaseModel):
    dry_run: bool = False
    query: Optional[str] = None
    scrapers: Optional[List[str]] = None


class AgentSearchRequest(BaseModel):
    query: Optional[str] = None
    prompt: Optional[str] = None


@app.get("/")
async def root():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Deal Scout v2 API is running"}


@app.get("/api/deals")
async def api_get_deals(
    verdict: Optional[str] = None,
    min_score: Optional[float] = None,
    include_ignored: bool = False,
    limit: int = 200
):
    deals = get_all_deals(
        verdict=verdict,
        min_score=min_score,
        include_ignored=include_ignored,
        limit=limit
    )
    all_all = get_all_deals(include_ignored=True, limit=5000)
    ignored_count = len([d for d in all_all if d.ignored])
    return {
        "total": len(deals),
        "ignored_count": ignored_count,
        "deals": [d.model_dump() for d in deals]
    }


@app.get("/api/deals/ignored")
async def api_get_ignored_deals():
    all_deals = get_all_deals(include_ignored=True, limit=5000)
    ignored = [d for d in all_deals if d.ignored]
    return {
        "total": len(ignored),
        "deals": [d.model_dump() for d in ignored]
    }


@app.post("/api/deals/unignore")
async def api_deal_unignore(req: IgnoreRequest):
    set_deal_ignored(req.deal_id, False)
    return {"status": "ok", "deal_id": req.deal_id, "ignored": False}


@app.get("/api/deals/feedback")
async def api_get_deals_feedback():
    return {"feedback": get_user_feedback_map()}


@app.delete("/api/deals")
async def api_clear_deals():
    count = clear_deals(keep_ignored=True)
    return {"status": "ok", "message": f"Cleared {count} deals"}


@app.delete("/api/deals/ignored")
async def api_clear_ignored_deals():
    count = clear_ignored_deals()
    return {"status": "ok", "message": f"Restored {count} ignored deals"}


@app.get("/api/deals/history")
async def api_deal_history(deal_id: str):
    history = get_price_history(deal_id)
    return {
        "deal_id": deal_id,
        "history": [h.model_dump() for h in history]
    }


@app.post("/api/deals/feedback")
async def api_deal_feedback(req: FeedbackRequest):
    save_user_feedback(req.deal_id, req.action)
    return {"status": "ok", "message": f"Feedback {req.action} recorded"}


@app.post("/api/deals/ignore")
async def api_deal_ignore(req: IgnoreRequest):
    set_deal_ignored(req.deal_id, req.ignored)
    return {"status": "ok", "deal_id": req.deal_id, "ignored": req.ignored}


def _run_cycle_worker(dry_run: bool, queries: Optional[List[str]], scrapers: Optional[List[str]]):
    global _is_running_cycle, _last_run_stats, _last_run_time
    _is_running_cycle = True
    _last_run_time = datetime.now().isoformat()
    _append_log(f"🚀 Deal scanner started (dry_run={dry_run}, scrapers={scrapers or 'all'})...")
    try:
        fresh_orch = DealScoutOrchestrator(load_config())
        q_list = [{"query": q} for q in queries] if queries else None
        res = fresh_orch.run_cycle(queries=q_list, scraper_names=scrapers, dry_run=dry_run)
        _last_run_stats = res
        _append_log(f"✓ Deal scanner completed. Scraped: {res.get('total_scraped', 0)} deals.")
        if res.get("rejections_summary") and res.get("new_deals", 0) == 0:
            _append_log(f"ℹ️ Why raw items were dropped: {res['rejections_summary']}")
    except Exception as e:
        _append_log(f"❌ Deal scanner error: {e}")
    finally:
        _is_running_cycle = False


@app.post("/api/run")
async def api_trigger_run(req: RunRequest, background_tasks: BackgroundTasks):
    global _is_running_cycle
    if _is_running_cycle:
        raise HTTPException(status_code=409, detail="An agent cycle is already running")

    queries = [req.query] if req.query else None
    background_tasks.add_task(_run_cycle_worker, req.dry_run, queries, req.scrapers)
    return {"status": "started", "dry_run": req.dry_run}


_active_agent_task: Optional[Any] = None


@app.post("/api/agent/search")
async def api_agent_search(req: AgentSearchRequest):
    global _active_agent_task
    query = (req.query or req.prompt or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query or prompt is required")

    from agent import search_and_judge
    from scrapers.base import Deal

    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, search_and_judge, query)
    _active_agent_task = task

    try:
        res = await asyncio.wrap_future(task)

        # Persist qualified deals (STEAL / WORTH_IT) into SQLite — never save SKIP noise
        for d in res.get("deals", []):
            if d.get("agent_verdict") not in ("STEAL", "WORTH_IT"):
                continue
            try:
                deal_obj = Deal(
                    title=d.get("title", ""),
                    brand=d.get("brand", ""),
                    original_price=float(d.get("original_price") or 0.0),
                    sale_price=float(d.get("sale_price") or 0.0),
                    discount_pct=float(d.get("discount_pct") or 0.0),
                    available_sizes=d.get("available_sizes") or [],
                    product_url=d.get("product_url") or "",
                    source=d.get("source") or "unknown",
                    image_url=d.get("image_url"),
                    wow_price=d.get("wow_price"),
                    wow_discount_pct=d.get("wow_discount_pct"),
                    gender=d.get("gender"),
                )
                upsert_scraped_deal(deal_obj)
            except Exception:
                pass

        return res
    except (asyncio.CancelledError, concurrent.futures.CancelledError):
        raise HTTPException(status_code=499, detail="Search aborted by user")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _active_agent_task = None


@app.post("/api/agent/abort")
async def api_agent_abort():
    global _active_agent_task
    if _active_agent_task and not _active_agent_task.done():
        _active_agent_task.cancel()
        _active_agent_task = None
        return {"status": "ok", "message": "Search aborted"}
    return {"status": "ok", "message": "No active search"}


@app.get("/api/status")
async def api_get_status():
    global _is_running_cycle, _last_run_stats, _last_run_time, _next_run_timestamp
    all_deals = get_all_deals(include_ignored=True, limit=5000)
    steals = [d for d in all_deals if d.verdict == "STEAL"]
    worth_it = [d for d in all_deals if d.verdict == "WORTH_IT"]
    ignored = [d for d in all_deals if d.ignored]

    trackers = get_price_trackers()
    active_trackers = [t for t in trackers if t.status == "ACTIVE"]
    hit_trackers = [t for t in trackers if t.status == "HIT"]

    cfg = load_config()
    sched = cfg.get("scheduler", {})
    sched_enabled = bool(sched.get("enabled", False))
    interval_m = int(sched.get("interval_minutes", 15))
    next_sec = None
    if sched_enabled and _next_run_timestamp:
        next_sec = max(0, int(_next_run_timestamp - time.time()))
    elif sched_enabled:
        next_sec = interval_m * 60

    return {
        "is_running": _is_running_cycle,
        "last_run": _last_run_stats,
        "last_run_time": _last_run_time,
        "logs": list(_logs[-200:]),
        "database": {
            "total_deals": len(all_deals),
            "steals_count": len(steals),
            "worth_it_count": len(worth_it),
            "ignored_count": len(ignored),
        },
        "trackers": {
            "total": len(trackers),
            "active": len(active_trackers),
            "hit": len(hit_trackers),
        },
        "scheduler": {
            "enabled": sched_enabled,
            "interval_minutes": interval_m,
            "next_run_in_seconds": next_sec,
        }
    }


@app.get("/api/config")
async def api_get_config():
    return load_config()


@app.post("/api/config")
async def api_save_config(new_cfg: Dict[str, Any]):
    save_config_yaml(new_cfg)
    return {"status": "ok", "message": "Config updated"}


class ScheduleRequest(BaseModel):
    enabled: bool
    interval_minutes: int = 15


@app.post("/api/schedule")
async def api_update_schedule(req: ScheduleRequest):
    cfg = load_config()
    cfg.setdefault("scheduler", {})["enabled"] = req.enabled
    cfg["scheduler"]["interval_minutes"] = req.interval_minutes
    save_config_yaml(cfg)

    _stop_scheduler_task()
    if req.enabled:
        _start_scheduler_task()

    next_sec = req.interval_minutes * 60 if req.enabled else None

    return {
        "status": "ok",
        "scheduler": {
            "enabled": req.enabled,
            "interval_minutes": req.interval_minutes,
            "next_run_in_seconds": next_sec,
        }
    }


@app.post("/api/stop")
async def api_stop_run():
    global _is_running_cycle
    _is_running_cycle = False
    return {"status": "ok", "message": "Run stopped"}


@app.post("/api/logs/clear")
async def api_clear_logs():
    _logs.clear()
    return {"status": "ok"}


# ── API: Price Trackers ───────────────────────────────────────────────────────

class CreateTrackerRequest(BaseModel):
    target_input: str  # URL or keyword
    target_price: float
    target_size: Optional[str] = None
    target_type: str = "ANY"
    check_interval: int = 30


@app.get("/api/trackers")
async def api_get_trackers(status: Optional[str] = None):
    trackers = get_price_trackers(status=status)
    return {"total": len(trackers), "trackers": [t.model_dump() for t in trackers]}


@app.get("/api/trackers/search")
async def api_search_tracker_candidates(keyword: str, limit: int = 20, force_scrape: bool = True):
    candidates = await asyncio.to_thread(
        TrackerAgent().search_keyword_candidates,
        keyword,
        limit,
        force_scrape,
    )
    return {"total": len(candidates), "candidates": [c.model_dump() for c in candidates]}


@app.post("/api/trackers")
async def api_create_tracker(req: CreateTrackerRequest):
    trackers = await asyncio.to_thread(
        TrackerAgent().create_tracker,
        req.target_input,
        req.target_price,
        req.target_size,
        req.target_type,
        req.check_interval,
        False,
    )
    return {"status": "ok", "trackers": [t.model_dump() for t in trackers]}


@app.post("/api/trackers/{tracker_id}/pause")
async def api_pause_tracker(tracker_id: int):
    set_tracker_status(tracker_id, "PAUSED")
    return {"status": "ok", "tracker_id": tracker_id, "new_status": "PAUSED"}


@app.post("/api/trackers/{tracker_id}/resume")
async def api_resume_tracker(tracker_id: int):
    set_tracker_status(tracker_id, "ACTIVE")
    return {"status": "ok", "tracker_id": tracker_id, "new_status": "ACTIVE"}


@app.delete("/api/trackers/{tracker_id}")
async def api_delete_tracker(tracker_id: int):
    delete_price_tracker(tracker_id)
    return {"status": "ok", "tracker_id": tracker_id}


@app.post("/api/trackers/check")
async def api_check_trackers(dry_run: bool = False):
    stats = await asyncio.to_thread(TrackerAgent().check_all_trackers, dry_run, True)
    return {"status": "ok", **stats}

