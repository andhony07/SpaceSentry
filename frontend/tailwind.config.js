/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Inter", "Segoe UI", "System UI", "-apple-system", "sans-serif"],
        sans: ["Inter", "Segoe UI", "System UI", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "ui-monospace", "monospace"],
      },
      colors: {
        // SpaceSentry brand accent (teal family) — used by components and
        // index.css @apply rules (btn-primary, focus rings, badges).
        sentry: {
          50: "#e3faf6",
          100: "#b9f2ea",
          200: "#8ce7dc",
          300: "#5bd7cb",
          400: "#33c1b6",
          500: "#0a8b80",
          600: "#087d74",
          700: "#0a6b63",
          800: "#0c5751",
          900: "#0a4240",
          950: "#062e2c",
        },
        navy: {
          50: "#0a0e1a",
          100: "#111827",
          200: "#1e293b",
          300: "#2a3e52",
          400: "#34495e",
          500: "#2c3e6b",
          600: "#1f2833",
          700: "#141a24",
          800: "#0d1320",
          900: "#050711",
        },
        cyan: {
          50: "#e0f7fa",
          100: "#b2d7d9",
          200: "#84b5bc",
          300: "#56949d",
          400: "#2d8c9f",
          500: "#0d8aa8",
          600: "#0a7d9c",
          700: "#08708e",
          800: "#06657e",
          900: "#035870",
        },
        surface: {
          0: "#12161f",
          1: "#1a1f2a",
          2: "#222634",
          3: "#2a2f3d",
        },
        border: "#3a4250",
        accent: "#64ffda",
        muted: "#8a9ba8",
      },
      borderRadius: {
        lg: "8px",
        md: "6px",
        sm: "4px",
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0,0,0,0.3)",
        card: "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
      },
    },
  },
  plugins: [],
};