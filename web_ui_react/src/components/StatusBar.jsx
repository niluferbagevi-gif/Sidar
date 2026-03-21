/**
 * StatusBar — WS bağlantı durumu ve oturum bilgisi.
 */

import React from "react";
import { useChatStore } from "../hooks/useChatStore.js";

const STATUS_LABEL = {
  connected:    { icon: "🟢", text: "Bağlı" },
  connecting:   { icon: "🟡", text: "Bağlanıyor…" },
  disconnected: { icon: "🔴", text: "Bağlantı kesildi" },
  error:        { icon: "🔴", text: "Hata" },
  unauthenticated: { icon: "🟠", text: "Token gerekli" },
};

export function StatusBar({ wsStatus, onNewSession, voiceStatus = "Hazır", roomId = "", collaborators = 0 }) {
  const { sessionId, messages } = useChatStore();
  const { icon, text } = STATUS_LABEL[wsStatus] ?? STATUS_LABEL.disconnected;

  return (
    <div className="status-bar">
      <span className="status-bar__ws" title={`Session: ${sessionId}`}>
        {icon} {text}
      </span>
      <span className="status-bar__room" title={`Workspace: ${roomId}`}>
        🧩 {roomId || "workspace:sidar"}
      </span>
      <span className="status-bar__count">
        {messages.length} mesaj
      </span>
      <span className="status-bar__count">
        👥 {collaborators} kişi
      </span>
      <span className="status-bar__voice">🎙 {voiceStatus}</span>
      <button
        className="status-bar__new-session"
        onClick={onNewSession}
        title="Yeni oturum başlat"
      >
        ✦ Yeni Oturum
      </button>
    </div>
  );
}
