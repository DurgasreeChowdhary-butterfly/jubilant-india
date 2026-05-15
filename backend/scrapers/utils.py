"""
utils.py — shared utilities for all Jubilant India scrapers
"""

import asyncio
import random
import re
from typing import List, Optional, Tuple

# ─────────────────────────────────────────────
# 1. User-Agent rotation
# ─────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 OPR/110.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Vivaldi/6.7.3329.21",
]

_REFERERS = [
    "https://www.google.co.in/",
    "https://www.google.com/",
    "https://www.linkedin.com/",
    "https://www.naukri.com/",
]

def get_random_headers() -> dict:
    """Return request headers with a random User-Agent, Indian locale, and referer."""
    return {
        "User-Agent":      random.choice(_USER_AGENTS),
        "Accept-Language": "en-IN,en-GB;q=0.9,en;q=0.8",
        "Referer":         random.choice(_REFERERS),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    }


# ─────────────────────────────────────────────
# 2. Salary parser
# ─────────────────────────────────────────────

_USD_TO_INR = 83


def parse_indian_salary(text: str) -> Tuple[Optional[int], Optional[int], str]:
    """
    Parse a salary string → (salary_min, salary_max, currency).
    Always returns currency="INR" (USD inputs are converted).
    Returns (None, None, "INR") for anything unparseable.

    Examples:
        "8-15 LPA"              → (800000, 1500000, "INR")
        "₹8L - ₹15L"           → (800000, 1500000, "INR")
        "8,00,000 - 15,00,000"  → (800000, 1500000, "INR")
        "40,000 per month"      → (480000, 480000,  "INR")
        "40k/month"             → (480000, 480000,  "INR")
        "$50,000"               → (4150000,4150000, "INR")
        "Not disclosed"         → (None, None,      "INR")
    """
    if not text:
        return None, None, "INR"

    t = text.strip()
    null = (None, None, "INR")

    is_usd     = bool(re.search(r'[$]|\bUSD\b', t, re.I))
    is_monthly = bool(re.search(r'per\s*month|/\s*month|\bmonthly\b|/mo\b|p\.m\b', t, re.I))

    def _finalise(mn: float, mx: float) -> Tuple[Optional[int], Optional[int], str]:
        if is_monthly:
            mn *= 12
            mx *= 12
        if is_usd:
            mn *= _USD_TO_INR
            mx *= _USD_TO_INR
        mn, mx = int(mn), int(mx)
        # Sanity: reject anything below ₹12,000/yr or above ₹50 Cr/yr
        if mn < 12_000 or mn > 500_000_000:
            return null
        return mn, mx, "INR"

    # ── LPA range: "8-15 LPA" / "8 - 15 LPA" ──
    m = re.search(r'([\d.]+)\s*[-–to]+\s*([\d.]+)\s*(?:LPA|L\.?P\.?A\.?)\b', t, re.I)
    if m:
        return _finalise(float(m.group(1)) * 100_000, float(m.group(2)) * 100_000)

    # ── Single LPA: "12 LPA" ──
    m = re.search(r'([\d.]+)\s*(?:LPA|L\.?P\.?A\.?)\b', t, re.I)
    if m:
        v = float(m.group(1)) * 100_000
        return _finalise(v, v)

    # ── Lakh range: "₹8L - ₹15L" / "8 Lakh - 15 Lakhs" ──
    m = re.search(
        r'([\d.]+)\s*[Ll](?:akh[s]?)?\b\s*[-–to]+\s*([\d.]+)\s*[Ll](?:akh[s]?)?\b',
        t, re.I,
    )
    if m:
        return _finalise(float(m.group(1)) * 100_000, float(m.group(2)) * 100_000)

    # ── Single lakh: "₹8L" / "8 Lakhs" ──
    m = re.search(r'([\d.]+)\s*[Ll](?:akh[s]?)?\b', t, re.I)
    if m:
        v = float(m.group(1)) * 100_000
        return _finalise(v, v)

    # ── K suffix range: "40k - 60k" ──
    m = re.search(r'([\d.]+)\s*[Kk]\s*[-–to]+\s*([\d.]+)\s*[Kk]', t)
    if m:
        return _finalise(float(m.group(1)) * 1_000, float(m.group(2)) * 1_000)

    # ── Single K: "40k" ──
    m = re.search(r'([\d.]+)\s*[Kk]\b', t)
    if m:
        v = float(m.group(1)) * 1_000
        return _finalise(v, v)

    # ── Raw number range (handles Indian comma format: 8,00,000) ──
    raw = re.findall(r'[\d,]+(?:\.\d+)?', t)
    nums = []
    for n in raw:
        try:
            nums.append(float(n.replace(",", "")))
        except ValueError:
            pass

    if len(nums) >= 2:
        return _finalise(nums[0], nums[1])
    if len(nums) == 1:
        return _finalise(nums[0], nums[0])

    return null


# ─────────────────────────────────────────────
# 3. City normaliser
# ─────────────────────────────────────────────

_CITY_MAP: List[Tuple[str, List[str]]] = [
    ("Bangalore",  ["bangalore", "bengaluru", "blr"]),
    ("Mumbai",     ["mumbai", "bombay", "mum"]),
    ("Delhi",      ["delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida", "faridabad"]),
    ("Hyderabad",  ["hyderabad", "hyd", "secunderabad", "cyberabad"]),
    ("Chennai",    ["chennai", "madras"]),
    ("Pune",       ["pune"]),
    ("Kolkata",    ["kolkata", "calcutta"]),
    ("Ahmedabad",  ["ahmedabad", "amdavad"]),
    ("Remote",     ["remote", "work from home", "wfh", "anywhere", "pan india", "pan-india"]),
]

def normalize_city(location_text: str) -> str:
    """
    Map any location string to a canonical city name.
    Falls back to 'Other' if no match is found.
    """
    if not location_text:
        return "Other"
    loc = location_text.lower()
    for city, keywords in _CITY_MAP:
        if any(k in loc for k in keywords):
            return city
    return "Other"


# ─────────────────────────────────────────────
# 4. Experience normaliser
# ─────────────────────────────────────────────

def normalize_experience(text: str) -> str:
    """
    Map a job title or experience string to a standard level:
    Fresher | Junior | Mid | Senior | Not Specified
    """
    if not text:
        return "Not Specified"
    t = text.lower()

    if any(w in t for w in [
        "fresher", "fresh graduate", "entry level", "entry-level",
        "graduate", "trainee", "0-1", "0 - 1", "0 to 1",
    ]):
        return "Fresher"

    if any(w in t for w in [
        "senior", "sr.", "sr ", "lead", "principal", "staff",
        "6+", "7+", "8+", "9+", "10+", "6 year", "7 year", "8 year",
    ]):
        return "Senior"

    if any(w in t for w in [
        "junior", "jr.", "jr ", "associate",
        "1-3", "1 - 3", "1 to 3", "2-3", "2 - 3",
    ]):
        return "Junior"

    if any(w in t for w in [
        "mid", "mid-level", "midlevel", "intermediate", "experienced",
        "3-6", "3 - 6", "3 to 6", "4-6", "5 year",
    ]):
        return "Mid"

    return "Not Specified"


# ─────────────────────────────────────────────
# 5. Tag extractor
# ─────────────────────────────────────────────

_TECH_TAGS = [
    "python", "javascript", "typescript", "react", "angular", "vue",
    "node", "java", "kotlin", "swift", "flutter", "dart", "golang",
    "rust", "c++", "c#", "php", "ruby", "django", "fastapi", "flask",
    "spring", "aws", "azure", "gcp", "docker", "kubernetes", "sql",
    "postgres", "mysql", "mongodb", "redis", "machine learning",
    "deep learning", "nlp", "ai", "data science", "devops", "ci/cd",
    "git", "linux", "react native", "android", "ios",
]

def extract_tags(title: str, description: str = "") -> List[str]:
    """
    Find tech skills mentioned in title and/or description.
    Returns up to 8 matched tags (lowercase), ordered by first appearance.
    """
    haystack = f"{title} {description}".lower()
    seen = []
    for tag in _TECH_TAGS:
        # Whole-word match for short tags to avoid false positives (e.g. "c" in "react")
        pattern = rf'\b{re.escape(tag)}\b' if len(tag) > 2 else rf'(?<!\w){re.escape(tag)}(?!\w)'
        if re.search(pattern, haystack) and tag not in seen:
            seen.append(tag)
        if len(seen) == 8:
            break
    return seen


# ─────────────────────────────────────────────
# 6. Polite async delay
# ─────────────────────────────────────────────

async def polite_delay(min: float = 1.0, max: float = 3.0) -> None:
    """Sleep for a random duration between min and max seconds."""
    await asyncio.sleep(random.uniform(min, max))
