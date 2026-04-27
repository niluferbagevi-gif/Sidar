import http from "node:http";
import { WebSocketServer } from "ws";

export async function startMockSidarBackend({ port = 7860 } = {}) {
  const server = http.createServer((req, res) => {
    if (req.url === "/healthz") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }
    res.writeHead(404);
    res.end();
  });

  const wss = new WebSocketServer({ server, path: "/ws/chat" });

  wss.on("connection", (socket, req) => {
    const token = req.headers["sec-websocket-protocol"] || "";
    if (!String(token).trim()) {
      socket.close(4001, "missing token");
      return;
    }

    socket.send(JSON.stringify({ auth_ok: true }));

    socket.on("message", (raw) => {
      const text = String(raw || "");
      let payload = {};
      try {
        payload = JSON.parse(text);
      } catch {
        return;
      }

      if (payload.action === "join_room") {
        socket.send(JSON.stringify({
          type: "room_state",
          room_id: payload.room_id || "workspace:sidar",
          participants: [
            { user_id: "agent-1", display_name: "Agent 1" },
            { user_id: "ops-1", display_name: payload.display_name || "Operatör" },
          ],
          messages: [],
          telemetry: [],
        }));
        socket.send(JSON.stringify({
          type: "presence",
          participants: [
            { user_id: "agent-1", display_name: "Agent 1" },
            { user_id: "ops-1", display_name: payload.display_name || "Operatör" },
          ],
        }));
        return;
      }

      if (payload.action === "message") {
        socket.send(JSON.stringify({ type: "assistant_stream_start", request_id: "req-e2e-1" }));
        socket.send(JSON.stringify({ type: "assistant_chunk", request_id: "req-e2e-1", chunk: "Mock backend " }));
        socket.send(JSON.stringify({ type: "assistant_chunk", request_id: "req-e2e-1", chunk: "yanıtı" }));
        socket.send(JSON.stringify({
          type: "assistant_done",
          request_id: "req-e2e-1",
          message: {
            id: "msg-e2e-1",
            role: "assistant",
            content: "Mock backend yanıtı",
            ts: new Date().toISOString(),
          },
        }));
      }
    });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolve());
  });

  return {
    async close() {
      await new Promise((resolve) => {
        wss.close(() => {
          server.close(() => resolve());
        });
      });
    },
  };
}
