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

// 1. ADIM: Hook'lara geçilen ayarları (options) yakalamak için dışarıda değişkenler tanımlıyoruz
let webSocketOptions = {};
let voiceAssistantOptions = {};

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => store,
}));

// 2. ADIM: useWebSocket mock'unu options'ı yakalayacak şekilde güncelliyoruz
vi.mock("../hooks/useWebSocket.js", () => ({
  useWebSocket: (sessionId, options) => {
    webSocketOptions = options;
    return { send, status: wsStatus };
  },
}));

// 3. ADIM: useVoiceAssistant mock'unu options'ı yakalayacak şekilde güncelliyoruz
vi.mock("../hooks/useVoiceAssistant.js", () => ({
  useVoiceAssistant: (options) => {
    voiceAssistantOptions = options;
    return {
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
    };
  },
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
    webSocketOptions = {};
    voiceAssistantOptions = {};
    
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

  // 4. ADIM: YENİ TEST - Tüm callback fonksiyonlarını tetikleyerek %100 coverage sağlıyoruz
  it("handles all websocket and voice assistant callbacks correctly", () => {
    render(<ChatPanel />);

    // WebSocket event'leri tetiklemesi ve testleri
    webSocketOptions.onStatus("Status Test");
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("status", "Status Test");

    webSocketOptions.onToolCall("Tool Test");
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("tool_call", "Tool Test");

    webSocketOptions.onThought("Thought Test");
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("thought", "Thought Test");

    webSocketOptions.onRoomState({ room_id: "ws:test", messages: [] });
    expect(store.hydrateRoom).toHaveBeenCalledWith({ room_id: "ws:test", messages: [] });

    webSocketOptions.onRoomMessage({ id: "m1", role: "user", content: "test" });
    expect(store.pushRoomMessage).toHaveBeenCalledWith({ id: "m1", role: "user", content: "test" });

    webSocketOptions.onPresence([{ id: "p1" }]);
    expect(store.updateParticipants).toHaveBeenCalledWith([{ id: "p1" }]);

    webSocketOptions.onAssistantStart("req-abc");
    expect(store.startAssistantStream).toHaveBeenCalledWith("req-abc");

    // WebSocket doğrudan callback referansları
    webSocketOptions.onChunk("parça metin", "req-1");
    expect(store.appendChunk).toHaveBeenCalledWith("parça metin", "req-1");

    webSocketOptions.onDone(undefined, "req-1");
    expect(store.commitAssistantMessage).toHaveBeenCalledWith(undefined, "req-1");

    webSocketOptions.onError("WS Hatası");
    expect(store.setError).toHaveBeenCalledWith("WS Hatası");

    webSocketOptions.onRoomEvent({ kind: "room_event", content: "Room Info" });
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("room_event", "Room Info", { kind: "room_event", content: "Room Info" });

    // RoomEvent - kind veya content undefined durumu (fallback)
    webSocketOptions.onRoomEvent({ content: null });
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("status", "", { content: null });

    // Voice Assistant event'leri tetiklemesi ve testleri
    voiceAssistantOptions.onUserTranscript("Nasılsın");
    expect(send).toHaveBeenCalledWith("@Sidar Nasılsın"); // 54. ve 55. Satırların çözümü!

    // Voice assistant doğrudan callback referansları
    voiceAssistantOptions.onAssistantChunk("ses parçası");
    expect(store.appendChunk).toHaveBeenCalledWith("ses parçası");

    voiceAssistantOptions.onAssistantDone();
    expect(store.commitAssistantMessage).toHaveBeenCalled();

    voiceAssistantOptions.onError("Ses Hatası");
    expect(store.setError).toHaveBeenCalledWith("Ses Hatası");

    voiceAssistantOptions.onTelemetry("voice_event", "Mic Active");
    expect(store.addTelemetryEvent).toHaveBeenCalledWith("voice_event", "Mic Active");
  });
});
