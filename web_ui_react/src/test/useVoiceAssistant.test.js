import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TOKEN_KEY } from "../lib/api.js";
import { useVoiceAssistant } from "../hooks/useVoiceAssistant.js";

class MockWebSocket {
  static OPEN = 1;
  static instances = [];

  constructor(url, protocols) {
    this.url = url;
    this.protocols = protocols;
    this.readyState = MockWebSocket.OPEN;
    this.sent = [];
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    MockWebSocket.instances.push(this);
  }

  send(payload) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  emitMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

class MockMediaRecorder {
  constructor(stream) {
    this.stream = stream;
    this.state = "inactive";
    this.ondataavailable = null;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
  }

  requestData() {}

  static isTypeSupported() {
    return true;
  }
}

class MockAudioContext {
  createMediaStreamSource() {
    return { connect: vi.fn() };
  }

  createAnalyser() {
    return {
      fftSize: 2048,
      smoothingTimeConstant: 0.82,
      getByteTimeDomainData: vi.fn(),
    };
  }

  close() {
    return Promise.resolve();
  }
}

const audioInstances = [];
class MockAudio {
  constructor(url) {
    this.url = url;
    this.currentTime = 0;
    this.onended = null;
    this.onerror = null;
    this.pause = vi.fn();
    this.play = vi.fn().mockResolvedValue();
    audioInstances.push(this);
  }
}

describe("useVoiceAssistant", () => {
  let revokeObjectURLSpy;

  beforeEach(() => {
    MockWebSocket.instances.length = 0;
    audioInstances.length = 0;
    localStorage.clear();
    localStorage.setItem(TOKEN_KEY, "test-token");

    vi.spyOn(URL, "createObjectURL").mockImplementation(() => `blob:${Math.random()}`);
    revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});

    vi.stubGlobal("WebSocket", MockWebSocket);
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("AudioContext", MockAudioContext);
    vi.stubGlobal("Audio", MockAudio);

    navigator.mediaDevices.getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop: vi.fn() }],
    });

    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
  });

  it("voice_interruption sırasında kuyruktaki URL'leri revoke eder", async () => {
    const { result } = renderHook(() => useVoiceAssistant());

    await act(async () => {
      await result.current.start();
    });

    const ws = MockWebSocket.instances[0];
    expect(ws).toBeTruthy();

    act(() => {
      ws.emitMessage({ auth_ok: true });
      ws.emitMessage({ audio_chunk: "QQ==", audio_mime_type: "audio/wav" });
      ws.emitMessage({ audio_chunk: "Qg==", audio_mime_type: "audio/wav" });
      ws.emitMessage({ voice_interruption: "server_cancel", cancelled_audio_sequences: 1 });
    });

    expect(revokeObjectURLSpy).toHaveBeenCalled();
    expect(result.current.state.lastInterruptReason).toBe("server_cancel");
  });

  it("ses oynatma bittiğinde mikrofon açıksa listening durumuna döner", async () => {
    const { result } = renderHook(() => useVoiceAssistant());

    await act(async () => {
      await result.current.start();
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emitMessage({ auth_ok: true });
      ws.emitMessage({ audio_chunk: "QQ==", audio_mime_type: "audio/wav" });
    });

    expect(audioInstances.length).toBe(1);

    act(() => {
      audioInstances[0].onended?.();
    });

    await waitFor(() => {
      expect(result.current.state.status).toBe("listening");
    });
  });

  it("done mesajında ses oynatımı yoksa assistant tamamlanınca idle dinamik durumunu günceller", async () => {
    const onAssistantDone = vi.fn();
    const { result } = renderHook(() => useVoiceAssistant({ onAssistantDone }));

    await act(async () => {
      await result.current.start();
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.emitMessage({ auth_ok: true });
    });

    act(() => {
      result.current.stop();
    });

    act(() => {
      ws.emitMessage({ done: true });
    });

    expect(onAssistantDone).toHaveBeenCalledTimes(1);
    expect(result.current.state.status).toBe("idle");
  });
});
