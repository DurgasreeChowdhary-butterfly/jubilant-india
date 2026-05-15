import asyncio
import os
from typing import Dict, List

import httpx

from scrapers.utils import (
    extract_tags,
    get_random_headers,
    normalize_city,
    normalize_experience,
    parse_indian_salary,
)

CUTSHORT_COOKIES = os.getenv("CUTSHORT_COOKIES", "")

SEARCHES = [
    "machine learning",
    "data scientist",
    "ai ml engineer",
    "python developer",
    "full stack developer",
    "backend developer",
    "react developer",
    "product manager",
    "devops",
    "android developer",
]


def _headers() -> Dict:
    h = get_random_headers()
    h.update({
        "Content-Type":    "application/json",
        "Referer":         "https://cutshort.io/jobs",
        "Accept":          "application/json",
        "Accept-Encoding": "gzip, deflate",
    })
    if CUTSHORT_COOKIES:
        h["Cookie"] = CUTSHORT_COOKIES
    return h


def _parse_job(j: Dict) -> Dict:
    job_id   = str(j.get("id") or j.get("_id") or "")
    title    = (j.get("title") or j.get("role") or "").strip()
    co       = j.get("company") or {}
    company  = (co.get("name") if isinstance(co, dict) else str(co or "")).strip()
    location = (j.get("location") or j.get("city") or "India").strip()
    sal_str  = j.get("salaryString") or j.get("salary") or ""
    sal_min, sal_max, _ = parse_indian_salary(sal_str)
    desc     = (j.get("description") or "")[:200]
    skills   = j.get("skills") or []
    combined = f"{title} {location} {desc}"

    return {
        "title":               title,
        "company":             company or "Unknown",
        "location":            location,
        "city":                normalize_city(combined),
        "salary_raw":          sal_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            "Remote" if "remote" in combined.lower() else "Full Time",
        "experience_level":    normalize_experience(str(j.get("experience") or "")),
        "description_snippet": desc,
        "source":              "Cutshort",
        "source_url":          f"cutshort_{job_id}",
        "apply_link":          f"https://cutshort.io/job/{job_id}",
        "tags":                list(dict.fromkeys(
                                   [str(s) for s in skills[:4]] +
                                   extract_tags(title, desc)
                               ))[:8],
        "date_posted":         (j.get("postedAt") or j.get("createdAt") or "")[:10],
    }


async def scrape_cutshort() -> List[Dict]:
    if not CUTSHORT_COOKIES:
        print("[Cutshort] CUTSHORT_COOKIES not set — skipping")
        return []

    seen = set()
    all_jobs: List[Dict] = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for query in SEARCHES:
            for page in (1, 2):
                try:
                    resp = await client.post(
                        "https://cutshort.io/api/jobs/search",
                        json={
                            "filters": {
                                "query":         query,
                                "locations":     ["Bangalore", "Mumbai", "Delhi", "Hyderabad", "Remote"],
                                "minExperience": 0,
                                "maxExperience": 10,
                            },
                            "page":  page,
                            "limit": 50,
                        },
                        headers=_headers(),
                    )
                    if resp.status_code in (401, 403):
                        print(f"[Cutshort] Blocked ({resp.status_code}) — check cookies")
                        break
                    if resp.status_code != 200:
                        break

                    data     = resp.json()
                    jobs_raw = data if isinstance(data, list) else (
                        data.get("data") or data.get("jobs") or data.get("results") or []
                    )
                    added = 0
                    for j in jobs_raw:
                        parsed = _parse_job(j)
                        key    = parsed["source_url"]
                        if key.endswith("_") or key in seen:
                            continue
                        seen.add(key)
                        all_jobs.append(parsed)
                        added += 1

                    print(f"[Cutshort] '{query}' p{page}: {added} jobs")
                    if len(jobs_raw) < 50:
                        break

                except Exception as e:
                    print(f"[Cutshort] '{query}' p{page}: {e}")
                    break

                await asyncio.sleep(1.0)

    print(f"[Cutshort] Total: {len(all_jobs)} jobs")
    return all_jobs
