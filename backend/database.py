"""
database.py — SQLite + SQLAlchemy 2.x for Jubilant India

get_jobs() uses raw sqlite3 for reliable parameterised queries and
predictable behaviour across SQLAlchemy versions.
All other functions (save_job, init_db, get_stats, clear_old_jobs)
continue to use SQLAlchemy ORM.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean, Column, Integer, String, Text,
    UniqueConstraint, and_, create_engine, func, or_, select,
)
from sqlalchemy.orm import DeclarativeBase, Session

# DB_PATH env var — set to /data/jobs.db on Render (persistent disk)
DB_PATH      = os.getenv("DB_PATH", "jobs.db")
_DB_FILE     = DB_PATH
DATABASE_URL = f"sqlite:///{DB_PATH}"


def _raw_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id                  = Column(Integer,  primary_key=True, autoincrement=True)
    title               = Column(String,   nullable=False)
    company             = Column(String,   nullable=False)
    location            = Column(Text)
    city                = Column(String)   # Bangalore | Mumbai | Delhi | Hyderabad | Chennai | Pune | Remote | Other
    salary_raw          = Column(Text)     # original string e.g. "8-15 LPA"
    salary_min          = Column(Integer)  # INR per year
    salary_max          = Column(Integer)  # INR per year
    job_type            = Column(String)   # Full Time | Internship | Contract | Remote
    experience_level    = Column(String)   # Fresher | Junior | Mid | Senior
    description_snippet = Column(Text)    # max 200 chars
    source              = Column(String)   # Hasjob | Wellfound | Instahyre | Cutshort | Zoho | Lever | Greenhouse | FreeJobAlert
    source_url          = Column(String,   unique=True)   # deduplication key
    apply_link          = Column(Text)
    tags                = Column(Text)     # JSON array as string e.g. '["python","django"]'
    date_posted         = Column(String)   # ISO date string from source
    date_added          = Column(String)   # ISO datetime when row was inserted
    is_active           = Column(Boolean,  default=True)


class UserTier(Base):
    __tablename__ = "user_tiers"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    email      = Column(String,  unique=True, nullable=False)
    tier       = Column(String,  default="free")   # free | pro | agency
    created_at = Column(String)
    expires_at = Column(String)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _session():
    return Session(engine)


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def init_db() -> None:
    """Create all tables (idempotent)."""
    Base.metadata.create_all(engine)


def save_job(job: Dict[str, Any]) -> bool:
    """
    Insert a job. Skips silently if source_url already exists.
    Returns True if inserted, False if duplicate.
    """
    source_url = job.get("source_url", "")
    if not source_url:
        return False

    # Truncate description to 200 chars
    snippet = (job.get("description_snippet") or "")[:200]

    # Normalise tags to JSON string
    tags_raw = job.get("tags", [])
    tags = json.dumps(tags_raw) if isinstance(tags_raw, list) else (tags_raw or "[]")

    with _session() as s:
        exists = s.execute(
            select(Job.id).where(Job.source_url == source_url)
        ).first()
        if exists:
            return False

        s.add(Job(
            title               = job.get("title", ""),
            company             = job.get("company", ""),
            location            = job.get("location", ""),
            city                = job.get("city", ""),
            salary_raw          = job.get("salary_raw", ""),
            salary_min          = job.get("salary_min"),
            salary_max          = job.get("salary_max"),
            job_type            = job.get("job_type", ""),
            experience_level    = job.get("experience_level", ""),
            description_snippet = snippet,
            source              = job.get("source", ""),
            source_url          = source_url,
            apply_link          = job.get("apply_link", ""),
            tags                = tags,
            date_posted         = job.get("date_posted", ""),
            date_added          = _now_iso(),
            is_active           = job.get("is_active", True),
        ))
        s.commit()
    return True


def get_jobs(
    keyword:          str  = "",
    city:             str  = "",
    job_type:         str  = "",
    experience_level: str  = "",
    source:           str  = "",
    salary_min:       int  = 0,
    has_salary:       bool = False,
    limit:            int  = 20,
    offset:           int  = 0,
    tier:             str  = "free",   # kept for API compat — gate disabled below
) -> Dict[str, Any]:
    """
    Query jobs with filters and pagination using raw sqlite3.

    Tier gate is intentionally disabled: all freshly scraped jobs are
    visible immediately.  Re-enable the commented block if you add a
    paid tier later.
    """
    conditions: List[str] = ["is_active = 1"]
    params:     List[Any] = []

    # ── Tier gate (disabled during development) ──────────────────────────────
    # if tier == "free":
    #     conditions.append("date_added < datetime('now', '-24 hours')")

    # ── Keyword search ────────────────────────────────────────────────────────
    kw = (keyword or "").strip()
    if kw:
        conditions.append(
            "(title LIKE ? OR company LIKE ? OR tags LIKE ? OR description_snippet LIKE ?)"
        )
        like = f"%{kw}%"
        params.extend([like, like, like, like])

    # ── Exact-match filters (skip "all" sentinel values) ─────────────────────
    _SKIP = {"", "all", "all cities", "all types", "all levels", "all sources"}

    def _exact(col: str, val: str) -> None:
        v = (val or "").strip()
        if v.lower() not in _SKIP:
            conditions.append(f"{col} = ?")
            params.append(v)

    _exact("city",             city)
    _exact("job_type",         job_type)
    _exact("experience_level", experience_level)
    _exact("source",           source)

    # ── Salary filters ────────────────────────────────────────────────────────
    if salary_min and salary_min > 0:
        conditions.append("salary_min >= ?")
        params.append(salary_min)

    if has_salary:
        conditions.append("(salary_min IS NOT NULL AND salary_min > 0)")

    # ── Build and execute ─────────────────────────────────────────────────────
    where   = " AND ".join(conditions)
    conn    = _raw_conn()

    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY date_added DESC, id DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    finally:
        conn.close()

    jobs = []
    for row in rows:
        d = dict(row)
        try:
            d["tags"] = json.loads(d.get("tags") or "[]")
        except Exception:
            d["tags"] = []
        jobs.append(d)

    print(f"[get_jobs] total={total}  returning={len(jobs)}  offset={offset}  kw={kw!r}")
    return {"jobs": jobs, "total": total, "count": len(jobs)}


def get_stats() -> Dict[str, Any]:
    """Return counts grouped by source, city, job_type, experience_level + hot companies."""
    conn = _raw_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE is_active = 1"
        ).fetchone()[0]

        def _group(col: str) -> Dict[str, int]:
            rows = conn.execute(
                f"SELECT {col}, COUNT(*) AS n FROM jobs "
                f"WHERE is_active = 1 AND {col} IS NOT NULL AND {col} != '' "
                f"GROUP BY {col} ORDER BY n DESC"
            ).fetchall()
            return {r[0]: r[1] for r in rows}

        hot = conn.execute(
            "SELECT company, COUNT(*) AS cnt FROM jobs "
            "WHERE is_active = 1 GROUP BY company HAVING cnt >= 5 ORDER BY cnt DESC"
        ).fetchall()

        return {
            "total":         total,
            "by_source":     _group("source"),
            "by_city":       _group("city"),
            "by_job_type":   _group("job_type"),
            "by_experience": _group("experience_level"),
            "hot_companies": [r[0] for r in hot],
        }
    finally:
        conn.close()


def get_all_jobs_for_export() -> List[Dict[str, Any]]:
    """Return all active jobs as a list of dicts for CSV export."""
    conn = _raw_conn()
    try:
        rows = conn.execute(
            "SELECT title, company, city, salary_raw, job_type, experience_level, "
            "source, apply_link, date_posted, date_added "
            "FROM jobs WHERE is_active = 1 ORDER BY date_added DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def clear_old_jobs(days: int = 30) -> int:
    """Delete jobs added more than `days` days ago. Returns count deleted."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _session() as s:
        rows = s.execute(
            select(Job).where(Job.date_added < cutoff)
        ).scalars().all()
        count = len(rows)
        for row in rows:
            s.delete(row)
        s.commit()
    return count
