"""
freejobaler.py — Scraper for freejobalert.com

FreeJobAlert.com aggregates government, PSU, and bank job notifications
for India. Pages are server-rendered HTML — no JS execution needed.

Scraped pages:
  - /latest-jobs/          General latest government jobs
  - /bank-jobs/            Banking sector
  - /railway-jobs/         Railway recruitment
  - /teaching-jobs/        Teaching / academic posts
"""

import html
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
    polite_delay,
)

BASE_URL = "https://www.freejobalert.com"

LISTING_PAGES = [
    (f"{BASE_URL}/bank-jobs/",          "Banking"),
    (f"{BASE_URL}/railway-jobs/",       "Railways"),
    (f"{BASE_URL}/sarkari-result/",     "Government"),
    (f"{BASE_URL}/defence-jobs/",       "Defence"),
    (f"{BASE_URL}/engineering-jobs/",   "Engineering"),
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


def _parse_last_date(text: str) -> str:
    """Try to parse a 'Last Date: DD-MM-YYYY' string into YYYY-MM-DD."""
    m = re.search(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", text or "")
    if m:
        d, mo, yr = m.group(1), m.group(2), m.group(3)
        return f"{yr}-{mo}-{d}"
    return _today()


def _headers() -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "text/html,application/xhtml+xml,*/*"
    return h


# ─────────────────────────────────────────────
# Parsers
# ─────────────────────────────────────────────

def _parse_listing_page(html_text: str, default_sector: str) -> List[Dict]:
    """
    Parse a FreeJobAlert listing page.

    The site uses WordPress and renders job notifications as:
      - Tables inside .entry-content  (structured with post name, org, date)
      - h2/h3 headings with <a> links to individual job pages
      - <p> tags with brief descriptions
    """
    soup = BeautifulSoup(html_text, "html.parser")
    jobs: List[Dict] = []

    # Strategy A: table rows (most structured data)
    for table in soup.select("table"):
        headers_row = table.select("th")
        col_names = [_strip(str(th)).lower() for th in headers_row]

        for row in table.select("tr"):
            cells = row.select("td")
            if len(cells) < 2:
                continue

            # Map cells to known columns if headers present
            if col_names:
                cell_map: Dict[str, str] = {}
                for idx, name in enumerate(col_names):
                    if idx < len(cells):
                        cell_map[name] = _strip(str(cells[idx]))

                post_name = (
                    cell_map.get("post name") or cell_map.get("post") or
                    cell_map.get("job title") or cell_map.get("vacancy") or
                    (_strip(str(cells[0])) if cells else "")
                )
                org = (
                    cell_map.get("organization") or cell_map.get("org") or
                    cell_map.get("department") or cell_map.get("employer") or
                    (_strip(str(cells[1])) if len(cells) > 1 else "")
                )
                last_date_str = (
                    cell_map.get("last date") or cell_map.get("closing date") or
                    cell_map.get("last date to apply") or ""
                )
            else:
                post_name    = _strip(str(cells[0]))
                org          = _strip(str(cells[1])) if len(cells) > 1 else ""
                last_date_str = _strip(str(cells[-1])) if cells else ""

            if not post_name or len(post_name) < 4:
                continue

            # Extract apply link if present
            a = row.select_one("a[href]")
            href = a.get("href", "") if a else ""
            apply_link = href if href.startswith("http") else f"{BASE_URL}{href}" if href else BASE_URL

            jobs.append({
                "title":       post_name,
                "company":     org or default_sector,
                "location":    "India",
                "description": f"{default_sector} recruitment. Last date: {last_date_str}",
                "source_url":  apply_link,
                "apply_link":  apply_link,
                "date_posted": _parse_last_date(last_date_str),
            })

    if jobs:
        return jobs

    # Strategy B: article/h2 headings with links
    for heading in soup.select("h2 a[href], h3 a[href]"):
        title = _strip(heading.get_text())
        if not title or len(title) < 8:
            continue
        href = heading.get("href", "")
        apply_link = href if href.startswith("http") else f"{BASE_URL}{href}"

        # Try to find a sibling <p> for description
        parent = heading.find_parent(["h2", "h3"])
        desc = ""
        if parent:
            sibling = parent.find_next_sibling("p")
            desc = _strip(str(sibling))[:200] if sibling else ""

        jobs.append({
            "title":       title,
            "company":     default_sector,
            "location":    "India",
            "description": desc,
            "source_url":  apply_link,
            "apply_link":  apply_link,
            "date_posted": _today(),
        })

    return jobs


# ─────────────────────────────────────────────
# Enrichment
# ─────────────────────────────────────────────

def _enrich(raw: Dict) -> Dict:
    title    = raw.get("title", "")
    location = raw.get("location", "India")
    desc     = raw.get("description", "")
    combined = f"{title} {location} {desc}"

    return {
        "title":               title,
        "company":             raw.get("company", "Government of India"),
        "location":            location,
        "city":                normalize_city(combined) or "Other",
        "salary_raw":          "",
        "salary_min":          None,
        "salary_max":          None,
        "job_type":            "Full Time",
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc[:200],
        "source":              "FreeJobAlert",
        "source_url":          raw.get("source_url", ""),
        "apply_link":          raw.get("apply_link", ""),
        "tags":                extract_tags(title, desc),
        "date_posted":         raw.get("date_posted", _today()),
    }


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def scrape_freejobaler() -> List[Dict]:
    """
    Scrape FreeJobAlert.com for government/PSU job notifications.
    Returns job dicts ready for database.save_job().
    """
    all_raw: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for i, (url, sector) in enumerate(LISTING_PAGES):
            try:
                resp = await client.get(url, headers=_headers())
                if resp.status_code != 200:
                    print(f"[FreeJobAlert] {url}: HTTP {resp.status_code}")
                    continue
                raw = _parse_listing_page(resp.text, sector)
                print(f"[FreeJobAlert] {url}: {len(raw)} jobs")
                all_raw.extend(raw)
            except Exception as exc:
                print(f"[FreeJobAlert] {url}: {exc}")

            if i < len(LISTING_PAGES) - 1:
                await polite_delay(1.5, 3.0)

    jobs = [_enrich(r) for r in all_raw]
    seen: set[str] = set()
    unique: List[Dict] = []
    for j in jobs:
        if j["source_url"] and j["source_url"] not in seen:
            seen.add(j["source_url"])
            unique.append(j)

    print(f"[FreeJobAlert] Total unique jobs: {len(unique)}")
    return unique
