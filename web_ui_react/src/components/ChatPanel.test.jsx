import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "./ChatPanel.jsx";

const store = {
  sessionId: "session-1",
  roomId: "workspace:sidar",
  displayName: "Operatör",
  setRoomId: vi.fn((nextRoomId) => {
    store.roomId = nextRoomId;
  }),
  setDisplayName: vi.fn((nextDisplayName) => {
    store.displayName = nextDisplayName;
  }),
  hydrateRoom: vi.fn(),
  updateParticipants: vi.fn(),
  pushRoomMessage: vi.fn(),
  startAssistantStream: vi.fn(),
  appendChunk: vi.fn(),
  commitAssistantMessage: vi.fn(),
  setError: vi.fn(),
  addTelemetryEvent: vi.fn(),
  newSession: vi.fn(),
  participants: [{ id: 1 }, { id: 2 }],
};

const send = vi.fn();
const stop = vi.fn();
let wsStatus = "connected";

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => store,
}));

vi.mock("../hooks/useWebSocket.js", () => ({
  useWebSocket: () => ({ send, status: wsStatus }),
}));

vi.mock("../hooks/useVoiceAssistant.js", () => ({
  useVoiceAssistant: () => ({
    stop,
    statusLabel: "Hazır",
    state: {
      status: "idle",
      isMicActive: false,
      isAssistantAudioPlaying: false,
      queueDepth: 0,
      summary: "Hazır",
      transcript: "",
      vad: { level: 0, speaking: false },
      lastInterruptReason: "",
      assistantTurnId: 0,
      bufferedBytes: 0,
      audioMimeType: "audio/wav",
      diagnostics: [],
    },
    toggle: vi.fn(),
    interrupt: vi.fn(),
    supported: true,
  }),
}));

vi.mock("./ChatWindow.jsx", () => ({ ChatWindow: () => <div>ChatWindow Mock</div> }));
vi.mock("./VoiceAssistantPanel.jsx", () => ({ VoiceAssistantPanel: () => <div>VoiceAssistant Mock</div> }));
vi.mock("./ChatInput.jsx", () => ({
  ChatInput: ({ onSend, disabled }) => (
    <button onClick={() => onSend("Merhaba SİDAR")} disabled={disabled}>
      Test Send
    </button>
  ),
}));
vi.mock("./StatusBar.jsx", () => ({
  StatusBar: ({ onNewSession, collaborators, roomId, voiceStatus, wsStatus }) => (
    <div>
      <span>{`${wsStatus}-${voiceStatus}-${roomId}-${collaborators}`}</span>
      <button onClick={onNewSession}>Yeni Oturum</button>
    </div>
  ),
}));

describe("ChatPanel", () => {
  beforeEach(() => {
    store.roomId = "workspace:sidar";
    store.displayName = "Operatör";
    send.mockClear();
    stop.mockClear();
    wsStatus = "connected";
    Object.values(store).forEach((value) => {
      if (typeof value === "function" && "mockClear" in value) value.mockClear();
    });
  });

  it("wires room inputs to the chat store and sends messages via the websocket hook", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.clear(screen.getByPlaceholderText("workspace:sidar"));
    await user.type(screen.getByPlaceholderText("workspace:sidar"), "workspace:demo");
    await user.clear(screen.getByPlaceholderText("Operatör"));
    await user.type(screen.getByPlaceholderText("Operatör"), "Demo Kullanıcı");
    await user.click(screen.getByRole("button", { name: "Test Send" }));

    expect(store.setRoomId).toHaveBeenCalled();
    expect(store.setDisplayName).toHaveBeenCalled();
    expect(send).toHaveBeenCalledWith("Merhaba SİDAR");
  });

  it("triggers StatusBar onNewSession and starts a fresh session after stopping voice", async () => {
    const user = userEvent.setup();
    render(<ChatPanel />);

    await user.click(screen.getByRole("button", { name: "Yeni Oturum" }));

    expect(stop).toHaveBeenCalledTimes(1);
    expect(store.newSession).toHaveBeenCalledTimes(1);
    expect(stop.mock.invocationCallOrder[0]).toBeLessThan(store.newSession.mock.invocationCallOrder[0]);
  });

  it("disables chat input action when websocket is disconnected", async () => {
    wsStatus = "disconnected";
    render(<ChatPanel />);

    expect(screen.getByRole("button", { name: "Test Send" })).toBeDisabled();
  });
});
