import React from "react";
import { render, screen } from "@testing-library/react";
import { P2PDialoguePanel } from "./P2PDialoguePanel.jsx";

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => ({
    telemetryEvents: [
      { id: "1", kind: "status", ts: "2025-01-01T10:00:00Z", source: "supervisor", content: "Plan oluşturuldu" },
      { id: "2", kind: "thought", ts: "2025-01-01T10:00:01Z", source: "reviewer", content: "Riskler değerlendiriliyor" },
      { id: "3", kind: "tool_call", ts: "2025-01-01T10:00:02Z", source: "coder", content: "repo_search" },
      { id: "4", kind: "room_event", ts: "2025-01-01T10:00:03Z", source: "system", content: "ignore" },
    ],
  }),
}));

describe("P2PDialoguePanel", () => {
  it("shows only dialogue-oriented telemetry events", () => {
    render(<P2PDialoguePanel />);

    expect(screen.getByText(/Plan oluşturuldu/)).toBeInTheDocument();
    expect(screen.getByText(/Riskler değerlendiriliyor/)).toBeInTheDocument();
    expect(screen.getByText(/repo_search/)).toBeInTheDocument();
    expect(screen.queryByText(/ignore/)).not.toBeInTheDocument();
  });
});