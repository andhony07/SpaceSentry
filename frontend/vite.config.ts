/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// SpaceSentry frontend. The backend is a local FastAPI server; the API base
// URL is documented in .env.example (VITE_SPACESSENTRY_API_URL) and defaults
// to the loopback FastAPI dev port. The app never talks to any other server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    css: false,
  },
});
