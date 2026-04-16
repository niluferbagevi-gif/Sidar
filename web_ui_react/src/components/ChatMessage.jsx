/**
 * ChatMessage — Tek bir sohbet mesajını render eder.
 * Asistan mesajları Markdown (kod vurgulamalı) olarak gösterilir.
 */

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

const markdownRenderers = {
  pre: ({ node, ...props }) => (
    <div className="code-block-wrapper">
      <pre {...props} />
    </div>
  ),
};

const MemoMarkdown = React.memo(function MemoMarkdown({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      className="message__markdown"
      components={markdownRenderers}
    >
      {content}
    </ReactMarkdown>
  );
});

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
          <MemoMarkdown content={message.content} />
        )}
        {isStreaming && <span className="message__cursor" aria-hidden>▊</span>}
      </div>
      <time className="message__time" dateTime={new Date(message.ts).toISOString()}>
        {new Date(message.ts).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}
      </time>
    </div>
  );
});
