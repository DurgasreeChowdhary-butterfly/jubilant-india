"""
rss_india.py — Alternative Indian job sources replacing broken Naukri/Indeed feeds

Sources:
  Arbeitnow   — JSON API, paginated, remote + India jobs
  Freshersworld — RSS (Indian freshers board)
  TimesJobs   — RSS (Indian job board)
  Shine.com   — RSS (Indian job board)
  Internshala — RSS (Indian internships + jobs)
  JobsForHer  — RSS (women in tech India)

Each source is attempted independently; failures are caught and skipped.
"""

import asyncio
import email.utils
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

# ── Arbeitnow (JSON) ──────────────────────────────────────────────────────────

ARBEITNOW_URL = "https://www.arbeitnow.com/api/job-board-api"

# ── RSS feeds ─────────────────────────────────────────────────────────────────

RSS_FEEDS: List[Tuple[str, str]] = [
    ("https://www.freshersworld.com/jobs/rss",                                    "Freshersworld"),
    ("https://www.timesjobs.com/candidate/jobs-in-india.html?rssJobsFeed=1",      "TimesJobs"),
    ("https://www.shine.com/rss/jobs-in-india.xml",                               "Shine"),
    ("https://internshala.com/rss/jobs",                                           "Internshala"),
    ("https://www.jobsforher.com/rss",                                             "JobsForHer"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_pubdate(value: str) -> str:
    if not value:
        return _today()
    try:
        tup = email.utils.parsedate(value.strip())
        if tup:
            return datetime(*tup[:3]).strftime("%Y-%m-%d")
    except Exception:
        pass
    return value[:10] if len(value) >= 10 else _today()


def _rss_text(item: ET.Element, tag: str) -> str:
    el = item.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _headers(json_mode: bool = False) -> dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "application/json" if json_mode else "application/rss+xml, application/xml, text/xml, */*"
    return h


def _build_job(title: str, company: str, location: str, desc: str,
               link: str, date: str, source: str) -> Dict:
    combined = f"{title} {location} {desc}"
    m = re.search(
        r"(?:Rs\.?|INR|₹|\$)?\s*[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?"
        r"(?:\s*(?:LPA|lakh[s]?|per\s*(?:month|year)|/\s*(?:mo|yr)))?",
        desc, re.I,
    )
    sal_raw             = m.group(0).strip() if m else ""
    sal_min, sal_max, _ = parse_indian_salary(sal_raw or desc)

    return {
        "title":               title,
        "company":             company,
        "location":            location or "India",
        "city":                normalize_city(combined),
        "salary_raw":          sal_raw,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            ("Remote"     if "remote" in combined.lower() else
                                "Internship" if "intern" in combined.lower() else
                                "Full Time"),
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc[:200],
        "source":              source,
        "source_url":          link,
        "apply_link":          link,
        "tags":                extract_tags(title, desc),
        "date_posted":         date,
    }


# ── Arbeitnow (JSON, paginated) ───────────────────────────────────────────────

async def _fetch_arbeitnow(client: httpx.AsyncClient) -> List[Dict]:
    """
    Fetch Arbeitnow job board API (paginated JSON).
    Keep only jobs where remote=True or location contains 'India'.
    """
    jobs: List[Dict] = []
    page = 1
    while page <= 5:   # cap at 5 pages (~500 jobs)
        try:
            resp = await client.get(
                ARBEITNOW_URL,
                params={"page": page},
                headers=_headers(json_mode=True),
                timeout=20,
            )
            if resp.status_code != 200:
                break
            data  = resp.json()
            items = data.get("data", [])
            if not items:
                break

            for item in items:
                remote   = item.get("remote", False)
                location = (item.get("location") or "").strip()
                # Keep if remote or location mentions India
                if not remote and "india" not in location.lower():
                    continue

                title   = (item.get("title") or "").strip()
                company = (item.get("company_name") or "").strip()
                if not title:
                    continue

                desc    = _strip(item.get("description") or "")
                link    = (item.get("url") or "").strip()
                tags    = [str(t) for t in (item.get("tags") or [])[:4]]
                created = item.get("created_at", 0)
                try:
                    date = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d")
                except Exception:
                    date = _today()

                if not link:
                    continue

                j = _build_job(title, company, location or "Remote", desc, link, date, "Arbeitnow")
                j["tags"] = list(dict.fromkeys(tags + j["tags"]))[:8]
                if remote:
                    j["job_type"] = "Remote"
                    j["city"]     = "Remote"
                jobs.append(j)

            # Check if there's a next page
            links = data.get("links", {})
            if not links.get("next"):
                break
            page += 1

        except Exception as exc:
            print(f"[Arbeitnow] page {page}: {exc}")
            break

    print(f"[Arbeitnow] {len(jobs)} jobs (India/Remote filter)")
    return jobs


# ── Generic RSS feed ──────────────────────────────────────────────────────────

async def _fetch_rss(
    client:      httpx.AsyncClient,
    url:         str,
    source_name: str,
) -> List[Dict]:
    try:
        resp = await client.get(url, headers=_headers(), timeout=20)
        if resp.status_code in (401, 403, 404, 429):
            print(f"[RSS] {source_name}: HTTP {resp.status_code}")
            return []
        resp.raise_for_status()

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            print(f"[RSS] {source_name}: not valid XML (likely HTML)")
            return []

        items = root.findall("./channel/item") or root.findall(".//item")
        jobs  = []
        for item in items:
            title   = _rss_text(item, "title")
            link    = _rss_text(item, "link")
            desc    = _strip(_rss_text(item, "description"))
            pubdate = _parse_pubdate(_rss_text(item, "pubDate"))
            if not title or not link:
                continue

            # Company: from <source> tag or description heuristic
            src_el  = item.find("source")
            company = (src_el.text or "").strip() if src_el is not None else ""
            if not company:
                m = re.search(r"(?:company|employer)[:\s]+([A-Za-z0-9 &.]+)", desc, re.I)
                company = m.group(1).strip() if m else source_name

            # Location: from <location> tag or description heuristic
            loc_el   = item.find("location")
            location = (loc_el.text or "").strip() if loc_el is not None else ""
            if not location:
                m = re.search(r"(?:location|city)[:\s]+([A-Za-z, ]+?)(?:\.|<|$)", desc, re.I)
                location = m.group(1).strip() if m else "India"

            jobs.append(_build_job(title, company, location, desc, link, pubdate, source_name))

        print(f"[RSS] {source_name}: {len(jobs)} jobs")
        return jobs

    except Exception as exc:
        print(f"[RSS] {source_name}: {exc}")
        return []


# ── Public entry point ────────────────────────────────────────────────────────

async def scrape_rss_india() -> List[Dict]:
    """
    Fetch Arbeitnow (JSON) + 5 RSS feeds concurrently.
    Returns job dicts ready for database.save_job().
    """
    async with httpx.AsyncClient(follow_redirects=True, timeout=25) as client:
        results = await asyncio.gather(
            _fetch_arbeitnow(client),
            *[_fetch_rss(client, url, src) for url, src in RSS_FEEDS],
            return_exceptions=True,
        )

    seen:   set[str]   = set()
    unique: List[Dict] = []
    for batch in results:
        if isinstance(batch, Exception):
            print(f"[RSS India] batch error: {batch}")
            continue
        for j in batch:
            if j["source_url"] and j["source_url"] not in seen:
                seen.add(j["source_url"])
                unique.append(j)

    print(f"[RSS India] Total unique jobs: {len(unique)}")
    return unique
