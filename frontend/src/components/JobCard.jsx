import { MapPin, Clock, ExternalLink, Flame } from "lucide-react";

// ── Color palette ─────────────────────────────────────────────────────────────

const AVATAR_COLORS = [
  { bg: "#1a1a2e", text: "#818cf8" },
  { bg: "#1a2a1a", text: "#4ade80" },
  { bg: "#2a1a1a", text: "#f87171" },
  { bg: "#1a2a2a", text: "#22d3ee" },
  { bg: "#2a2a1a", text: "#facc15" },
  { bg: "#2a1a2a", text: "#c084fc" },
  { bg: "#1a1a2a", text: "#60a5fa" },
  { bg: "#2a1a20", text: "#fb923c" },
];

const SOURCE_COLORS = {
  Lever:        { bg: "#1e1030", text: "#a78bfa" },
  Greenhouse:   { bg: "#0e2818", text: "#4ade80" },
  Adzuna:       { bg: "#101828", text: "#60a5fa" },
  FreeJobAlert: { bg: "#281808", text: "#fb923c" },
  Hasjob:       { bg: "#282008", text: "#facc15" },
  Arbeitnow:    { bg: "#081c20", text: "#22d3ee" },
  Remotive:     { bg: "#0c2020", text: "#2dd4bf" },
  Wellfound:    { bg: "#201408", text: "#fb923c" },
  Cutshort:     { bg: "#200818", text: "#f472b6" },
  Instahyre:    { bg: "#1a0a28", text: "#c084fc" },
};

const TYPE_COLORS = {
  "Full Time":  { bg: "#181820", text: "#9090a8" },
  "Internship": { bg: "#0e1e30", text: "#60a5fa" },
  "Contract":   { bg: "#281e08", text: "#fbbf24" },
  "Remote":     { bg: "#081e1e", text: "#22d3ee" },
  "Government": { bg: "#281008", text: "#fb923c" },
};

const EXP_COLORS = {
  "Fresher":       { bg: "#122010", text: "#4ade80" },
  "Junior":        { bg: "#0e1c28", text: "#60a5fa" },
  "Mid":           { bg: "#14122a", text: "#a78bfa" },
  "Senior":        { bg: "#280e10", text: "#f87171" },
  "Not Specified": null,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function getAvatarColor(name) {
  let h = 0;
  for (const c of name || "") h = (h * 31 + c.charCodeAt(0)) & 0xff;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function formatSalary(min, max) {
  if (!min && !max) return null;
  const fmt = n => n >= 100_000 ? `₹${(n / 100_000).toFixed(0)}L` : `₹${(n / 1000).toFixed(0)}K`;
  if (min && max && min !== max) return `${fmt(min)} – ${fmt(max)}/yr`;
  return `${fmt(min || max)}/yr`;
}

function timeAgo(iso) {
  if (!iso) return "Recently";
  const d    = Date.now() - new Date(iso).getTime();
  if (isNaN(d) || d < 0) return "Recently";
  const mins = Math.floor(d / 60_000);
  const hrs  = Math.floor(d / 3_600_000);
  const days = Math.floor(d / 86_400_000);
  if (mins < 60)  return `${mins}m ago`;
  if (hrs  < 24)  return `${hrs}h ago`;
  if (days === 1) return "Yesterday";
  if (days < 7)   return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

function Badge({ label, colors, style: extra }) {
  if (!label || !colors) return null;
  return (
    <span style={{
      padding: "2px 9px", borderRadius: "999px", fontSize: "11px",
      fontWeight: 600, background: colors.bg, color: colors.text,
      letterSpacing: "0.02em", ...extra,
    }}>
      {label}
    </span>
  );
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function JobCard({ job, hotCompanies }) {
  if (!job) return null;

  const title    = job.title    || "Untitled Position";
  const company  = job.company  || "Unknown Company";
  const location = job.city     || job.location || "India";
  const salary   = formatSalary(job.salary_min, job.salary_max) || job.salary_raw || null;
  const tags     = Array.isArray(job.tags) ? job.tags : [];
  const applyUrl = job.apply_link || job.source_url || null;

  const avatarClr = getAvatarColor(company);
  const srcClr    = SOURCE_COLORS[job.source];
  const typeClr   = TYPE_COLORS[job.job_type];
  const expClr    = EXP_COLORS[job.experience_level] ?? null;

  const isNew  = job.date_added &&
    (Date.now() - new Date(job.date_added).getTime()) < 86_400_000;
  const isHot  = hotCompanies instanceof Set
    ? hotCompanies.has(company)
    : false;

  return (
    <div
      className="fade-up"
      style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: "12px", padding: "16px 18px",
        transition: "border-color 0.15s, box-shadow 0.15s",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = "var(--accent-border)";
        e.currentTarget.style.boxShadow   = "0 0 0 1px var(--accent-dim)";
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = "var(--border)";
        e.currentTarget.style.boxShadow   = "none";
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>

        {/* Company avatar */}
        <div style={{
          flexShrink: 0, width: 40, height: 40, borderRadius: "10px",
          background: avatarClr.bg, color: avatarClr.text,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: "16px", fontWeight: 700,
        }}>
          {(company[0] || "?").toUpperCase()}
        </div>

        {/* Title + company */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "7px", flexWrap: "wrap" }}>
            <h3 style={{
              margin: 0, fontSize: "14px", fontWeight: 600, color: "var(--text)",
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
              maxWidth: "380px",
            }}>
              {title}
            </h3>
            {isNew && (
              <span style={{
                padding: "1px 7px", borderRadius: "999px", fontSize: "10px",
                fontWeight: 700, background: "var(--accent)", color: "#0c0c0f",
                letterSpacing: "0.05em",
              }}>NEW</span>
            )}
            {isHot && (
              <span style={{
                display: "flex", alignItems: "center", gap: "2px",
                padding: "1px 7px", borderRadius: "999px", fontSize: "10px",
                fontWeight: 700, background: "#2a1008", color: "#fb923c",
              }}>
                <Flame size={9} /> Hot
              </span>
            )}
          </div>
          <p style={{ margin: "2px 0 0", fontSize: "12px", color: "var(--muted)" }}>
            {company} &nbsp;·&nbsp;
            <span style={{ display: "inline-flex", alignItems: "center", gap: "3px" }}>
              <MapPin size={10} /> {location}
            </span>
          </p>
        </div>

        {/* Apply button */}
        {applyUrl ? (
          <a
            href={applyUrl} target="_blank" rel="noopener noreferrer"
            style={{
              flexShrink: 0, display: "flex", alignItems: "center", gap: "4px",
              padding: "7px 14px", borderRadius: "8px", fontSize: "12px",
              fontWeight: 600, background: "var(--accent)", color: "#0c0c0f",
              textDecoration: "none", whiteSpace: "nowrap",
            }}
            onMouseEnter={e => (e.currentTarget.style.opacity = "0.85")}
            onMouseLeave={e => (e.currentTarget.style.opacity = "1")}
          >
            Apply <ExternalLink size={11} />
          </a>
        ) : (
          <span style={{
            flexShrink: 0, padding: "7px 14px", borderRadius: "8px",
            fontSize: "12px", fontWeight: 600,
            background: "var(--surface-2)", color: "var(--muted)",
          }}>
            No link
          </span>
        )}
      </div>

      {/* Divider */}
      <div style={{ height: "1px", background: "var(--border)", margin: "12px 0" }} />

      {/* Salary + time */}
      <div style={{
        display: "flex", alignItems: "center", gap: "16px",
        fontSize: "12px", flexWrap: "wrap",
      }}>
        {salary ? (
          <span style={{
            display: "flex", alignItems: "center", gap: "4px",
            color: "var(--green)", fontWeight: 600,
          }}>
            💰 {salary}
          </span>
        ) : (
          <span style={{ color: "var(--muted)", fontStyle: "italic" }}>
            💰 Salary not disclosed
          </span>
        )}
        <span style={{
          display: "flex", alignItems: "center", gap: "4px", color: "var(--muted)",
        }}>
          <Clock size={11} /> {timeAgo(job.date_added)}
        </span>
      </div>

      {/* Badges + tags */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "5px", marginTop: "10px" }}>
        <Badge label={job.source}         colors={srcClr} />
        <Badge label={job.job_type}       colors={typeClr} />
        {expClr && <Badge label={job.experience_level} colors={expClr} />}
        {tags.slice(0, 4).map(tag => (
          <span key={tag} style={{
            padding: "2px 9px", borderRadius: "999px", fontSize: "11px",
            background: "var(--tag-bg)", color: "var(--muted)",
          }}>
            {tag}
          </span>
        ))}
      </div>

      {/* Snippet */}
      {job.description_snippet && (
        <p style={{
          margin: "10px 0 0", fontSize: "12px", color: "var(--muted)",
          lineHeight: 1.65,
          display: "-webkit-box", WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical", overflow: "hidden",
        }}>
          {job.description_snippet}
        </p>
      )}
    </div>
  );
}
