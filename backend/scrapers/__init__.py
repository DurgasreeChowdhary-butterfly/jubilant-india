"""
scrapers/__init__.py — central scrape_all() for Jubilant India

Runs all scrapers concurrently via asyncio.gather.
Cookie-based scrapers skip gracefully when env vars are not set.
Any individual scraper failure is caught; the rest continue unaffected.
"""

import asyncio
from typing import Dict, List

from .adzuna_scraper import scrape_adzuna
from .ats_india      import scrape_ats_all
from .cutshort       import scrape_cutshort
from .freejobaler    import scrape_freejobaler
from .hasjob         import scrape_hasjob
from .iimjobs        import scrape_iimjobs
from .linkedin       import scrape_linkedin
from .naukri         import scrape_naukri
from .remotive_scraper import scrape_remotive
from .rss_india      import scrape_rss_india
from .wellfound      import scrape_wellfound

_SCRAPERS = [
    # Always-on (no cookies needed)
    ("Hasjob",       scrape_hasjob),
    ("ATS",          scrape_ats_all),
    ("FreeJobAlert", scrape_freejobaler),
    ("Remotive",     scrape_remotive),
    ("RSS India",    scrape_rss_india),
    ("Adzuna",       scrape_adzuna),
    # Cookie-based (skip gracefully if env var not set)
    ("Naukri",       scrape_naukri),
    ("Wellfound",    scrape_wellfound),
    ("Cutshort",     scrape_cutshort),
    ("IIMJobs",      scrape_iimjobs),
    ("LinkedIn",     scrape_linkedin),
]


async def scrape_all() -> Dict:
    """
    Run all scrapers concurrently.

    Returns:
        {
            "jobs":  List[Dict],
            "stats": Dict[str, int],   # per-scraper job counts
            "total": int,
        }
    """
    names = [name for name, _  in _SCRAPERS]
    fns   = [fn   for _,    fn in _SCRAPERS]

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
            status = "skipped" if count == 0 else f"{count} jobs"
            print(f"[scrape_all] {name}: {status}")

    total = len(all_jobs)
    sep   = "=" * 48
    print(f"\n{sep}")
    print(f"  TOTAL COLLECTED : {total} jobs")
    print(sep)
    return {"jobs": all_jobs, "stats": stats, "total": total}
