import { useEffect, useRef } from "react";
import { Search, X } from "lucide-react";

export default function SearchBar({ value, onChange }) {
  const ref = useRef(null);

  // Press "/" anywhere to focus
  useEffect(() => {
    const handler = (e) => {
      if (
        e.key === "/" &&
        document.activeElement?.tagName !== "INPUT" &&
        document.activeElement?.tagName !== "TEXTAREA"
      ) {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  return (
    <div style={{ position: "relative" }}>
      <Search
        size={17}
        style={{
          position: "absolute", left: 14, top: "50%",
          transform: "translateY(-50%)",
          color: "var(--muted)", pointerEvents: "none",
        }}
      />

      <input
        ref={ref}
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="Search jobs, skills, companies… (press /)"
        style={{
          width: "100%", padding: "13px 40px 13px 42px",
          borderRadius: "12px",
          border: "1px solid var(--border)",
          background: "var(--surface)",
          color: "var(--text)", fontSize: "14px",
          outline: "none", transition: "border-color 0.15s, box-shadow 0.15s",
        }}
        onFocus={e => {
          e.target.style.borderColor = "var(--accent)";
          e.target.style.boxShadow  = "0 0 0 2px var(--accent-dim)";
        }}
        onBlur={e => {
          e.target.style.borderColor = "var(--border)";
          e.target.style.boxShadow   = "none";
        }}
      />

      {value && (
        <button
          onClick={() => onChange("")}
          style={{
            position: "absolute", right: 12, top: "50%",
            transform: "translateY(-50%)",
            background: "none", border: "none", cursor: "pointer",
            color: "var(--muted)", padding: "2px",
            display: "flex", alignItems: "center",
            borderRadius: "4px",
          }}
          onMouseEnter={e => (e.currentTarget.style.color = "var(--text)")}
          onMouseLeave={e => (e.currentTarget.style.color = "var(--muted)")}
        >
          <X size={15} />
        </button>
      )}
    </div>
  );
}
