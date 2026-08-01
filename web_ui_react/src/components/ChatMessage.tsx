/**
 * ChatMessage — Tek bir sohbet mesajını render eder.
 * Asistan mesajları Markdown (kod vurgulamalı) olarak gösterilir.
 */

import React, { Suspense } from "react";
import type { ChatMessage as ChatMessageModel } from "../hooks/useChatStore.js";

const LazyChatMarkdownRenderer = React.lazy<React.ComponentType<{ content: string }>>(() =>
  import("./ChatMarkdownRenderer.jsx").then((module) => ({
    default: module.ChatMarkdownRenderer,
  })),
);

interface ChatMessageProps {
  message: ChatMessageModel;
  isStreaming?: boolean;
}

function MarkdownFallback({ content }: { content: string }) {
  return <span className="message__text message__text--markdown-loading">{content}</span>;
}

export const ChatMessage = React.memo(function ChatMessage({
  message,
  isStreaming = false,
}: ChatMessageProps) {
  const role = message.role || "assistant";
  const content = message.content || "";
  const timestamp = message.ts || new Date().toISOString();
  const isUser = role === "user";
  const authorName = message.author_name || (isUser ? "Ekip Üyesi" : "SİDAR");

  return (
    <div className={`message message--${role}${isStreaming ? " message--streaming" : ""}`}>
      <div className="message__avatar">
        {role === "system" ? "📣" : isUser ? "👤" : "🤖"}
      </div>
      <div className="message__body">
        <div className="message__author">{authorName}</div>
        {isUser ? (
          <span className="message__text">{content}</span>
        ) : (
          <Suspense fallback={<MarkdownFallback content={content} />}>
            <LazyChatMarkdownRenderer content={content} />
          </Suspense>
        )}
        {isStreaming && <span className="message__cursor" aria-hidden>▊</span>}
      </div>
      <time className="message__time" dateTime={new Date(timestamp).toISOString()}>
        {new Date(timestamp).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
      </time>
    </div>
  );
});
