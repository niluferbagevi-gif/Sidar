/**
 * ChatMessage — Tek bir sohbet mesajını render eder.
 * Asistan mesajları Markdown (kod vurgulamalı) olarak gösterilir.
 */

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

export function ChatMessage({ message, isStreaming = false }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  return (
    <div className={`message message--${message.role}${isStreaming ? " message--streaming" : ""}`}>
      <div className="message__avatar">
        {isUser ? "👤" : "🤖"}
      </div>
      <div className="message__body">
        {isUser ? (
          <span className="message__text">{message.content}</span>
        ) : (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            className="message__markdown"
            components={{
              pre: ({ node, ...props }) => (
                <div className="code-block-wrapper">
                  <pre {...props} />
                </div>
              ),
            }}
          >
            {message.content}
          </ReactMarkdown>
        )}
        {isStreaming && <span className="message__cursor" aria-hidden>▊</span>}
      </div>
      <time className="message__time" dateTime={new Date(message.ts).toISOString()}>
        {new Date(message.ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
      </time>
    </div>
  );
}