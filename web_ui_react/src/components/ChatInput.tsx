/**
 * ChatInput — Mesaj giriş alanı.
 * Enter gönderir, Shift+Enter yeni satır ekler.
 */

import { type KeyboardEvent, useCallback, useRef, useState } from "react";
import { useChatStore } from "../hooks/useChatStore.js";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isStreaming = useChatStore((state) => state.isStreaming);

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSend(trimmed);
    setText("");
    textareaRef.current?.focus();
  }, [text, isStreaming, disabled, onSend]);

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="chat-input">
      <textarea
        ref={textareaRef}
        className="chat-input__textarea"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="@Sidar ile komut verin veya ekip notu bırakın… (Enter: gönder, Shift+Enter: satır)"
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
