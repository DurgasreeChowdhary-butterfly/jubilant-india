"""
hasjob.py — Scraper for hasjob.co

Runs all 15 query variants concurrently via asyncio.gather.
Primary path:  undocumented JSON API  (?format=json&q=...)
Fallback path: RSS XML  (?rss=1&q=...)  — kept for resilience even though
               hasjob's RSS has historically returned HTML instead of XML.
Per-job detail fetches are skipped (too slow at 80+ scale); descriptions
come from the listing API instead.
"""

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List
from urllib.parse import urlencode, urlparse, parse_qs

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

BASE_URL = "https://hasjob.co"

# 15 query variants the user requested (mirrors the RSS feed list)
_QUERIES = [
    "",           # all jobs (no keyword filter)
    "developer",
    "engineer",
    "python",
    "javascript",
    "react",
    "data",
    "devops",
    "remote",
    "fullstack",
    "backend",
    "frontend",
    "mobile",
    "android",
    "ios",
]


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

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


def _json_headers() -> dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "application/json, text/javascript, */*"
    return h


def _html_headers() -> dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "text/html,application/xhtml+xml,*/*"
    return h


# ─────────────────────────────────────────────
# Path A — JSON API  (?format=json)
# ─────────────────────────────────────────────

async def _fetch_json(client: httpx.AsyncClient, q: str) -> List[Dict]:
    """Fetch one JSON listing page from hasjob's internal API."""
    params: dict = {"format": "json"}
    if q:
        params["q"] = q
    try:
        resp = await client.get(BASE_URL + "/", params=params, headers=_json_headers(), timeout=15)
        resp.raise_for_status()
        data  = resp.json()
        posts = []
        for group in data.get("grouped", []):
            for post in group.get("posts", []):
                url = post.get("url", "")
                if not url:
                    continue
                posts.append({
                    "title":   (post.get("headline") or "").strip(),
                    "company": (post.get("company_name") or "").strip(),
                    "location":(post.get("location") or "").strip(),
                    "date":    _parse_date(post.get("date", "")),
                    "desc":    _strip(post.get("description") or ""),
                    "url":     url,
                })
        if posts:
            print(f"[Hasjob] JSON q={q!r}: {len(posts)} posts")
        return posts
    except Exception as exc:
        print(f"[Hasjob] JSON q={q!r} error: {exc}")
        return []


# ─────────────────────────────────────────────
# Path B — RSS XML  (?rss=1)
# ─────────────────────────────────────────────

def _parse_rss_item(item: ET.Element) -> Dict | None:
    """Parse one <item> from hasjob RSS into a raw dict."""
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    title_el = item.find("title")
    link_el  = item.find("link")
    desc_el  = item.find("description")
    date_el  = item.find("pubDate")

    title_raw = (title_el.text or "") if title_el is not None else ""
    link      = (link_el.text or "").strip() if link_el is not None else ""
    if not link:
        return None

    # Hasjob RSS title format: "Job Title at Company Name"
    if " at " in title_raw:
        parts    = title_raw.rsplit(" at ", 1)
        title    = parts[0].strip()
        company  = parts[1].strip()
    else:
        title   = title_raw.strip()
        company = ""

    desc = _strip(desc_el.text or "") if desc_el is not None else ""
    # RSS link is full URL; convert to relative path for dedup key
    path = urlparse(link).path

    return {
        "title":   title,
        "company": company,
        "location":"",
        "date":    _today(),
        "desc":    desc[:200],
        "url":     path,
    }


async def _fetch_rss(client: httpx.AsyncClient, q: str) -> List[Dict]:
    """Try fetching hasjob RSS (may return HTML — handled gracefully)."""
    params: dict = {"rss": "1"}
    if q:
        params["q"] = q
    try:
        resp = await client.get(BASE_URL + "/", params=params, headers=_html_headers(), timeout=15)
        if resp.status_code != 200:
            return []
        root  = ET.fromstring(resp.content)   # bytes avoids encoding issues
        items = root.findall("./channel/item")
        posts = [_parse_rss_item(it) for it in items]
        posts = [p for p in posts if p]
        if posts:
            print(f"[Hasjob] RSS  q={q!r}: {len(posts)} posts")
        return posts
    except ET.ParseError:
        return []   # HTML response (not XML) — silently skip
    except Exception as exc:
        print(f"[Hasjob] RSS  q={q!r} error: {exc}")
        return []


# ─────────────────────────────────────────────
# Enrichment
# ─────────────────────────────────────────────

def _enrich(raw: Dict) -> Dict:
    title    = raw["title"]
    location = raw["location"]
    desc     = raw["desc"]
    combined = f"{title} {location} {desc}"

    m = re.search(
        r"(?:Rs\.?|INR|₹|\$)?\s*[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?"
        r"(?:\s*(?:LPA|lakh[s]?|per\s*(?:month|year)|/\s*(?:mo|yr)))?",
        desc, re.I,
    )
    salary_raw_str      = m.group(0).strip() if m else ""
    sal_min, sal_max, _ = parse_indian_salary(salary_raw_str or desc)

    apply_link = raw["url"] if raw["url"].startswith("http") else BASE_URL + raw["url"]

    return {
        "title":               title,
        "company":             raw["company"],
        "location":            location,
        "city":                normalize_city(combined),
        "salary_raw":          salary_raw_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            ("Internship" if "intern" in combined.lower()
                                else "Remote" if "remote" in combined.lower()
                                else "Full Time"),
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc[:200],
        "source":              "Hasjob",
        "source_url":          apply_link,
        "apply_link":          apply_link,
        "tags":                extract_tags(title, desc),
        "date_posted":         raw["date"],
    }


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def scrape_hasjob() -> List[Dict]:
    """
    Scrape Hasjob.co — all 15 query variants via JSON API + RSS, concurrently.
    Returns job dicts ready for database.save_job().
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        tasks = (
            [_fetch_json(client, q) for q in _QUERIES] +
            [_fetch_rss(client,  q) for q in _QUERIES]
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and deduplicate by relative URL path
    seen = set()
    raw_posts: List[Dict] = []
    for batch in results:
        if isinstance(batch, Exception):
            continue
        for post in batch:
            key = post["url"]
            if key and key not in seen:
                seen.add(key)
                raw_posts.append(post)

    jobs = [_enrich(r) for r in raw_posts]
    print(f"[Hasjob] Total unique jobs: {len(jobs)}")
    return jobs
