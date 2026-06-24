import http from "node:http";
import { WebSocketServer } from "ws";

function sendJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString("utf8");
  if (!text.trim()) return {};
  return JSON.parse(text);
}

const pendingHitl = [
  {
    request_id: "hitl-e2e-1",
    action: "graph_review",
    description: "Mock graph düğümü için operatör onayı",
    requested_by: "mock-backend",
    payload: { node_id: "supervisor" },
  },
];

export async function startMockSidarBackend({ port = 0 } = {}) {
  const server = http.createServer(async (req, res) => {
    if (req.url === "/healthz") {
      sendJson(res, 200, { ok: true });
      return;
    }

    if (req.method === "GET" && req.url === "/api/hitl/pending") {
      sendJson(res, 200, { pending: pendingHitl });
      return;
    }

    if (req.method === "POST" && req.url === "/api/operations/landing-page") {
      const body = await readJson(req);
      sendJson(res, 200, {
        success: true,
        title: `${body.brand_name || "Sidar"} landing page hazır`,
        sections: ["hero", "social_proof", "cta"],
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/operations/campaign-copy") {
      const body = await readJson(req);
      sendJson(res, 200, {
        success: true,
        campaign_name: body.campaign_name || "E2E kampanya",
        copy: "Mock kampanya kopyası üretildi.",
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/qa/coverage/analyze") {
      sendJson(res, 200, {
        success: true,
        hotspots: [{ path: "core/router.py", missing_lines: [42, 43] }],
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/qa/coverage/batch") {
      sendJson(res, 200, {
        success: true,
        planned: 1,
        batches: [{ id: "coverage-e2e-1", status: "queued" }],
      });
      return;
    }

    if (req.method === "GET" && req.url?.startsWith("/api/autonomy/activity")) {
      sendJson(res, 200, {
        activity: {
          total: 1,
          counts_by_status: { success: 1 },
          counts_by_source: { scheduler: 1 },
          items: [
            {
              trigger_id: "auto-e2e-1",
              event_name: "nightly_scan",
              source: "scheduler",
              status: "success",
              summary: "Mock nightly autonomy trigger completed.",
            },
          ],
        },
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/swarm/execute") {
      const body = await readJson(req);
      const tasks = Array.isArray(body.tasks) && body.tasks.length > 0 ? body.tasks : [{ intent: "mixed" }];
      sendJson(res, 200, {
        session_id: body.session_id || "ui-swarm-session",
        mode: body.mode || "parallel",
        results: tasks.map((task, index) => ({
          task_id: `task-e2e-${index + 1}`,
          agent_role: task.preferred_agent || (index % 2 === 0 ? "reviewer" : "coder"),
          status: "success",
          elapsed_ms: 25 + index,
          summary: `Mock swarm sonucu: ${task.intent || "mixed"}`,
          handoffs: index === 0 ? [{
            task_id: `task-e2e-${index + 1}`,
            sender: "supervisor",
            receiver: "reviewer",
            reason: "targeted_rerun",
            intent: task.intent || "mixed",
            handoff_depth: 1,
            swarm_hop: 1,
          }] : [],
          graph: { p2p_sender: "supervisor", p2p_receiver: "reviewer", p2p_reason: "targeted_rerun" },
        })),
      });
      return;
    }

    if (req.method === "POST" && req.url === "/api/hitl/request") {
      const body = await readJson(req);
      const request = {
        request_id: `hitl-e2e-${pendingHitl.length + 1}`,
        action: body.action || "graph_review",
        description: body.description || "Mock HITL isteği",
        requested_by: body.requested_by || "e2e",
        payload: body.payload || {},
      };
      pendingHitl.unshift(request);
      sendJson(res, 200, request);
      return;
    }

    if (req.method === "POST" && req.url?.startsWith("/api/hitl/respond/")) {
      const requestId = decodeURIComponent(req.url.split("/").pop() || "");
      const body = await readJson(req);
      sendJson(res, 200, {
        request_id: requestId,
        decision: body.approved ? "approved" : "rejected",
      });
      return;
    }

    res.writeHead(404);
    res.end();
  });

  const wss = new WebSocketServer({ server, path: "/ws/chat" });
  const voiceWss = new WebSocketServer({ server, path: "/ws/voice" });

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

  voiceWss.on("connection", (socket, req) => {
    const token = req.headers["sec-websocket-protocol"] || "";
    if (!String(token).trim()) {
      socket.close(4001, "missing token");
      return;
    }

    socket.send(JSON.stringify({ auth_ok: true }));
    socket.send(JSON.stringify({ voice_session: "ready" }));

    socket.on("message", (raw) => {
      let payload = {};
      try {
        payload = JSON.parse(String(raw || ""));
      } catch {
        return;
      }

      if (payload.action === "start") {
        socket.send(JSON.stringify({ voice_state: "speech_start", assistant_turn_id: 1, buffered_bytes: 0 }));
      }
      if (payload.action === "append_base64") {
        socket.send(JSON.stringify({ buffered_bytes: 32 }));
      }
      if (payload.action === "commit") {
        socket.send(JSON.stringify({ transcript: "Mock sesli komut" }));
        socket.send(JSON.stringify({ chunk: "Mock voice response" }));
        socket.send(JSON.stringify({ voice_state: "processed", assistant_turn_id: 1, buffered_bytes: 0 }));
        socket.send(JSON.stringify({ done: true }));
      }
      if (payload.action === "cancel") {
        socket.send(JSON.stringify({ voice_interruption: "manual_interrupt", cancelled_audio_sequences: 1 }));
      }
    });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "0.0.0.0", () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    await new Promise((resolve) => server.close(() => resolve()));
    throw new Error("Mock Sidar backend dinleme portunu döndürmedi.");
  }

  return {
    port: address.port,
    url: `http://127.0.0.1:${address.port}`,
    async close() {
      await new Promise((resolve) => {
        voiceWss.close(() => {
          wss.close(() => {
            server.close(() => resolve());
          });
        });
      });
    },
  };
}
