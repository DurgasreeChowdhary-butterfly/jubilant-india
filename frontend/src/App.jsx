import { useCallback, useEffect, useRef, useState } from "react";
import FilterBar  from "./components/FilterBar";
import JobCard    from "./components/JobCard";
import SearchBar  from "./components/SearchBar";
import StatsBar   from "./components/StatsBar";

const API = import.meta.env.VITE_API_URL || "http://localhost:8001";
const PER_PAGE = 20;

const EMPTY = {
  keyword: "", city: "", jobType: "", experience: "",
  source: "", salaryMin: 0, hasSalary: false,
};

function useDebounce(v, ms = 400) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

// ── Skeleton card ─────────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: "12px", padding: "16px 18px",
    }}>
      <div style={{ display: "flex", gap: "12px" }}>
        <div className="skeleton" style={{ width: 40, height: 40, borderRadius: "10px", flexShrink: 0 }} />
        <div style={{ flex: 1 }}>
          <div className="skeleton" style={{ height: 14, width: "55%", marginBottom: 8 }} />
          <div className="skeleton" style={{ height: 11, width: "35%" }} />
        </div>
        <div className="skeleton" style={{ width: 72, height: 32, borderRadius: 8 }} />
      </div>
      <div style={{ height: 1, background: "var(--border)", margin: "12px 0" }} />
      <div style={{ display: "flex", gap: 12 }}>
        <div className="skeleton" style={{ height: 11, width: 90 }} />
        <div className="skeleton" style={{ height: 11, width: 70 }} />
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        {[60, 70, 55, 50].map((w, i) => (
          <div key={i} className="skeleton" style={{ height: 18, width: w, borderRadius: 999 }} />
        ))}
      </div>
    </div>
  );
}

// ── Main app ──────────────────────────────────────────────────────────────────
export default function App() {
  const [filters,      setFilters]      = useState(EMPTY);
  const [jobs,         setJobs]         = useState([]);
  const [total,        setTotal]        = useState(0);
  const [page,         setPage]         = useState(0);
  const [loading,      setLoading]      = useState(true);
  const [loadingMore,  setLoadingMore]  = useState(false);
  const [stats,        setStats]        = useState(null);
  const [scrapeStatus, setScrapeStatus] = useState(null);
  const [hotSet,       setHotSet]       = useState(new Set());

  const abortRef = useRef(null);
  const debouncedKw = useDebounce(filters.keyword);

  // ── Fetch jobs ─────────────────────────────────────────────────────────────
  const fetchJobs = useCallback(async (f, pg = 0) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    pg === 0 ? setLoading(true) : setLoadingMore(true);

    const p = new URLSearchParams();
    const kw = (f.keyword || "").trim();
    if (kw)              p.append("keyword",          kw);
    if (f.city)          p.append("city",             f.city);
    if (f.jobType)       p.append("job_type",         f.jobType);
    if (f.experience)    p.append("experience_level", f.experience);
    if (f.source)        p.append("source",           f.source);
    if (f.salaryMin > 0) p.append("salary_min",       f.salaryMin);
    if (f.hasSalary)     p.append("has_salary",       "true");
    p.append("limit",  PER_PAGE);
    p.append("offset", pg * PER_PAGE);

    console.log("[fetchJobs]", `${API}/jobs?${p}`);
    try {
      const res  = await fetch(`${API}/jobs?${p}`, { signal: abortRef.current.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      console.log("[fetchJobs] total=", data.total, "count=", data.count);
      setTotal(data.total ?? 0);
      setPage(pg);
      setJobs(prev => pg === 0 ? (data.jobs || []) : [...prev, ...(data.jobs || [])]);
    } catch (err) {
      if (err.name !== "AbortError") console.error("[fetchJobs]", err);
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  // Initial load
  useEffect(() => { fetchJobs(EMPTY, 0); }, [fetchJobs]);

  // Re-fetch on filter change (using debounced keyword)
  useEffect(() => {
    fetchJobs({ ...filters, keyword: debouncedKw }, 0);
  }, [debouncedKw, filters.city, filters.jobType, filters.experience,
      filters.source, filters.salaryMin, filters.hasSalary, fetchJobs]);

  // ── Stats + scrape status poll ─────────────────────────────────────────────
  useEffect(() => {
    const poll = async () => {
      try {
        const [s, ss] = await Promise.all([
          fetch(`${API}/jobs/stats`).then(r => r.json()),
          fetch(`${API}/scrape/status`).then(r => r.json()),
        ]);
        setStats(s);
        setScrapeStatus(ss);
        setHotSet(new Set(s.hot_companies || []));
      } catch (_) {}
    };
    poll();
    const id = setInterval(poll, 15_000);
    return () => clearInterval(id);
  }, []);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const setF = (key, val) => setFilters(prev => ({ ...prev, [key]: val }));

  const handleScrapeNow = async () => {
    try {
      await fetch(`${API}/scrape`, { method: "POST" });
      setScrapeStatus(prev => ({ ...prev, running: true }));
    } catch (_) {}
  };

  const clearFilters = () => setFilters(EMPTY);

  const hasMore    = jobs.length < total;
  const hasFilters = Object.entries(filters).some(([k, v]) =>
    k !== "keyword" ? (Boolean(v) && v !== 0) : v.trim() !== ""
  );

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", background: "var(--bg)" }}>

      {/* ── STICKY HEADER ─────────────────────────────────────── */}
      <header style={{
        position: "sticky", top: 0, zIndex: 100,
        background: "rgba(20,20,24,0.88)",
        backdropFilter: "blur(18px)", WebkitBackdropFilter: "blur(18px)",
        borderBottom: "1px solid var(--border)",
      }}>
        <div style={{
          maxWidth: 960, margin: "0 auto", padding: "0 20px",
          height: 56, display: "flex", alignItems: "center", gap: 12,
        }}>
          {/* Logo */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 20 }}>🇮🇳</span>
            <span style={{ fontSize: 16, fontWeight: 800, color: "var(--text)", letterSpacing: "-0.02em" }}>
              Jubilant India
            </span>
            <span style={{
              padding: "1px 6px", borderRadius: 5, fontSize: 10, fontWeight: 700,
              background: "var(--accent-dim)", color: "var(--accent)",
              border: "1px solid var(--accent-border)",
            }}>BETA</span>
          </div>

          {/* Live count */}
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            marginLeft: "auto",
            fontSize: 12, color: "var(--muted)",
          }}>
            <span className="pulse" style={{
              width: 7, height: 7, borderRadius: "50%", background: "var(--green)",
              display: "inline-block",
            }} />
            <span>
              <strong style={{ color: "var(--text)" }}>
                {(stats?.total ?? total ?? 0).toLocaleString()}
              </strong>{" "}jobs live
            </span>
          </div>

          {/* Scrape button */}
          <button
            onClick={handleScrapeNow}
            disabled={scrapeStatus?.running}
            style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "6px 14px", borderRadius: 8, fontSize: 12, fontWeight: 600,
              border: "none", cursor: scrapeStatus?.running ? "not-allowed" : "pointer",
              background: scrapeStatus?.running ? "var(--surface-2)" : "var(--accent)",
              color:      scrapeStatus?.running ? "var(--muted)"     : "#0c0c0f",
            }}
          >
            {scrapeStatus?.running ? "⏳ Scraping…" : "⚡ Scrape Now"}
          </button>
        </div>
      </header>

      {/* ── HERO ──────────────────────────────────────────────── */}
      <div className="grid-bg" style={{ borderBottom: "1px solid var(--border)" }}>
        <div style={{
          maxWidth: 960, margin: "0 auto", padding: "48px 20px 36px",
          textAlign: "center",
        }}>
          <h1 style={{
            margin: "0 0 8px", fontWeight: 800, letterSpacing: "-0.03em",
            fontSize: "clamp(26px, 5vw, 44px)",
            background: "linear-gradient(135deg, var(--text) 30%, var(--accent) 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}>
            Find Your Next Job in India 🇮🇳
          </h1>
          <p style={{
            margin: "0 0 24px", color: "var(--muted)", fontSize: 14,
          }}>
            {(stats?.total ?? 0).toLocaleString()} live jobs from Adzuna, Lever, Greenhouse, FreeJobAlert & more
          </p>
          <div style={{ maxWidth: 600, margin: "0 auto" }}>
            <SearchBar
              value={filters.keyword}
              onChange={v => setF("keyword", v)}
            />
          </div>
        </div>
      </div>

      {/* ── MAIN CONTENT ──────────────────────────────────────── */}
      <main style={{ maxWidth: 960, margin: "0 auto", padding: "20px 20px 60px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          <FilterBar
            filters={filters}
            onChange={setFilters}
            stats={stats}
          />

          <StatsBar
            total={total}
            showing={jobs.length}
            stats={stats}
            scrapeStatus={scrapeStatus}
            onScrapeNow={handleScrapeNow}
          />

          {/* ── Skeleton loading ─────────────────────────────── */}
          {loading && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
            </div>
          )}

          {/* ── Empty state ───────────────────────────────────── */}
          {!loading && jobs.length === 0 && (
            <div style={{
              textAlign: "center", padding: "72px 20px",
              color: "var(--muted)",
            }}>
              <div style={{ fontSize: 52, marginBottom: 12 }}>🔍</div>
              <p style={{ margin: 0, fontWeight: 700, color: "var(--text)", fontSize: 16 }}>
                No jobs found
              </p>
              <p style={{ margin: "6px 0 20px", fontSize: 13 }}>
                Try adjusting your filters or search term
              </p>
              {hasFilters && (
                <button
                  onClick={clearFilters}
                  style={{
                    padding: "8px 20px", borderRadius: 8, fontSize: 13,
                    fontWeight: 600, border: "1px solid var(--border)",
                    background: "var(--surface)", color: "var(--text)",
                    cursor: "pointer",
                  }}
                >
                  Clear filters
                </button>
              )}
            </div>
          )}

          {/* ── Job list ──────────────────────────────────────── */}
          {!loading && jobs.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {jobs.map((job, i) => (
                <JobCard
                  key={job.id ?? i}
                  job={job}
                  hotCompanies={hotSet}
                />
              ))}
            </div>
          )}

          {/* ── Load more / end ───────────────────────────────── */}
          {!loading && jobs.length > 0 && (
            <div style={{ display: "flex", justifyContent: "center", paddingTop: 12 }}>
              {hasMore ? (
                <button
                  onClick={() => fetchJobs({ ...filters, keyword: debouncedKw }, page + 1)}
                  disabled={loadingMore}
                  style={{
                    padding: "10px 28px", borderRadius: 10, fontSize: 13,
                    fontWeight: 600, border: "1px solid var(--border)",
                    background: "var(--surface-2)", color: loadingMore ? "var(--muted)" : "var(--text)",
                    cursor: loadingMore ? "not-allowed" : "pointer", transition: "all 0.15s",
                  }}
                  onMouseEnter={e => !loadingMore && (e.currentTarget.style.borderColor = "var(--accent-border)")}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = "var(--border)")}
                >
                  {loadingMore
                    ? "Loading…"
                    : `Load more jobs  ·  ${(total - jobs.length).toLocaleString()} remaining`}
                </button>
              ) : (
                <p style={{ color: "var(--muted)", fontSize: 13, margin: 0 }}>
                  — You've seen all {total.toLocaleString()} jobs —
                </p>
              )}
            </div>
          )}
        </div>
      </main>

      {/* ── FOOTER ────────────────────────────────────────────── */}
      <footer style={{
        borderTop: "1px solid var(--border)", padding: "24px 20px",
        textAlign: "center", fontSize: 12, color: "var(--muted)",
      }}>
        <p style={{ margin: "0 0 8px" }}>
          Jubilant India — aggregating Indian job boards since 2024
        </p>
        <div style={{ display: "flex", justifyContent: "center", gap: 16 }}>
          {[
            ["API Docs", `${API}/docs`],
            ["Export CSV", `${API}/jobs/export`],
          ].map(([label, href]) => (
            <a key={label} href={href} target="_blank" rel="noopener noreferrer"
              style={{ color: "var(--muted)", textDecoration: "none" }}
              onMouseEnter={e => (e.currentTarget.style.color = "var(--accent)")}
              onMouseLeave={e => (e.currentTarget.style.color = "var(--muted)")}
            >
              {label}
            </a>
          ))}
        </div>
      </footer>
    </div>
  );
}
