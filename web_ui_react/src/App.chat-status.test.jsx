import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";

const chatStore = {
  sessionId: "session-integration",
  roomId: "workspace:sidar",
  displayName: "Operatör",
  setRoomId: vi.fn(),
  setDisplayName: vi.fn(),
  hydrateRoom: vi.fn(),
  updateParticipants: vi.fn(),
  pushRoomMessage: vi.fn(),
  startAssistantStream: vi.fn(),
  appendChunk: vi.fn(),
  commitAssistantMessage: vi.fn(),
  setError: vi.fn(),
  addTelemetryEvent: vi.fn(),
  newSession: vi.fn(),
  participants: [],
  messages: [],
};

vi.mock("./hooks/useChatStore.js", () => ({
  useChatStore: (selector) => (typeof selector === "function" ? selector(chatStore) : chatStore),
}));

vi.mock("./hooks/useVoiceAssistant.js", () => ({
  useVoiceAssistant: () => ({
    stop: vi.fn(),
    statusLabel: "Hazır",
  }),
}));

vi.mock("./components/ChatWindow.jsx", () => ({ ChatWindow: () => <div /> }));
vi.mock("./components/VoiceAssistantPanel.jsx", () => ({ VoiceAssistantPanel: () => <div /> }));
vi.mock("./components/ChatInput.jsx", () => ({ ChatInput: () => <div /> }));

describe("App /chat websocket status integration", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("shows the unauthenticated StatusBar label when the browser has no token", () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("ws-status")).toHaveAttribute("data-state", "unauthenticated");
    expect(screen.getByTestId("ws-status")).toHaveTextContent("🟠 Token gerekli");
    expect(chatStore.setError).not.toHaveBeenCalled();
  });
});
