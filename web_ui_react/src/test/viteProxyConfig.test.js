import { describe, expect, it, vi } from "vitest";
import { createSidarProxyConfig } from "../../vite.config.js";

describe("createSidarProxyConfig", () => {
  it("proxies websocket upgrades with origin rewriting enabled", () => {
    const proxy = createSidarProxyConfig("http://127.0.0.1:9999");

    expect(proxy["/ws"]).toEqual({
      target: "ws://127.0.0.1:9999",
      ws: true,
      changeOrigin: true,
      configure: expect.any(Function),
    });
  });

  it("forwards websocket subprotocol headers during proxy upgrades", () => {
    const proxy = createSidarProxyConfig("http://127.0.0.1:9999");
    const listeners = new Map();
    const proxyServer = {
      on: (eventName, listener) => listeners.set(eventName, listener),
    };

    proxy["/ws"].configure(proxyServer);

    const setHeader = vi.fn();
    listeners.get("proxyReqWs")?.(
      { setHeader },
      { headers: { "sec-websocket-protocol": "e2e-test-token" } },
    );

    expect(setHeader).toHaveBeenCalledWith("sec-websocket-protocol", "e2e-test-token");
  });
});
