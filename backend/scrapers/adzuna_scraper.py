"""
adzuna_scraper.py — Adzuna India Jobs API

Sequential fetch with 1.5s polite delay to avoid 429 rate limits.
Each of 15 queries fetches page 1 + page 2 (up to 100 jobs per query).
Requires env vars: ADZUNA_APP_ID and ADZUNA_APP_KEY
"""

import asyncio
import html
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
COUNTRY  = "in"

SEARCHES = [
    "software engineer",
    "python developer",
    "react developer",
    "data scientist",
    "devops engineer",
    "full stack developer",
    "android developer",
    "java developer",
    "machine learning engineer",
    "ui ux designer",
    "nodejs developer",
    "cloud engineer",
    "flutter developer",
    "backend developer",
    "frontend developer",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_date(value: str) -> str:
    if not value:
        return _today()
    try:
        return value[:10]
    except Exception:
        return _today()


def _salary_raw(mn: Optional[float], mx: Optional[float]) -> str:
    if mn and mx:
        return f"{int(mn / 100_000)}-{int(mx / 100_000)} LPA"
    if mn:
        return f"{int(mn / 100_000)} LPA"
    return ""


def _headers() -> dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "application/json"
    return h


# ── Single-page fetch ─────────────────────────────────────────────────────────

async def _fetch_page(
    client:  httpx.AsyncClient,
    app_id:  str,
    app_key: str,
    query:   str,
    page:    int,
) -> List[Dict]:
    """Fetch one search result page and return enriched job dicts."""
    url    = f"{BASE_URL}/{COUNTRY}/search/{page}"
    params = {
        "app_id":           app_id,
        "app_key":          app_key,
        "results_per_page": 50,
        "what":             query,
        "sort_by":          "date",
    }
    try:
        resp = await client.get(url, params=params, headers=_headers(), timeout=20)
        if resp.status_code == 401:
            print(f"[Adzuna] 401 Unauthorized — check API keys")
            return []
        if resp.status_code == 429:
            print(f"[Adzuna] '{query}' p{page}: 429 rate-limited")
            return []
        resp.raise_for_status()

        results = resp.json().get("results", [])
        jobs    = []
        for r in results:
            title = (r.get("title") or "").strip()
            if not title:
                continue

            co_obj   = r.get("company") or {}
            company  = (co_obj.get("display_name") or "").strip() if isinstance(co_obj, dict) else ""
            loc_obj  = r.get("location") or {}
            location = (loc_obj.get("display_name") or "India").strip() if isinstance(loc_obj, dict) else "India"
            desc     = _strip(r.get("description") or "")
            redirect = (r.get("redirect_url") or "").strip()
            if not redirect:
                continue

            mn       = r.get("salary_min")
            mx       = r.get("salary_max")
            sal_raw  = _salary_raw(mn, mx)
            if sal_raw:
                sal_min, sal_max, _ = parse_indian_salary(sal_raw)
            else:
                sal_min = int(mn) if mn else None
                sal_max = int(mx) if mx else None

            combined = f"{title} {location} {desc}"
            jobs.append({
                "title":               title,
                "company":             company or "Unknown",
                "location":            location,
                "city":                normalize_city(combined),
                "salary_raw":          sal_raw,
                "salary_min":          sal_min,
                "salary_max":          sal_max,
                "job_type":            ("Remote"      if "remote" in combined.lower() else
                                        "Internship"  if "intern" in combined.lower() else
                                        "Full Time"),
                "experience_level":    normalize_experience(combined),
                "description_snippet": desc[:200],
                "source":              "Adzuna",
                "source_url":          redirect,
                "apply_link":          redirect,
                "tags":                extract_tags(title, desc),
                "date_posted":         _parse_date(r.get("created") or ""),
            })
        return jobs

    except Exception as exc:
        print(f"[Adzuna] '{query}' p{page}: {exc}")
        return []


# ── Public entry point ────────────────────────────────────────────────────────

async def scrape_adzuna() -> List[Dict]:
    """
    Fetch 15 queries × 2 pages sequentially with 1.5s delay to stay under
    Adzuna's rate limit. Returns job dicts ready for database.save_job().
    """
    app_id  = os.getenv("ADZUNA_APP_ID",  "").strip()
    app_key = os.getenv("ADZUNA_APP_KEY", "").strip()

    if not app_id or not app_key:
        print("[Adzuna] WARNING: ADZUNA_APP_ID / ADZUNA_APP_KEY not set — skipping.")
        return []

    seen:     set[str]   = set()
    all_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        for query in SEARCHES:
            query_total = 0
            for page in (1, 2):
                jobs = await _fetch_page(client, app_id, app_key, query, page)
                for j in jobs:
                    if j["source_url"] not in seen:
                        seen.add(j["source_url"])
                        all_jobs.append(j)
                        query_total += 1

                await asyncio.sleep(1.5)   # polite delay between every request

                # Stop paginating if the page wasn't full (no page 2 exists)
                if len(jobs) < 50:
                    break

            print(f"[Adzuna] '{query}': {query_total} jobs")

    print(f"[Adzuna] Total unique jobs: {len(all_jobs)}")
    return all_jobs
