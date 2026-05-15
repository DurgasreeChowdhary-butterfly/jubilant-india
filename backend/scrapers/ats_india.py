"""
ats_india.py — Scrape public ATS job boards used by Indian companies.

Sources:
  Lever      — jobs.lever.co/{slug}            (httpx + BeautifulSoup)
  Greenhouse — boards.greenhouse.io/{slug}      (httpx + BeautifulSoup)
  Zoho       — careers.zohocorp.com/jobs/Careers (Playwright, JS-rendered)

Board health: most slugs listed here return 404 — companies move ATS platforms
frequently. 404s are skipped silently. The lists are kept comprehensive so
that any board that comes back online is picked up automatically.
"""

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

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

# ─────────────────────────────────────────────
# Slug lists  (404 slugs are skipped gracefully)
# ─────────────────────────────────────────────

LEVER_SLUGS = [
    # Confirmed working
    "meesho", "paytm", "cred", "fi", "fi-money", "freshworks",
    # Fintech — payments, neo-banking, wealth
    "coinswitch", "coinbase", "jupiter", "jupiter-money", "slice", "slice-pay",
    "niyo", "smallcase", "zerodha", "upstox", "angelone", "groww",
    "razorpay", "cashfree", "payu", "billdesk",
    # Edtech
    "unacademy", "vedantu", "scaler", "upgrad", "physicswallah",
    "testbook", "doubtnut", "byju", "classplus",
    # Q-commerce / food / mobility
    "dunzo", "blinkit", "zepto", "swiggy", "zomato",
    "ola", "rapido", "yulu", "bounce",
    # EV / Clean energy
    "ather", "ola-electric", "euler",
    # Healthtech
    "innovaccer", "practo", "mfine", "pristyncare", "healthifyme",
    "lenskart", "1mg", "pharmeasy", "netmeds",
    # B2B SaaS
    "darwinbox", "leadsquared", "chargebee", "hasura", "setu", "recko",
    "cleartax", "taxbuddy",
    # Travel / Hospitality
    "oyo", "treebo", "zostel", "fab-hotels",
    # E-commerce / Consumer
    "nykaa", "mamaearth", "boat-lifestyle", "myntra", "flipkart",
    # Social / Content
    "sharechat", "dailyhunt", "moj", "lokal", "koo", "josh",
    # Gaming
    "dream11", "mpl", "mpl-gaming", "games24x7", "gamezy",
    # Logistics
    "blackbuck", "rivigo", "delhivery", "shiprocket", "pickrr", "eshipz",
    # Global tech with India offices
    "turing", "geektrust", "instahyre",
    "thoughtworks", "publicissapient", "mphasis", "hexaware",
    "microsoft-india", "amazon-india", "uber-india",
]

GREENHOUSE_SLUGS = [
    # Confirmed working
    "groww", "inmobi", "postman", "turing",
    # SaaS / Infra
    "browserstack", "freshworks", "chargebee",
    "clevertap", "moengage", "webengage",
    # Conversational AI / CPaaS
    "yellowmessenger", "gupshup", "exotel",
    # Fintech
    "razorpay", "cashfree", "setu",
    # Hyperlocal / Home services
    "urban-company", "housejoy",
    # Agri / Grocery
    "ninjacart", "dehaat", "bigbasket",
    "milkbasket", "grofers", "jiomart",
    # Auto / Mobility
    "cars24", "spinny", "droom",
    "euler-motors", "ather-energy", "ola-electric",
    # Real estate
    "nobroker", "magicbricks", "99acres",
    # Insurance / Lending
    "policybazaar", "acko", "digit-insurance",
    "lendingkart", "capital-float", "incred",
    # Edtech
    "testbook", "classplus", "teachmint",
    # Logistics
    "rivigo", "blackbuck", "delhivery",
    "shiprocket", "eshipz", "pickrr",
]

ZOHO_CAREERS_URL = "https://careers.zohocorp.com/jobs/Careers"


# ─────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────

def _headers(accept_html: bool = False) -> Dict:
    h = get_random_headers()
    h["Accept-Encoding"] = "gzip, deflate"
    h["Accept"] = "text/html,application/xhtml+xml,*/*" if accept_html else "text/html,*/*"
    return h


def _strip(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _infer_job_type(title: str, desc: str) -> str:
    t = f"{title} {desc}".lower()
    if "intern"   in t: return "Internship"
    if "contract" in t or "freelance" in t: return "Contract"
    if "remote"   in t or "work from home" in t or "wfh" in t: return "Remote"
    return "Full Time"


def _enrich(raw: Dict, source: str) -> Dict:
    title    = raw.get("title",    "")
    company  = raw.get("company",  "")
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
        "company":             company,
        "location":            location,
        "city":                normalize_city(combined),
        "salary_raw":          salary_raw_str,
        "salary_min":          sal_min,
        "salary_max":          sal_max,
        "job_type":            _infer_job_type(title, desc),
        "experience_level":    normalize_experience(combined),
        "description_snippet": desc[:200],
        "source":              source,
        "source_url":          raw.get("source_url", ""),
        "apply_link":          raw.get("apply_link", ""),
        "tags":                extract_tags(title, desc),
        "date_posted":         raw.get("date_posted", _today()),
    }


# ─────────────────────────────────────────────
# 1. Lever
# ─────────────────────────────────────────────

def _parse_lever(html_text: str, company: str) -> List[Dict]:
    """
    Selectors confirmed May 2026:
      a.posting-title                    — wraps each job (href = full URL)
      h5[data-qa="posting-name"]         — job title
      span.sort-by-location              — location
      span.sort-by-team                  — department (sometimes absent)
    """
    soup = BeautifulSoup(html_text, "html.parser")
    jobs = []
    for a in soup.select("a.posting-title"):
        try:
            title_el = a.select_one("h5[data-qa='posting-name'], h5")
            loc_el   = a.select_one("span.sort-by-location")
            dept_el  = a.select_one("span.sort-by-team")
            title    = _strip(str(title_el)) if title_el else _strip(a.get_text())
            if not title:
                continue
            href = a.get("href", "")
            jobs.append({
                "title":       title,
                "company":     company,
                "location":    _strip(str(loc_el)) if loc_el else "",
                "description": _strip(str(dept_el)) if dept_el else "",
                "source_url":  href if href.startswith("http") else f"https://jobs.lever.co{href}",
                "apply_link":  href if href.startswith("http") else f"https://jobs.lever.co{href}",
                "date_posted": _today(),
            })
        except Exception:
            continue
    return jobs


async def scrape_lever() -> Tuple[List[Dict], List[Tuple[str, int, str]]]:
    """Returns (jobs, summary_rows) where each summary row is (slug, count, status)."""
    all_jobs: List[Dict]                  = []
    summary:  List[Tuple[str, int, str]]  = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for i, slug in enumerate(LEVER_SLUGS):
            try:
                resp = await client.get(
                    f"https://jobs.lever.co/{slug}",
                    headers=_headers(accept_html=True),
                )
                if resp.status_code == 404:
                    summary.append((slug, 0, "404"))
                    continue
                if resp.status_code != 200:
                    summary.append((slug, 0, f"HTTP {resp.status_code}"))
                    continue

                company  = slug.replace("-", " ").title()
                raw      = _parse_lever(resp.text, company)
                enriched = [_enrich(r, "Lever") for r in raw]
                all_jobs.extend(enriched)
                summary.append((slug, len(enriched), "OK"))
                if enriched:
                    print(f"[Lever] {slug}: {len(enriched)} jobs")

            except Exception as exc:
                summary.append((slug, 0, f"ERR: {exc}"))

            if i < len(LEVER_SLUGS) - 1:
                await asyncio.sleep(0.8)

    return all_jobs, summary


# ─────────────────────────────────────────────
# 2. Greenhouse
# ─────────────────────────────────────────────

def _parse_greenhouse(html_text: str, company: str) -> List[Dict]:
    """
    Selectors confirmed May 2026 (EU boards use tr.job-post, legacy use div.opening):
      tr.job-post > td.cell > a
        p:first-child  — title
        p:last-child   — location
    """
    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.select("tr.job-post") or soup.select("div.opening")
    jobs = []
    for row in rows:
        try:
            anchor = row.select_one("a[href]")
            if not anchor:
                continue
            ps     = anchor.select("p")
            title  = _strip(str(ps[0])) if ps else _strip(anchor.get_text())
            if not title:
                continue
            location = _strip(str(ps[1])) if len(ps) > 1 else ""
            if not location:
                loc_el = row.select_one("span.location, .location")
                location = _strip(str(loc_el)) if loc_el else ""
            href = anchor.get("href", "")
            jobs.append({
                "title":       title,
                "company":     company,
                "location":    location,
                "description": "",
                "source_url":  href if href.startswith("http") else f"https://boards.greenhouse.io{href}",
                "apply_link":  href if href.startswith("http") else f"https://boards.greenhouse.io{href}",
                "date_posted": _today(),
            })
        except Exception:
            continue
    return jobs


async def scrape_greenhouse() -> Tuple[List[Dict], List[Tuple[str, int, str]]]:
    all_jobs: List[Dict]                  = []
    summary:  List[Tuple[str, int, str]]  = []

    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        for i, slug in enumerate(GREENHOUSE_SLUGS):
            try:
                resp = await client.get(
                    f"https://boards.greenhouse.io/{slug}",
                    headers=_headers(accept_html=True),
                )
                if resp.status_code == 404:
                    summary.append((slug, 0, "404"))
                    continue
                if resp.status_code != 200:
                    summary.append((slug, 0, f"HTTP {resp.status_code}"))
                    continue

                company  = slug.replace("-", " ").title()
                raw      = _parse_greenhouse(resp.text, company)
                enriched = [_enrich(r, "Greenhouse") for r in raw]
                all_jobs.extend(enriched)
                summary.append((slug, len(enriched), "OK"))
                if enriched:
                    print(f"[Greenhouse] {slug}: {len(enriched)} jobs")

            except Exception as exc:
                summary.append((slug, 0, f"ERR: {exc}"))

            if i < len(GREENHOUSE_SLUGS) - 1:
                await polite_delay(1.5, 3.0)

    return all_jobs, summary


# ─────────────────────────────────────────────
# 3. Zoho Careers (Playwright — JS-rendered)
# ─────────────────────────────────────────────

def _zoho_playwright_sync() -> str:
    """
    Fetch careers.zohocorp.com using Playwright sync API in a thread.
    Returns the fully-rendered HTML, or "" on failure.

    Runs in a thread via asyncio.to_thread() to avoid blocking the async loop.
    On Windows, uvicorn uses SelectorEventLoop which can't spawn subprocesses;
    we replace it with ProactorEventLoop inside this thread before Playwright starts.
    """
    import asyncio, sys
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx     = browser.new_context(
                user_agent=get_random_headers()["User-Agent"],
                locale="en-IN",
            )
            page = ctx.new_page()
            page.goto(ZOHO_CAREERS_URL, wait_until="networkidle", timeout=30_000)
            # Try waiting for job cards to appear after JS renders
            for sel in [
                "tr.job-listing", "li.job-item", "[class*='jobCard']",
                "table.job-table tr", ".career-list li", ".job-list li",
            ]:
                try:
                    page.wait_for_selector(sel, timeout=5_000)
                    break
                except Exception:
                    continue
            html_content = page.content()
            browser.close()
            return html_content
    except ImportError:
        print("[Zoho] Playwright not installed — skipping")
    except Exception as exc:
        print(f"[Zoho] Playwright error: {exc}")
    return ""


def _parse_zoho(html_text: str) -> List[Dict]:
    """
    Parse the Zoho Corp careers page HTML.
    Tries multiple selector patterns since the page structure may vary.
    """
    if not html_text:
        return []

    soup = BeautifulSoup(html_text, "html.parser")

    # Detect empty/error page
    body_text = soup.get_text()
    if "does not exist" in body_text or len(body_text.strip()) < 200:
        return []

    jobs = []

    # Try selector patterns in priority order
    selector_sets = [
        # (row_sel, title_sel, loc_sel, link_sel)
        ("tr.job-listing",       ".job-title, td:first-child a", ".location, td:nth-child(2)", "a[href]"),
        ("li.job-item",          ".title, h3, h4",               ".location",                  "a[href]"),
        ("[class*='jobCard']",   "[class*='title']",             "[class*='location']",         "a[href]"),
        ("table.job-table tr",   "td:first-child",               "td:nth-child(2)",             "a[href]"),
        (".career-list li",      "a",                            ".location",                   "a[href]"),
    ]

    for row_sel, title_sel, loc_sel, link_sel in selector_sets:
        rows = soup.select(row_sel)
        if not rows:
            continue
        for row in rows:
            try:
                title_el = row.select_one(title_sel)
                loc_el   = row.select_one(loc_sel)
                link_el  = row.select_one(link_sel)
                title    = _strip(str(title_el)) if title_el else ""
                if not title or len(title) < 3:
                    continue
                location   = _strip(str(loc_el)) if loc_el else "India"
                href       = link_el.get("href", "") if link_el else ""
                apply_link = href if href.startswith("http") else f"https://careers.zohocorp.com{href}"
                jobs.append({
                    "title":       title,
                    "company":     "Zoho",
                    "location":    location,
                    "description": "",
                    "source_url":  apply_link,
                    "apply_link":  apply_link,
                    "date_posted": _today(),
                })
            except Exception:
                continue
        if jobs:
            break   # stop at first selector set that yields results

    return jobs


async def scrape_zoho() -> Tuple[List[Dict], List[Tuple[str, int, str]]]:
    """
    Scrape Zoho Corp's own careers page via Playwright.
    Set PLAYWRIGHT_ENABLED=false to skip (required on Railway / serverless hosts
    that don't have a Chromium binary available).
    """
    import os
    if os.getenv("PLAYWRIGHT_ENABLED", "true").lower() != "true":
        print("[Zoho] Playwright disabled via PLAYWRIGHT_ENABLED env var — skipping")
        return [], [("careers.zohocorp.com", 0, "disabled")]

    print("[Zoho] Launching headless browser for careers.zohocorp.com …")
    html_content = await asyncio.to_thread(_zoho_playwright_sync)

    raw      = _parse_zoho(html_content)
    enriched = [_enrich(r, "Zoho") for r in raw]

    status = "OK" if enriched else ("JS-rendered/empty" if html_content else "Playwright error")
    print(f"[Zoho] careers.zohocorp.com: {len(enriched)} jobs ({status})")

    return enriched, [("careers.zohocorp.com", len(enriched), status)]


# ─────────────────────────────────────────────
# Aggregate
# ─────────────────────────────────────────────

def _print_summary(all_summary: List[Tuple[str, str, int, str]]) -> None:
    """Print a compact summary table (ASCII-only to avoid Windows charmap errors)."""
    hits  = [r for r in all_summary if r[2] > 0]
    fours = [r for r in all_summary if r[3] == "404"]

    col_w  = max((len(r[1]) for r in all_summary), default=20) + 2
    header = f"{'ATS':<12} {'Slug':<{col_w}} {'Jobs':>5}  Status"
    rule   = "-" * len(header)

    print(f"\n{rule}")
    print(header)
    print(rule)
    for ats, slug, count, status in hits:
        print(f"  {ats:<10} {slug:<{col_w}} {count:>5}  {status}")
    misses = [r for r in all_summary if r[2] == 0 and r[3] != "404"]
    for ats, slug, count, status in misses:
        print(f"  {ats:<10} {slug:<{col_w}} {count:>5}  {status}")
    print(rule)
    total_jobs = sum(r[2] for r in all_summary)
    print(f"  {'TOTAL':<10} {'':<{col_w}} {total_jobs:>5}  ({len(fours)} boards 404)")
    print(rule)


async def scrape_ats_all() -> List[Dict]:
    """Run Lever, Greenhouse, and Zoho scrapers concurrently."""
    (lever_jobs,      lever_sum), \
    (greenhouse_jobs, gh_sum),    \
    (zoho_jobs,       zoho_sum)   = await asyncio.gather(
        scrape_lever(),
        scrape_greenhouse(),
        scrape_zoho(),
    )

    combined: List[Dict] = []
    for batch in (lever_jobs, greenhouse_jobs, zoho_jobs):
        if isinstance(batch, list):
            combined.extend(batch)

    # Deduplicate by source_url
    seen:   set[str]   = set()
    unique: List[Dict] = []
    for j in combined:
        url = j.get("source_url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(j)

    # Build unified summary with ATS label prepended
    all_summary: List[Tuple[str, str, int, str]] = (
        [("Lever",      slug, cnt, st) for slug, cnt, st in lever_sum] +
        [("Greenhouse", slug, cnt, st) for slug, cnt, st in gh_sum]    +
        [("Zoho",       slug, cnt, st) for slug, cnt, st in zoho_sum]
    )
    _print_summary(all_summary)
    print(f"\n[ATS] Grand total unique jobs: {len(unique)}")
    return unique
