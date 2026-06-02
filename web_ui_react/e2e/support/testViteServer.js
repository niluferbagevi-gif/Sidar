import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { createSidarProxyConfig } from "../../vite.config.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_UI_ROOT = path.resolve(__dirname, "../..");
const VITE_CONFIG_FILE = path.join(WEB_UI_ROOT, "vite.config.js");

const READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 100;

async function reserveAvailablePort() {
  const probe = net.createServer();
  await new Promise((resolve, reject) => {
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", resolve);
  });
  const address = probe.address();
  if (!address || typeof address === "string") {
    await new Promise((resolve) => probe.close(resolve));
    throw new Error("Vite E2E sunucusu için boş port ayrılamadı.");
  }
  await new Promise((resolve, reject) => {
    probe.close((error) => (error ? reject(error) : resolve()));
  });
  return address.port;
}

async function fetchReadyResponse(url, validateBody = () => true) {
  const response = await fetch(url);
  if (!response.ok) return false;
  return validateBody(await response.text());
}

async function waitUntilReady(url) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const [indexReady, chatRouteReady, entryReady] = await Promise.all([
        fetchReadyResponse(url, (html) => html.includes('id="root"')),
        fetchReadyResponse(`${url}/chat`, (html) => html.includes('id="root"')),
        fetchReadyResponse(`${url}/src/main.jsx`),
      ]);
      if (indexReady && chatRouteReady && entryReady) return;
    } catch {
      // Vite may still be binding, transforming the SPA entry, or optimizing dependencies.
    }
    await new Promise((resolve) => setTimeout(resolve, READY_POLL_MS));
  }
  throw new Error(`Vite E2E sunucusu hazır olmadı: ${url}`);
}

export async function startTestViteServer({ backendUrl }) {
  const port = await reserveAvailablePort();
  let server;
  try {
    server = await createServer({
      root: WEB_UI_ROOT,
      configFile: VITE_CONFIG_FILE,
      server: {
        host: "127.0.0.1",
        port,
        strictPort: true,
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
