import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "./useWebSocket.js";

// WebSocket mock factory
function makeWsMock() {
  const ws = {
    readyState: WebSocket.CONNECTING,
    send: vi.fn(),
    close: vi.fn(),
    onmessage: null,
    onerror: null,
    onclose: null,
  };
  return ws;
}

function makeWebSocketCtor(instanceFactory) {
  const ctor = vi.fn(function webSocketCtorProxy(...args) {
    return instanceFactory(...args);
  });
  ctor.CONNECTING = 0;
  ctor.OPEN = 1;
  ctor.CLOSING = 2;
  ctor.CLOSED = 3;
  return ctor;
}

let wsMockInstance = null;

beforeEach(() => {
  vi.restoreAllMocks();
  // localStorage stub
  const store = {};
  vi.spyOn(Storage.prototype, "getItem").mockImplementation((key) => store[key] ?? null);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation((key, val) => { store[key] = val; });

  // WebSocket global stub
  wsMockInstance = makeWsMock();
  globalThis.WebSocket = makeWebSocketCtor(() => wsMockInstance);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useWebSocket — bağlantı kurulumu", () => {
  it("attempts to connect on mount when token exists", () => {
    localStorage.setItem("sidar_access_token", "test-token");
    renderHook(() => useWebSocket("session-1", { roomId: "ws:test" }));
    expect(globalThis.WebSocket).toHaveBeenCalledTimes(1);
  });

  it("sets status to unauthenticated when no token", () => {
    const onError = vi.fn();
    const { result } = renderHook(() =>
      useWebSocket("session-1", { onError })
    );
    expect(result.current.status).toBe("unauthenticated");
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("belirteci"));
  });

  it("does NOT create WebSocket when no token", () => {
    renderHook(() => useWebSocket("session-1", {}));
    expect(globalThis.WebSocket).not.toHaveBeenCalled();
  });

  it("sets status to connecting when token exists", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));
    expect(result.current.status).toBe("connecting");
  });
});

describe("useWebSocket — auth_ok sonrası bağlı durum", () => {
  it("sets status to connected after auth_ok message", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", { roomId: "ws:demo" }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    expect(result.current.status).toBe("connected");
  });
});

describe("useWebSocket — mesaj işleme", () => {
  const setup = (callbacks = {}) => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() =>
      useWebSocket("s1", { roomId: "ws:demo", ...callbacks })
    );
    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });
    return result;
  };

  it("calls onRoomState for room_state message", () => {
    const onRoomState = vi.fn();
    setup({ onRoomState });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_state", room_id: "ws:demo", messages: [] }) });
    });
    expect(onRoomState).toHaveBeenCalledTimes(1);
  });

  it("calls onPresence for presence message", () => {
    const onPresence = vi.fn();
    setup({ onPresence });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "presence", participants: [{ id: 1 }] }) });
    });
    expect(onPresence).toHaveBeenCalledWith([{ id: 1 }]);
  });

  it("calls onRoomMessage for room_message", () => {
    const onRoomMessage = vi.fn();
    setup({ onRoomMessage });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_message", message: { id: "m1" } }) });
    });
    expect(onRoomMessage).toHaveBeenCalledWith({ id: "m1" });
  });

  it("calls onAssistantStart for assistant_stream_start", () => {
    const onAssistantStart = vi.fn();
    setup({ onAssistantStart });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_stream_start", request_id: "req-1" }) });
    });
    expect(onAssistantStart).toHaveBeenCalledWith("req-1");
  });

  it("calls onChunk for assistant_chunk message", () => {
    const onChunk = vi.fn();
    setup({ onChunk });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_chunk", chunk: "parça metin", request_id: "req-1" }) });
    });
    expect(onChunk).toHaveBeenCalledWith("parça metin", "req-1");
  });

  it("calls onDone for assistant_done message", () => {
    const onDone = vi.fn();
    setup({ onDone });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_done", message: { id: "m1" }, request_id: "r1" }) });
    });
    expect(onDone).toHaveBeenCalledWith({ id: "m1" }, "r1");
  });

  it("calls onError for room_error message", () => {
    const onError = vi.fn();
    setup({ onError });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_error", error: "bir hata" }) });
    });
    expect(onError).toHaveBeenCalledWith("bir hata");
  });

  it("routes collaboration_event kinds to status/tool/thought callbacks", () => {
    const onRoomEvent = vi.fn();
    const onStatus = vi.fn();
    const onToolCall = vi.fn();
    const onThought = vi.fn();
    setup({ onRoomEvent, onStatus, onToolCall, onThought });

    act(() => {
      wsMockInstance.onmessage?.({
        data: JSON.stringify({
          type: "collaboration_event",
          event: { kind: "status", source: "supervisor", content: "Plan hazır" },
        }),
      });
    });
    act(() => {
      wsMockInstance.onmessage?.({
        data: JSON.stringify({
          type: "collaboration_event",
          event: { kind: "tool_call", source: "reviewer", content: "repo_search" },
        }),
      });
    });
    act(() => {
      wsMockInstance.onmessage?.({
        data: JSON.stringify({
          type: "collaboration_event",
          event: { kind: "thought", source: "coder", content: "Refactor gerekli" },
        }),
      });
    });

    expect(onRoomEvent).toHaveBeenCalledTimes(3);
    expect(onStatus).toHaveBeenCalledWith("supervisor: Plan hazır");
    expect(onToolCall).toHaveBeenCalledWith("repo_search");
    expect(onThought).toHaveBeenCalledWith("Refactor gerekli");
  });

  it("handles legacy status/tool_call/thought fields and done fallback", () => {
    const onStatus = vi.fn();
    const onToolCall = vi.fn();
    const onThought = vi.fn();
    const onDone = vi.fn();
    setup({ onStatus, onToolCall, onThought, onDone });

    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ status: "işleniyor" }) });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ tool_call: "fs.read" }) });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ thought: "hipotez" }) });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ done: true, content: "tamam" }) });
    });

    expect(onStatus).toHaveBeenCalledWith("işleniyor");
    expect(onToolCall).toHaveBeenCalledWith("fs.read");
    expect(onThought).toHaveBeenCalledWith("hipotez");
    expect(onDone).toHaveBeenCalledWith("tamam");
  });


  it("handles generic chunk and error payloads outside main message types", () => {
    const onChunk = vi.fn();
    const onError = vi.fn();
    setup({ onChunk, onError });

    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ chunk: "legacy chunk" }) });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ error: "legacy error" }) });
    });

    expect(onChunk).toHaveBeenCalledWith("legacy chunk");
    expect(onError).toHaveBeenCalledWith("legacy error");
  });

  it("routes standalone tool_call and thought payloads", () => {
    const onToolCall = vi.fn();
    const onThought = vi.fn();
    setup({ onToolCall, onThought });

    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ tool_call: "python.exec" }) });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: JSON.stringify({ thought: "analysis note" }) });
    });

    expect(onToolCall).toHaveBeenCalledWith("python.exec");
    expect(onThought).toHaveBeenCalledWith("analysis note");
  });

  it("buffers raw text when JSON parsing fails and flushes on [DONE]", () => {
    const onChunk = vi.fn();
    const onDone = vi.fn();
    setup({ onChunk, onDone });

    act(() => {
      wsMockInstance.onmessage?.({ data: "ham metin" });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: " ikinci" });
    });
    act(() => {
      wsMockInstance.onmessage?.({ data: "[DONE]" });
    });

    expect(onChunk).toHaveBeenNthCalledWith(1, "ham metin");
    expect(onChunk).toHaveBeenNthCalledWith(2, " ikinci");
    expect(onDone).toHaveBeenCalledWith("ham metin ikinci");
  });
  it("calls onChunk for raw non-JSON text", () => {
    const onChunk = vi.fn();
    setup({ onChunk });
    act(() => {
      wsMockInstance.onmessage?.({ data: "ham metin" });
    });
    expect(onChunk).toHaveBeenCalledWith("ham metin");
  });

  it("calls onDone for [DONE] signal", () => {
    const onDone = vi.fn();
    setup({ onDone });
    act(() => {
      wsMockInstance.onmessage?.({ data: "[DONE]" });
    });
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});

describe("useWebSocket — onerror / onclose", () => {
  it("sets status to error on WebSocket error", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onError = vi.fn();
    const { result } = renderHook(() => useWebSocket("s1", { onError }));

    act(() => {
      wsMockInstance.onerror?.();
    });

    expect(result.current.status).toBe("error");
    expect(onError).toHaveBeenCalledWith("WebSocket bağlantı hatası.");
  });

  it("sets status to reconnecting on WebSocket close", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));

    act(() => {
      wsMockInstance.onclose?.();
    });

    expect(result.current.status).toBe("reconnecting");
  });
});

describe("useWebSocket — send", () => {
  it("sends JSON payload when connection is open", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() =>
      useWebSocket("s1", { roomId: "ws:demo", displayName: "Test" })
    );

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    // auth_ok sonrası joinRoom da bir send() çağrısı yapar; onu sıfırla
    wsMockInstance.send.mockClear();

    act(() => {
      result.current.send("merhaba");
    });

    expect(wsMockInstance.send).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(wsMockInstance.send.mock.calls[0][0]);
    expect(payload.action).toBe("message");
    expect(payload.message).toBe("merhaba");
  });

  it("calls onError when connection is not open", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onError = vi.fn();
    const { result } = renderHook(() => useWebSocket("s1", { onError }));

    act(() => {
      result.current.send("bağlantısız mesaj");
    });

    expect(onError).toHaveBeenCalledWith("Bağlantı kapalı.");
  });
});

describe("useWebSocket — disconnect", () => {
  it("closes the WebSocket on disconnect", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));

    act(() => {
      result.current.disconnect();
    });

    expect(wsMockInstance.close).toHaveBeenCalledTimes(1);
  });
});

describe("useWebSocket — eksik branch testleri (100% Coverage için)", () => {
  it("uses wss:// when protocol is https: (Satır 4)", () => {
    const originalLocation = globalThis.location;
    delete globalThis.location;
    globalThis.location = { protocol: "https:", host: "localhost" };

    localStorage.setItem("sidar_access_token", "tok");
    renderHook(() => useWebSocket("s1", {}));

    expect(globalThis.WebSocket).toHaveBeenCalledWith("wss://localhost/ws/chat", ["tok"]);

    globalThis.location = originalLocation;
  });

  it("does not reconnect if already OPEN (Satır 44)", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));

    globalThis.WebSocket.mockClear();

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      result.current.connect();
    });

    expect(globalThis.WebSocket).not.toHaveBeenCalled();
  });

  it("handles joinRoom edge cases and fallbacks (Satır 33-36)", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    wsMockInstance.send.mockClear();

    act(() => {
      result.current.joinRoom("new_room", null);
    });

    const payload = JSON.parse(wsMockInstance.send.mock.calls[0][0]);
    expect(payload.display_name).toBe("Operatör");
  });

  it("handles missing optional fields in incoming WS messages (Satır 76-113)", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onRoomState = vi.fn();
    const onChunk = vi.fn();
    const onDone = vi.fn();
    const onStatus = vi.fn();
    const onRoomMessage = vi.fn();

    renderHook(() => useWebSocket("s1", {
      onRoomState,
      onChunk,
      onDone,
      onStatus,
      onRoomMessage,
    }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_state" }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_message" }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_chunk" }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_done" }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "collaboration_event", event: {} }) });
    });

    expect(onRoomState).toHaveBeenCalled();
    expect(onRoomMessage).not.toHaveBeenCalled();
    expect(onChunk).toHaveBeenCalledWith("", "");
    expect(onDone).toHaveBeenCalledWith(null, "");
    expect(onStatus).toHaveBeenCalledWith("room: ");
  });

  it("sends an object payload directly instead of a string (Satır 174)", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", { roomId: "ws:demo", displayName: "Test" }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
    });

    wsMockInstance.send.mockClear();

    act(() => {
      result.current.send({ action: "custom_ping", customValue: 123 });
    });

    const payload = JSON.parse(wsMockInstance.send.mock.calls[0][0]);
    expect(payload.action).toBe("custom_ping");
    expect(payload.customValue).toBe(123);
    expect(payload.room_id).toBe("ws:demo");
  });

  it("covers collaboration/tool/thought and room_error fallback branches", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onToolCall = vi.fn();
    const onThought = vi.fn();
    const onError = vi.fn();

    renderHook(() => useWebSocket("s1", { onToolCall, onThought, onError }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "collaboration_event", event: { kind: "tool_call" } }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "collaboration_event", event: { kind: "thought" } }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "room_error" }) });
    });

    expect(onToolCall).toHaveBeenCalledWith("");
    expect(onThought).toHaveBeenCalledWith("");
    expect(onError).toHaveBeenCalledWith("Ortak çalışma alanı hatası.");
  });

  it("covers done fallback when buffer and content are empty", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onDone = vi.fn();

    renderHook(() => useWebSocket("s1", { onDone }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "done" }) });
    });

    expect(onDone).toHaveBeenCalledWith("");
  });

  it("covers presence and assistant_start fallback branches", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const onPresence = vi.fn();
    const onAssistantStart = vi.fn();

    renderHook(() => useWebSocket("s1", { onPresence, onAssistantStart }));

    act(() => {
      wsMockInstance.readyState = WebSocket.OPEN;
      wsMockInstance.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "presence" }) });
      wsMockInstance.onmessage?.({ data: JSON.stringify({ type: "assistant_stream_start" }) });
    });

    expect(onPresence).toHaveBeenCalledWith([]);
    expect(onAssistantStart).toHaveBeenCalledWith("");
  });
});
