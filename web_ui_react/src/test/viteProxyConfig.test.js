import { describe, expect, it } from "vitest";
import { createSidarManualChunks, createSidarProxyConfig } from "../../vite.config.js";

describe("createSidarProxyConfig", () => {
  it("proxies websocket upgrades with origin rewriting enabled", () => {
    const proxy = createSidarProxyConfig("http://127.0.0.1:9999");

    expect(proxy["/ws"]).toMatchObject({
      target: "ws://127.0.0.1:9999",
      ws: true,
      changeOrigin: true,
    });
    expect(proxy["/ws"].configure).toBeTypeOf("function");
  });
});

describe("createSidarManualChunks", () => {
  it("splits high-signal vendor chunks for bundle analysis and cacheability", () => {
    expect(createSidarManualChunks("/repo/node_modules/react-dom/client.js")).toBe("react-dom-client");
    expect(createSidarManualChunks("/repo/node_modules/react-dom/server.browser.js")).toBe("react-dom-server");
    expect(createSidarManualChunks("/repo/node_modules/highlight.js/lib/core.js")).toBe("highlight-js-core");
    expect(createSidarManualChunks("/repo/src/App.tsx")).toBeUndefined();
  });
});
