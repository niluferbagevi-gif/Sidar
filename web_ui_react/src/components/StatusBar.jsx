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
};

export function StatusBar({ wsStatus, onNewSession }) {
  const { sessionId, messages } = useChatStore();
  const { icon, text } = STATUS_LABEL[wsStatus] ?? STATUS_LABEL.disconnected;

  return (
    <div className="status-bar">
      <span className="status-bar__ws" title={`Session: ${sessionId}`}>
        {icon} {text}
      </span>
      <span className="status-bar__count">
        {messages.length} mesaj
      </span>
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