import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  const sidarBackendUrl = process.env.SIDAR_BACKEND_URL || "http://127.0.0.1:7860";
  const sidarWebSocketUrl = sidarBackendUrl.replace(/^http/, "ws");

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "react-router-dom": path.resolve(__dirname, "src/lib/routerShim.jsx"),
      },
    },
    server: {
      // Geliştirme sırasında FastAPI backend'e proxy — CORS sorununu önler
      proxy: {
        "/api": { target: sidarBackendUrl, changeOrigin: true },
        "/ws": { target: sidarWebSocketUrl, ws: true },
        "/admin": { target: sidarBackendUrl, changeOrigin: true },
        "/sessions": { target: sidarBackendUrl, changeOrigin: true },
        "/metrics": { target: sidarBackendUrl, changeOrigin: true },
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
      include: ["src/**/*.{test,spec}.{js,jsx}"],
      exclude: ["e2e/**", "dist/**", "node_modules/**"],
      coverage: {
        provider: "v8",
        reporter: [["text", { skipFull: false }], "text-summary", "html", "lcov"],
        skipFull: false,
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
  };
});
