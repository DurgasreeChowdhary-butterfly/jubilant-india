"""
main.py — FastAPI application for Jubilant India

Run from inside the backend/ directory:
    uvicorn main:app --reload --port 8001
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()   # load .env before any os.getenv() calls in scrapers

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import BackgroundTasks, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

import csv
import io

from fastapi.responses import Response

from database import clear_old_jobs, get_all_jobs_for_export, get_jobs, get_stats, init_db, save_job
from scrapers import scrape_all


# ─────────────────────────────────────────────
# Scrape state  (mutated in-place so all references stay live)
# ─────────────────────────────────────────────

scrape_status: dict = {
    "running":    False,
    "last_run_at": None,
    "last_count":  0,        # jobs inserted in last run
    "last_total":  0,        # jobs collected (before dedup/db filter)
    "per_source":  {},       # {scraper_name: count} from last run
    "error":       None,
}

scheduler = AsyncIOScheduler(timezone="UTC")


# ─────────────────────────────────────────────
# Core scrape task
# ─────────────────────────────────────────────

async def run_scrape() -> None:
    if scrape_status["running"]:
        print("[run_scrape] Already running — skipped.")
        return

    scrape_status["running"] = True
    scrape_status["error"]   = None
    print("[run_scrape] Starting scrape…")

    try:
        result = await scrape_all()
        jobs   = result["jobs"]

        saved = 0
        for job in jobs:
            try:
                if save_job(job):
                    saved += 1
            except Exception as exc:
                print(f"[run_scrape] save_job error: {exc}")

        scrape_status.update({
            "last_run_at": datetime.now(timezone.utc).isoformat(),
            "last_count":  saved,
            "last_total":  result["total"],
            "per_source":  result["stats"],
        })
        print(f"[run_scrape] Done — {saved} new jobs saved  "
              f"({result['total']} collected, {result['total'] - saved} duplicates/skipped).")

        deleted = clear_old_jobs(days=30)
        if deleted:
            print(f"[run_scrape] Pruned {deleted} jobs older than 30 days.")

    except Exception as exc:
        scrape_status["error"] = str(exc)
        print(f"[run_scrape] Fatal error: {exc}")
    finally:
        scrape_status["running"] = False


# ─────────────────────────────────────────────
# App lifecycle
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler.add_job(
        run_scrape,
        IntervalTrigger(hours=4),
        id="auto_scrape",
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    asyncio.create_task(run_scrape())   # initial scrape on startup
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Jubilant India API",
    version="1.0.0",
    description="Indian job aggregator — Hasjob, Wellfound, Cutshort, ATS boards, FreeJobAlert.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Jubilant India API", "docs": "/docs"}


@app.get("/jobs")
def jobs_route(
    keyword:          str  = Query(default=""),
    city:             str  = Query(default=""),
    job_type:         str  = Query(default=""),
    experience_level: str  = Query(default=""),
    source:           str  = Query(default=""),
    salary_min:       int  = Query(default=0),
    has_salary:       bool = Query(default=False),
    limit:            int  = Query(default=20, le=100),
    offset:           int  = Query(default=0),
):
    return get_jobs(
        keyword=keyword,
        city=city,
        job_type=job_type,
        experience_level=experience_level,
        source=source,
        salary_min=salary_min,
        has_salary=has_salary,
        limit=limit,
        offset=offset,
    )


@app.get("/jobs/stats")
def stats_route():
    return get_stats()


@app.post("/scrape")
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Trigger a manual scrape. Returns immediately; scrape runs in background."""
    if scrape_status["running"]:
        return {"message": "A scrape is already in progress.", "status": "already_running"}
    background_tasks.add_task(run_scrape)
    return {"message": "Scrape started in background.", "status": "started"}


@app.get("/jobs/export")
def export_jobs():
    """Download all active jobs as CSV."""
    jobs  = get_all_jobs_for_export()
    out   = io.StringIO()
    fields = [
        "title", "company", "city", "salary_raw", "job_type",
        "experience_level", "source", "apply_link", "date_posted", "date_added",
    ]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(jobs)
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=jubilant_india_jobs.csv"},
    )


@app.get("/scrape/status")
def get_scrape_status():
    """Current scrape state plus next scheduled run time."""
    job      = scheduler.get_job("auto_scrape")
    next_run = job.next_run_time.isoformat() if (job and job.next_run_time) else None
    return {**scrape_status, "next_scrape_at": next_run}
