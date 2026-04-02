import { create } from "zustand";

const genId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

const DISPLAY_NAME_KEY = "sidar_collab_display_name";
const ROOM_ID_KEY = "sidar_collab_room_id";

function readStoredValue(key, fallback) {
  if (typeof localStorage === "undefined") return fallback;
  return (localStorage.getItem(key) || "").trim() || fallback;
}

function persistValue(key, value) {
  if (typeof localStorage === "undefined") return;
  const normalized = String(value || "").trim();
  if (normalized) {
    localStorage.setItem(key, normalized);
  } else {
    localStorage.removeItem(key);
  }
}

export const useChatStore = create((set, get) => ({
  sessionId: genId(),
  roomId: readStoredValue(ROOM_ID_KEY, "workspace:sidar"),
  displayName: readStoredValue(DISPLAY_NAME_KEY, "Operatör"),
  messages: [],
  streamingText: "",
  streamingRequestId: "",
  isStreaming: false,
  error: null,
  telemetryEvents: [],
  participants: [],

  setRoomId(roomId) {
    const normalized = String(roomId || "").trim();
    persistValue(ROOM_ID_KEY, normalized);
    set({ roomId: normalized || "workspace:sidar" });
  },

  setDisplayName(displayName) {
    const normalized = String(displayName || "").trim();
    persistValue(DISPLAY_NAME_KEY, normalized);
    set({ displayName: normalized || "Operatör" });
  },

  hydrateRoom(snapshot = {}) {
    const messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
    const telemetry = Array.isArray(snapshot.telemetry) ? snapshot.telemetry : [];
    const participants = Array.isArray(snapshot.participants) ? snapshot.participants : [];
    set({
      roomId: snapshot.room_id || get().roomId,
      messages,
      telemetryEvents: telemetry,
      participants,
      streamingText: "",
      streamingRequestId: "",
      isStreaming: false,
      error: null,
    });
  },

  updateParticipants(participants) {
    set({ participants: Array.isArray(participants) ? participants : [] });
  },

  pushRoomMessage(message) {
    if (!message) return;
    set((state) => {
      const exists = state.messages.some((item) => item.id === message.id);
      return exists ? state : { messages: [...state.messages, message], error: null };
    });
  },

  startAssistantStream(requestId) {
    set({
      isStreaming: true,
      streamingText: "",
      streamingRequestId: String(requestId || ""),
      error: null,
    });
  },

  appendChunk(text, requestId = "") {
    set((state) => {
      const currentRequestId = requestId || state.streamingRequestId;
      return {
        streamingText: state.streamingRequestId && state.streamingRequestId !== currentRequestId
          ? text
          : state.streamingText + text,
        streamingRequestId: currentRequestId,
        isStreaming: true,
      };
    });
  },

  commitAssistantMessage(message = null, requestId = "") {
    const state = get();
    const finalText = message?.content || state.streamingText;
    if (!finalText) {
      set({ streamingText: "", isStreaming: false, streamingRequestId: "" });
      return;
    }
    const nextMessage = message || {
      id: genId(),
      room_id: state.roomId,
      role: "assistant",
      kind: "assistant_reply",
      content: finalText,
      author_name: "SİDAR",
      author_id: "sidar",
      request_id: requestId || state.streamingRequestId,
      ts: new Date().toISOString(),
    };
    set((prev) => ({
      messages: prev.messages.some((item) => item.id === nextMessage.id) ? prev.messages : [...prev.messages, nextMessage],
      streamingText: "",
      isStreaming: false,
      streamingRequestId: "",
    }));
  },

  addTelemetryEvent(kind, content, meta = {}) {
    if (!content) return;
    const evt = {
      id: meta.id || genId(),
      kind,
      content: String(content),
      ts: meta.ts || new Date().toISOString(),
      source: meta.source || "",
    };
    set((state) => ({
      telemetryEvents: [...state.telemetryEvents.filter((item) => item.id !== evt.id).slice(-119), evt],
    }));
  },

  setError(msg) {
    set({ error: msg, isStreaming: false, streamingText: "", streamingRequestId: "" });
  },

  clearMessages() {
    set({ messages: [], streamingText: "", error: null, telemetryEvents: [], streamingRequestId: "", isStreaming: false });
  },

  newSession() {
    set({
      sessionId: genId(),
      messages: [],
      streamingText: "",
      error: null,
      isStreaming: false,
      telemetryEvents: [],
      streamingRequestId: "",
      participants: [],
    });
  },
}));
