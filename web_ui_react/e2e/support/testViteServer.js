import { createServer } from "vite";
import { createSidarProxyConfig } from "../../vite.config.js";

const READY_TIMEOUT_MS = 15_000;
const READY_POLL_MS = 100;

async function waitUntilReady(url) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Vite may still be binding or optimizing dependencies.
    }
    await new Promise((resolve) => setTimeout(resolve, READY_POLL_MS));
  }
  throw new Error(`Vite E2E sunucusu hazır olmadı: ${url}`);
}

export async function startTestViteServer({ backendUrl }) {
  let server;
  try {
    server = await createServer({
      server: {
        host: "0.0.0.0",
        port: 15_173,
        strictPort: false,
        proxy: createSidarProxyConfig(backendUrl),
      },
    });
    await server.listen();
  } catch (error) {
    await server?.close();
    throw error;
  }

  const address = server.httpServer?.address();
  if (!address || typeof address === "string") {
    await server.close();
    throw new Error("Vite E2E sunucusu dinleme portunu döndürmedi.");
  }

  const url = `http://127.0.0.1:${address.port}`;
  try {
    await waitUntilReady(url);
  } catch (error) {
    await server.close();
    throw error;
  }
  return {
    port: address.port,
    url,
    async close() {
      await server.close();
    },
  };
}
