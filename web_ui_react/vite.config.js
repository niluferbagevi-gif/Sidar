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
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }

          const modulePath = id.split("node_modules/")[1];
          if (!modulePath) {
            return "vendor";
          }

          const parts = modulePath.split("/");
          if (parts[0]?.startsWith("@") && parts.length > 1) {
            return `${parts[0]}/${parts[1]}`;
          }

          return parts[0] || "vendor";
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
    css: false,
    globals: true,
    pool: "forks",
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["src/**/*.{js,jsx}"],
      exclude: [
        "src/test/setup.js",
        "src/main.jsx",
        "src/**/*.test.{js,jsx}",
        "src/test/**",
      ],
      thresholds: {
        lines: 90,
        functions: 90,
        branches: 90,
        statements: 90,
      },
    },
  },
});
