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
  // react-markdown 10 dropped the `className` prop (it used to wrap output in
  // a `<div className="...">` for you); the explicit wrapper below produces
  // the exact same DOM the removed prop did, so `.message__markdown`'s
  // descendant selectors in index.css are unaffected.
  return (
    <div className="message__markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins}
        components={markdownRenderers}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
