"""
wellfound.py — Scraper for wellfound.com (formerly AngelList Talent)

Strategy:
  1. Fetch /company/{slug}/jobs for each Indian startup
  2. Extract jobs from __NEXT_DATA__ JSON (Next.js SSR)
  3. Fall back to BeautifulSoup selectors if JSON yields nothing
  4. Cloudflare may block — set WELLFOUND_COOKIES env var to bypass

Set WELLFOUND_COOKIES to the raw Cookie header string from a logged-in
browser session to bypass Cloudflare protection.
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

BASE_URL = "https://wellfound.com"

# Top Indian startups with Wellfound profiles.
# Slugs are best-effort; 404s are skipped gracefully.
COMPANY_SLUGS = [
    "meesho", "razorpay", "groww", "zepto", "cred-3",
    "coinswitch-kuber", "slice-2", "jupiter-money", "fi-money", "smallcase",
    "urban-company", "unacademy", "physics-wallah", "scaler-3",
    "dunzo", "rapido", "mfine", "pristyn-care", "licious",
    "freshworks", "chargebee", "postman", "browserstack", "darwinbox",
    "leadsquared", "innovaccer", "cleartax-india", "hasura", "setu",
]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _build_headers() -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "text/html,application/xhtml+xml,*/*"
    cookies_str = os.getenv("WELLFOUND_COOKIES", "").strip()
    if cookies_str:
        h["Cookie"] = cookies_str
    return h


def _strip(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _walk_for_jobs(obj, company_name: str, found: List[Dict], depth: int = 0) -> None:
    """Recursively walk __NEXT_DATA__ looking for job-like objects."""
    if depth > 12:
        return
    if isinstance(obj, list):
        for item in obj:
            _walk_for_jobs(item, company_name, found, depth + 1)
    elif isinstance(obj, dict):
        title = obj.get("title") or obj.get("role") or obj.get("jobTitle") or ""
        if isinstance(title, str) and 3 < len(title) < 120:
            loc_raw = obj.get("locationNames") or obj.get("location") or ""
            if obj.get("remote") or obj.get("remote_ok"):
                loc_raw = loc_raw or "Remote"
            if isinstance(loc_raw, list):
                loc_raw = ", ".join(str(x) for x in loc_raw)
            elif not isinstance(loc_raw, str):
                loc_raw = ""

            job_id   = obj.get("id") or obj.get("slug") or ""
            slug_val = obj.get("slug") or str(job_id)
            apply_link = f"{BASE_URL}/jobs/{slug_val}" if slug_val else BASE_URL

            found.append({
                "title":       title,
                "company":     company_name,
                "location":    loc_raw,
                "description": str(obj.get("description") or "")[:400],
                "source_url":  apply_link,
                "apply_link":  apply_link,
                "date_posted": _today(),
            })
        else:
            for v in obj.values():
                _walk_for_jobs(v, company_name, found, depth + 1)


def _parse_page(html_text: str, company_name: str) -> List[Dict]:
    """
    Two-pass parse: __NEXT_DATA__ JSON first, BeautifulSoup selectors second.
    """
    soup = BeautifulSoup(html_text, "html.parser")

    # Pass 1 — __NEXT_DATA__
    script = soup.find("script", {"id": "__NEXT_DATA__"})
    if script and script.string:
        try:
            data = json.loads(script.string)
            jobs: List[Dict] = []
            _walk_for_jobs(data, company_name, jobs)
            if jobs:
                return jobs
        except Exception:
            pass

    # Pass 2 — CSS selectors (class names change per deploy, try multiple)
    jobs = []
    selector_chains = [
        "li[data-test='startup-job']",
        "[data-testid='job-listing']",
        "div[class*='JobListing']",
        "div[class*='job-listing']",
        "li[class*='job']",
    ]
    for sel in selector_chains:
        rows = soup.select(sel)
        if not rows:
            continue
        for row in rows:
            a       = row.select_one("a[href]")
            t_el    = row.select_one("h3, h4, [class*='title']")
            loc_el  = row.select_one("[class*='location'], [class*='city']")
            title   = _strip(str(t_el)) if t_el else (_strip(a.get_text()) if a else "")
            if not title:
                continue
            href = a.get("href", "") if a else ""
            apply_link = href if href.startswith("http") else f"{BASE_URL}{href}"
            jobs.append({
                "title":       title,
                "company":     company_name,
                "location":    _strip(str(loc_el)) if loc_el else "",
                "description": "",
                "source_url":  apply_link,
                "apply_link":  apply_link,
                "date_posted": _today(),
            })
        if jobs:
            break

    return jobs


def _infer_job_type(title: str, desc: str) -> str:
    t = f"{title} {desc}".lower()
    if "intern"   in t: return "Internship"
    if "contract" in t or "freelance" in t: return "Contract"
    if "remote"   in t or "work from home" in t: return "Remote"
    return "Full Time"


def _enrich(raw: Dict) -> Dict:
    title    = raw.get("title", "")
    location = raw.get("location", "")
    desc     = raw.get("description", "")
    combined = f"{title} {location} {desc}"

    m = re.search(
        r"(?:Rs\.?|INR|₹|\$)?\s*[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?"
        r"(?:\s*(?:LPA|lakh[s]?|per\s*(?:month|year)|/\s*(?:mo|yr)))?",
        desc, re.I,
    )
    salary_raw_str      = m.group(0).strip() if m else ""
    sal_min, sal_max, _ = parse_indian_salary(salary_raw_str or desc)

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
        "source":              "Wellfound",
        "source_url":          raw.get("source_url", ""),
        "apply_link":          raw.get("apply_link", ""),
        "tags":                extract_tags(title, desc),
        "date_posted":         raw.get("date_posted", _today()),
    }


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def scrape_wellfound() -> List[Dict]:
    """
    Scrape Wellfound company job pages for major Indian startups.
    Returns job dicts ready for database.save_job().

    Set WELLFOUND_COOKIES env var to bypass Cloudflare protection.
    """
    all_raw: List[Dict] = []
    cf_blocked = False

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for i, slug in enumerate(COMPANY_SLUGS):
            if cf_blocked:
                break
            try:
                resp = await client.get(
                    f"{BASE_URL}/company/{slug}/jobs",
                    headers=_build_headers(),
                )
                if resp.status_code == 404:
                    continue
                if resp.status_code in (401, 403):
                    print(f"[Wellfound] Cloudflare blocked ({resp.status_code}). "
                          "Set WELLFOUND_COOKIES to bypass.")
                    cf_blocked = True
                    continue
                if resp.status_code != 200:
                    continue

                company_name = slug.replace("-", " ").title()
                raw = _parse_page(resp.text, company_name)
                if raw:
                    print(f"[Wellfound] {slug}: {len(raw)} jobs")
                    all_raw.extend(raw)

            except Exception as exc:
                print(f"[Wellfound] {slug}: {exc}")

            if i < len(COMPANY_SLUGS) - 1:
                await polite_delay(1.5, 3.0)

    jobs = [_enrich(r) for r in all_raw]
    seen: set[str] = set()
    unique: List[Dict] = []
    for j in jobs:
        if j["source_url"] and j["source_url"] not in seen:
            seen.add(j["source_url"])
            unique.append(j)

    print(f"[Wellfound] Total unique jobs: {len(unique)}")
    return unique
