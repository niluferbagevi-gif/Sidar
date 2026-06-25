import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export function createSidarProxyConfig(
  backendUrl = process.env.SIDAR_BACKEND_URL || "http://127.0.0.1:7860",
) {
  const webSocketUrl = backendUrl.replace(/^http/, "ws");
  return {
    "/api": { target: backendUrl, changeOrigin: true },
    "/ws": {
      target: webSocketUrl,
      ws: true,
      changeOrigin: true,
      configure: (proxy) => {
        proxy.on("proxyReqWs", (proxyReq, req) => {
          const subprotocol = req.headers["sec-websocket-protocol"];
          if (subprotocol) {
            proxyReq.setHeader("sec-websocket-protocol", subprotocol);
          }
        });
      },
    },
    "/admin": { target: backendUrl, changeOrigin: true },
    "/sessions": { target: backendUrl, changeOrigin: true },
    "/metrics": { target: backendUrl, changeOrigin: true },
  };
}

export default defineConfig(() => {
  return {
    plugins: [react()],
    resolve: {
      alias: {
        "react-router-dom": path.resolve(__dirname, "src/lib/routerShim.jsx"),
      },
    },
    optimizeDeps: {
      entries: [
        "index.html",
        "src/main.jsx",
        "src/App.jsx",
        "src/components/*.jsx",
        "!src/**/*.test.{js,jsx}",
        "!e2e/**",
      ],
    },
    server: {
      // Geliştirme sırasında FastAPI backend'e proxy — CORS sorununu önler.
      proxy: createSidarProxyConfig(),
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
          "src/components/PanelErrorBoundary.jsx", // minimal fallback boundary; behavior is covered by dedicated tests
          "src/lib/routerShim.jsx", // shim behavior is covered by dedicated router tests
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