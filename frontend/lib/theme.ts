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
    llm_generated_scraper:  "#8b5cf6",
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
  llm_generated_scraper:  "LLM Generated",
  computer_use_agent:     "CUA Agent",
  none:                   "Failed",
};

export const strategyColors: Record<string, string> = colors.strategy;
