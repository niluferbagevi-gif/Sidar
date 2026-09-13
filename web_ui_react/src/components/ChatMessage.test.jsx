import { render, screen } from "@testing-library/react";
import { ChatMessage } from "./ChatMessage.tsx";

// ReactMarkdown ve eklentilerini stub'la — jsdom ortamında sorunsuz çalışsın
vi.mock("react-markdown", () => ({
  default: ({ children, components }) => {
    const text = String(children || "");
    if (text.includes("```") && components?.pre) {
      return <div data-testid="markdown">{components.pre({ children: <code>demo</code> })}</div>;
    }
    return <div data-testid="markdown">{children}</div>;
  },
}));
vi.mock("remark-gfm", () => ({ default: () => {} }));
vi.mock("../lib/rehypeSidarHighlight.js", () => ({ default: () => {} }));

const makeMsg = (overrides = {}) => ({
  id: "msg-1",
  role: "user",
  content: "Merhaba SİDAR",
  ts: new Date("2024-01-01T10:00:00").getTime(),
  author_name: "",
  ...overrides,
});

describe("ChatMessage — kullanıcı mesajı", () => {
  it("renders user message text as plain span", () => {
    render(<ChatMessage message={makeMsg()} />);
    expect(screen.getByText("Merhaba SİDAR")).toBeInTheDocument();
  });

  it("shows default author 'Ekip Üyesi' for user role without author_name", () => {
    render(<ChatMessage message={makeMsg()} />);
    expect(screen.getByText("Ekip Üyesi")).toBeInTheDocument();
  });

  it("shows custom author_name when provided", () => {
    render(<ChatMessage message={makeMsg({ author_name: "Ali Veli" })} />);
    expect(screen.getByText("Ali Veli")).toBeInTheDocument();
  });

  it("shows 👤 avatar icon for user", () => {
    render(<ChatMessage message={makeMsg()} />);
    expect(screen.getByText("👤")).toBeInTheDocument();
  });

  it("applies message--user CSS class", () => {
    const { container } = render(<ChatMessage message={makeMsg()} />);
    expect(container.querySelector(".message--user")).toBeInTheDocument();
  });

  it("formats timestamp in HH:MM", () => {
    const { container } = render(<ChatMessage message={makeMsg()} />);
    const timeEl = container.querySelector("time");
    expect(timeEl).toBeTruthy();
    expect(timeEl.dateTime).toContain("2024-01-01");
  });
});

describe("ChatMessage — asistan mesajı", () => {
  // ChatMessage.tsx's LazyChatMarkdownRenderer is a module-scoped React.lazy():
  // its dynamic import() only starts on first render and resolves on a later
  // microtask. A test that renders an assistant message and returns without
  // waiting for that resolution lets afterEach's cleanup() unmount the
  // component while the import is still in flight; when it later settles,
  // React updates an already-unmounted Suspense boundary outside any test's
  // act() scope, logging "A suspended resource finished loading inside a
  // test, but the event was not wrapped in act(...)". Every test below that
  // renders an assistant message therefore awaits the markdown testid before
  // finishing, same as the first test already did.
  it("renders assistant content through the lazy Markdown renderer", async () => {
    const msg = makeMsg({ role: "assistant", content: "**Kalın metin**" });
    render(<ChatMessage message={msg} />);
    expect(screen.getByText("**Kalın metin**")).toHaveClass("message__text--markdown-loading");
    expect(await screen.findByTestId("markdown")).toHaveTextContent("**Kalın metin**");
  });

  it("shows default author 'SİDAR' for assistant role", async () => {
    render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(screen.getByText("SİDAR")).toBeInTheDocument();
    await screen.findByTestId("markdown");
  });

  it("shows 🤖 avatar icon for assistant", async () => {
    render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(screen.getByText("🤖")).toBeInTheDocument();
    await screen.findByTestId("markdown");
  });

  it("applies message--assistant CSS class", async () => {
    const { container } = render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(container.querySelector(".message--assistant")).toBeInTheDocument();
    await screen.findByTestId("markdown");
  });

  it("wraps markdown code blocks in .code-block-wrapper", async () => {
    const msg = makeMsg({ role: "assistant", content: "```js\nconsole.log('x')\n```" });
    const { container } = render(<ChatMessage message={msg} />);
    await screen.findByTestId("markdown");
    expect(container.querySelector(".code-block-wrapper")).toBeInTheDocument();
  });

  it("normalizes sparse messages to safe assistant defaults", async () => {
    const { container } = render(<ChatMessage message={{ id: "sparse" }} />);

    expect(container.querySelector(".message--assistant")).toBeInTheDocument();
    expect(container.querySelector("time")?.dateTime).toBeTruthy();
    expect(await screen.findByTestId("markdown")).toHaveTextContent("");
  });
});

describe("ChatMessage — sistem mesajı", () => {
  it("shows 📣 avatar icon for system role", () => {
    render(<ChatMessage message={makeMsg({ role: "system" })} />);
    expect(screen.getByText("📣")).toBeInTheDocument();
  });

  it("applies message--system CSS class", () => {
    const { container } = render(<ChatMessage message={makeMsg({ role: "system" })} />);
    expect(container.querySelector(".message--system")).toBeInTheDocument();
  });
});

describe("ChatMessage — isStreaming prop", () => {
  // Same module-scoped lazy-import race as "ChatMessage — asistan mesajı"
  // above (assistant role here too) -- await the markdown testid so cleanup()
  // never unmounts while the import is still in flight, regardless of
  // whether this describe block happens to run before that one (e.g. `-t`
  // filtering or `.only`).
  it("shows blinking cursor when isStreaming is true", async () => {
    const msg = makeMsg({ role: "assistant" });
    const { container } = render(<ChatMessage message={msg} isStreaming />);
    expect(container.querySelector(".message--streaming")).toBeInTheDocument();
    expect(screen.getByText("▊")).toBeInTheDocument();
    await screen.findByTestId("markdown");
  });

  it("does NOT show cursor when isStreaming is false", async () => {
    const msg = makeMsg({ role: "assistant" });
    render(<ChatMessage message={msg} isStreaming={false} />);
    expect(screen.queryByText("▊")).not.toBeInTheDocument();
    await screen.findByTestId("markdown");
  });
});
