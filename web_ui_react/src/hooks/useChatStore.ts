import { create } from "zustand";
import { createThrottledStreamController } from "./useThrottledStream.js";
import type { StreamStateGetter, StreamStateSetter } from "./useThrottledStream.js";
import type {
  CollaborationEvent,
  RoomMessage,
  RoomParticipant,
} from "./useWebSocket.js";

export interface ChatMessage extends RoomMessage {
  id: string;
  content?: string;
  role?: string;
  room_id?: string;
  kind?: string;
  author_name?: string;
  author_id?: string;
  request_id?: string;
  ts?: string;
}

export interface ChatTelemetryEvent extends CollaborationEvent {
  id: string;
  kind: string;
  content: string;
  ts: string;
  source: string;
}

export interface ChatRoomSnapshot {
  room_id?: string;
  messages?: ChatMessage[];
  telemetry?: ChatTelemetryEvent[];
  participants?: RoomParticipant[];
  [key: string]: unknown;
}

export interface ChatStoreState {
  sessionId: string;
  roomId: string;
  displayName: string;
  messages: ChatMessage[];
  streamingText: string;
  streamingRequestId: string;
  isStreaming: boolean;
  error: string | null;
  telemetryEvents: ChatTelemetryEvent[];
  participants: RoomParticipant[];
  setRoomId: (roomId: unknown) => void;
  setDisplayName: (displayName: unknown) => void;
  hydrateRoom: (snapshot?: ChatRoomSnapshot) => void;
  updateParticipants: (participants: RoomParticipant[] | null | undefined) => void;
  pushRoomMessage: (message: ChatMessage | null | undefined) => void;
  startAssistantStream: (requestId?: string) => void;
  appendChunk: (text: unknown, requestId?: string) => void;
  commitAssistantMessage: (message?: string | ChatMessage | null, requestId?: string) => void;
  addTelemetryEvent: (kind: string, content: unknown, meta?: Partial<ChatTelemetryEvent>) => void;
  setError: (message: string | null) => void;
  clearMessages: () => void;
  newSession: () => void;
}


const genId = (): string => {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === "function") {
    return webCrypto.randomUUID();
  }
  if (typeof webCrypto?.getRandomValues === "function") {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16));
    // RFC 4122 version 4 UUID bits. getRandomValues keeps the fallback
    // cryptographically strong on browsers that predate crypto.randomUUID().
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex
      .slice(6, 8)
      .join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }
  throw new Error("Secure Web Crypto API is required to create chat session identifiers.");
};

const DISPLAY_NAME_KEY = "sidar_collab_display_name";
const ROOM_ID_KEY = "sidar_collab_room_id";
const STREAM_THROTTLE_MS = 120;
const MAX_MESSAGES = 500;
const streamController = createThrottledStreamController({ throttleMs: STREAM_THROTTLE_MS });

function readStoredValue(key: string, fallback: string): string {
  if (typeof localStorage === "undefined") return fallback;
  return (localStorage.getItem(key) || "").trim() || fallback;
}

function persistValue(key: string, value: unknown): void {
  if (typeof localStorage === "undefined") return;
  const normalized = String(value || "").trim();
  if (normalized) {
    localStorage.setItem(key, normalized);
  } else {
    localStorage.removeItem(key);
  }
}

export const __chatStoreTestUtils = {
  setPendingChunk(text: unknown = "", requestId: unknown = "") {
    streamController.setPending(text, requestId);
  },
  flushPendingChunk(set: StreamStateSetter, get: StreamStateGetter): void {
    streamController.flush({ set, get });
  },
  scheduleChunkFlush(set: StreamStateSetter, get: StreamStateGetter): void {
    streamController.scheduleFlush({ set, get });
  },
  clearStreamFlushTimer: streamController.clearTimer,
  getFlushTimer: streamController.getFlushTimer,
};

export const useChatStore = create<ChatStoreState>((set, get) => ({
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

  setRoomId(roomId: unknown) {
    const normalized = String(roomId || "").trim();
    persistValue(ROOM_ID_KEY, normalized);
    set({ roomId: normalized || "workspace:sidar" });
  },

  setDisplayName(displayName: unknown) {
    const normalized = String(displayName || "").trim();
    persistValue(DISPLAY_NAME_KEY, normalized);
    set({ displayName: normalized || "Operatör" });
  },

  hydrateRoom(snapshot: ChatRoomSnapshot = {}) {
    const messages = Array.isArray(snapshot.messages)
      ? snapshot.messages.slice(-MAX_MESSAGES)
      : [];
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

  updateParticipants(participants: RoomParticipant[] | null | undefined) {
    set({ participants: Array.isArray(participants) ? participants : [] });
  },

  pushRoomMessage(message: ChatMessage | null | undefined) {
    if (!message) return;
    set((state) => {
      const exists = state.messages.some((item) => item.id === message.id);
      return exists
        ? state
        : { messages: [...state.messages, message].slice(-MAX_MESSAGES), error: null };
    });
  },

  startAssistantStream(requestId = "") {
    streamController.reset();
    set({
      isStreaming: true,
      streamingText: "",
      streamingRequestId: String(requestId || ""),
      error: null,
    });
  },

  appendChunk(text: unknown, requestId = "") {
    const normalized = String(text || "");
    if (!normalized) return;
    streamController.reset();
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

  commitAssistantMessage(message: string | ChatMessage | null = null, requestId = "") {
    streamController.flush({ set, get });
    const state = get();
    const suppliedMessage = typeof message === "object" && message !== null ? message : null;
    const finalText = typeof message === "string"
      ? message
      : suppliedMessage?.content || state.streamingText;
    if (!finalText) {
      streamController.reset();
      set({ streamingText: "", isStreaming: false, streamingRequestId: "" });
      return;
    }
    const nextMessage = suppliedMessage || {
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
      messages: prev.messages.some((item) => item.id === nextMessage.id)
        ? prev.messages
        : [...prev.messages, nextMessage].slice(-MAX_MESSAGES),
      streamingText: "",
      isStreaming: false,
      streamingRequestId: "",
    }));
    streamController.reset();
  },

  addTelemetryEvent(kind: string, content: unknown, meta: Partial<ChatTelemetryEvent> = {}) {
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

  setError(msg: string | null) {
    streamController.reset();
    set({ error: msg, isStreaming: false, streamingText: "", streamingRequestId: "" });
  },

  clearMessages() {
    streamController.reset();
    set({ messages: [], streamingText: "", error: null, telemetryEvents: [], streamingRequestId: "", isStreaming: false });
  },

  newSession() {
    streamController.reset();
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
