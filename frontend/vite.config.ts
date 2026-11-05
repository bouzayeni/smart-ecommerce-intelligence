import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API runs on :8000; proxying /api keeps the browser on one origin, so
// the API's CORS allowlist only needs the dev server origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: false } },
  },
  build: { sourcemap: true, chunkSizeWarningLimit: 900 },
});
