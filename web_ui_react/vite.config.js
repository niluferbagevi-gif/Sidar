import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "react-router-dom": path.resolve(__dirname, "src/lib/routerShim.jsx"),
    },
  },
  server: {
    // Geliştirme sırasında FastAPI backend'e proxy — CORS sorununu önler
    proxy: {
      "/api": { target: "http://localhost:7860", changeOrigin: true },
      "/ws": { target: "ws://localhost:7860", ws: true },
      "/admin": { target: "http://localhost:7860", changeOrigin: true },
      "/sessions": { target: "http://localhost:7860", changeOrigin: true },
      "/metrics": { target: "http://localhost:7860", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    css: false,
    globals: true,
  },
});