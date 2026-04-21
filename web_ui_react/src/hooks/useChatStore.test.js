import { beforeEach, describe, expect, it, vi } from "vitest";
import { __chatStoreTestUtils, useChatStore } from "./useChatStore.js";

// Her testten önce store'u sıfırla
beforeEach(() => {
  useChatStore.setState({
    messages: [],
    streamingText: "",
    streamingRequestId: "",
    isStreaming: false,
    error: null,
    telemetryEvents: [],
    participants: [],
  });
});

describe("useChatStore — başlangıç durumu", () => {
  it("has empty messages array initially", () => {
    expect(useChatStore.getState().messages).toEqual([]);
  });

  it("has isStreaming false initially", () => {
    expect(useChatStore.getState().isStreaming).toBe(false);
  });

  it("has null error initially", () => {
    expect(useChatStore.getState().error).toBeNull();
  });

  it("has non-empty sessionId", () => {
    expect(useChatStore.getState().sessionId).toBeTruthy();
  });
});



describe("useChatStore — environment fallbacks", () => {
  it("falls back to Math.random id generation when crypto is unavailable", async () => {
    const originalCrypto = globalThis.crypto;
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.123456789);

    try {
      Object.defineProperty(globalThis, "crypto", {
        value: undefined,
        configurable: true,
        writable: true,
      });
      vi.resetModules();
      const { useChatStore: fallbackStore } = await import("./useChatStore.js");

      expect(fallbackStore.getState().sessionId).toBeTruthy();
      expect(randomSpy).toHaveBeenCalled();
    } finally {
      if (originalCrypto === undefined) {
        delete globalThis.crypto;
      } else {
        Object.defineProperty(globalThis, "crypto", {
          value: originalCrypto,
          configurable: true,
          writable: true,
        });
      }
      randomSpy.mockRestore();
      vi.resetModules();
    }
  });

  it("uses default room and display name when localStorage is unavailable", async () => {
    const originalLocalStorage = globalThis.localStorage;

    try {
      Object.defineProperty(globalThis, "localStorage", {
        value: undefined,
        configurable: true,
        writable: true,
      });
      vi.resetModules();
      const { useChatStore: fallbackStore } = await import("./useChatStore.js");

      expect(fallbackStore.getState().roomId).toBe("workspace:sidar");
      expect(fallbackStore.getState().displayName).toBe("Operatör");
      expect(() => fallbackStore.getState().setRoomId("workspace:demo")).not.toThrow();
      expect(() => fallbackStore.getState().setDisplayName("Demo Kullanıcı")).not.toThrow();
    } finally {
      if (originalLocalStorage === undefined) {
        delete globalThis.localStorage;
      } else {
        Object.defineProperty(globalThis, "localStorage", {
          value: originalLocalStorage,
          configurable: true,
          writable: true,
        });
      }
      vi.resetModules();
    }
  });
});
describe("useChatStore — setRoomId", () => {
  it("sets roomId to provided value", () => {
    useChatStore.getState().setRoomId("workspace:test");
    expect(useChatStore.getState().roomId).toBe("workspace:test");
  });

  it("falls back to workspace:sidar when empty string provided", () => {
    useChatStore.getState().setRoomId("");
    expect(useChatStore.getState().roomId).toBe("workspace:sidar");
  });
});

describe("useChatStore — setDisplayName", () => {
  it("sets displayName to provided value", () => {
    useChatStore.getState().setDisplayName("Ali Veli");
    expect(useChatStore.getState().displayName).toBe("Ali Veli");
  });

  it("falls back to Operatör when empty string provided", () => {
    useChatStore.getState().setDisplayName("");
    expect(useChatStore.getState().displayName).toBe("Operatör");
  });
});

describe("useChatStore — localStorage removeItem", () => {
  it("removes keys from localStorage when empty strings are provided", () => {
    useChatStore.getState().setRoomId("test-room");
    useChatStore.getState().setDisplayName("test-user");

    useChatStore.getState().setRoomId("");
    useChatStore.getState().setDisplayName("");

    expect(localStorage.getItem("sidar_collab_room_id")).toBeNull();
    expect(localStorage.getItem("sidar_collab_display_name")).toBeNull();
  });
});

describe("useChatStore — pushRoomMessage", () => {
  it("appends a new message to messages array", () => {
    const msg = { id: "m1", role: "user", content: "merhaba" };
    useChatStore.getState().pushRoomMessage(msg);
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0]).toEqual(msg);
  });

  it("does not add duplicate messages (same id)", () => {
    const msg = { id: "m1", role: "user", content: "merhaba" };
    useChatStore.getState().pushRoomMessage(msg);
    useChatStore.getState().pushRoomMessage(msg);
    expect(useChatStore.getState().messages).toHaveLength(1);
  });

  it("keeps message list unchanged when a different payload has an existing id", () => {
    useChatStore.getState().pushRoomMessage({ id: "m1", role: "user", content: "ilk" });
    useChatStore.getState().pushRoomMessage({ id: "m1", role: "assistant", content: "ikinci" });

    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0]).toEqual({ id: "m1", role: "user", content: "ilk" });
  });

  it("clears error on push", () => {
    useChatStore.setState({ error: "önceki hata" });
    useChatStore.getState().pushRoomMessage({ id: "m1", role: "user", content: "x" });
    expect(useChatStore.getState().error).toBeNull();
  });

  it("ignores null/undefined message", () => {
    useChatStore.getState().pushRoomMessage(null);
    expect(useChatStore.getState().messages).toHaveLength(0);
  });
});

describe("useChatStore — startAssistantStream", () => {
  it("sets isStreaming to true", () => {
    useChatStore.getState().startAssistantStream("req-1");
    expect(useChatStore.getState().isStreaming).toBe(true);
  });

  it("resets streamingText to empty string", () => {
    useChatStore.setState({ streamingText: "önceki" });
    useChatStore.getState().startAssistantStream("req-1");
    expect(useChatStore.getState().streamingText).toBe("");
  });

  it("sets streamingRequestId", () => {
    useChatStore.getState().startAssistantStream("req-xyz");
    expect(useChatStore.getState().streamingRequestId).toBe("req-xyz");
  });

  it("falls back to empty streamingRequestId when requestId is not provided", () => {
    useChatStore.setState({ streamingRequestId: "eski-istek" });
    useChatStore.getState().startAssistantStream();
    expect(useChatStore.getState().streamingRequestId).toBe("");
  });

  it("clears error", () => {
    useChatStore.setState({ error: "önceki hata" });
    useChatStore.getState().startAssistantStream("req-1");
    expect(useChatStore.getState().error).toBeNull();
  });
});

describe("useChatStore — appendChunk", () => {
  it("appends text to streamingText", () => {
    useChatStore.setState({ streamingText: "başlangıç ", streamingRequestId: "req-1", isStreaming: true });
    useChatStore.getState().appendChunk("devam", "req-1");
    expect(useChatStore.getState().streamingText).toBe("başlangıç devam");
  });

  it("resets streamingText on new request ID", () => {
    useChatStore.setState({ streamingText: "eski", streamingRequestId: "req-1", isStreaming: true });
    useChatStore.getState().appendChunk("yeni", "req-2");
    expect(useChatStore.getState().streamingText).toBe("yeni");
  });

  it("appends text correctly when streamingRequestId is currently empty", () => {
    useChatStore.setState({ streamingText: "başlangıç ", streamingRequestId: "", isStreaming: false });
    useChatStore.getState().appendChunk("devam");
    expect(useChatStore.getState().streamingText).toBe("başlangıç devam");
  });

  it("ignores empty chunk text", () => {
    useChatStore.setState({ streamingText: "korunmalı", streamingRequestId: "req-1", isStreaming: true });
    useChatStore.getState().appendChunk("");

    const state = useChatStore.getState();
    expect(state.streamingText).toBe("korunmalı");
    expect(state.streamingRequestId).toBe("req-1");
  });
});

describe("useChatStore — commitAssistantMessage", () => {
  it("adds assistant message to messages", () => {
    useChatStore.setState({ streamingText: "yanıt metni", streamingRequestId: "r1", isStreaming: true });
    useChatStore.getState().commitAssistantMessage();
    const state = useChatStore.getState();
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0].content).toBe("yanıt metni");
    expect(state.messages[0].role).toBe("assistant");
  });

  it("sets isStreaming to false after commit", () => {
    useChatStore.setState({ streamingText: "yanıt", isStreaming: true });
    useChatStore.getState().commitAssistantMessage();
    expect(useChatStore.getState().isStreaming).toBe(false);
  });

  it("clears streamingText after commit", () => {
    useChatStore.setState({ streamingText: "yanıt", isStreaming: true });
    useChatStore.getState().commitAssistantMessage();
    expect(useChatStore.getState().streamingText).toBe("");
  });

  it("does not add message when streamingText is empty", () => {
    useChatStore.setState({ streamingText: "", isStreaming: true });
    useChatStore.getState().commitAssistantMessage();
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it("uses provided message content over streamingText", () => {
    useChatStore.setState({ streamingText: "akış metni", isStreaming: true });
    useChatStore.getState().commitAssistantMessage({ id: "custom-1", content: "özel içerik", role: "assistant" });
    expect(useChatStore.getState().messages[0].content).toBe("özel içerik");
  });

  it("uses streamingText if provided message object lacks content", () => {
    useChatStore.setState({ streamingText: "akış metni", isStreaming: true });
    useChatStore.getState().commitAssistantMessage({ id: "custom-1", role: "assistant" });
    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].id).toBe("custom-1");
  });

  it("uses explicitly provided requestId", () => {
    useChatStore.setState({ streamingText: "akış", isStreaming: true, streamingRequestId: "eski-req" });
    useChatStore.getState().commitAssistantMessage(null, "yeni-req");
    expect(useChatStore.getState().messages[0].request_id).toBe("yeni-req");
  });

  it("does not duplicate an assistant message if it already exists", () => {
    useChatStore.setState({ messages: [{ id: "msg-1", role: "assistant", content: "ilk mesaj" }] });
    useChatStore.getState().commitAssistantMessage({ id: "msg-1", role: "assistant", content: "ikinci mesaj" });

    expect(useChatStore.getState().messages).toHaveLength(1);
    expect(useChatStore.getState().messages[0].content).toBe("ilk mesaj");
  });
});

describe("useChatStore — setError", () => {
  it("sets error message", () => {
    useChatStore.getState().setError("bir hata oluştu");
    expect(useChatStore.getState().error).toBe("bir hata oluştu");
  });

  it("stops streaming on error", () => {
    useChatStore.setState({ isStreaming: true });
    useChatStore.getState().setError("hata");
    expect(useChatStore.getState().isStreaming).toBe(false);
  });
});

describe("useChatStore — clearMessages", () => {
  it("clears all messages", () => {
    useChatStore.setState({ messages: [{ id: "1" }, { id: "2" }] });
    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it("resets streaming state", () => {
    useChatStore.setState({ isStreaming: true, streamingText: "akış" });
    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().isStreaming).toBe(false);
    expect(useChatStore.getState().streamingText).toBe("");
  });

  it("clears error", () => {
    useChatStore.setState({ error: "hata" });
    useChatStore.getState().clearMessages();
    expect(useChatStore.getState().error).toBeNull();
  });
});

describe("useChatStore — newSession", () => {
  it("generates a new sessionId", () => {
    const oldId = useChatStore.getState().sessionId;
    useChatStore.getState().newSession();
    expect(useChatStore.getState().sessionId).not.toBe(oldId);
  });

  it("clears all messages on new session", () => {
    useChatStore.setState({ messages: [{ id: "1" }] });
    useChatStore.getState().newSession();
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it("resets participants on new session", () => {
    useChatStore.setState({ participants: [{ id: "p1" }] });
    useChatStore.getState().newSession();
    expect(useChatStore.getState().participants).toHaveLength(0);
  });
});

describe("useChatStore — hydrateRoom", () => {
  it("loads messages from snapshot", () => {
    useChatStore.getState().hydrateRoom({ messages: [{ id: "1" }, { id: "2" }] });
    expect(useChatStore.getState().messages).toHaveLength(2);
  });

  it("sets roomId from snapshot", () => {
    useChatStore.getState().hydrateRoom({ room_id: "workspace:demo", messages: [] });
    expect(useChatStore.getState().roomId).toBe("workspace:demo");
  });

  it("handles empty snapshot gracefully", () => {
    useChatStore.getState().hydrateRoom({});
    expect(useChatStore.getState().messages).toHaveLength(0);
  });

  it("resets streaming state after hydration", () => {
    useChatStore.setState({ isStreaming: true, streamingText: "akış" });
    useChatStore.getState().hydrateRoom({});
    expect(useChatStore.getState().isStreaming).toBe(false);
    expect(useChatStore.getState().streamingText).toBe("");
  });

  it("hydrates telemetry and participants successfully when arrays are provided", () => {
    const telemetry = [{ id: "t1", content: "test" }];
    const participants = [{ id: "p1", name: "User" }];
    useChatStore.getState().hydrateRoom({ telemetry, participants });

    expect(useChatStore.getState().telemetryEvents).toEqual(telemetry);
    expect(useChatStore.getState().participants).toEqual(participants);
  });
});

describe("useChatStore — addTelemetryEvent", () => {
  it("adds a telemetry event", () => {
    useChatStore.getState().addTelemetryEvent("status", "bağlandı");
    expect(useChatStore.getState().telemetryEvents).toHaveLength(1);
    expect(useChatStore.getState().telemetryEvents[0].content).toBe("bağlandı");
  });

  it("does not add event when content is empty", () => {
    useChatStore.getState().addTelemetryEvent("status", "");
    expect(useChatStore.getState().telemetryEvents).toHaveLength(0);
  });

  it("caps telemetry events at 120", () => {
    for (let i = 0; i < 130; i++) {
      useChatStore.getState().addTelemetryEvent("status", `event-${i}`);
    }
    expect(useChatStore.getState().telemetryEvents.length).toBeLessThanOrEqual(120);
  });

  it("uses provided meta properties (id, ts, source)", () => {
    const meta = { id: "t-özel", ts: "2024-01-01T00:00:00.000Z", source: "agent" };
    useChatStore.getState().addTelemetryEvent("status", "özel mesaj", meta);

    const evt = useChatStore.getState().telemetryEvents[0];
    expect(evt.id).toBe("t-özel");
    expect(evt.ts).toBe("2024-01-01T00:00:00.000Z");
    expect(evt.source).toBe("agent");
  });

  it("updates existing telemetry event by filtering out the old one", () => {
    useChatStore.setState({
      telemetryEvents: [{ id: "t1", kind: "status", content: "eski", ts: "1", source: "" }],
    });
    useChatStore.getState().addTelemetryEvent("status", "yeni", { id: "t1" });

    const events = useChatStore.getState().telemetryEvents;
    expect(events).toHaveLength(1);
    expect(events[0].content).toBe("yeni");
  });
});

describe("useChatStore — updateParticipants", () => {
  it("sets participants array", () => {
    useChatStore.getState().updateParticipants([{ id: "p1" }, { id: "p2" }]);
    expect(useChatStore.getState().participants).toHaveLength(2);
  });

  it("sets empty array for non-array input", () => {
    useChatStore.getState().updateParticipants(null);
    expect(useChatStore.getState().participants).toEqual([]);
  });
});

describe("useChatStore — stream flush yardımcıları", () => {
  it("flushPendingChunk clears an active timer even if there is no buffered chunk", () => {
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout");

    __chatStoreTestUtils.scheduleChunkFlush(useChatStore.setState, useChatStore.getState);
    expect(__chatStoreTestUtils.getFlushTimer()).toBeTruthy();

    __chatStoreTestUtils.flushPendingChunk(useChatStore.setState, useChatStore.getState);

    expect(clearTimeoutSpy).toHaveBeenCalled();
    expect(__chatStoreTestUtils.getFlushTimer()).toBeNull();

    clearTimeoutSpy.mockRestore();
    vi.useRealTimers();
  });

  it("flushPendingChunk writes buffered text and resets stream text on switched request", () => {
    useChatStore.setState({ streamingText: "önceki", streamingRequestId: "req-eski", isStreaming: false });

    __chatStoreTestUtils.setPendingChunk("yeni parça", "req-yeni");
    __chatStoreTestUtils.flushPendingChunk(useChatStore.setState, useChatStore.getState);

    const state = useChatStore.getState();
    expect(state.streamingText).toBe("yeni parça");
    expect(state.streamingRequestId).toBe("req-yeni");
    expect(state.isStreaming).toBe(true);
  });

  it("flushPendingChunk falls back to active streaming request id when pending id is empty", () => {
    useChatStore.setState({ streamingText: "devam ", streamingRequestId: "req-aktif", isStreaming: true });

    __chatStoreTestUtils.setPendingChunk("parça", "");
    __chatStoreTestUtils.flushPendingChunk(useChatStore.setState, useChatStore.getState);

    const state = useChatStore.getState();
    expect(state.streamingRequestId).toBe("req-aktif");
    expect(state.streamingText).toBe("devam parça");
  });

  it("setPendingChunk normalizes non-string values", () => {
    useChatStore.setState({ streamingText: "önce ", streamingRequestId: "req-1", isStreaming: true });

    __chatStoreTestUtils.setPendingChunk(42, 99);
    __chatStoreTestUtils.flushPendingChunk(useChatStore.setState, useChatStore.getState);

    const state = useChatStore.getState();
    expect(state.streamingText).toBe("42");
    expect(state.streamingRequestId).toBe("99");
  });

  it("setPendingChunk applies default empty values when args are omitted", () => {
    useChatStore.setState({ streamingText: "değişmeden", streamingRequestId: "req-aktif", isStreaming: true });

    __chatStoreTestUtils.setPendingChunk();
    __chatStoreTestUtils.flushPendingChunk(useChatStore.setState, useChatStore.getState);

    const state = useChatStore.getState();
    expect(state.streamingText).toBe("değişmeden");
    expect(state.streamingRequestId).toBe("req-aktif");
  });

  it("scheduleChunkFlush does not create duplicate timers", () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");

    __chatStoreTestUtils.setPendingChunk("parça", "req-1");
    __chatStoreTestUtils.scheduleChunkFlush(useChatStore.setState, useChatStore.getState);
    __chatStoreTestUtils.scheduleChunkFlush(useChatStore.setState, useChatStore.getState);

    expect(setTimeoutSpy).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(150);
    expect(useChatStore.getState().streamingText).toContain("parça");

    setTimeoutSpy.mockRestore();
    vi.useRealTimers();
  });
});
