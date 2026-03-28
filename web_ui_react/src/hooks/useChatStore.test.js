import { beforeEach, describe, expect, it } from "vitest";
import { useChatStore } from "./useChatStore.js";

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
