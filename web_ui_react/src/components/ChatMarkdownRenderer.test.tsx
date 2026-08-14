import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatMarkdownRenderer } from "./ChatMarkdownRenderer.js";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="markdown-body">{children}</div>
  ),
}));
vi.mock("remark-gfm", () => ({ default: () => undefined }));
vi.mock("./HighlightedChatMarkdownRenderer.js", () => ({
  HighlightedChatMarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="highlighted-markdown">{content}</div>
  ),
}));

describe("ChatMarkdownRenderer lazy syntax highlighting", () => {
  it("does not request the highlighting renderer for ordinary Markdown", async () => {
    render(<ChatMarkdownRenderer content="**normal markdown**" />);

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByTestId("markdown-body")).toHaveTextContent("**normal markdown**");
    expect(screen.queryByTestId("highlighted-markdown")).not.toBeInTheDocument();
  });

  it.each(["```ts\nconst ready = true;\n```", "~~~python\nprint('ready')\n~~~"])(
    "loads the highlighting renderer only for a fenced code block",
    async (content) => {
      render(<ChatMarkdownRenderer content={content} />);

      expect(await screen.findByTestId("highlighted-markdown")).toHaveTextContent("ready");
    },
  );
});
