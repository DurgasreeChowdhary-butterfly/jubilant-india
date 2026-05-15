"""
instahyre.py — Scraper for instahyre.com

Architecture:
  1. Try the semi-public REST API  (GET /api/v1/opportunity/?format=json)
  2. If blocked (403/401), fall back to BeautifulSoup on /jobs-in-india/
  3. If both fail (Cloudflare challenge), return [] with a clear log message.

Cloudflare note:
  Instahyre is behind Cloudflare bot protection.  To authenticate, set the
  environment variable INSTAHYRE_COOKIES to the raw Cookie header string
  copied from a logged-in browser session, e.g.:

      INSTAHYRE_COOKIES="csrftoken=abc; sessionid=xyz; ..."

  When the env var is present the scraper injects it into every request and
  Cloudflare allows the request through.
"""

import html
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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

BASE_URL    = "https://www.instahyre.com"
API_URL     = f"{BASE_URL}/api/v1/opportunity/"
LISTING_URL = f"{BASE_URL}/jobs-in-india/"

PAGE_OFFSETS  = [0, 50, 100, 150]   # 4 pages × 50 = 200 jobs max
PAGE_SIZE     = 50


# ─────────────────────────────────────────────
# Headers
# ─────────────────────────────────────────────

def _build_headers(extra: Optional[Dict] = None) -> Dict:
    h = get_random_headers()
    h.update({
        "X-Requested-With": "XMLHttpRequest",
        "Referer":          LISTING_URL,
        "Accept":           "application/json, text/javascript, */*",
        "Accept-Encoding":  "gzip, deflate",
    })
    # Inject session cookies if provided (bypasses Cloudflare)
    cookies_str = os.getenv("INSTAHYRE_COOKIES", "").strip()
    if cookies_str:
        h["Cookie"] = cookies_str
    if extra:
        h.update(extra)
    return h


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: str) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        return value[:10]
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _infer_job_type(title: str, desc: str) -> str:
    t = f"{title} {desc}".lower()
    if "intern" in t:
        return "Internship"
    if "contract" in t or "freelance" in t or "consultant" in t:
        return "Contract"
    if "remote" in t or "work from home" in t:
        return "Remote"
    return "Full Time"


def _enrich(raw: Dict) -> Dict:
    """Apply all utils normalizers to a raw job dict and return enriched job."""
    title    = raw.get("title", "")
    company  = raw.get("company", "")
    location = raw.get("location", "")
    desc     = raw.get("description", "")

    combined            = f"{title} {location} {desc}"
    sal_raw             = re.search(
        r"(?:Rs\.?|INR|₹|\$|USD)?\s*[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?"
        r"(?:\s*(?:LPA|lakh[s]?|per\s*(?:month|year)|/\s*(?:mo|yr)))?",
        desc, re.I,
    )
    salary_raw_str      = sal_raw.group(0).strip() if sal_raw else ""
    sal_min, sal_max, _ = parse_indian_salary(salary_raw_str or desc)
    city                = normalize_city(f"{location} {combined}")
    experience_level    = normalize_experience(f"{title} {desc}")
    job_type            = _infer_job_type(title, desc)
    tags                = extract_tags(title, desc)

    return {
        "title":               title,
        "company":             company,
        "location":            location,
        "city":                city,
        "salary_raw":          salary_raw_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            job_type,
        "experience_level":    experience_level,
        "description_snippet": desc[:200],
        "source":              "Instahyre",
        "source_url":          raw.get("source_url", ""),
        "apply_link":          raw.get("apply_link", ""),
        "tags":                tags,
        "date_posted":         raw.get("date_posted", ""),
    }


# ─────────────────────────────────────────────
# Path 1 — REST API
# ─────────────────────────────────────────────

def _parse_api_item(item: Dict) -> Optional[Dict]:
    """
    Map one API result dict to a normalised raw job dict.

    Instahyre's API uses nested objects; we handle both v1 and v2 shapes:
      v1: {id, role:{title}, employer:{name}, location, description, created}
      v2: {id, designation, company_name, city, description, updated}
    """
    job_id = item.get("id")
    if not job_id:
        return None

    # Title
    role = item.get("role") or {}
    title = (
        role.get("title")
        or item.get("designation")
        or item.get("title")
        or ""
    ).strip()

    # Company
    employer = item.get("employer") or {}
    company = (
        employer.get("name")
        or item.get("company_name")
        or item.get("company")
        or ""
    ).strip()

    if not title or not company:
        return None

    location = (
        item.get("location")
        or item.get("city")
        or ""
    ).strip()

    desc = _strip_html(
        item.get("description")
        or item.get("job_description")
        or ""
    )

    date_posted = _parse_date(
        item.get("created") or item.get("updated") or item.get("date_posted") or ""
    )

    apply_link = f"{BASE_URL}/job-{job_id}/"

    return {
        "title":       title,
        "company":     company,
        "location":    location,
        "description": desc,
        "source_url":  apply_link,
        "apply_link":  apply_link,
        "date_posted": date_posted,
    }


async def _try_api(client: httpx.AsyncClient) -> Tuple[List[Dict], bool]:
    """
    Attempt to paginate the JSON API.
    Returns (raw_jobs, success).  success=False on 403/401/404.
    """
    raw_jobs: List[Dict] = []
    headers  = _build_headers()

    for i, offset in enumerate(PAGE_OFFSETS):
        try:
            resp = await client.get(
                API_URL,
                params={"format": "json", "limit": PAGE_SIZE, "offset": offset},
                headers=headers,
            )
        except Exception as exc:
            print(f"[Instahyre] API network error at offset {offset}: {exc}")
            break

        if resp.status_code in (401, 403):
            print(f"[Instahyre] API blocked ({resp.status_code}) — Cloudflare active. "
                  f"Set INSTAHYRE_COOKIES env var with a valid browser session cookie.")
            return [], False

        if resp.status_code == 404:
            print("[Instahyre] API endpoint not found (may have been deprecated).")
            return [], False

        if resp.status_code != 200:
            print(f"[Instahyre] API returned HTTP {resp.status_code} at offset {offset}")
            break

        try:
            data    = resp.json()
            results = data.get("results") or data.get("data") or (data if isinstance(data, list) else [])
        except Exception:
            print(f"[Instahyre] JSON parse error at offset {offset}")
            break

        page_jobs = [_parse_api_item(item) for item in results]
        page_jobs = [j for j in page_jobs if j]
        raw_jobs.extend(page_jobs)
        print(f"[Instahyre] API offset={offset} -> {len(page_jobs)} jobs")

        # Stop early when the page is under the limit (last page)
        if len(results) < PAGE_SIZE:
            break

        if i < len(PAGE_OFFSETS) - 1:
            await polite_delay(1.0, 2.0)

    return raw_jobs, True


# ─────────────────────────────────────────────
# Path 2 — BeautifulSoup fallback
# ─────────────────────────────────────────────

def _parse_html_card(card) -> Optional[Dict]:
    """Extract fields from one BeautifulSoup job card element."""
    try:
        # Instahyre uses various class names depending on deploy version;
        # try a priority list of selectors for each field.
        title_el = (
            card.select_one(".opportunity-title, .job-title, h3.title, h2.title, h3, h2")
        )
        company_el = (
            card.select_one(".company-name, .employer-name, .company, [class*='company']")
        )
        loc_el = (
            card.select_one(".location, .job-location, [class*='location']")
        )
        link_el = card.select_one("a[href]")
        desc_el = (
            card.select_one(".description, .job-description, [class*='desc'], p")
        )

        title   = _strip_html(str(title_el))   if title_el   else ""
        company = _strip_html(str(company_el)) if company_el else ""
        if not title or not company:
            return None

        location = _strip_html(str(loc_el)) if loc_el else ""
        desc     = _strip_html(str(desc_el)) if desc_el else ""

        href = (link_el["href"] if link_el else "") or ""
        apply_link = href if href.startswith("http") else f"{BASE_URL}{href}"

        return {
            "title":       title,
            "company":     company,
            "location":    location,
            "description": desc,
            "source_url":  apply_link,
            "apply_link":  apply_link,
            "date_posted": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
    except Exception:
        return None


async def _try_html(client: httpx.AsyncClient) -> List[Dict]:
    """
    Fallback: scrape /jobs-in-india/ with BeautifulSoup.
    Returns [] when Cloudflare blocks the request.
    """
    headers = _build_headers({"Accept": "text/html,application/xhtml+xml,*/*"})
    headers.pop("X-Requested-With", None)  # not needed for HTML pages

    try:
        resp = await client.get(LISTING_URL, headers=headers)
    except Exception as exc:
        print(f"[Instahyre] HTML fallback network error: {exc}")
        return []

    if resp.status_code in (401, 403):
        print(f"[Instahyre] HTML fallback also blocked ({resp.status_code}). "
              "Instahyre requires a valid session — set INSTAHYRE_COOKIES.")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Try selectors in priority order
    cards = (
        soup.select(".opportunity-card")
        or soup.select(".job-card")
        or soup.select("[class*='opportunity']")
        or soup.select("[class*='job-listing']")
        or soup.select("article")
    )

    if not cards:
        print("[Instahyre] HTML fallback: no job cards found "
              "(page may be JS-rendered or Cloudflare-challenged).")
        return []

    raw_jobs = [_parse_html_card(c) for c in cards]
    raw_jobs = [j for j in raw_jobs if j]
    print(f"[Instahyre] HTML fallback: {len(raw_jobs)} jobs from {LISTING_URL}")
    return raw_jobs


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def scrape_instahyre() -> List[Dict]:
    """
    Scrape Instahyre via REST API (primary) or BeautifulSoup (fallback).
    Returns job dicts ready for database.save_job().

    Set INSTAHYRE_COOKIES env var to a valid browser Cookie header string
    to bypass Cloudflare protection.
    """
    raw_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        raw_jobs, api_ok = await _try_api(client)

        if not api_ok and not raw_jobs:
            print("[Instahyre] Falling back to HTML scraper…")
            raw_jobs = await _try_html(client)

    jobs = [_enrich(r) for r in raw_jobs]
    # Deduplicate by source_url
    seen:   set[str]   = set()
    unique: List[Dict] = []
    for j in jobs:
        if j["source_url"] and j["source_url"] not in seen:
            seen.add(j["source_url"])
            unique.append(j)

    print(f"[Instahyre] Total unique jobs: {len(unique)}")
    return unique
