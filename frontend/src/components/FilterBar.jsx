const CITIES = [
  { id: "",           label: "🌐 All Cities"  },
  { id: "Bangalore",  label: "🏙️ Bangalore"   },
  { id: "Mumbai",     label: "🌆 Mumbai"       },
  { id: "Delhi",      label: "🏛️ Delhi NCR"   },
  { id: "Hyderabad",  label: "🌇 Hyderabad"   },
  { id: "Chennai",    label: "🌃 Chennai"      },
  { id: "Pune",       label: "🌉 Pune"         },
  { id: "Remote",     label: "💻 Remote"       },
  { id: "__GOVT__",   label: "🏛️ Govt Jobs", isGovt: true },
];

const JOB_TYPES = [
  "All Types", "Full Time", "Internship", "Contract", "Remote",
];

const EXPERIENCES = [
  { label: "All Levels",       value: "" },
  { label: "Fresher (0–1yr)",  value: "Fresher" },
  { label: "Junior (1–3yr)",   value: "Junior"  },
  { label: "Mid (3–6yr)",      value: "Mid"     },
  { label: "Senior (6yr+)",    value: "Senior"  },
];

const SOURCES = [
  "All Sources", "Adzuna", "Lever", "Greenhouse",
  "FreeJobAlert", "Hasjob", "Arbeitnow", "Remotive",
  "Wellfound", "Cutshort",
];

const SALARY_OPTS = [
  { label: "Any Salary", value: 0 },
  { label: "3+ LPA",     value: 300_000  },
  { label: "5+ LPA",     value: 500_000  },
  { label: "8+ LPA",     value: 800_000  },
  { label: "12+ LPA",    value: 1_200_000 },
  { label: "20+ LPA",    value: 2_000_000 },
];

const pill = (active) => ({
  flexShrink: 0, padding: "6px 13px", borderRadius: "999px",
  fontSize: "12px", fontWeight: 500, cursor: "pointer",
  whiteSpace: "nowrap", transition: "all 0.15s",
  border: active ? "1px solid var(--accent)"          : "1px solid var(--border)",
  background: active ? "var(--accent)"                : "var(--surface)",
  color:       active ? "#0c0c0f"                     : "var(--muted)",
});

const sel = {
  padding: "7px 11px", borderRadius: "8px", fontSize: "13px",
  border: "1px solid var(--border)", background: "var(--surface)",
  color: "var(--text)", cursor: "pointer", outline: "none",
  appearance: "none", WebkitAppearance: "none",
  paddingRight: "28px",
};

function SelWrap({ value, onChange, options }) {
  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={sel}
        onFocus={e  => (e.target.style.borderColor = "var(--accent-border)")}
        onBlur={e   => (e.target.style.borderColor = "var(--border)")}
      >
        {options.map(o => (
          <option key={o.value ?? o} value={o.value ?? o}>
            {o.label ?? o}
          </option>
        ))}
      </select>
      <span style={{
        position: "absolute", right: 8, top: "50%",
        transform: "translateY(-50%)", pointerEvents: "none",
        color: "var(--muted)", fontSize: "10px",
      }}>▾</span>
    </div>
  );
}

export default function FilterBar({ filters, onChange, stats }) {
  const cityCounts = stats?.by_city || {};
  const isGovtMode = filters.source === "FreeJobAlert";

  function handleCity(c) {
    if (c.isGovt) {
      // Toggle govt mode: set/clear source filter
      onChange({
        ...filters,
        city:   "",
        source: isGovtMode ? "" : "FreeJobAlert",
      });
    } else {
      onChange({ ...filters, city: c.id, source: isGovtMode ? "" : filters.source });
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>

      {/* City pills */}
      <div style={{ display: "flex", gap: "7px", overflowX: "auto", paddingBottom: "2px" }}>
        {CITIES.map(c => {
          const active = c.isGovt ? isGovtMode : filters.city === c.id;
          const count  = !c.isGovt && c.id ? cityCounts[c.id] : null;
          return (
            <button key={c.id} onClick={() => handleCity(c)} style={pill(active)}>
              {c.label}{count != null ? ` (${count})` : ""}
            </button>
          );
        })}
      </div>

      {/* Dropdowns */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>

        <SelWrap
          value={filters.jobType || "All Types"}
          onChange={v => onChange({ ...filters, jobType: v === "All Types" ? "" : v })}
          options={JOB_TYPES}
        />

        <SelWrap
          value={filters.experience || ""}
          onChange={v => onChange({ ...filters, experience: v })}
          options={EXPERIENCES}
        />

        <SelWrap
          value={isGovtMode ? "FreeJobAlert" : (filters.source || "All Sources")}
          onChange={v => onChange({ ...filters, source: v === "All Sources" ? "" : v })}
          options={SOURCES}
        />

        <SelWrap
          value={filters.salaryMin ?? 0}
          onChange={v => onChange({ ...filters, salaryMin: Number(v) })}
          options={SALARY_OPTS}
        />

        {/* Has salary toggle */}
        <button
          onClick={() => onChange({ ...filters, hasSalary: !filters.hasSalary })}
          style={pill(filters.hasSalary)}
        >
          ₹ Salary info
        </button>
      </div>
    </div>
  );
}
