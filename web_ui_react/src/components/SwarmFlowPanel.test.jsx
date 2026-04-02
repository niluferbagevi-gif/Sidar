import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SwarmFlowPanel } from "./SwarmFlowPanel.jsx";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));
const { telemetryState } = vi.hoisted(() => ({
  telemetryState: {
    events: [
      { id: "evt-1", kind: "status", ts: "2025-01-01T10:00:00Z", content: "supervisor: plan created" },
      { id: "evt-2", kind: "tool_call", ts: "2025-01-01T10:00:01Z", content: "reviewer: code_search" },
    ],
  },
}));

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => ({
    telemetryEvents: telemetryState.events,
  }),
}));

vi.mock("../lib/api.js", () => ({ fetchJson }));

describe("SwarmFlowPanel", () => {
  beforeEach(() => {
    fetchJson.mockReset();
    telemetryState.events = [
      { id: "evt-1", kind: "status", ts: "2025-01-01T10:00:00Z", content: "supervisor: plan created" },
      { id: "evt-2", kind: "tool_call", ts: "2025-01-01T10:00:01Z", content: "reviewer: code_search" },
    ];
  });

  it("loads autonomy activity and pending approvals, then refreshes activity on demand", async () => {
    const user = userEvent.setup();
    fetchJson
      .mockResolvedValueOnce({
        activity: {
          items: [{ trigger_id: "trg-1", event_name: "nightly_scan", summary: "Tarama tamamlandı", source: "cron", status: "success" }],
          counts_by_status: { success: 1 },
          counts_by_source: { cron: 1 },
          total: 1,
        },
      })
      .mockResolvedValueOnce({
        pending: [{ request_id: "hitl-1", action: "graph_review", description: "İnceleme bekliyor", requested_by: "operator" }],
      })
      .mockResolvedValueOnce({
        activity: {
          items: [{ trigger_id: "trg-2", event_name: "manual_run", summary: "Elle tetiklendi", source: "manual", status: "success" }],
          counts_by_status: { success: 1 },
          counts_by_source: { manual: 1 },
          total: 1,
        },
      });

    render(<SwarmFlowPanel />);

    expect(await screen.findByText(/Pending HITL 1/)).toBeInTheDocument();
    expect(screen.getAllByText("nightly_scan").length).toBeGreaterThan(0);
    expect(screen.getByText(/İnceleme bekliyor/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aktiviteyi Yenile" }));

    await waitFor(() => expect(screen.getAllByText("manual_run").length).toBeGreaterThan(0));
    expect(fetchJson).toHaveBeenCalledWith("/api/autonomy/activity?limit=8");
    expect(fetchJson).toHaveBeenCalledWith("/api/hitl/pending");
  });

  it("handles node actions, HITL review flow, approval response and empty-task validation", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-9", event_name: "manual_run", summary: "Graf kaydı", source: "manual", status: "failed" }],
            counts_by_status: { failed: 1 },
            counts_by_source: { manual: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") {
        return {
          pending: [{ request_id: "hitl-9", action: "graph_review", description: "Onay bekliyor", requested_by: "operator" }],
        };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{ task_id: "t-1", agent_role: "reviewer", status: "success", elapsed_ms: 22, summary: "Tamam" }],
        };
      }
      if (url === "/api/hitl/request" && options?.method === "POST") {
        return { request_id: "hitl-req-1" };
      }
      if (url === "/api/hitl/respond/hitl-9" && options?.method === "POST") {
        return { request_id: "hitl-9", decision: "rejected" };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    expect(await screen.findByText(/Pending HITL 1/)).toBeInTheDocument();
    expect(screen.getAllByText("manual_run").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Run node" }));
    await waitFor(() => expect(fetchJson).toHaveBeenCalledWith("/api/swarm/execute", expect.objectContaining({ method: "POST" })));
    expect(await screen.findByText(/Seçili düğüm için hedefli swarm çalıştı/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "İnceleme İsteği Aç" }));
    expect(await screen.findByText(/HITL isteği oluşturuldu: hitl-req-1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText(/HITL kararı işlendi: hitl-9 → rejected/)).toBeInTheDocument();

    const goalBoxes = screen.getAllByPlaceholderText("Görevin açıklaması");
    for (const area of goalBoxes) {
      await user.clear(area);
    }
    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    expect(await screen.findByText("En az bir görev girmelisiniz.")).toBeInTheDocument();
  });

  it("shows request-node-review errors when HITL endpoint fails", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-2", event_name: "nightly_scan", summary: "Tarama", source: "cron", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { cron: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/hitl/request" && options?.method === "POST") {
        throw new Error("HITL endpoint down");
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect((await screen.findAllByText("nightly_scan")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "İnceleme İsteği Aç" }));
    expect(await screen.findByText("HITL endpoint down")).toBeInTheDocument();
    expect(await screen.findByText(/HITL isteği oluşturulamadı: HITL endpoint down/)).toBeInTheDocument();
  });

  it("renders empty states and loading labels for activity/approvals/telemetry", async () => {
    const user = userEvent.setup();
    telemetryState.events = [];

    let activityCalls = 0;
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        activityCalls += 1;
        if (activityCalls === 1) {
          return new Promise(() => {});
        }
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    expect(screen.getByRole("button", { name: "Yükleniyor…" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Bekleyenleri Yenile" }));
    expect(await screen.findByText("Bekleyen HITL kaydı yok.")).toBeInTheDocument();
    expect(screen.getByText("Henüz kullanıcı aksiyonu kaydedilmedi.")).toBeInTheDocument();
    expect(screen.getByText("Henüz proaktif aktivite kaydı yok.")).toBeInTheDocument();
    expect(screen.getByText("Akış verisi bulunamadı.")).toBeInTheDocument();
  });

  it("supports keyboard node selection and sync operation failure logging", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-kb", event_name: "nightly_scan", summary: "Klavye test", source: "cron", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { cron: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/hitl/request" && options?.method === "POST") {
        throw new Error("review request failed");
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    const nightlyNode = await screen.findByRole("button", { name: /nightly_scan/i });

    await user.keyboard("[Tab]");
    nightlyNode.focus();
    await user.keyboard("[Enter]");

    await user.click(screen.getByRole("button", { name: "Yüzeyi Yenile" }));
    await user.click(screen.getByRole("button", { name: "İnceleme İsteği Aç" }));

    expect(await screen.findByText("review request failed")).toBeInTheDocument();
  });

  it("renders handoff outcome edges when swarm result includes p2p handoff chain", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{
            task_id: "task-99",
            agent_role: "reviewer",
            status: "success",
            elapsed_ms: 14,
            summary: "handoff tamamlandı",
            handoffs: [{
              task_id: "task-99",
              sender: "supervisor",
              receiver: "reviewer",
              reason: "delegation",
              intent: "review",
              handoff_depth: 1,
              swarm_hop: 1,
            }],
          }],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: "Run node" }));

    await waitFor(() => expect(screen.getByText("handoff outcome")).toBeInTheDocument());
    expect(screen.getByText(/supervisor → reviewer/i)).toBeInTheDocument();
  });

  it("renders graph fallback handoff when result has p2p_sender/p2p_receiver without handoff array", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{
            task_id: "task-graph",
            agent_role: "reviewer",
            status: "success",
            summary: "graph fallback",
            graph: {
              p2p_sender: "supervisor",
              p2p_receiver: "reviewer",
              p2p_reason: "delegation",
              intent: "review",
              p2p_handoff_depth: 2,
              swarm_hop: 2,
            },
          }],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: "Run node" }));

    await waitFor(() => expect(screen.getByText(/supervisor → reviewer/i)).toBeInTheDocument());
    expect(screen.getByText(/depth 2 · hop 2/i)).toBeInTheDocument();
  });

  it("handles form edits, task add/remove, and pipeline-specific graph edges", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-pipe", event_name: "manual_run", summary: "pipeline görünümü", source: "manual", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { manual: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect((await screen.findAllByText("manual_run")).length).toBeGreaterThan(0);

    const sessionInput = screen.getByPlaceholderText("ui-swarm-session");
    await user.clear(sessionInput);
    await user.type(sessionInput, "custom-session");

    const concurrencyInput = screen.getByLabelText(/Maksimum eşzamanlılık/i);
    await user.clear(concurrencyInput);
    await user.type(concurrencyInput, "5");

    await user.selectOptions(screen.getByRole("combobox"), "pipeline");
    await user.click(screen.getByRole("button", { name: "Yeni Görev Ekle" }));

    const intentInputs = screen.getAllByPlaceholderText("security_audit");
    await user.clear(intentInputs[intentInputs.length - 1]);
    await user.type(intentInputs[intentInputs.length - 1], "custom_intent");

    const agentInputs = screen.getAllByPlaceholderText("opsiyonel role_name");
    await user.type(agentInputs[agentInputs.length - 1], "custom_agent");

    const removeButtons = screen.getAllByRole("button", { name: "Görevi Sil" });
    await user.click(removeButtons[0]);

    expect(screen.getByDisplayValue("custom-session")).toBeInTheDocument();
    expect(screen.getByDisplayValue("5")).toBeInTheDocument();
    expect(screen.getByText("next stage")).toBeInTheDocument();
  });

  it("handles space-key node selection and truncates long autonomy summaries", async () => {
    const user = userEvent.setup();
    const longSummary = "A".repeat(180);
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-long", event_name: "test_event", summary: longSummary, source: "manual", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { manual: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    const truncated = `${longSummary.slice(0, 159)}…`;
    const truncatedNodeBody = await screen.findByText(truncated);
    expect(truncatedNodeBody).toBeInTheDocument();

    const node = screen.getByRole("button", { name: /test_event/i });
    node.focus();
    await user.keyboard(" ");

    expect(screen.getByRole("button", { name: "Task’e ekle" })).toBeInTheDocument();
  });

  it("covers inferHitlActionFromNode branches for task, result-warning and handoff nodes", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{
            task_id: "task-hitl",
            agent_role: "multi_word-role",
            status: "failed",
            summary: "Failed test",
            handoffs: [{ task_id: "task-hitl", sender: "supervisor", receiver: "coder", reason: "delegation" }],
          }],
        };
      }
      if (url === "/api/hitl/request" && options?.method === "POST") {
        return { request_id: "hitl-req-test" };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: "Swarm Başlat" }));
    await waitFor(() => expect(screen.getByText("handoff outcome")).toBeInTheDocument());

    const openReviewForNode = async (predicate) => {
      const node = screen.getAllByRole("button").find(predicate);
      expect(node).toBeTruthy();
      node.focus();
      await user.keyboard("[Enter]");
      await user.click(screen.getByRole("button", { name: "İnceleme İsteği Aç" }));
    };

    await openReviewForNode((button) => button.className.includes("swarm-graph__node--task"));
    await openReviewForNode((button) => button.className.includes("swarm-graph__node--result-warning"));
    await openReviewForNode((button) => button.className.includes("swarm-graph__node--handoff"));

    const hitlCalls = fetchJson.mock.calls.filter(([url]) => url === "/api/hitl/request");
    expect(hitlCalls).toHaveLength(3);

    const parsedPayloads = hitlCalls.map(([, options]) => JSON.parse(options.body));
    expect(parsedPayloads.map((payload) => payload.action)).toEqual([
      "task_review",
      "result_review",
      "handoff_review",
    ]);
  });

});

it("shows global error banner when autonomy activity fetch fails", async () => {
  fetchJson.mockImplementation(async (url) => {
    if (url === "/api/autonomy/activity?limit=8") {
      throw new Error("activity unavailable");
    }
    if (url === "/api/hitl/pending") {
      return { pending: [] };
    }
    throw new Error(`Beklenmeyen çağrı: ${url}`);
  });

  render(<SwarmFlowPanel />);

  expect(await screen.findByText("activity unavailable")).toBeInTheDocument();
  expect(await screen.findByText(/Autonomy aktivitesi alınamadı/)).toBeInTheDocument();
});

it("logs approval response errors when HITL decision endpoint fails", async () => {
  const user = userEvent.setup();
  fetchJson.mockImplementation(async (url, options) => {
    if (url === "/api/autonomy/activity?limit=8") {
      return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
    }
    if (url === "/api/hitl/pending") {
      return {
        pending: [{ request_id: "hitl-err", action: "graph_review", description: "karar bekliyor", requested_by: "qa" }],
      };
    }
    if (url === "/api/hitl/respond/hitl-err" && options?.method === "POST") {
      throw new Error("decision endpoint failed");
    }
    throw new Error(`Beklenmeyen çağrı: ${url}`);
  });

  render(<SwarmFlowPanel />);
  expect(await screen.findByText(/karar bekliyor/)).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Approve" }));

  expect(await screen.findByText("decision endpoint failed")).toBeInTheDocument();
  expect(await screen.findByText(/HITL kararı gönderilemedi: decision endpoint failed/)).toBeInTheDocument();
});