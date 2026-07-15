/**
 * ChatMessage — Tek bir sohbet mesajını render eder.
 * Asistan mesajları Markdown (kod vurgulamalı) olarak gösterilir.
 */

import React, { Suspense } from "react";

const LazyChatMarkdownRenderer = React.lazy(() =>
  import("./ChatMarkdownRenderer.jsx").then((module) => ({
    default: module.ChatMarkdownRenderer,
  })),
);

function MarkdownFallback({ content }) {
  return <span className="message__text message__text--markdown-loading">{content}</span>;
}

export const ChatMessage = React.memo(function ChatMessage({ message, isStreaming = false }) {
  const isUser = message.role === "user";
  const authorName = message.author_name || (isUser ? "Ekip Üyesi" : "SİDAR");

  return (
    <div className={`message message--${message.role}${isStreaming ? " message--streaming" : ""}`}>
      <div className="message__avatar">
        {message.role === "system" ? "📣" : isUser ? "👤" : "🤖"}
      </div>
      <div className="message__body">
        <div className="message__author">{authorName}</div>
        {isUser ? (
          <span className="message__text">{message.content}</span>
        ) : (
          <Suspense fallback={<MarkdownFallback content={message.content} />}>
            <LazyChatMarkdownRenderer content={message.content} />
          </Suspense>
        )}
        {isStreaming && <span className="message__cursor" aria-hidden>▊</span>}
      </div>
      <time className="message__time" dateTime={new Date(message.ts).toISOString()}>
        {new Date(message.ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
      </time>
    </div>
  );
});
