"""
remotive_scraper.py — Scraper for Remotive's public JSON API

Geo filter: keep jobs unless the location string explicitly says
"X only" (e.g. "US Only", "UK Only"). Blank/null location = worldwide = keep.
9 categories fetched concurrently at higher limits.
"""

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
)

# ── Endpoints ─────────────────────────────────────────────────────────────────

URLS = [
    "https://remotive.com/api/remote-jobs?category=software-dev&limit=100",
    "https://remotive.com/api/remote-jobs?category=data&limit=100",
    "https://remotive.com/api/remote-jobs?category=devops-sysadmin&limit=100",
    "https://remotive.com/api/remote-jobs?category=product&limit=100",
    "https://remotive.com/api/remote-jobs?category=design&limit=50",
    "https://remotive.com/api/remote-jobs?category=backend&limit=100",
    "https://remotive.com/api/remote-jobs?category=frontend&limit=100",
    "https://remotive.com/api/remote-jobs?category=fullstack&limit=100",
    "https://remotive.com/api/remote-jobs?category=mobile&limit=50",
]

# Skip only when the location string ends with "only" for a non-India region.
# Everything else is kept (blank = worldwide; "USA" without "only" = ambiguous → keep).
_SKIP_ONLY_PATTERNS = [
    r"\bus\s+only\b", r"\busa\s+only\b", r"\bunited\s+states\s+only\b",
    r"\buk\s+only\b",  r"\bunited\s+kingdom\s+only\b",
    r"\beurope\s+only\b", r"\beu\s+only\b",
    r"\bcanada\s+only\b", r"\baustralia\s+only\b",
    r"\bnew\s+zealand\s+only\b", r"\blatin\s+america\s+only\b",
    r"\bbrazil\s+only\b",
]
_SKIP_COMPILED = [re.compile(p, re.I) for p in _SKIP_ONLY_PATTERNS]


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


def _location_ok(loc: str) -> bool:
    """
    Keep the job unless location explicitly says "X only" for a non-India region.

    Rules:
      - Empty / None  → keep  (worldwide)
      - Contains "india", "worldwide", "anywhere", "global", "asia" → keep
      - Matches a _SKIP_ONLY pattern  → skip
      - Anything else (e.g. "USA", "US, Canada")  → keep
        (we don't want to exclude ambiguous multi-region roles)
    """
    if not loc or not loc.strip():
        return True

    loc_lower = loc.lower()

    # Explicit India-friendly keywords → always keep
    for kw in ("india", "worldwide", "anywhere", "global", "asia", "remote"):
        if kw in loc_lower:
            return True

    # Explicit exclude-only patterns → skip
    for pattern in _SKIP_COMPILED:
        if pattern.search(loc_lower):
            return False

    # Default: keep (ambiguous location like "USA", "US, Canada", "Europe")
    return True


def _headers() -> dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "application/json"
    return h


# ── Fetch + parse ─────────────────────────────────────────────────────────────

async def _fetch_category(client: httpx.AsyncClient, url: str) -> List[Dict]:
    try:
        resp = await client.get(url, headers=_headers(), timeout=25)
        resp.raise_for_status()
        jobs_raw = resp.json().get("jobs", [])

        kept = []
        for j in jobs_raw:
            loc = (j.get("candidate_required_location") or "").strip()
            if not _location_ok(loc):
                continue

            title   = (j.get("job_title") or "").strip()
            company = (j.get("company_name") or "").strip()
            if not title:
                continue

            desc_raw = _strip(j.get("description") or "")
            url_val  = (j.get("url") or "").strip()
            api_tags = j.get("tags") or []
            combined = f"{title} {loc} {desc_raw}"

            kept.append({
                "title":               title,
                "company":             company,
                "location":            loc or "Remote",
                "city":                "Remote",
                "salary_raw":          "",
                "salary_min":          None,
                "salary_max":          None,
                "job_type":            "Remote",
                "experience_level":    normalize_experience(combined),
                "description_snippet": desc_raw[:200],
                "source":              "Remotive",
                "source_url":          url_val,
                "apply_link":          url_val,
                "tags":                list(dict.fromkeys(
                    [t for t in api_tags[:4] if isinstance(t, str)] +
                    extract_tags(title, desc_raw)
                ))[:8],
                "date_posted":         _parse_date(j.get("publication_date") or ""),
            })

        cat = url.split("category=")[1].split("&")[0]
        print(f"[Remotive] {cat}: {len(kept)} kept (of {len(jobs_raw)} total)")
        return kept

    except Exception as exc:
        cat = url.split("category=")[1].split("&")[0] if "category=" in url else url
        print(f"[Remotive] {cat}: {exc}")
        return []


# ── Public entry point ────────────────────────────────────────────────────────

async def scrape_remotive() -> List[Dict]:
    """
    Fetch 9 Remotive categories concurrently.
    Returns job dicts ready for database.save_job().
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        results = await asyncio.gather(
            *[_fetch_category(client, url) for url in URLS],
            return_exceptions=True,
        )

    seen = set()
    unique: List[Dict] = []
    for batch in results:
        if isinstance(batch, Exception):
            print(f"[Remotive] batch error: {batch}")
            continue
        for j in batch:
            if j["source_url"] and j["source_url"] not in seen:
                seen.add(j["source_url"])
                unique.append(j)

    print(f"[Remotive] Total unique jobs: {len(unique)}")
    return unique
