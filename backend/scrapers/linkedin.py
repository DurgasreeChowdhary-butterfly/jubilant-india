"""
LinkedIn job scraper — strictly rate-limited, cookie-based.
Max 100 jobs per session, 3-5 s between requests, stops on 429.
Only use with YOUR OWN LinkedIn cookies.
"""

import asyncio
import os
import random
import re
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from scrapers.utils import extract_tags, get_random_headers, normalize_city, normalize_experience

LINKEDIN_COOKIES = os.getenv("LINKEDIN_COOKIES", "")

MAX_JOBS = 100
SEARCHES = [
    "machine learning engineer india",
    "data scientist india",
    "ai engineer india",
    "mlops engineer india",
    "nlp engineer india",
    "deep learning india",
]


def _headers() -> Dict:
    h = get_random_headers()
    h.update({
        "Cookie":                       LINKEDIN_COOKIES,
        "Accept":                       "text/html,application/xhtml+xml,*/*",
        "Accept-Encoding":              "gzip, deflate",
        "X-Li-Lang":                    "en_US",
        "X-Restli-Protocol-Version":    "2.0.0",
    })
    return h


def _parse_cards(html_text: str) -> List[Dict]:
    soup  = BeautifulSoup(html_text, "html.parser")
    cards = (
        soup.select("div.base-card") or
        soup.select("li.jobs-search-results__list-item") or
        soup.select("div.job-search-card")
    )
    jobs = []
    for card in cards:
        try:
            title_el   = card.select_one("h3.base-search-card__title, h3")
            company_el = card.select_one("h4.base-search-card__subtitle, h4")
            loc_el     = card.select_one("span.job-search-card__location, .job-search-card__location")
            link_el    = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            time_el    = card.select_one("time")

            title = (title_el.get_text(strip=True) if title_el else "").strip()
            if not title:
                continue

            href   = link_el.get("href", "") if link_el else ""
            m      = re.search(r"/jobs/view/(\d+)", href)
            job_id = m.group(1) if m else ""
            if not job_id:
                continue

            company  = (company_el.get_text(strip=True) if company_el else "").strip()
            location = (loc_el.get_text(strip=True)     if loc_el     else "India").strip()
            date     = (time_el.get("datetime", "")     if time_el    else "")[:10]
            apply    = f"https://www.linkedin.com/jobs/view/{job_id}/"
            combined = f"{title} {location}"

            jobs.append({
                "title":               title,
                "company":             company or "Unknown",
                "location":            location,
                "city":                normalize_city(combined),
                "salary_raw":          "",
                "salary_min":          None,
                "salary_max":          None,
                "job_type":            "Remote" if "remote" in combined.lower() else "Full Time",
                "experience_level":    normalize_experience(title),
                "description_snippet": "",
                "source":              "LinkedIn",
                "source_url":          f"linkedin_{job_id}",
                "apply_link":          apply,
                "tags":                extract_tags(title, ""),
                "date_posted":         date,
            })
        except Exception:
            continue

    return jobs


async def scrape_linkedin() -> List[Dict]:
    if not LINKEDIN_COOKIES:
        print("[LinkedIn] LINKEDIN_COOKIES not set — skipping")
        return []

    seen = set()
    all_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for query in SEARCHES:
            if len(all_jobs) >= MAX_JOBS:
                break
            try:
                resp = await client.get(
                    "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
                    params={
                        "keywords": query,
                        "location": "India",
                        "f_TPR":    "r86400",  # last 24 hours
                        "start":    0,
                    },
                    headers=_headers(),
                )
                if resp.status_code == 429:
                    print("[LinkedIn] 429 rate-limited — stopping immediately")
                    break
                if resp.status_code in (401, 403):
                    print(f"[LinkedIn] Blocked ({resp.status_code}) — check cookies")
                    break
                if resp.status_code != 200:
                    continue

                jobs  = _parse_cards(resp.text)
                added = 0
                for j in jobs:
                    if len(all_jobs) >= MAX_JOBS:
                        break
                    key = j["source_url"]
                    if key not in seen:
                        seen.add(key)
                        all_jobs.append(j)
                        added += 1

                print(f"[LinkedIn] '{query}': {added} jobs")

            except Exception as e:
                print(f"[LinkedIn] '{query}': {e}")

            await asyncio.sleep(random.uniform(3.0, 5.0))

    print(f"[LinkedIn] Total: {len(all_jobs)} jobs (cap={MAX_JOBS})")
    return all_jobs
