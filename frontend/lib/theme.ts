/**
 * Design tokens — single source of truth for all visual constants.
 * Import in components for type-safe access to the design system.
 */

export const colors = {
  brand:   { 50: "#eef2ff", 100: "#e0e7ff", 500: "#6366f1", 600: "#4f46e5", 700: "#4338ca", 900: "#312e81" },
  success: "#10b981",
  warning: "#f59e0b",
  error:   "#ef4444",
  info:    "#3b82f6",

  strategy: {
    manual_scraper:         "#3b82f6",
    existing_scraper:       "#6366f1",
    deterministic_template: "#10b981",
    adaptive_universal:     "#0ea5e9",
    llm_generated_scraper:  "#8b5cf6",
    learned_route:          "#14b8a6",
    computer_use_agent:     "#ec4899",
    none:                   "#f43f5e",
  },
} as const;

export const radius = {
  sm: "6px", base: "10px", lg: "14px", xl: "18px", "2xl": "24px",
} as const;

export const shadow = {
  sm: "0 1px 2px 0 rgb(0 0 0/0.05)",
  base: "0 1px 3px 0 rgb(0 0 0/0.07),0 1px 2px -1px rgb(0 0 0/0.05)",
  md: "0 4px 6px -1px rgb(0 0 0/0.07),0 2px 4px -2px rgb(0 0 0/0.05)",
  lg: "0 10px 15px -3px rgb(0 0 0/0.08),0 4px 6px -4px rgb(0 0 0/0.04)",
} as const;

export const strategyLabels: Record<string, string> = {
  manual_scraper:         "Manual",
  existing_scraper:       "Cached",
  deterministic_template: "Deterministic",
  adaptive_universal:     "Universal Adaptive",
  llm_generated_scraper:  "LLM Generated",
  learned_route:          "Learned Route",
  computer_use_agent:     "CUA Agent",
  none:                   "Failed",
};

export const strategyColors: Record<string, string> = colors.strategy;

// ── Outcome buckets (honest-reporting) ──────────────────────────────────────
// Mirrors backend phase3_integration/outcomes.py. Ordered best → needs-attention.
export const OUTCOME_ORDER = [
  "success", "no_documents", "expired", "unreachable",
  "auth_gated", "captcha", "blocked", "error",
] as const;

export const outcomeColors: Record<string, string> = {
  success:      "#10b981",
  no_documents: "#94a3b8",
  expired:      "#f59e0b",
  unreachable:  "#0ea5e9",
  auth_gated:   "#a855f7",
  captcha:      "#ec4899",
  blocked:      "#ef4444",
  error:        "#64748b",
};

export const outcomeLabels: Record<string, string> = {
  success:      "Succeeded",
  auth_gated:   "Login / registration",
  captcha:      "CAPTCHA / bot block",
  expired:      "Expired or not found",
  unreachable:  "Unreachable",
  no_documents: "No documents",
  blocked:      "Blocked (security)",
  error:        "Error",
};

// Buckets a human can resolve by stepping in.
export const NEEDS_MANUAL_BUCKETS = new Set(["auth_gated", "captcha"]);
