import React from "react";
import { MarkdownBody } from "./MarkdownBody.js";

const HighlightedChatMarkdownRenderer = React.lazy(() =>
  import("./HighlightedChatMarkdownRenderer.js").then((module) => ({
    default: module.HighlightedChatMarkdownRenderer,
  })),
);

const FENCED_CODE_BLOCK = /(?:^|\n)\s*(?:```|~~~)[^\n]*\n/;

export interface ChatMarkdownRendererProps {
  content: string;
}

export const ChatMarkdownRenderer = React.memo(function ChatMarkdownRenderer({ content }: ChatMarkdownRendererProps) {
  if (!FENCED_CODE_BLOCK.test(content)) {
    return <MarkdownBody content={content} />;
  }

  return (
    <React.Suspense fallback={<MarkdownBody content={content} />}>
      <HighlightedChatMarkdownRenderer content={content} />
    </React.Suspense>
  );
});
