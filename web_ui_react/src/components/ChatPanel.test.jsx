import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { ChatPanel } from "./ChatPanel.jsx";

const store = {
  sessionId: "session-1",
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
  participants: [{ id: 1 }, { id: 2 }],
};

const send = vi.fn();
const stop = vi.fn();

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => store,
}));

vi.mock("../hooks/useWebSocket.js", () => ({
  useWebSocket: () => ({ send, status: "connected" }),
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
    send.mockClear();
    stop.mockClear();
    Object.values(store).forEach((value) => {
      if (typeof value === "function" && "mockClear" in value) value.mockClear();
    });
  });

  it("wires room inputs to the chat store and sends messages via the websocket hook", () => {
    render(<ChatPanel />);

    fireEvent.change(screen.getByPlaceholderText("workspace:sidar"), { target: { value: "workspace:demo" } });
    fireEvent.change(screen.getByPlaceholderText("Operatör"), { target: { value: "Demo Kullanıcı" } });
    fireEvent.click(screen.getByRole("button", { name: "Test Send" }));

    expect(store.setRoomId).toHaveBeenCalledWith("workspace:demo");
    expect(store.setDisplayName).toHaveBeenCalledWith("Demo Kullanıcı");
    expect(send).toHaveBeenCalledWith("Merhaba SİDAR");
  });

  it("stops the voice assistant before starting a fresh session", () => {
    render(<ChatPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Yeni Oturum" }));

    expect(stop).toHaveBeenCalledTimes(1);
    expect(store.newSession).toHaveBeenCalledTimes(1);
  });
});