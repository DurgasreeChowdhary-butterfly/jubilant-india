"""
scrapers/__init__.py — central scrape_all() for Jubilant India

Runs all 8 scrapers concurrently via asyncio.gather.
Any individual failure is caught; the rest continue unaffected.
"""

import asyncio
from typing import Dict, List

from .adzuna_scraper import scrape_adzuna
from .ats_india import scrape_ats_all
from .cutshort import scrape_cutshort
from .freejobaler import scrape_freejobaler
from .hasjob import scrape_hasjob
from .remotive_scraper import scrape_remotive
from .rss_india import scrape_rss_india
from .wellfound import scrape_wellfound

_SCRAPERS = [
    ("Hasjob",       scrape_hasjob),
    ("ATS",          scrape_ats_all),
    ("Wellfound",    scrape_wellfound),
    ("Cutshort",     scrape_cutshort),
    ("FreeJobAlert", scrape_freejobaler),
    ("Remotive",     scrape_remotive),
    ("RSS India",    scrape_rss_india),
    ("Adzuna",       scrape_adzuna),
]


async def scrape_all() -> Dict:
    """
    Run all scrapers concurrently.

    Returns:
        {
            "jobs":  List[Dict],
            "stats": Dict[str, int],   # per-scraper counts
            "total": int,
        }
    """
    names   = [name for name, _  in _SCRAPERS]
    fns     = [fn   for _,    fn in _SCRAPERS]

    results = await asyncio.gather(*[fn() for fn in fns], return_exceptions=True)

    all_jobs: List[Dict]     = []
    stats:    Dict[str, int] = {}

    for name, result in zip(names, results):
        if isinstance(result, Exception):
            print(f"[scrape_all] {name} FAILED: {result}")
            stats[name] = 0
        else:
            count = len(result)
            all_jobs.extend(result)
            stats[name] = count
            print(f"[scrape_all] {name}: {count} jobs")

    total = len(all_jobs)
    sep   = "=" * 40
    print(f"\n{sep}")
    print(f"TOTAL COLLECTED : {total}")
    print(sep)
    return {"jobs": all_jobs, "stats": stats, "total": total}
