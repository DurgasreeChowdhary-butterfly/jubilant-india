import asyncio
import os
from datetime import datetime
from typing import Dict, List

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

NAUKRI_COOKIES = os.getenv("NAUKRI_COOKIES", "")

QUERIES = [
    "machine learning engineer",
    "data scientist",
    "ai engineer",
    "python developer",
    "mlops engineer",
    "nlp engineer",
    "deep learning",
    "data engineer",
]


async def scrape_naukri() -> List[Dict]:
    if not NAUKRI_COOKIES:
        print("[Naukri] NAUKRI_COOKIES not set in .env — skipping")
        return []

    all_jobs: List[Dict] = []
    seen = set()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for query in QUERIES:
            try:
                resp = await client.get(
                    "https://www.naukri.com/jobapi/v3/search",
                    params={
                        "noOfResults": 50,
                        "urlType":     "search_by_keyword",
                        "searchType":  "adv",
                        "keyword":     query,
                        "k":           query,
                        "src":         "jobsearchDesk",
                    },
                    headers={
                        "appid":      "109",
                        "systemid":   "Naukri",
                        "accept":     "application/json",
                        "Cookie":     NAUKRI_COOKIES,
                        "User-Agent": get_random_headers()["User-Agent"],
                    },
                )
                data     = resp.json()
                jobs_raw = data.get("jobDetails", [])
                count    = 0

                for j in jobs_raw:
                    job_id = str(j.get("jobId", ""))
                    key    = f"naukri_{job_id}"
                    if key in seen:
                        continue
                    seen.add(key)

                    locs     = j.get("placeholders") or []
                    location = locs[0].get("label", "India") if locs else "India"

                    ts = j.get("modifiedDate", 0)
                    try:
                        date_posted = datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
                    except Exception:
                        date_posted = ""

                    sal                  = j.get("salary", "")
                    sal_min, sal_max, _  = parse_indian_salary(sal)
                    title                = j.get("title", "")
                    desc                 = j.get("jobDescription", "")

                    all_jobs.append({
                        "title":               title,
                        "company":             j.get("companyName", ""),
                        "location":            location,
                        "city":                normalize_city(location),
                        "salary_raw":          sal,
                        "salary_min":          sal_min,
                        "salary_max":          sal_max,
                        "description_snippet": desc[:200] if desc else "",
                        "apply_link":          j.get("jdURL", ""),
                        "source_url":          key,
                        "source":              "Naukri",
                        "date_posted":         date_posted,
                        "job_type":            "Full Time",
                        "experience_level":    normalize_experience(j.get("experienceText", "")),
                        "tags":                extract_tags(title, desc),
                    })
                    count += 1

                print(f"[Naukri] {query}: {count} jobs")

            except Exception as e:
                print(f"[Naukri] {query} failed: {e}")

            await asyncio.sleep(1.5)

    print(f"[Naukri] Total: {len(all_jobs)} jobs")
    return all_jobs
