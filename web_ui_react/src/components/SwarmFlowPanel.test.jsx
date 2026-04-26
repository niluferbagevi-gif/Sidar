import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  SwarmFlowPanel,
  buildTaskDraftFromNode,
  clampText,
  inferTelemetryActor,
  prettifyReason,
  prettifyRole,
  toDetailEntries,
} from "./SwarmFlowPanel.jsx";

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

const bootstrapApiMock = ({ activityItems = [], pending = [] } = {}) => async (url) => {
  if (url === "/api/autonomy/activity?limit=8") {
    return {
      activity: {
        items: activityItems,
        counts_by_status: {},
        counts_by_source: {},
        total: activityItems.length,
      },
    };
  }
  if (url === "/api/hitl/pending") {
    return { pending };
  }
  throw new Error(`Beklenmeyen çağrı: ${url}`);
};

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

  it("renders accessible region and operation log live region", async () => {
    fetchJson.mockImplementation(bootstrapApiMock());
    render(<SwarmFlowPanel />);
    expect(await screen.findByRole("region", { name: /swarm görev akışı paneli/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/operasyon günlüğü/i)).toHaveAttribute("aria-live", "polite");
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

  it("shows error when swarm execution fails via executeSwarm catch block", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8" || url === "/api/hitl/pending") {
        return bootstrapApiMock()(url);
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        throw new Error("Swarm API Error");
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: "Swarm Başlat" }));

    expect(await screen.findByText("Swarm API Error")).toBeInTheDocument();
    expect(await screen.findByText(/Swarm tetiklenemedi: Swarm API Error/)).toBeInTheDocument();
  });

  it("handles inspector actions: add draft, replace first task, graph add and run", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-1", event_name: "test_event", summary: "summary", source: "cron", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { cron: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      if (url === "/api/swarm/execute" && options?.method === "POST") return { results: [] };
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: /test_event/i }));

    await user.click(screen.getByRole("button", { name: /İlk Goal.ı Değiştir/i }));
    expect(await screen.findByText(/İlk görev seçili düğümden yeniden yazıldı/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Takip Görevi Ekle" }));
    expect(await screen.findByText(/Seçili düğüm görev taslağına eklendi/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Task’e ekle" }));
    expect((await screen.findAllByText(/Seçili düğüm görev taslağına eklendi/i)).length).toBeGreaterThan(1);

    await user.click(screen.getByRole("button", { name: /Bu Node.u Çalıştır/i }));
    expect(await screen.findByText(/Seçili düğüm için hedefli swarm çalıştı/i)).toBeInTheDocument();
  });

  it("sends HITL request for autonomy node to cover autonomy_review branch", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-auto", event_name: "auto_event", summary: "oto özet", source: "cron", status: "success" }],
            counts_by_status: { success: 1 },
            counts_by_source: { cron: 1 },
            total: 1,
          },
        };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      if (url === "/api/hitl/request" && options?.method === "POST") return { request_id: "hitl-req-auto" };
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    await user.click(await screen.findByRole("button", { name: /auto_event/i }));
    await user.click(screen.getByRole("button", { name: "İnceleme İsteği Aç" }));

    expect(fetchJson).toHaveBeenCalledWith("/api/hitl/request", expect.objectContaining({
      body: expect.stringContaining("\"action\":\"autonomy_review\""),
    }));
  });

  it("updates task goal field correctly on user typing", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(bootstrapApiMock());

    render(<SwarmFlowPanel />);
    const goalBoxes = await screen.findAllByPlaceholderText("Görevin açıklaması");
    await user.type(goalBoxes[0], "X");
    expect(screen.getAllByPlaceholderText("Görevin açıklaması")[0].value).toContain("X");
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

  it("covers neutral results, thought telemetry, empty contents, and ignored keys", async () => {
    const user = userEvent.setup();

    telemetryState.events = [
      { id: "evt-empty", kind: "status", ts: "2025-01-01T10:00:00Z", content: "   " },
      { id: "evt-thought", kind: "thought", ts: "2025-01-01T10:00:01Z", content: "I should analyze this without prefix." },
    ];

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
            task_id: "t-neutral",
            agent_role: "planner",
            status: "processing",
            elapsed_ms: 10,
            summary: "",
          }],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    const nodes = await screen.findAllByRole("button");
    const nodeElements = nodes.filter((node) => node.className && node.className.includes("swarm-graph__node"));
    if (nodeElements.length > 0) {
      nodeElements[0].focus();
      await user.keyboard("{Escape}");
      await user.keyboard("A");
    }

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));

    expect(await screen.findByText("Açıklama bekleniyor.")).toBeInTheDocument();
    expect(await screen.findAllByText("Decision")).not.toHaveLength(0);
  });


  it("handles runSelectedNode execution failure correctly", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        throw new Error("Targeted swarm execution failed");
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    await user.click(await screen.findByRole("button", { name: "Run node" }));

    expect(await screen.findByText("Targeted swarm execution failed")).toBeInTheDocument();
    expect(screen.queryByText(/Seçili düğüm için hedefli swarm çalıştı/i)).not.toBeInTheDocument();
  });

  it("sends HITL request for supervisor node to cover graph_review branch", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8" || url === "/api/hitl/pending") {
        return bootstrapApiMock()(url);
      }
      if (url === "/api/hitl/request" && options?.method === "POST") return { request_id: "hitl-req-supervisor" };
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    await user.click(await screen.findByRole("button", { name: "İnceleme İsteği Aç" }));

    const hitlCall = fetchJson.mock.calls.find(([url]) => url === "/api/hitl/request");
    expect(hitlCall).toBeTruthy();
    expect(hitlCall[1].body).toContain('"action":"graph_review"');
  });

  it("preserves previous error state when multiple fetches fail concurrently", async () => {
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        throw new Error("First Priority Error");
      }
      if (url === "/api/hitl/pending") {
        throw new Error("Second Ignored Error");
      }
      return {};
    });

    render(<SwarmFlowPanel />);

    expect(await screen.findByText("First Priority Error")).toBeInTheDocument();
    expect(screen.queryByText("Second Ignored Error")).not.toBeInTheDocument();
  });


  it("covers disabled states during actionBusy and running", async () => {
    const user = userEvent.setup();
    let resolveSwarm;
    let resolveHitl;

    fetchJson.mockImplementation((url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return Promise.resolve({ activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } });
      }
      if (url === "/api/hitl/pending") {
        return Promise.resolve({ pending: [] });
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return new Promise((resolve) => {
          resolveSwarm = resolve;
        });
      }
      if (url === "/api/hitl/request" && options?.method === "POST") {
        return new Promise((resolve) => {
          resolveHitl = resolve;
        });
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    await screen.findByRole("button", { name: "Swarm Başlat" });
    const firstNode = screen.getAllByRole("button").find((node) => node.className?.includes("swarm-graph__node"));
    expect(firstNode).toBeTruthy();
    firstNode.focus();
    await user.keyboard("[Enter]");

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    expect(screen.getByRole("button", { name: "Run node" })).toBeDisabled();

    resolveSwarm({ results: [] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Swarm Başlat" })).not.toBeDisabled());

    const reviewBtn = screen.getByRole("button", { name: "İnceleme İsteği Aç" });
    await user.click(reviewBtn);

    expect(reviewBtn).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run node" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Task’e ekle" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Takip Görevi Ekle" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "İlk Goal’ı Değiştir" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bu Node’u Çalıştır" })).toBeDisabled();

    resolveHitl({ request_id: "hitl-test-id" });
    await waitFor(() => expect(reviewBtn).not.toBeDisabled());
  });

  it("covers fallback values for empty maxConcurrency and sessionId", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return { results: [] };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    const sessionInput = await screen.findByPlaceholderText("ui-swarm-session");
    await user.clear(sessionInput);

    const concurrencyInput = screen.getByLabelText(/Maksimum eşzamanlılık/i);
    await user.clear(concurrencyInput);

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith(
        "/api/swarm/execute",
        expect.objectContaining({
          body: expect.stringContaining('"max_concurrency":1'),
        }),
      );
    });

    const firstNode = screen.getAllByRole("button").find((node) => node.className?.includes("swarm-graph__node"));
    expect(firstNode).toBeTruthy();
    firstNode.focus();
    await user.keyboard("[Enter]");

    await user.click(screen.getByRole("button", { name: "Run node" }));

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith(
        "/api/swarm/execute",
        expect.objectContaining({
          body: expect.stringContaining('"session_id":"ui-swarm-session-node"'),
        }),
      );
    });
  });


  it("covers pipeline context-handoff edge creation branch", async () => {
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
          results: [
            { task_id: "pipe-1", agent_role: "reviewer", status: "success", summary: "ilk" },
            { task_id: "pipe-2", agent_role: "supervisor", status: "success", summary: "ikinci" },
          ],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    await user.selectOptions(screen.getByRole("combobox"), "pipeline");
    await user.click(screen.getByRole("button", { name: "Yeni Görev Ekle" }));

    const goals = screen.getAllByPlaceholderText("Görevin açıklaması");
    await user.clear(goals[0]);
    await user.type(goals[0], "ilk görev");
    await user.type(goals[1], "ikinci görev");

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));

    await waitFor(() => expect(screen.getAllByText("context handoff").length).toBeGreaterThan(0));
  });

  it("covers selected-node fallback when previous node disappears", async () => {
    const user = userEvent.setup();
    let activityCall = 0;
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        activityCall += 1;
        if (activityCall === 1) {
          return {
            activity: {
              items: [{ trigger_id: "trg-fallback", event_name: "nightly_scan", summary: "ilk yük", source: "cron", status: "success" }],
              counts_by_status: { success: 1 },
              counts_by_source: { cron: 1 },
              total: 1,
            },
          };
        }
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    const disappearingNode = await screen.findByRole("button", { name: /nightly_scan/i });
    await user.click(disappearingNode);
    expect(screen.getByText(/Selected nightly_scan/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aktiviteyi Yenile" }));

    await waitFor(() => expect(screen.getByText(/Selected Supervisor/i)).toBeInTheDocument());
  });

  it("covers fallback branches for sparse swarm/autonomy/HITL payloads and approve flow", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [{ trigger_id: "trg-fallback", payload: { raw: true } }],
          },
        };
      }
      if (url === "/api/hitl/pending") {
        return {
          pending: [{ request_id: "hitl-fallback" }],
        };
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{
            task_id: "task-fallback",
            elapsed_ms: 1,
            handoffs: [{ resultIndex: 0 }],
          }],
        };
      }
      if (url === "/api/hitl/respond/hitl-fallback" && options?.method === "POST") {
        return { request_id: "hitl-fallback", decision: "approved" };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    expect(await screen.findByText("Pending HITL 1")).toBeInTheDocument();
    expect(screen.getAllByText("trigger").length).toBeGreaterThan(0);
    expect(screen.getByText("Özet yok.")).toBeInTheDocument();
    expect(screen.getAllByText("manual · unknown").length).toBeGreaterThan(0);
    expect(screen.getByText("Açıklama yok.")).toBeInTheDocument();
    expect(screen.getByText("operator")).toBeInTheDocument();

    const intentInput = screen.getAllByPlaceholderText("security_audit")[0];
    await user.clear(intentInput);

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    await waitFor(() => expect(screen.getByText("result")).toBeInTheDocument());
    expect(screen.getByText(/Unknown → Unknown/i)).toBeInTheDocument();
    expect(screen.getByText("Delegation")).toBeInTheDocument();

    await waitFor(() => {
      expect(fetchJson).toHaveBeenCalledWith(
        "/api/swarm/execute",
        expect.objectContaining({
          body: expect.stringContaining("\"intent\":\"mixed\""),
        }),
      );
    });

    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText(/HITL kararı işlendi: hitl-fallback → approved/)).toBeInTheDocument();
  });

  it("covers proactive activity fallback when activity.items is omitted", async () => {
    const user = userEvent.setup();
    let activityCalls = 0;
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") {
        activityCalls += 1;
        if (activityCalls === 1) {
          return { activity: {} };
        }
        return {
          activity: {
            items: [{ trigger_id: "trg-refresh" }],
          },
        };
      }
      if (url === "/api/hitl/pending") {
        return { pending: [] };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect(await screen.findByText("Henüz proaktif aktivite kaydı yok.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Aktiviteyi Yenile" }));
    expect((await screen.findAllByText("manual · unknown")).length).toBeGreaterThan(0);
  });

  it("covers autonomy edge chaining and extra-result lane fallback branches", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return {
          activity: {
            items: [
              { trigger_id: "a1", event_name: "cron_a", summary: "A", source: "cron", status: "success" },
              { trigger_id: "a2", event_name: "cron_b", summary: "B", source: "cron", status: "success" },
            ],
          },
        };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [
            { task_id: "r1", agent_role: "reviewer", status: "success", summary: "ok" },
            { task_id: "r2", status: "failed", summary: "fallback lane" },
            { status: "success", summary: "index fallback id" },
          ],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect(await screen.findByText("wake signal")).toBeInTheDocument();
    expect(screen.getByText("trigger chain")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    await waitFor(() => expect(screen.getAllByText("output").length).toBeGreaterThan(1));
  });



  it("covers result edge fallback when all tasks are removed before execution", async () => {
    const user = userEvent.setup();
    fetchJson.mockImplementation(async (url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
      }
      if (url === "/api/hitl/pending") return { pending: [] };
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return {
          results: [{ status: "success", summary: "tasks removed", agent_role: "reviewer" }],
        };
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);

    const removeButtons = await screen.findAllByRole("button", { name: "Görevi Sil" });
    for (const button of removeButtons) {
      await user.click(button);
    }

    await user.click(screen.getByRole("button", { name: "Run node" }));

    expect(await screen.findByText(/Seçili düğüm için hedefli swarm çalıştı/)).toBeInTheDocument();
    expect(screen.getByText("tasks removed")).toBeInTheDocument();
    expect(screen.getByText("output")).toBeInTheDocument();
  });

  it("covers omitted activity/pending payload keys on initial loaders", async () => {
    fetchJson.mockImplementation(async (url) => {
      if (url === "/api/autonomy/activity?limit=8") return {};
      if (url === "/api/hitl/pending") return {};
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect(await screen.findByText("Bekleyen HITL kaydı yok.")).toBeInTheDocument();
    expect(screen.getByText("Henüz proaktif aktivite kaydı yok.")).toBeInTheDocument();
  });

  it("covers fallback branches for task/result/handoff linking and preserves earlier error on pending refresh failure", async () => {
    const user = userEvent.setup();
    let pendingRefreshCount = 0;
    let resolveApproval;

    fetchJson.mockImplementation((url, options) => {
      if (url === "/api/autonomy/activity?limit=8") {
        return Promise.resolve({
          activity: {
            items: [{ event_name: "fallback_event", summary: "payload", source: "manual" }],
          },
        });
      }
      if (url === "/api/hitl/pending") {
        pendingRefreshCount += 1;
        if (pendingRefreshCount === 1) {
          return Promise.resolve({ pending: [{ request_id: "hitl-keep", description: "bekliyor" }] });
        }
        throw new Error("pending refresh failed");
      }
      if (url === "/api/swarm/execute" && options?.method === "POST") {
        return Promise.resolve({
          results: [
            {
              task_id: "task-a",
              status: "success",
              summary: "ok",
              handoffs: [{ sender: "supervisor", receiver: "reviewer", reason: "delegation" }],
            },
            { task_id: "task-b", status: "success", summary: "ok-2" },
            {
              status: "failed",
              summary: "extra",
              handoffs: [{ sender: "reviewer", receiver: "coder", reason: "escalation" }],
            },
          ],
        });
      }
      if (url === "/api/hitl/respond/hitl-keep" && options?.method === "POST") {
        return new Promise((resolve) => {
          resolveApproval = resolve;
        });
      }
      throw new Error(`Beklenmeyen çağrı: ${url}`);
    });

    render(<SwarmFlowPanel />);
    expect(await screen.findByText("Pending HITL 1")).toBeInTheDocument();
    expect(screen.getAllByText("manual · unknown").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    await waitFor(() => expect(screen.getAllByText("output").length).toBeGreaterThan(1));
    expect(screen.getByText(/Reviewer → Coder/i)).toBeInTheDocument();

    const approvalButton = screen.getByRole("button", { name: "Approve" });
    const rejectButton = screen.getByRole("button", { name: "Reject" });
    await user.click(approvalButton);
    expect(rejectButton).toBeDisabled();

    resolveApproval({ request_id: "hitl-keep", decision: "approved" });
    expect(await screen.findByText(/HITL kararı işlendi: hitl-keep → approved/)).toBeInTheDocument();

    const goalBoxes = screen.getAllByPlaceholderText("Görevin açıklaması");
    for (const area of goalBoxes) {
      await user.clear(area);
    }
    await user.click(screen.getByRole("button", { name: "Swarm Başlat" }));
    expect(await screen.findByText("En az bir görev girmelisiniz.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Bekleyenleri Yenile" }));
    expect((await screen.findAllByText(/HITL bekleyen kayıtları alınamadı: pending refresh failed/)).length).toBeGreaterThan(0);
    expect(screen.getByText("En az bir görev girmelisiniz.")).toBeInTheDocument();
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

it("disables reject action while approval response is in-flight", async () => {
  const user = userEvent.setup();
  let resolveDecision;
  fetchJson.mockImplementation((url, options) => {
    if (url === "/api/autonomy/activity?limit=8") {
      return Promise.resolve({ activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } });
    }
    if (url === "/api/hitl/pending") {
      return Promise.resolve({
        pending: [{ request_id: "hitl-busy", action: "graph_review", description: "karar bekliyor", requested_by: "qa" }],
      });
    }
    if (url === "/api/hitl/respond/hitl-busy" && options?.method === "POST") {
      return new Promise((resolve) => {
        resolveDecision = resolve;
      });
    }
    throw new Error(`Beklenmeyen çağrı: ${url}`);
  });

  render(<SwarmFlowPanel />);
  const rejectButton = await screen.findByRole("button", { name: "Reject" });
  await user.click(rejectButton);
  expect(rejectButton).toBeDisabled();

  resolveDecision({ request_id: "hitl-busy", decision: "rejected" });
  expect(await screen.findByText(/HITL kararı işlendi: hitl-busy → rejected/)).toBeInTheDocument();
});

it("renders pending approval rows with fallback key/id fields", async () => {
  fetchJson.mockImplementation(async (url) => {
    if (url === "/api/autonomy/activity?limit=8") {
      return { activity: { items: [], counts_by_status: {}, counts_by_source: {}, total: 0 } };
    }
    if (url === "/api/hitl/pending") {
      return { pending: [{}] };
    }
    throw new Error(`Beklenmeyen çağrı: ${url}`);
  });

  render(<SwarmFlowPanel />);
  expect(await screen.findByText("manual")).toBeInTheDocument();
  expect(screen.getByText("Açıklama yok.")).toBeInTheDocument();
});
