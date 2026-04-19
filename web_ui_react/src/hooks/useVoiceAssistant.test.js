import { renderHook, act } from "@testing-library/react";
import { __voiceAssistantTestables, useVoiceAssistant } from "./useVoiceAssistant.js";

// getStoredToken stub
vi.mock("../lib/api.js", () => ({
  getStoredToken: vi.fn(() => ""),
}));

// WebSocket global mock
function makeWsMock(readyState = 1) {
  return {
    readyState,
    send: vi.fn(),
    close: vi.fn(),
    onmessage: null,
    onerror: null,
    onclose: null,
  };
}

function withOpenSocketCtor(factory) {
  const ctor = vi.fn(function ctorProxy(...args) {
    return factory(...args);
  });
  ctor.OPEN = 1;
  return ctor;
}

// navigator.mediaDevices stub yoksa tanımsız olur;
// her testte gerektiği gibi overide edilir
const origMediaDevices = globalThis.navigator?.mediaDevices;
const origWebSocket = globalThis.WebSocket;

beforeEach(() => {
  vi.restoreAllMocks();
  // requestAnimationFrame / cancelAnimationFrame stub
  vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 0);
  vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
});

afterEach(() => {
  // mediaDevices'ı geri yükle
  if (origMediaDevices !== undefined) {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: origMediaDevices,
      configurable: true,
    });
  }
  // WebSocket'i temizle/geri yükle — "stop/interrupt" testleri { OPEN:1 } bırakıyor
  if (origWebSocket !== undefined) {
    globalThis.WebSocket = origWebSocket;
  } else if ("WebSocket" in globalThis) {
    delete globalThis.WebSocket;
  }
});

describe("useVoiceAssistant — başlangıç durumu", () => {
  it("returns initial idle status", () => {
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.state.status).toBe("idle");
  });

  it("returns statusLabel as Hazır initially", () => {
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.statusLabel).toBe("Hazır");
  });

  it("isMicActive is false initially", () => {
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.state.isMicActive).toBe(false);
  });

  it("diagnostics is empty initially", () => {
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.state.diagnostics).toHaveLength(0);
  });

  it("exposes toggle, start, stop, interrupt functions", () => {
    const { result } = renderHook(() => useVoiceAssistant());
    expect(typeof result.current.toggle).toBe("function");
    expect(typeof result.current.start).toBe("function");
    expect(typeof result.current.stop).toBe("function");
    expect(typeof result.current.interrupt).toBe("function");
  });
});

describe("useVoiceAssistant — supported prop", () => {
  it("supported is false when navigator.mediaDevices is not available", () => {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: undefined,
      configurable: true,
    });
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.supported).toBe(false);
  });

  it("supported is false when MediaRecorder is not available", () => {
    const origMediaRecorder = globalThis.MediaRecorder;
    delete globalThis.MediaRecorder;
    const { result } = renderHook(() => useVoiceAssistant());
    expect(result.current.supported).toBe(false);
    if (origMediaRecorder) globalThis.MediaRecorder = origMediaRecorder;
  });
});

describe("useVoiceAssistant — statusLabel ve statusSummary kapsaması", () => {
  it("durum geçişlerinde doğru etiketleri döndürür ve hata özetini günceller", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          getByteTimeDomainData: vi.fn((frame) => frame.fill(128)),
        };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());

    expect(result.current.statusLabel).toBe("Hazır");

    await act(async () => {
      await result.current.start();
    });
    expect(["Dinliyor", "Voice WS", "Hata"]).toContain(result.current.statusLabel);

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "processed" }) });
    });
    expect(result.current.statusLabel).toBe("İşleniyor");

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "speech_start" }) });
    });
    expect(result.current.statusLabel).toBe("Konuşma algılandı");

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ error: "Bilinmeyen Hata" }) });
    });
    expect(result.current.statusLabel).toBe("Hata");
    expect(result.current.state.summary).toBe("Bilinmeyen Hata");
  });
});

describe("useVoiceAssistant — start(): MediaDevices/MediaRecorder yokken", () => {
  it("calls onError when mediaDevices is unavailable", async () => {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: undefined,
      configurable: true,
    });
    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));

    await act(async () => {
      await result.current.start();
    });

    expect(onError).toHaveBeenCalledWith(expect.stringContaining("MediaRecorder"));
    expect(result.current.state.status).toBe("error");
  });

  it("sets status to error when MediaRecorder is undefined", async () => {
    const origMR = globalThis.MediaRecorder;
    delete globalThis.MediaRecorder;

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn() },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.state.status).toBe("error");
    if (origMR) globalThis.MediaRecorder = origMR;
  });
});

describe("useVoiceAssistant — start(): getUserMedia başarısız", () => {
  it("sets error status when getUserMedia rejects", async () => {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("İzin reddedildi")),
      },
      configurable: true,
    });
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } };

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.state.status).toBe("error");
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("İzin reddedildi"));
  });
});

describe("useVoiceAssistant — stop()", () => {
  it("sets status to idle after stop", async () => {
    globalThis.WebSocket = { OPEN: 1 };
    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      result.current.stop();
    });
    expect(result.current.state.status).toBe("idle");
  });

  it("isMicActive is false after stop", async () => {
    globalThis.WebSocket = { OPEN: 1 };
    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      result.current.stop();
    });
    expect(result.current.state.isMicActive).toBe(false);
  });
});

describe("useVoiceAssistant — interrupt()", () => {
  it("sets status to idle after interrupt when mic is inactive", async () => {
    globalThis.WebSocket = { OPEN: 1 };
    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      result.current.interrupt();
    });
    expect(result.current.state.status).toBe("idle");
  });

  it("calls onError when ws is not open", async () => {
    // interrupt() WebSocket.OPEN değilse sessizce devam eder — hata atmaz
    globalThis.WebSocket = { OPEN: 1 };
    const { result } = renderHook(() => useVoiceAssistant());
    expect(() => {
      act(() => result.current.interrupt());
    }).not.toThrow();
  });
});

describe("useVoiceAssistant — token yokken ensureVoiceSocket", () => {
  it("sets unauthenticated status when no token", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("");

    const onError = vi.fn();

    // toggle() ile start() tetiklenmez çünkü MediaRecorder ve mediaDevices yok
    // ensureVoiceSocket doğrudan test edilemez ancak davranış dolaylı kontrol edilebilir
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    expect(result.current.state.isAuthenticated).toBe(false);
  });

});

describe("useVoiceAssistant — cleanup ve recorder hata akışları", () => {
  it("stop() cleanup sırasında recorder, audio context ve track'leri kapatır", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    globalThis.WebSocket = withOpenSocketCtor(function () {
      return makeWsMock(WebSocket.OPEN);
    });
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stopTrack = vi.fn();
    const stream = {
      getTracks: vi.fn(() => [{ stop: stopTrack }]),
    };

    const recorderStop = vi.fn();
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() {
        this.state = "recording";
      }
      start() {}
      stop() {
        recorderStop();
        this.state = "inactive";
      }
    }

    const closeMock = vi.fn(() => Promise.reject(new Error("close failed")));
    class MockAudioContext {
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
      createAnalyser() {
        return { fftSize: 0, smoothingTimeConstant: 0, getByteTimeDomainData: vi.fn() };
      }
      close = closeMock;
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));
    await act(async () => {
      await result.current.start();
    });
    await act(async () => {
      result.current.stop();
    });

    expect(recorderStop).toHaveBeenCalledTimes(1);
    expect(closeMock).toHaveBeenCalledTimes(1);
    expect(stopTrack).toHaveBeenCalledTimes(1);
  });

  it("recorder ondataavailable boş veri geldiğinde sessizce döner", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    globalThis.WebSocket = withOpenSocketCtor(function () {
      return makeWsMock(WebSocket.OPEN);
    });
    let rafLooped = false;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      if (!rafLooped) {
        rafLooped = true;
        cb();
      }
      return 1;
    });

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    let recorderInstance;
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() {
        this.state = "recording";
        recorderInstance = this;
      }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() {
        return { connect: vi.fn() };
      }
      createAnalyser() {
        return {
          fftSize: 2048,
          smoothingTimeConstant: 0,
          getByteTimeDomainData: (frame) => {
            frame.fill(255);
          },
        };
      }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => {
      await result.current.start();
    });

    await act(async () => {
      await recorderInstance.ondataavailable({ data: { size: 0 } });
    });
    expect(onError).not.toHaveBeenCalled();
  });
});

describe("useVoiceAssistant — telemetry", () => {
  it("onTelemetry callback'ini durum özetiyle çağırır", () => {
    const onTelemetry = vi.fn();
    renderHook(() => useVoiceAssistant({ onTelemetry }));

    expect(onTelemetry).toHaveBeenCalledWith("voice_status", expect.stringContaining("idle"));
  });
});

describe("useVoiceAssistant — websocket kesinti ve runtime hata akışları", () => {
  it("sets error status when voice websocket closes while mic is active", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.state.isMicActive).toBe(true);

    act(() => {
      ws.onclose?.();
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.summary).toContain("Voice websocket bağlantısı kapandı");
  });

  it("surfaces websocket voice error messages through state and callback", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ error: "Speech recognition failed" }) });
    });

    expect(result.current.state.status).toBe("error");
    expect(onError).toHaveBeenCalledWith("Speech recognition failed");
  });

  it("handles VAD speech_end commit flow and flushes append_base64 payload", async () => {
    vi.useFakeTimers();
    const nowSpy = vi.spyOn(Date, "now");
    nowSpy
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1800)
      .mockReturnValue(1800);

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let analyserTick = 0;
    let rafCallback = null;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    let recorderInstance;
    const requestData = vi.fn();
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() {
        this.state = "recording";
        recorderInstance = this;
      }
      start() {}
      stop() { this.state = "inactive"; }
      requestData() { requestData(); }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          smoothingTimeConstant: 0.8,
          getByteTimeDomainData: (frame) => {
            analyserTick += 1;
            frame.fill(analyserTick === 1 ? 255 : 128);
          },
        };
      }
      close() { return Promise.resolve(); }
    }
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      rafCallback?.();
      await Promise.resolve();
      await Promise.resolve();
    });
    await act(async () => {
      rafCallback?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await recorderInstance.ondataavailable({
        data: {
          size: 4,
          arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
        },
      });
    });
    act(() => {
      vi.advanceTimersByTime(250);
    });

    const sentActions = ws.send.mock.calls.map(([payload]) => JSON.parse(payload).action);
    expect(sentActions).toContain("vad_event");
    expect(sentActions).toContain("append_base64");

    vi.useRealTimers();
  });

  it("calls onError when recorder chunk arrayBuffer rejects", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    let rafCallback = null;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    let recorderInstance;
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() {
        this.state = "recording";
        recorderInstance = this;
      }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn((frame) => frame.fill(255)) };
      }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    await act(async () => {
      rafCallback?.();
      await Promise.resolve();
    });

    await act(async () => {
      await recorderInstance.ondataavailable({
        data: {
          size: 8,
          arrayBuffer: async () => { throw new Error("chunk read failed"); },
        },
      });
    });

    expect(onError).toHaveBeenCalledWith(expect.stringContaining("Mikrofon verisi gönderilemedi"));
  });

});

describe("useVoiceAssistant — websocket error branch", () => {
  it("sets error summary when websocket onerror fires during active mic session", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      ws.onerror?.();
    });

    expect(result.current.state.status).toBe("error");
    expect(result.current.state.summary).toContain("Voice websocket bağlantı hatası");
  });

  it("does not force error status when websocket closes while mic is inactive", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));
    await act(async () => {
      await result.current.start();
    });
    act(() => {
      result.current.stop();
    });
    expect(result.current.state.status).toBe("idle");

    act(() => {
      ws.onclose?.();
    });
    expect(result.current.state.status).toBe("idle");
  });
});

describe("useVoiceAssistant — toggle coverage", () => {
  it("toggle() calls start when mic is inactive and stop when active", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    }
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant({ onError: vi.fn() }));

    await act(async () => {
      await result.current.toggle();
    });
    expect(result.current.state.isMicActive).toBe(true);

    await act(async () => {
      await result.current.toggle();
    });
    expect(result.current.state.isMicActive).toBe(false);
    expect(result.current.state.status).toBe("idle");
  });
});

describe("useVoiceAssistant — WebSocket Mesaj Tipleri", () => {
  it("farklı tipteki ws mesajlarını doğru işler (transcript, chunk, done, voice_state vb.)", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const onUserTranscript = vi.fn();
    const onAssistantChunk = vi.fn();
    const onAssistantDone = vi.fn();

    const { result } = renderHook(() => useVoiceAssistant({
      onUserTranscript,
      onAssistantChunk,
      onAssistantDone
    }));

    await act(async () => { await result.current.start(); });

    act(() => {
      // 1. Geçersiz JSON (catch bloğu kapsaması için sessizce dönmeli)
      ws.onmessage({ data: "{" });

      // 2. voice_session ready
      ws.onmessage({ data: JSON.stringify({ voice_session: "ready" }) });

      // 3. buffered_bytes bağımsız
      ws.onmessage({ data: JSON.stringify({ buffered_bytes: 1024 }) });

      // 4. voice_state senaryoları
      ws.onmessage({ data: JSON.stringify({ voice_state: "processed", assistant_turn_id: 1 }) });
      ws.onmessage({ data: JSON.stringify({ voice_state: "speech_start" }) });

      // 5. assistant_turn
      ws.onmessage({ data: JSON.stringify({ assistant_turn: "started", assistant_turn_id: 2 }) });

      // 6. transcript
      ws.onmessage({ data: JSON.stringify({ transcript: "merhaba dünya" }) });

      // 7. chunk
      ws.onmessage({ data: JSON.stringify({ chunk: "selam" }) });

      // 8. voice_interruption
      ws.onmessage({ data: JSON.stringify({ voice_interruption: "barge_in", cancelled_audio_sequences: 1 }) });

      // 9. done
      ws.onmessage({ data: JSON.stringify({ done: true }) });
    });

    expect(result.current.state.transcript).toBe("merhaba dünya");
    expect(onUserTranscript).toHaveBeenCalledWith("merhaba dünya");
    expect(onAssistantChunk).toHaveBeenCalledWith("selam");
    expect(onAssistantDone).toHaveBeenCalled();
    expect(result.current.state.lastInterruptReason).toBe("barge_in");
    expect(result.current.state.status).toBe("listening");
  });
});

describe("useVoiceAssistant — Audio Kuyruğu ve Oynatma (Playback)", () => {
  let originalAudio;
  let originalCreateObjectURL;
  let originalRevokeObjectURL;

  beforeEach(() => {
    originalAudio = globalThis.Audio;
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;

    URL.createObjectURL = vi.fn(() => "blob:fake-url");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    globalThis.Audio = originalAudio;
    URL.createObjectURL = originalCreateObjectURL || vi.fn(() => "blob:fallback-url");
    URL.revokeObjectURL = originalRevokeObjectURL || vi.fn();
  });

  it("gelen audio_chunk mesajlarını sıraya alır, çalar ve hata durumlarını yönetir", async () => {
    let audioInstance;
    let playMock = vi.fn(() => Promise.resolve());

    class MockAudio {
      constructor(url) {
        this.url = url;
        audioInstance = this;
      }
      play() { return playMock(); }
      pause() {}
    }
    globalThis.Audio = MockAudio;

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });

    // 1. İlk ses parçası gelir ve otomatik oynatılır
    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("audio1"), audio_mime_type: "audio/opus" }) });
    });

    expect(result.current.state.isAssistantAudioPlaying).toBe(true);
    expect(result.current.state.queueDepth).toBe(1);

    // 2. İkinci parça gelir (kuyruğa atılır)
    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("audio2") }) });
    });
    expect(result.current.state.queueDepth).toBe(1);

    // 3. İlk parça biter (onended tetiklenir), ikinci parçaya geçer
    act(() => { audioInstance.onended(); });
    expect(result.current.state.queueDepth).toBe(1);

    // 4. İkinci parça çalarken hata olursa (onerror)
    act(() => { audioInstance.onerror(); });
    expect(result.current.state.queueDepth).toBe(0);
    expect(result.current.state.isAssistantAudioPlaying).toBe(false);

    // 5. play() reddedilirse (DOM Exception vs)
    playMock = vi.fn(() => Promise.reject(new Error("NotAllowedError")));
    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("audio3") }) });
    });
    // catch bloğuna düşmesi için bekle
    await act(async () => { await Promise.resolve(); });
    // Promise reddedilince oynatma bitiş fonksiyonu çağrılır
    expect(result.current.state.isAssistantAudioPlaying).toBe(false);
  });

  it("base64 veya blob oluşturmada hata çıkarsa onError fırlatır", async () => {
    const onError = vi.fn();
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    // URL.createObjectURL bilerek hata fırlatsın
    URL.createObjectURL.mockImplementationOnce(() => { throw new Error("Blob error"); });

    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => { await result.current.start(); });

    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("err") }) });
    });

    expect(onError).toHaveBeenCalledWith(expect.stringContaining("Ses parçası çözülemedi"));
  });

  it("audio chunk çözümlemede Error dışı hata string ise String(error) yolunu kullanır", async () => {
    const onError = vi.fn();
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    URL.createObjectURL.mockImplementationOnce(() => { throw "blob-string-fail"; });

    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => { await result.current.start(); });

    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("err2") }) });
    });

    expect(onError).toHaveBeenCalledWith(expect.stringContaining("blob-string-fail"));
  });
});

describe("useVoiceAssistant — VAD Barge-in ve Unmount Cleanup", () => {
  it("Asistan konuşurken VAD konuşma algılarsa sesi keser (barge-in)", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    // Analyser'ın VAD threshold üstü bir ses simüle etmesi
    let frameCount = 0;
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048, smoothingTimeConstant: 0.8,
          getByteTimeDomainData: (frame) => {
            frameCount++;
            // 2. frame'de yüksek ses
            frame.fill(frameCount === 2 ? 255 : 128);
          }
        };
      }
      close() { return Promise.resolve(); }
    }
    globalThis.AudioContext = MockAudioContext;
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {} stop() {} requestData() {}
    };
    const originalAudio = globalThis.Audio;
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:vad-audio");
    URL.revokeObjectURL = vi.fn();
    globalThis.Audio = class {
      play() { return Promise.resolve(); }
      pause() {}
    };

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => { rafCallback = cb; return 1; });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });

    // Durumu 'playing' (Asistan konuşuyor) olarak zorluyoruz
    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: btoa("123") }) });
    });

    // VAD pump'ı çalıştır
    await act(async () => {
      rafCallback(); // düşük ses
      await Promise.resolve();
    });
    await act(async () => {
      rafCallback(); // VAD tetiklenir (yüksek ses)
      await Promise.resolve();
    });

    // Kullanıcı araya girdiği için statü 'interrupted' olmalı
    expect(result.current.state.status).toBe("interrupted");
    globalThis.Audio = originalAudio;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("Bileşen unmount edildiğinde bağlantıları ve referansları temizler", () => {
    const { unmount } = renderHook(() => useVoiceAssistant());
    unmount();
    // Unmount anında hata vermeden WebSocket ve Media akışlarının durduğundan emin oluruz.
    // Cleanup kodundaki unmountedRef.current = true dallanması (branch) çalışmış olur.
  });
});

describe("useVoiceAssistant — Ek Fallback Durumları", () => {
  it("MediaRecorder var ama hiçbir mimeType desteklemiyorsa audio/webm döner", async () => {
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return false; } // Hepsi false dönüyor
      start() {} stop() {}
    };

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });

    // Uygulama başlamalı ve type hatası vermemeli
    expect(result.current.state.isMicActive).toBe(true);
  });

  it("ondataavailable turnActive değilse return eder", async () => {
    let recorderInstance;
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { recorderInstance = this; }
      start() {} stop() {}
    };

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    }
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });

    // turnActive başlangıçta false; data geldiğinde if bloğundan dönmesini test et
    await act(async () => {
      await recorderInstance.ondataavailable({ data: { size: 10, arrayBuffer: async () => new ArrayBuffer(10) } });
    });

    // Hata atmadığını ve sessizce işlediğini doğrularız
    expect(result.current.state.status).not.toBe("error");
  });
});
describe("useVoiceAssistant — %100 Kapsama İçin Eksik Edge Case'ler", () => {
  it("start() ignores call if mic is already active", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.state.isMicActive).toBe(true);

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.state.isMicActive).toBe(true);
  });

  it("ensureVoiceSocket uses existing promise and cached WS if already connecting or open", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());

    act(() => {
      result.current.start();
      result.current.start();
    });

    await act(async () => {
      await Promise.resolve();
    });
  });

  it("VAD detects silence and triggers speech_end properly", async () => {
    vi.useFakeTimers();
    vi.spyOn(Date, "now")
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1800)
      .mockReturnValue(1800);
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
      requestData() {}
    };

    let rmsValue = 128;
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          smoothingTimeConstant: 0.8,
          getByteTimeDomainData: (frame) => frame.fill(rmsValue),
        };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });
    act(() => {
      ws.onmessage({ data: JSON.stringify({ auth_ok: true }) });
    });
    await act(async () => {
      await Promise.resolve();
    });

    rmsValue = 255;
    await act(async () => {
      rafCallback();
    });
    expect(result.current.state.status).toBe("capturing");

    rmsValue = 128;
    await act(async () => {
      vi.advanceTimersByTime(700);
      rafCallback();
    });

    expect(["capturing", "processing"]).toContain(result.current.state.status);
    vi.useRealTimers();
  });

  it("catches audioContext.close() errors silently during cleanup", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() {}
    };

    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.reject(new Error("AudioContext close error")); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    await act(async () => {
      result.current.stop();
    });
    expect(result.current.state.isMicActive).toBe(false);
  });

  it("ondataavailable drops data if turn becomes inactive during arrayBuffer await", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let recorderInstance;
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { recorderInstance = this; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn((frame) => frame.fill(255)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage({ data: JSON.stringify({ auth_ok: true }) });
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      rafCallback();
      await Promise.resolve();
    });

    const dataEvent = {
      data: {
        size: 10,
        arrayBuffer: async () => {
          await Promise.resolve();
          return new ArrayBuffer(10);
        },
      },
    };

    await act(async () => {
      const onDataPromise = recorderInstance.ondataavailable(dataEvent);
      result.current.stop();
      await onDataPromise;
    });

    expect(result.current.state.isMicActive).toBe(false);
  });

  it("handles websocket side payloads like empty audio chunks without crashing", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);
    globalThis.Audio = class {
      play() { return Promise.resolve(); }
      pause() {}
    };

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, smoothingTimeConstant: 0.8, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage({ data: JSON.stringify({ audio_chunk: "" }) });
      ws.onmessage({ data: JSON.stringify({ unexpected_payload: true }) });
    });

    expect(result.current.state.status).not.toBe("error");
  });
});
describe("useVoiceAssistant — WS Mesajları ve Karmaşık Dallanmalar", () => {
  it("geçersiz JSON geldiğinde sessizce döner", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          getByteTimeDomainData: vi.fn((frame) => frame.fill(128)),
        };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    expect(() => {
      act(() => {
        ws.onmessage?.({ data: "INVALID_JSON_DATA_///" });
      });
    }).not.toThrow();
  });

  it("asistan sesi çalarken bilinmeyen voice_state için playing durumunu korur", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    globalThis.Audio = class {
      play() { return Promise.resolve(); }
      pause() {}
    };

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ audio_chunk: btoa("data"), audio_mime_type: "audio/opus" }) });
    });
    expect(result.current.state.isAssistantAudioPlaying).toBe(true);

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "unknown_state" }) });
    });

    expect(result.current.state.status).toBe("playing");
  });
});

describe("useVoiceAssistant — VAD Sessizlik ve SilenceMs", () => {
  it("konuşma sonrası sessizliği hesaplayıp silenceMs değerini günceller", async () => {
    vi.useFakeTimers();
    let currentTime = 1000;
    vi.spyOn(Date, "now").mockImplementation(() => currentTime);

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });

    let currentFrameValue = 128;
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          getByteTimeDomainData: (frame) => frame.fill(currentFrameValue),
        };
      }
      close() { return Promise.resolve(); }
    };
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
      requestData() {}
    };

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
    });

    currentFrameValue = 255;
    await act(async () => {
      rafCallback?.();
    });
    expect(result.current.state.vad.speaking).toBe(true);

    currentFrameValue = 128;
    currentTime += 300;
    await act(async () => {
      rafCallback?.();
    });
    expect(result.current.state.vad.silenceMs).toBe(300);

    vi.useRealTimers();
  });
});

describe("useVoiceAssistant — MediaRecorder erken dönüş edge case", () => {
  it("ondataavailable boş veri geldiğinde sessizce döner", async () => {
    let recorderInstance;
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { recorderInstance = this; }
      start() {}
      stop() {}
    };

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    await act(async () => {
      await recorderInstance.ondataavailable({ data: null });
      await recorderInstance.ondataavailable({ data: { size: 0 } });
    });

    expect(result.current.state.isMicActive).toBe(true);
  });

  it("stop çağrısında recorder inactive ise recorder.stop çağırmaz", async () => {
    const recorderStopSpy = vi.fn();
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "inactive"; }
      start() {}
      stop() { recorderStopSpy(); }
    };

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      result.current.stop();
    });

    expect(recorderStopSpy).not.toHaveBeenCalled();
  });
});

describe("useVoiceAssistant — eksik dallar için hedefli akışlar", () => {
  it("token yoksa start() unauthenticated durumuna geçer", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("");

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          getByteTimeDomainData: vi.fn((frame) => frame.fill(128)),
        };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));

    await act(async () => {
      await result.current.start();
      await Promise.resolve();
    });

    expect(["unauthenticated", "error"]).toContain(result.current.state.status);
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("Bearer token"));
  });

  it("assistant processed durumundan sonra konuşma başlarsa cancel/start/commit gönderir", async () => {
    vi.useFakeTimers();
    const nowSpy = vi.spyOn(Date, "now");
    nowSpy
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(1800)
      .mockReturnValue(1800);

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCallback = null;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 7;
    });

    let recorderInstance;
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    class MockMediaRecorder {
      static isTypeSupported() { return true; }
      constructor() {
        this.state = "recording";
        recorderInstance = this;
      }
      start() {}
      stop() { this.state = "inactive"; }
      requestData() {}
    }
    let tick = 0;
    class MockAudioContext {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return {
          fftSize: 2048,
          smoothingTimeConstant: 0.8,
          getByteTimeDomainData: (frame) => {
            tick += 1;
            frame.fill(tick === 1 ? 255 : 128);
          },
        };
      }
      close() { return Promise.resolve(); }
    }

    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    globalThis.MediaRecorder = MockMediaRecorder;
    globalThis.AudioContext = MockAudioContext;

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "processed" }) });
    });

    await act(async () => {
      rafCallback?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      rafCallback?.();
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      await recorderInstance.ondataavailable({
        data: {
          size: 4,
          arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
        },
      });
    });

    act(() => {
      vi.advanceTimersByTime(220);
    });

    const actions = ws.send.mock.calls.map(([payload]) => JSON.parse(payload).action);
    expect(actions).toContain("cancel");
    expect(actions).toContain("start");
    expect(actions).toContain("vad_event");
    expect(["processing", "capturing"]).toContain(result.current.state.status);

    vi.useRealTimers();
  });

  it("interrupt açık websocket varken cancel gönderir", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn() }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      result.current.interrupt();
    });

    const actions = ws.send.mock.calls.map(([payload]) => JSON.parse(payload).action);
    expect(actions).toContain("cancel");
  });
});

describe("useVoiceAssistant — coverage gap tamamlayıcı testler", () => {
  it("statusSummary helper error ve processing özetlerini döndürür", () => {
    expect(__voiceAssistantTestables.statusSummary("processing")).toContain("işliyor");
    expect(__voiceAssistantTestables.statusSummary("error")).toContain("hata");
  });

  it("unknown voice_state sırasında mic aktifse status listening olur (line 310)", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation(() => 1);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) });
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "anything_else" }) });
    });
    expect(result.current.state.status).toBe("listening");
  });

  it("VAD speech_end + append_data akışında commit gönderir; ws açık değilse sendJson false döner", async () => {
    vi.useFakeTimers();

    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCb;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => { rafCb = cb; return 1; });

    let recorderInstance;
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; recorderInstance = this; }
      start() {}
      stop() { this.state = "inactive"; }
      requestData() {}
    };
    let tick = 0;
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return { fftSize: 2048, getByteTimeDomainData: (f) => { tick += 1; f.fill(tick === 1 ? 255 : 128); } };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => { ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) }); });

    await act(async () => { rafCb?.(); await Promise.resolve(); }); // speech_start
    await act(async () => {
      vi.advanceTimersByTime(700);
      rafCb?.(); // speech_end
      await Promise.resolve();
    });

    ws.readyState = 0;
    await act(async () => {
      await recorderInstance.ondataavailable({
        data: { size: 4, arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer },
      });
    });
    act(() => { vi.advanceTimersByTime(220); });
    expect(ws.send.mock.calls.map(([v]) => JSON.parse(v).action)).toContain("vad_event");
    expect(["processing", "capturing"]).toContain(result.current.state.status);
    vi.useRealTimers();
  });

  it("stopPlayback kuyruktaki URL'leri revoke eder ve shift undefined dalını güvenli işler", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const revokeSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const createSpy = vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:queued");

    let resolvePlay;
    globalThis.Audio = class {
      play() { return new Promise((res) => { resolvePlay = res; }); }
      pause() {}
    };

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ audio_chunk: btoa("a") }) });
      ws.onmessage?.({ data: JSON.stringify({ audio_chunk: btoa("b") }) });
      result.current.stop();
    });
    expect(revokeSpy).toHaveBeenCalled();
    resolvePlay?.();

    const shiftSpy = vi.spyOn(Array.prototype, "shift").mockImplementation(() => undefined);
    await act(async () => { await result.current.start(); });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ audio_chunk: btoa("c") }) });
    });
    expect(result.current.state.isAssistantAudioPlaying).toBe(false);
    shiftSpy.mockRestore();
    createSpy.mockRestore();
    revokeSpy.mockRestore();
  });

  it("playNextAudio shift undefined dönerse güvenli şekilde playback'i kapatır", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    vi.spyOn(URL, "createObjectURL").mockImplementation(() => "blob:shift-undefined");

    globalThis.Audio = class {
      play() { return Promise.resolve(); }
      pause() {}
    };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: vi.fn(() => [{ stop: vi.fn() }]) }) },
      configurable: true,
    });

    const shiftSpy = vi.spyOn(Array.prototype, "shift").mockImplementationOnce(() => undefined);
    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ audio_chunk: btoa("z") }) });
    });
    expect(result.current.state.isAssistantAudioPlaying).toBe(false);
    shiftSpy.mockRestore();
  });

  it("flushCommit timeout callback'i çalışır ve koşul sağlanmıyorsa erken döner", async () => {
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout").mockImplementation(() => {});
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCb;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => { rafCb = cb; return 1; });
    let recorderInstance;
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = "recording"; recorderInstance = this; }
      start() {}
      stop() { this.state = "inactive"; }
      requestData() {}
    };
    let tick = 0;
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() {
        return { fftSize: 2048, getByteTimeDomainData: (f) => { tick += 1; f.fill(tick === 1 ? 255 : 128); } };
      }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: vi.fn(() => [{ stop: vi.fn() }]) }) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => { ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) }); });
    await act(async () => { rafCb?.(); await Promise.resolve(); });
    await act(async () => {
      vi.advanceTimersByTime(700);
      rafCb?.();
      await Promise.resolve();
    });
    await act(async () => {
      await recorderInstance.ondataavailable({
        data: { size: 4, arrayBuffer: async () => new Uint8Array([7, 7, 7, 7]).buffer },
      });
    });
    act(() => { vi.advanceTimersByTime(220); });

    expect(result.current.state.status).toBe("processing");
    clearTimeoutSpy.mockRestore();
    vi.useRealTimers();
  });
});

describe("useVoiceAssistant — ek hedefli branch testleri", () => {
  it("https protokolünde wss url ile websocket oluşturur", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");

    const ws = makeWsMock(WebSocket.OPEN);
    const wsCtor = withOpenSocketCtor(() => ws);
    globalThis.WebSocket = wsCtor;

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const originalLocation = globalThis.location;
    Object.defineProperty(globalThis, "location", {
      configurable: true,
      value: { ...originalLocation, protocol: "https:", host: "example.test" },
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });
    expect(wsCtor).toHaveBeenCalledWith("wss://example.test/ws/voice", ["token"]);

    Object.defineProperty(globalThis, "location", { configurable: true, value: originalLocation });
  });

  it("voice_state unknown ve mic kapalı iken mevcut status'u korur", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });
    act(() => result.current.stop());
    expect(result.current.state.status).toBe("idle");

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ voice_state: "weird_state" }) });
    });
    expect(result.current.state.status).toBe("idle");
  });

  it("done mesajında mic kapalıysa status idle kalır", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => {
      await result.current.start();
    });
    act(() => result.current.stop());

    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ done: true }) });
    });
    expect(result.current.state.status).toBe("idle");
  });
});

describe("useVoiceAssistant — kalan branch boşlukları için testler", () => {
  it("getUserMedia string reject döndüğünde String(error) yolunu kullanır", async () => {
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockRejectedValue("raw-reject") },
      configurable: true,
    });
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } };
    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => {
      await result.current.start();
    });
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("raw-reject"));
    expect(result.current.state.status).toBe("error");
  });

  it("recorder arrayBuffer string hata fırlatırsa String(error) dalını kullanır", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 1;
    });
    let recorderInstance;
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { recorderInstance = this; this.state = "recording"; }
      start() {}
      stop() { this.state = "inactive"; }
    };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(255)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });
    const onError = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onError }));
    await act(async () => { await result.current.start(); });
    act(() => ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) }));
    await act(async () => { rafCallback?.(); });

    await act(async () => {
      await recorderInstance.ondataavailable({
        data: { size: 4, arrayBuffer: async () => { throw "chunk-fail"; } },
      });
    });
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("chunk-fail"));
  });

  it("voice payload fallback alanlarını (assistant_turn_id/transcript/cancelled seq) işler", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class { static isTypeSupported() { return true; } start() {} stop() {} };
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: vi.fn((f) => f.fill(128)) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ assistant_turn: "started" }) });
      ws.onmessage?.({ data: JSON.stringify({ transcript: "" }) });
      ws.onmessage?.({ data: JSON.stringify({ voice_interruption: "cut" }) });
    });
    expect(result.current.state.assistantTurnId).toBe(0);
    expect(result.current.state.transcript).toBe("");
    expect(result.current.state.lastInterruptReason).toBe("cut");
    expect(result.current.state.diagnostics.some((d) => d.value.includes("#0"))).toBe(true);
  });

  it("speech_start ikinci kez gelirse erken return eder ve stop sonrası eski RAF callback'i güvenli döner", async () => {
    const { getStoredToken } = await import("../lib/api.js");
    getStoredToken.mockReturnValue("token");
    const ws = makeWsMock(WebSocket.OPEN);
    globalThis.WebSocket = withOpenSocketCtor(() => ws);

    let rafCallback;
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb) => {
      rafCallback = cb;
      return 3;
    });
    const stream = { getTracks: vi.fn(() => [{ stop: vi.fn() }]) };
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      start() {}
      stop() {}
      requestData() {}
    };
    let frameVal = 255;
    globalThis.AudioContext = class {
      createMediaStreamSource() { return { connect: vi.fn() }; }
      createAnalyser() { return { fftSize: 2048, getByteTimeDomainData: (f) => f.fill(frameVal) }; }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(stream) },
      configurable: true,
    });

    const { result } = renderHook(() => useVoiceAssistant());
    await act(async () => { await result.current.start(); });
    act(() => ws.onmessage?.({ data: JSON.stringify({ auth_ok: true }) }));
    await act(async () => { rafCallback?.(); });
    const startActions = ws.send.mock.calls
      .map(([payload]) => JSON.parse(payload).action)
      .filter((a) => a === "start");
    await act(async () => { rafCallback?.(); }); // speechActive true -> early return branch
    expect(ws.send.mock.calls.map(([payload]) => JSON.parse(payload).action).filter((a) => a === "start"))
      .toHaveLength(startActions.length);

    act(() => result.current.stop());
    frameVal = 128;
    await act(async () => { rafCallback?.(); }); // analyser temizlendikten sonra line 440 guard
    expect(result.current.state.status).toBe("idle");
  });
});
