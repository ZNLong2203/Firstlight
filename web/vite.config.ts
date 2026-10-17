import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// In development the API runs on :8000. FIRSTLIGHT_API points the dev server at another one, such as the
// demo, to work on the console with real data. In production Caddy routes /v1 to the API.
export default defineConfig(({ mode }) => {
  const api = loadEnv(mode, ".", "FIRSTLIGHT_").FIRSTLIGHT_API || "http://localhost:8000";
  const proxy = { target: api, changeOrigin: true };
  return {
    plugins: [react(), tailwindcss()],
    build: { chunkSizeWarningLimit: 600 }, // the chart chunk is ECharts, loaded on demand
    server: { proxy: { "/v1": proxy, "/healthz": proxy } },
  };
});
