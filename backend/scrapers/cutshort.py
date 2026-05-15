"""
cutshort.py — Scraper for cutshort.io

Cutshort is a startup-focused hiring platform popular in India.

Strategy:
  1. Try their undocumented JSON search API (GET /api/public/jobs)
  2. Fall back to BeautifulSoup on /jobs listing page
  3. Try __NEXT_DATA__ extraction from the HTML

Cutshort may return a Cloudflare challenge for repeated requests.
Set CUTSHORT_COOKIES env var with a valid browser Cookie header to bypass.
"""

import html
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
    polite_delay,
)

BASE_URL    = "https://cutshort.io"
JOBS_URL    = f"{BASE_URL}/jobs"
# Cutshort paginates their public job feed with these params
API_PAGES   = [
    {"page": 1, "limit": 30},
    {"page": 2, "limit": 30},
    {"page": 3, "limit": 30},
]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _build_headers(json_mode: bool = False) -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    if json_mode:
        h["Accept"] = "application/json, text/javascript, */*"
        h["X-Requested-With"] = "XMLHttpRequest"
    else:
        h["Accept"] = "text/html,application/xhtml+xml,*/*"
    cookies_str = os.getenv("CUTSHORT_COOKIES", "").strip()
    if cookies_str:
        h["Cookie"] = cookies_str
    return h


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


def _infer_job_type(title: str, desc: str) -> str:
    t = f"{title} {desc}".lower()
    if "intern"   in t: return "Internship"
    if "contract" in t or "freelance" in t: return "Contract"
    if "remote"   in t or "work from home" in t or "wfh" in t: return "Remote"
    return "Full Time"


def _enrich(raw: Dict) -> Dict:
    title    = raw.get("title", "")
    location = raw.get("location", "")
    desc     = raw.get("description", "")
    combined = f"{title} {location} {desc}"

    m = re.search(
        r"(?:Rs\.?|INR|₹|\$)?\s*[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?"
        r"(?:\s*(?:LPA|lakh[s]?|per\s*(?:month|year)|/\s*(?:mo|yr)))?",
        combined, re.I,
    )
    salary_raw_str      = m.group(0).strip() if m else ""
    sal_min, sal_max, _ = parse_indian_salary(salary_raw_str or combined)

    return {
        "title":               title,
        "company":             raw.get("company", ""),
        "location":            location,
        "city":                normalize_city(combined),
        "salary_raw":          salary_raw_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            _infer_job_type(title, desc),
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc[:200],
        "source":              "Cutshort",
        "source_url":          raw.get("source_url", ""),
        "apply_link":          raw.get("apply_link", ""),
        "tags":                extract_tags(title, desc),
        "date_posted":         raw.get("date_posted", _today()),
    }


# ─────────────────────────────────────────────
# Path 1 — JSON API
# ─────────────────────────────────────────────

def _parse_api_job(item: Dict) -> Optional[Dict]:
    title   = (item.get("title") or item.get("designation") or "").strip()
    company_obj = item.get("company") or {}
    company = (
        company_obj.get("name") if isinstance(company_obj, dict)
        else item.get("company_name") or ""
    ).strip()
    if not title:
        return None

    job_id = item.get("id") or item.get("slug") or ""
    apply_link = f"{BASE_URL}/job/{job_id}" if job_id else BASE_URL

    location = ""
    loc_raw = item.get("location") or item.get("locations") or item.get("city") or ""
    if isinstance(loc_raw, list):
        location = ", ".join(str(x) for x in loc_raw)
    elif isinstance(loc_raw, str):
        location = loc_raw

    salary_raw = ""
    sal = item.get("salary") or item.get("ctc") or {}
    if isinstance(sal, dict):
        mn = sal.get("min") or sal.get("minimum") or 0
        mx = sal.get("max") or sal.get("maximum") or 0
        if mn:
            salary_raw = f"{int(mn/100_000)}-{int(mx/100_000)} LPA" if mx else f"{int(mn/100_000)} LPA"
    elif isinstance(sal, str):
        salary_raw = sal

    desc = str(item.get("description") or item.get("about") or "")[:400]

    return {
        "title":       title,
        "company":     company or "Unknown",
        "location":    location,
        "description": desc,
        "salary_raw":  salary_raw,
        "source_url":  apply_link,
        "apply_link":  apply_link,
        "date_posted": _parse_date(item.get("createdAt") or item.get("posted_at") or ""),
    }


async def _try_api(client: httpx.AsyncClient) -> List[Dict]:
    """Try Cutshort's internal JSON API endpoints."""
    raw: List[Dict] = []
    endpoints = [
        (f"{BASE_URL}/api/public/jobs", {"page": 1, "limit": 30, "country": "India"}),
        (f"{BASE_URL}/api/v1/jobs",     {"page": 1, "limit": 30}),
        (f"{BASE_URL}/api/jobs",        {"page": 1, "count": 30}),
    ]
    for url, params in endpoints:
        try:
            resp = await client.get(url, params=params, headers=_build_headers(json_mode=True))
            if resp.status_code in (401, 403, 404):
                continue
            if resp.status_code != 200:
                continue
            data    = resp.json()
            results = (
                data.get("data") or data.get("jobs") or data.get("results")
                or (data if isinstance(data, list) else [])
            )
            for item in results:
                parsed = _parse_api_job(item)
                if parsed:
                    raw.append(parsed)
            if raw:
                print(f"[Cutshort] API {url}: {len(raw)} jobs")
                return raw
        except Exception:
            continue
    return raw


# ─────────────────────────────────────────────
# Path 2 — HTML / __NEXT_DATA__
# ─────────────────────────────────────────────

def _parse_job_card(card) -> Optional[Dict]:
    try:
        title_el   = card.select_one("h2, h3, h4, [class*='title'], [class*='job-name']")
        company_el = card.select_one("[class*='company'], [class*='employer']")
        loc_el     = card.select_one("[class*='location'], [class*='city']")
        link_el    = card.select_one("a[href]")
        desc_el    = card.select_one("[class*='desc'], p")

        title = _strip(str(title_el)) if title_el else ""
        if not title:
            return None
        company  = _strip(str(company_el)) if company_el else ""
        location = _strip(str(loc_el))    if loc_el    else ""
        desc     = _strip(str(desc_el))   if desc_el   else ""

        href = link_el.get("href", "") if link_el else ""
        apply_link = href if href.startswith("http") else f"{BASE_URL}{href}"

        return {
            "title": title, "company": company, "location": location,
            "description": desc, "source_url": apply_link,
            "apply_link": apply_link, "date_posted": _today(),
        }
    except Exception:
        return None


def _parse_next_data(html_text: str) -> List[Dict]:
    soup   = BeautifulSoup(html_text, "html.parser")
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script or not script.string:
        return []
    try:
        data = json.loads(script.string)
    except Exception:
        return []

    # Search for arrays of job-like objects
    jobs: List[Dict] = []

    def _walk(obj, depth=0):
        if depth > 10 or len(jobs) > 200:
            return
        if isinstance(obj, list) and obj:
            for item in obj:
                title = item.get("title") or item.get("designation") if isinstance(item, dict) else None
                if title and isinstance(title, str) and 3 < len(title) < 100:
                    parsed = _parse_api_job(item)
                    if parsed:
                        jobs.append(parsed)
                else:
                    _walk(item, depth + 1)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v, depth + 1)

    _walk(data)
    return jobs


async def _try_html(client: httpx.AsyncClient) -> List[Dict]:
    """Scrape /jobs page via BeautifulSoup."""
    try:
        resp = await client.get(JOBS_URL, headers=_build_headers())
    except Exception as exc:
        print(f"[Cutshort] HTML error: {exc}")
        return []

    if resp.status_code in (401, 403):
        print(f"[Cutshort] Blocked ({resp.status_code}). Set CUTSHORT_COOKIES to bypass.")
        return []
    if resp.status_code != 200:
        return []

    # Try __NEXT_DATA__ first
    jobs = _parse_next_data(resp.text)
    if jobs:
        print(f"[Cutshort] __NEXT_DATA__: {len(jobs)} jobs")
        return jobs

    # BeautifulSoup fallback
    soup  = BeautifulSoup(resp.text, "html.parser")
    cards = (
        soup.select("[data-testid='job-card']")
        or soup.select("[class*='jobCard']")
        or soup.select("[class*='job-card']")
        or soup.select("article")
    )
    raw = [_parse_job_card(c) for c in cards]
    raw = [r for r in raw if r]
    print(f"[Cutshort] HTML selectors: {len(raw)} jobs")
    return raw


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def scrape_cutshort() -> List[Dict]:
    """
    Scrape Cutshort.io via JSON API (primary) or BeautifulSoup (fallback).
    Returns job dicts ready for database.save_job().

    Set CUTSHORT_COOKIES env var to bypass Cloudflare if needed.
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        raw = await _try_api(client)
        if not raw:
            await polite_delay(1.0, 2.0)
            raw = await _try_html(client)

    jobs = [_enrich(r) for r in raw]
    seen = set()
    unique: List[Dict] = []
    for j in jobs:
        if j["source_url"] and j["source_url"] not in seen:
            seen.add(j["source_url"])
            unique.append(j)

    print(f"[Cutshort] Total unique jobs: {len(unique)}")
    return unique
