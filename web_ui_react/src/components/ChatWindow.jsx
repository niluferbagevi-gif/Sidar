/**
 * ChatWindow — Mesaj listesi + akış tamponu gösterimi.
 * Yeni mesaj geldiğinde alt kısma otomatik kaydırır.
 */

import React, { useEffect, useRef } from "react";
import { useChatStore } from "../hooks/useChatStore.js";
import { ChatMessage } from "./ChatMessage.jsx";

export function ChatWindow() {
  const { messages, streamingText, isStreaming, error } = useChatStore();
  const bottomRef = useRef(null);

  // Yeni içerik gelince alta kaydır
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, streamingText]);

  return (
    <div className="chat-window" role="log" aria-live="polite" aria-label="Sohbet geçmişi">
      {messages.length === 0 && !isStreaming && (
        <div className="chat-window__empty">
          <p>👋 Merhaba! Size nasıl yardımcı olabilirim?</p>
          <p className="chat-window__hint">Kod yazma, inceleme, araştırma ve daha fazlası…</p>
        </div>
      )}

      {messages.map((msg) => (
        <ChatMessage key={msg.id} message={msg} />
      ))}

      {isStreaming && streamingText && (
        <ChatMessage
          message={{ id: "streaming", role: "assistant", content: streamingText, ts: Date.now() }}
          isStreaming
        />
      )}

      {error && (
        <div className="chat-window__error" role="alert">
          ⚠️ {error}
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
