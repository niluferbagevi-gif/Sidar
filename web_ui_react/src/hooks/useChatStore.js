import { create } from "zustand";

const genId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

const DISPLAY_NAME_KEY = "sidar_collab_display_name";
const ROOM_ID_KEY = "sidar_collab_room_id";
const STREAM_THROTTLE_MS = 120;

let pendingChunkText = "";
let pendingChunkRequestId = "";
let flushTimer = null;

function clearStreamFlushTimer() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
}

function flushPendingChunk(set, get) {
  if (!pendingChunkText) {
    clearStreamFlushTimer();
    return;
  }
  const chunk = pendingChunkText;
  const requestId = pendingChunkRequestId;
  pendingChunkText = "";
  pendingChunkRequestId = "";
  clearStreamFlushTimer();
  set((state) => {
    const currentRequestId = requestId || state.streamingRequestId;
    const switchedRequest = Boolean(state.streamingRequestId && state.streamingRequestId !== currentRequestId);
    return {
      streamingText: switchedRequest ? chunk : state.streamingText + chunk,
      streamingRequestId: currentRequestId,
      isStreaming: true,
    };
  });
}

function scheduleChunkFlush(set, get) {
  if (flushTimer) return;
  flushTimer = setTimeout(() => flushPendingChunk(set, get), STREAM_THROTTLE_MS);
}

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

export const __chatStoreTestUtils = {
  setPendingChunk(text = "", requestId = "") {
    pendingChunkText = String(text || "");
    pendingChunkRequestId = String(requestId || "");
  },
  flushPendingChunk,
  scheduleChunkFlush,
  clearStreamFlushTimer,
  getFlushTimer: () => flushTimer,
};

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
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
    set({
      isStreaming: true,
      streamingText: "",
      streamingRequestId: String(requestId || ""),
      error: null,
    });
  },

  appendChunk(text, requestId = "") {
    const normalized = String(text || "");
    if (!normalized) return;
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
    set((state) => {
      const activeRequestId = String(requestId || state.streamingRequestId || "");
      const switchedRequest = Boolean(
        activeRequestId && state.streamingRequestId && state.streamingRequestId !== activeRequestId
      );
      return {
        streamingText: (switchedRequest ? "" : state.streamingText) + normalized,
        streamingRequestId: activeRequestId,
        isStreaming: true,
      };
    });
  },

  commitAssistantMessage(message = null, requestId = "") {
    flushPendingChunk(set, get);
    const state = get();
    const finalText = message?.content || state.streamingText;
    if (!finalText) {
      pendingChunkText = "";
      pendingChunkRequestId = "";
      clearStreamFlushTimer();
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
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
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
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
    set({ error: msg, isStreaming: false, streamingText: "", streamingRequestId: "" });
  },

  clearMessages() {
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
    set({ messages: [], streamingText: "", error: null, telemetryEvents: [], streamingRequestId: "", isStreaming: false });
  },

  newSession() {
    pendingChunkText = "";
    pendingChunkRequestId = "";
    clearStreamFlushTimer();
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
