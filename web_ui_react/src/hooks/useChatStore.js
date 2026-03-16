/**
 * useChatStore — Zustand tabanlı sohbet durumu yönetimi.
 *
 * Mesajlar, oturum bilgisi ve akış durumunu tek merkezde tutar.
 */

import { create } from "zustand";
import { nanoid } from "nanoid"; // vite ile tree-shaken edilir; gerekirse crypto.randomUUID() kullan

// nanoid yoksa basit UUID fallback
const genId = () =>
  typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);

export const useChatStore = create((set, get) => ({
  // ── Durum ────────────────────────────────────────────────────────────
  sessionId: genId(),
  messages: [],       // { id, role, content, ts }[]
  streamingText: "",  // asistan akış tamponu
  isStreaming: false,
  error: null,

  // ── Eylemler ─────────────────────────────────────────────────────────
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

  setError(msg) {
    set({ error: msg, isStreaming: false, streamingText: "" });
  },

  clearMessages() {
    set({ messages: [], streamingText: "", error: null });
  },

  newSession() {
    set({ sessionId: genId(), messages: [], streamingText: "", error: null, isStreaming: false });
  },
}));
