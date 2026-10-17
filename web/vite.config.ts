import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000; in production Caddy routes /v1 to it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/v1": "http://localhost:8000", "/healthz": "http://localhost:8000" } },
});
