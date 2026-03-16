/**
 * ChatInput — Mesaj giriş alanı.
 * Enter gönderir, Shift+Enter yeni satır ekler.
 */

import React, { useRef, useState, useCallback } from "react";
import { useChatStore } from "../hooks/useChatStore.js";

export function ChatInput({ onSend, disabled = false }) {
  const [text, setText] = useState("");
  const textareaRef = useRef(null);
  const { isStreaming } = useChatStore();

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSend(trimmed);
    setText("");
    textareaRef.current?.focus();
  }, [text, isStreaming, disabled, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="chat-input">
      <textarea
        ref={textareaRef}
        className="chat-input__textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Mesajınızı yazın… (Enter: gönder, Shift+Enter: satır)"
        rows={3}
        disabled={isStreaming || disabled}
        aria-label="Mesaj giriş alanı"
      />
      <button
        className="chat-input__send"
        onClick={handleSubmit}
        disabled={!text.trim() || isStreaming || disabled}
        aria-label="Gönder"
        title="Gönder (Enter)"
      >
        {isStreaming ? "⏳" : "➤"}
      </button>
    </div>
  );
}