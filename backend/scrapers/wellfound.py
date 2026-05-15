"""
wellfound.py — Scraper for wellfound.com (formerly AngelList Talent)

Uses Wellfound's internal GraphQL API with session cookies.
Falls back to REST search endpoint if GraphQL returns nothing.
Requires WELLFOUND_COOKIES env var — returns [] gracefully if not set.
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

GRAPHQL_URL = "https://wellfound.com/graphql"
REST_URL    = "https://wellfound.com/api/talent/search/job_listings"

SEARCHES = [
    "machine learning",
    "data scientist",
    "ai engineer",
    "python developer",
    "full stack",
    "backend engineer",
    "react developer",
    "devops",
]

GRAPHQL_QUERY = """
query JobSearchResults($query: String!, $locationId: Int) {
  talent {
    jobListings(query: $query, locationId: $locationId) {
      jobListings {
        id
        title
        slug
        description
        remote
        locationNames
        compensation
        jobType
        createdAt
        startupRole {
          startup {
            name
            websiteUrl
          }
        }
      }
    }
  }
}
"""


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


def _headers(cookies: str, json_mode: bool = False) -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Cookie"]          = cookies
    h["Accept"]          = "application/json" if json_mode else "text/html,*/*"
    if json_mode:
        h["Content-Type"] = "application/json"
    return h


def _map_listing(node: Dict) -> Optional[Dict]:
    job_id = str(node.get("id") or node.get("slug") or "")
    if not job_id:
        return None
    title = (node.get("title") or "").strip()
    if not title:
        return None

    startup = (node.get("startupRole") or {}).get("startup") or {}
    company = (startup.get("name") or "").strip() or "Unknown"

    remote = node.get("remote", False)
    locs   = node.get("locationNames") or []
    location = ", ".join(locs) if locs else ("Remote" if remote else "India")

    desc     = _strip(node.get("description") or "")[:200]
    comp_str = node.get("compensation") or ""
    sal_min, sal_max, _ = parse_indian_salary(comp_str)
    combined = f"{title} {location} {desc}"

    job_type = "Remote" if remote else (node.get("jobType") or "Full Time")

    return {
        "title":               title,
        "company":             company,
        "location":            location,
        "city":                "Remote" if remote else normalize_city(combined),
        "salary_raw":          comp_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            job_type,
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc,
        "source":              "Wellfound",
        "source_url":          f"wellfound_{job_id}",
        "apply_link":          f"https://wellfound.com/jobs/{job_id}",
        "tags":                extract_tags(title, desc),
        "date_posted":         _parse_date(node.get("createdAt") or ""),
    }


# ── GraphQL path ──────────────────────────────────────────────────────────────

async def _graphql_search(
    client: httpx.AsyncClient, cookies: str, query: str, location_id: Optional[int] = None
) -> List[Dict]:
    payload = {
        "query":     GRAPHQL_QUERY,
        "variables": {"query": query, "locationId": location_id},
    }
    try:
        resp = await client.post(GRAPHQL_URL, json=payload, headers=_headers(cookies, json_mode=True), timeout=20)
        if resp.status_code in (401, 403):
            return []
        resp.raise_for_status()
        data  = resp.json()
        nodes = (
            data.get("data", {})
                .get("talent", {})
                .get("jobListings", {})
                .get("jobListings", [])
        )
        jobs = [_map_listing(n) for n in (nodes or [])]
        return [j for j in jobs if j]
    except Exception as exc:
        print(f"[Wellfound] GraphQL '{query}': {exc}")
        return []


# ── REST fallback ─────────────────────────────────────────────────────────────

async def _rest_search(client: httpx.AsyncClient, cookies: str, query: str) -> List[Dict]:
    try:
        resp = await client.get(
            REST_URL,
            params={"query": query},
            headers=_headers(cookies, json_mode=True),
            timeout=20,
        )
        if resp.status_code not in (200,):
            return []
        items = resp.json()
        if isinstance(items, dict):
            items = items.get("jobListings") or items.get("results") or []
        return [j for j in (_map_listing(n) for n in items) if j]
    except Exception as exc:
        print(f"[Wellfound] REST '{query}': {exc}")
        return []


# ── Public entry point ────────────────────────────────────────────────────────

async def scrape_wellfound() -> List[Dict]:
    """
    Scrape Wellfound via GraphQL (then REST fallback) using session cookies.
    Requires WELLFOUND_COOKIES env var — returns [] if not set.
    """
    cookies = os.getenv("WELLFOUND_COOKIES", "").strip()
    if not cookies:
        print("[Wellfound] WELLFOUND_COOKIES not set — skipping.")
        return []

    seen = set()
    all_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        for query in SEARCHES:
            # Try GraphQL with Bangalore location (1513) then worldwide
            batch: List[Dict] = []
            for loc_id in (1513, None):
                results = await _graphql_search(client, cookies, query, loc_id)
                batch.extend(results)
                await asyncio.sleep(1.0)

            # Fall back to REST if GraphQL returned nothing
            if not batch:
                batch = await _rest_search(client, cookies, query)
                await asyncio.sleep(1.0)

            added = 0
            for job in batch:
                key = job["source_url"]
                if key not in seen:
                    seen.add(key)
                    all_jobs.append(job)
                    added += 1

            print(f"[Wellfound] '{query}': {added} jobs")
            await asyncio.sleep(1.0)

    print(f"[Wellfound] Total unique jobs: {len(all_jobs)}")
    return all_jobs
