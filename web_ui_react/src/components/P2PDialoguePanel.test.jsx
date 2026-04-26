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

  it("shows only the last 16 events when more exist", () => {
    const events = Array.from({ length: 20 }, (_, i) => ({
      id: `e${i}`,
      kind: "status",
      ts: "2025-01-01T10:00:00Z",
      content: `event-${i}`,
    }));
    useChatStoreMock.mockReturnValue({ telemetryEvents: events });

    render(<P2PDialoguePanel />);

    expect(screen.queryByText("event-0")).not.toBeInTheDocument();
    expect(screen.queryByText("event-3")).not.toBeInTheDocument();
    expect(screen.getByText("event-4")).toBeInTheDocument();
    expect(screen.getByText("event-19")).toBeInTheDocument();
  });

  it("renders source as bold label when present", () => {
    useChatStoreMock.mockReturnValue({
      telemetryEvents: [
        {
          id: "1",
          kind: "status",
          ts: "2025-01-01T10:00:00Z",
          source: "supervisor",
          content: "Plan hazır",
        },
      ],
    });
    render(<P2PDialoguePanel />);

    const label = screen.getByText("supervisor:", { selector: "strong" });
    expect(label).toBeInTheDocument();
    expect(label.tagName).toBe("STRONG");
  });

  it("applies correct CSS class based on event kind", () => {
    useChatStoreMock.mockReturnValue({
      telemetryEvents: [{ id: "1", kind: "tool_call", ts: "2025-01-01T10:00:00Z", content: "repo_search" }],
    });
    const { container } = render(<P2PDialoguePanel />);

    expect(container.querySelector(".event-list__item--tool_call")).toBeInTheDocument();
  });

  it("exposes accessible region and live log attributes", () => {
    useChatStoreMock.mockReturnValue({ telemetryEvents: [] });
    render(<P2PDialoguePanel />);
    expect(screen.getByRole("region", { name: /canlı p2p ajan diyaloğu paneli/i })).toBeInTheDocument();
    expect(screen.getByRole("log", { name: /p2p diyalog olayları/i })).toBeInTheDocument();
  });
});
