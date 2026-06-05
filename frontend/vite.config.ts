import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig, type Plugin } from "vite";

const rootIndexFallback = (): Plugin => ({
  name: "parkpulse-root-index-fallback",
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      if (!req.url) {
        next();
        return;
      }

      const [pathname, query] = req.url.split("?", 2);
      if (pathname === "/") {
        req.url = `/index.html${query ? `?${query}` : ""}`;
      }

      next();
    });
  },
});

export default defineConfig({
  plugins: [rootIndexFallback(), react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 3003,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.VITE_PARKPULSE_API_PROXY ?? "http://127.0.0.1:8010",
        changeOrigin: true,
      },
      "/readyz": {
        target: process.env.VITE_PARKPULSE_API_PROXY ?? "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
});
