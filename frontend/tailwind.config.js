/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Primary brand = indigo so btn-primary, brand-600, brand-700, etc.
        // all resolve to the same indigo palette used everywhere in the app.
        brand: {
          50:  "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          500: "#6366f1",
          600: "#4f46e5",
          700: "#4338ca",
          900: "#312e81",
        },
        // Explicit indigo aliases matching brand (eliminates the indigo-650 trap —
        // there is no 650 in Tailwind; we add it as an alias to 600).
        indigo: {
          50:  "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#6366f1",
          600: "#4f46e5",
          // 650 is a common mistake — alias to 600 so it resolves instead of silently failing
          650: "#4f46e5",
          700: "#4338ca",
          800: "#3730a3",
          900: "#312e81",
          950: "#1e1b4b",
        },
        // Slate with intermediate shades to prevent silent no-ops
        slate: {
          50:   "#f8fafc",
          100:  "#f1f5f9",
          150:  "#eaeff5",
          200:  "#e2e8f0",
          250:  "#d5dde8",
          300:  "#cbd5e1",
          350:  "#b0bec5",
          400:  "#94a3b8",
          450:  "#7c8fa6",
          500:  "#64748b",
          550:  "#526075",
          600:  "#475569",
          650:  "#3d4a5c",
          700:  "#334155",
          800:  "#1e293b",
          850:  "#172033",
          900:  "#0f172a",
          950:  "#020617",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      animation: {
        "fade-in":    "fadeIn 0.2s ease-out",
        "slide-down": "slideDown 0.2s ease-out",
      },
      keyframes: {
        fadeIn:    { from: { opacity: "0" }, to: { opacity: "1" } },
        slideDown: { from: { opacity: "0", transform: "translateY(-8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};
