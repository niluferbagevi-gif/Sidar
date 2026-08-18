import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MarkdownBody } from "./MarkdownBody.js";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="markdown-body">{children}</div>
  ),
}));
vi.mock("remark-gfm", () => ({ default: () => undefined }));

describe("MarkdownBody", () => {
  it("wraps ReactMarkdown's output in a .message__markdown container", () => {
    // react-markdown 10 removed the `className` prop (it used to wrap
    // output in a `<div className="...">` for you) — this locks in that
    // MarkdownBody's explicit wrapper div still produces the same class on
    // the same DOM position, so index.css's `.message__markdown ...`
    // descendant selectors keep matching.
    render(<MarkdownBody content="hello" />);

    const markdown = screen.getByTestId("markdown-body");
    expect(markdown.parentElement).toHaveClass("message__markdown");
  });
});
