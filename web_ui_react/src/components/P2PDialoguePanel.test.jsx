import React from "react";
import { render, screen } from "@testing-library/react";
import { P2PDialoguePanel } from "./P2PDialoguePanel.jsx";

const { useChatStoreMock } = vi.hoisted(() => ({
  useChatStoreMock: vi.fn(),
}));

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => useChatStoreMock(),
}));

describe("P2PDialoguePanel", () => {
  beforeEach(() => {
    useChatStoreMock.mockReset();
  });

  it("shows only dialogue-oriented telemetry events", () => {
    useChatStoreMock.mockReturnValue({
      telemetryEvents: [
        { id: "1", kind: "status", ts: "2025-01-01T10:00:00Z", source: "supervisor", content: "Plan oluşturuldu" },
        { id: "2", kind: "thought", ts: "2025-01-01T10:00:01Z", source: "reviewer", content: "Riskler değerlendiriliyor" },
        { id: "3", kind: "tool_call", ts: "2025-01-01T10:00:02Z", source: "coder", content: "repo_search" },
        { id: "4", kind: "room_event", ts: "2025-01-01T10:00:03Z", source: "system", content: "ignore" },
      ],
    });

    render(<P2PDialoguePanel />);

    expect(screen.getByText(/Plan oluşturuldu/)).toBeInTheDocument();
    expect(screen.getByText(/Riskler değerlendiriliyor/)).toBeInTheDocument();
    expect(screen.getByText(/repo_search/)).toBeInTheDocument();
    expect(screen.queryByText(/ignore/)).not.toBeInTheDocument();
  });

  it("renders empty state when no dialogue events exist", () => {
    useChatStoreMock.mockReturnValue({ telemetryEvents: [] });
    render(<P2PDialoguePanel />);

    expect(screen.getByText("Henüz P2P etkinliği yok. Sohbete mesaj gönderin.")).toBeInTheDocument();
  });

  it("renders content without source label when source is missing", () => {
    useChatStoreMock.mockReturnValue({
      telemetryEvents: [{ id: "evt", kind: "status", ts: "2025-01-01T10:00:00Z", content: "Kaynak yok mesajı" }],
    });
    render(<P2PDialoguePanel />);

    expect(screen.getByText("Kaynak yok mesajı")).toBeInTheDocument();
    expect(screen.queryByText(/:\s$/)).not.toBeInTheDocument();
  });
});
