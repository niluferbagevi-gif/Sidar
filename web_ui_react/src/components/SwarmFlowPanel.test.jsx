import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SwarmFlowPanel } from "./SwarmFlowPanel.jsx";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => ({
    telemetryEvents: [
      { id: "evt-1", kind: "status", ts: "2025-01-01T10:00:00Z", content: "supervisor: plan created" },
      { id: "evt-2", kind: "tool_call", ts: "2025-01-01T10:00:01Z", content: "reviewer: code_search" },
    ],
  }),
}));

vi.mock("../lib/api.js", () => ({ fetchJson }));

describe("SwarmFlowPanel", () => {
  beforeEach(() => {
    fetchJson.mockReset();
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
});
