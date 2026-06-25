import { describe, expect, it } from "vitest";
import { createSidarProxyConfig } from "../../vite.config.js";

describe("createSidarProxyConfig", () => {
  it("proxies websocket upgrades with origin rewriting enabled", () => {
    const proxy = createSidarProxyConfig("http://127.0.0.1:9999");

    expect(proxy["/ws"]).toEqual({
      target: "ws://127.0.0.1:9999",
      ws: true,
      changeOrigin: true,
    });
  });
});
