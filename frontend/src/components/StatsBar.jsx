import { Loader2, RefreshCw } from "lucide-react";

function timeAgo(iso) {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60)    return "just now";
  if (s < 3600)  return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function StatsBar({ total, showing, stats, scrapeStatus, onScrapeNow }) {
  const isRunning   = scrapeStatus?.running;
  const lastRun     = scrapeStatus?.last_run_at;
  const city        = stats?.by_city   || {};
  const blr         = city["Bangalore"] || 0;
  const remote      = city["Remote"]    || 0;
  const govt        = (stats?.by_source || {})["FreeJobAlert"] || 0;

  return (
    <div style={{
      display: "flex", flexWrap: "wrap", alignItems: "center",
      gap: "8px", padding: "10px 14px",
      background: "var(--surface)", borderLeft: "3px solid var(--accent)",
      borderRadius: "0 10px 10px 0", fontSize: "12px",
    }}>
      {/* Counts */}
      <span style={{ color: "var(--text)", fontWeight: 600 }}>
        Showing <span style={{ color: "var(--accent)" }}>{showing}</span>{" "}
        of <span style={{ color: "var(--accent)" }}>{total?.toLocaleString()}</span> jobs
      </span>

      <span style={{ color: "var(--border)" }}>•</span>

      {blr > 0 && (
        <span style={{ color: "var(--muted)" }}>🏙️ Bangalore {blr}</span>
      )}
      {remote > 0 && (
        <>
          <span style={{ color: "var(--border)" }}>•</span>
          <span style={{ color: "var(--muted)" }}>💻 Remote {remote}</span>
        </>
      )}
      {govt > 0 && (
        <>
          <span style={{ color: "var(--border)" }}>•</span>
          <span style={{ color: "var(--muted)" }}>🏛️ Govt {govt}</span>
        </>
      )}

      <div style={{ flex: 1 }} />

      {/* Updated time */}
      <span style={{ color: "var(--muted)" }}>
        {isRunning ? "Scraping…" : `Updated ${timeAgo(lastRun)}`}
      </span>

      {/* Scrape button */}
      <button
        onClick={onScrapeNow}
        disabled={isRunning}
        style={{
          display: "flex", alignItems: "center", gap: "5px",
          padding: "5px 11px", borderRadius: "7px", fontSize: "12px",
          fontWeight: 600, border: "none", cursor: isRunning ? "not-allowed" : "pointer",
          background: isRunning ? "var(--surface-2)" : "var(--accent)",
          color:      isRunning ? "var(--muted)"     : "#0c0c0f",
          transition: "opacity 0.15s",
        }}
        onMouseEnter={e => !isRunning && (e.currentTarget.style.opacity = "0.85")}
        onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
      >
        {isRunning
          ? <><Loader2 size={11} className="spin" /> Scraping…</>
          : <><RefreshCw size={11} /> Scrape ⚡</>
        }
      </button>
    </div>
  );
}
