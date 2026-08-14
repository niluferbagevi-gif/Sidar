import React from "react";
import rehypeSidarHighlight from "../lib/rehypeSidarHighlight.js";
import type { ChatMarkdownRendererProps } from "./ChatMarkdownRenderer.js";
import { MarkdownBody } from "./MarkdownBody.js";

/** Render fenced code blocks after the syntax-highlighting chunk is requested. */
export const HighlightedChatMarkdownRenderer = React.memo(
  function HighlightedChatMarkdownRenderer({ content }: ChatMarkdownRendererProps) {
    return <MarkdownBody content={content} rehypePlugins={[rehypeSidarHighlight]} />;
  },
);
