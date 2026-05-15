import asyncio
import html
import os
import re
from typing import Dict, List

import httpx
from bs4 import BeautifulSoup

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

IIMJOBS_COOKIES = os.getenv("IIMJOBS_COOKIES", "")

SEARCHES = [
    "machine learning",
    "data scientist",
    "product manager",
    "python developer",
    "full stack developer",
]


def _strip(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _headers(with_cookies: bool = False) -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"]          = "text/html,application/xhtml+xml,*/*"
    if with_cookies and IIMJOBS_COOKIES:
        h["Cookie"] = IIMJOBS_COOKIES
    return h


def _parse_page(html_text: str) -> List[Dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    jobs = []

    cards = (
        soup.select("div.job-container") or
        soup.select("li.job") or
        soup.select("div.jobTuple") or
        soup.select("article.job-post")
    )
    for card in cards:
        try:
            title_el   = card.select_one("h2 a, h3 a, .job-title a, a.title")
            company_el = card.select_one(".company, .employer, .comp-name")
            loc_el     = card.select_one(".location, .loc, .job-loc")
            sal_el     = card.select_one(".salary, .sal, .ctc")
            exp_el     = card.select_one(".exp, .experience")

            title = _strip(str(title_el)) if title_el else ""
            if not title:
                continue

            href = title_el.get("href", "") if title_el else ""
            if not href:
                continue

            m      = re.search(r"/(\d+)/?", href)
            job_id = m.group(1) if m else href.split("/")[-1]
            apply  = f"https://www.iimjobs.com{href}" if href.startswith("/") else href

            company  = _strip(str(company_el)) if company_el else ""
            location = _strip(str(loc_el))     if loc_el     else "India"
            sal_str  = _strip(str(sal_el))      if sal_el     else ""
            exp_str  = _strip(str(exp_el))      if exp_el     else ""

            sal_min, sal_max, _ = parse_indian_salary(sal_str)
            combined = f"{title} {location} {exp_str}"

            jobs.append({
                "title":               title,
                "company":             company or "Unknown",
                "location":            location,
                "city":                normalize_city(combined),
                "salary_raw":          sal_str,
                "salary_min":          sal_min,
                "salary_max":          sal_max,
                "job_type":            "Full Time",
                "experience_level":    normalize_experience(f"{title} {exp_str}"),
                "description_snippet": "",
                "source":              "IIMJobs",
                "source_url":          f"iimjobs_{job_id}",
                "apply_link":          apply,
                "tags":                extract_tags(title, ""),
                "date_posted":         "",
            })
        except Exception:
            continue

    return jobs


async def scrape_iimjobs() -> List[Dict]:
    use_cookies = bool(IIMJOBS_COOKIES)
    seen = set()
    all_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for query in SEARCHES:
            slug = query.replace(" ", "-")
            urls = [
                f"https://www.iimjobs.com/j/search.php?search={query.replace(' ', '+')}&location=india",
                f"https://www.iimjobs.com/jobs/{slug}-jobs-in-india",
            ]
            for url in urls:
                try:
                    resp = await client.get(url, headers=_headers(use_cookies))
                    if resp.status_code in (403, 429):
                        print(f"[IIMJobs] Blocked ({resp.status_code}) for '{query}'")
                        break
                    if resp.status_code != 200:
                        continue

                    jobs  = _parse_page(resp.text)
                    added = 0
                    for j in jobs:
                        key = j["source_url"]
                        if key not in seen:
                            seen.add(key)
                            all_jobs.append(j)
                            added += 1

                    if added:
                        print(f"[IIMJobs] '{query}': {added} jobs")
                        break

                except Exception as e:
                    print(f"[IIMJobs] '{query}': {e}")

            await asyncio.sleep(2.0)

    print(f"[IIMJobs] Total: {len(all_jobs)} jobs")
    return all_jobs
