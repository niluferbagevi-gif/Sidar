import { create } from "zustand";

const genId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

export const useChatStore = create((set, get) => ({
  sessionId: genId(),
  messages: [],
  streamingText: "",
  isStreaming: false,
  error: null,
  telemetryEvents: [], // { id, kind, content, ts }

  addUserMessage(content) {
    const msg = { id: genId(), role: "user", content, ts: Date.now() };
    set((s) => ({ messages: [...s.messages, msg], error: null }));
    return msg.id;
  },

  appendChunk(text) {
    set((s) => ({ streamingText: s.streamingText + text, isStreaming: true }));
  },

  commitAssistantMessage() {
    const { streamingText } = get();
    if (!streamingText) return;
    const msg = { id: genId(), role: "assistant", content: streamingText, ts: Date.now() };
    set((s) => ({ messages: [...s.messages, msg], streamingText: "", isStreaming: false }));
  },

  addTelemetryEvent(kind, content) {
    if (!content) return;
    const evt = { id: genId(), kind, content: String(content), ts: Date.now() };
    set((s) => ({ telemetryEvents: [...s.telemetryEvents.slice(-99), evt] }));
  },

  setError(msg) {
    set({ error: msg, isStreaming: false, streamingText: "" });
  },

  clearMessages() {
    set({ messages: [], streamingText: "", error: null, telemetryEvents: [] });
  },

  newSession() {
    set({
      sessionId: genId(),
      messages: [],
      streamingText: "",
      error: null,
      isStreaming: false,
      telemetryEvents: [],
    });
  },
}));
