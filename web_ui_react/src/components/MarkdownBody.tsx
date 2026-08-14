import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMarkdownRendererProps } from "./ChatMarkdownRenderer.js";

const markdownRenderers: Components = {
  pre: ({ node: _node, ...props }) => (
    <div className="code-block-wrapper">
      <pre {...props} />
    </div>
  ),
};

type MarkdownBodyProps = ChatMarkdownRendererProps & {
  rehypePlugins?: React.ComponentProps<typeof ReactMarkdown>["rehypePlugins"];
};

/** Render Markdown with optional rehype transforms supplied by a lazy feature chunk. */
export function MarkdownBody({ content, rehypePlugins = [] }: MarkdownBodyProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={rehypePlugins}
      className="message__markdown"
      components={markdownRenderers}
    >
      {content}
    </ReactMarkdown>
  );
}
