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

let wsMockInstance = null;

beforeEach(() => {
  vi.restoreAllMocks();
  // localStorage stub
  const store = {};
  vi.spyOn(Storage.prototype, "getItem").mockImplementation((key) => store[key] ?? null);
  vi.spyOn(Storage.prototype, "setItem").mockImplementation((key, val) => { store[key] = val; });

  // WebSocket global stub
  wsMockInstance = makeWsMock();
  globalThis.WebSocket = vi.fn(() => wsMockInstance);
  globalThis.WebSocket.CONNECTING = 0;
  globalThis.WebSocket.OPEN = 1;
  globalThis.WebSocket.CLOSING = 2;
  globalThis.WebSocket.CLOSED = 3;
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

  it("sets status to disconnected on WebSocket close", () => {
    localStorage.setItem("sidar_access_token", "tok");
    const { result } = renderHook(() => useWebSocket("s1", {}));

    act(() => {
      wsMockInstance.onclose?.();
    });

    expect(result.current.status).toBe("disconnected");
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
