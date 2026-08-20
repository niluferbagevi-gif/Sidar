import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import rehypeSidarHighlight from "../lib/rehypeSidarHighlight.js";
import { HighlightedChatMarkdownRenderer } from "./HighlightedChatMarkdownRenderer.js";

const { reactMarkdownSpy } = vi.hoisted(() => ({
  reactMarkdownSpy: vi.fn(
    ({ children }: { children: ReactNode; rehypePlugins?: unknown[] }) => (
      <div data-testid="highlighted-markdown-body">{children}</div>
    ),
  ),
}));

vi.mock("react-markdown", () => ({ default: reactMarkdownSpy }));
vi.mock("remark-gfm", () => ({ default: () => undefined }));

describe("HighlightedChatMarkdownRenderer", () => {
  it("passes content and the Sidar highlight plugin to MarkdownBody", () => {
    const content = "```ts\nconst ready = true;\n```";

    render(<HighlightedChatMarkdownRenderer content={content} />);

    expect(screen.getByTestId("highlighted-markdown-body").textContent).toBe(content);
    expect(reactMarkdownSpy).toHaveBeenCalledOnce();
    expect(reactMarkdownSpy.mock.calls[0]?.[0]).toMatchObject({
      children: content,
      rehypePlugins: [rehypeSidarHighlight],
    });
  });
});
