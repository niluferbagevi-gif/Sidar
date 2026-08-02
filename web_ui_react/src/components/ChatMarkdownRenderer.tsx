import React from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSidarHighlight from "../lib/rehypeSidarHighlight.js";

const markdownRenderers: Components = {
  pre: ({ node: _node, ...props }) => (
    <div className="code-block-wrapper">
      <pre {...props} />
    </div>
  ),
};

interface ChatMarkdownRendererProps {
  content: string;
}

export const ChatMarkdownRenderer = React.memo(function ChatMarkdownRenderer({ content }: ChatMarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeSidarHighlight]}
      className="message__markdown"
      components={markdownRenderers}
    >
      {content}
    </ReactMarkdown>
  );
});
