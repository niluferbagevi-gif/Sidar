import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Geliştirme sırasında FastAPI backend'e proxy — CORS sorununu önler
    proxy: {
      "/api":       { target: "http://localhost:7860", changeOrigin: true },
      "/ws":        { target: "ws://localhost:7860",   ws: true },
      "/admin":     { target: "http://localhost:7860", changeOrigin: true },
      "/sessions":  { target: "http://localhost:7860", changeOrigin: true },
      "/metrics":   { target: "http://localhost:7860", changeOrigin: true },
    },
  },
  build: {
    outDir: "../web_ui_built",   // `npm run build` çıktısı FastAPI'nin mount ettiği dizine gider
    emptyOutDir: true,
  },
});
