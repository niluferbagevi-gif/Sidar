import React from "react";
import { render, screen } from "@testing-library/react";
import { ChatMessage } from "./ChatMessage.jsx";

// ReactMarkdown ve eklentilerini stub'la — jsdom ortamında sorunsuz çalışsın
vi.mock("react-markdown", () => ({
  default: ({ children }) => <div data-testid="markdown">{children}</div>,
}));
vi.mock("remark-gfm", () => ({ default: () => {} }));
vi.mock("rehype-highlight", () => ({ default: () => {} }));

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
    render(<ChatMessage message={makeMsg()} />);
    // toLocaleTimeString Türkçe ile oluşturulan saat değeri mevcut olmalı
    const timeEl = document.querySelector("time");
    expect(timeEl).toBeTruthy();
    expect(timeEl.dateTime).toContain("2024-01-01");
  });
});

describe("ChatMessage — asistan mesajı", () => {
  it("renders assistant content through ReactMarkdown", () => {
    const msg = makeMsg({ role: "assistant", content: "**Kalın metin**" });
    render(<ChatMessage message={msg} />);
    expect(screen.getByTestId("markdown")).toHaveTextContent("**Kalın metin**");
  });

  it("shows default author 'SİDAR' for assistant role", () => {
    render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(screen.getByText("SİDAR")).toBeInTheDocument();
  });

  it("shows 🤖 avatar icon for assistant", () => {
    render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(screen.getByText("🤖")).toBeInTheDocument();
  });

  it("applies message--assistant CSS class", () => {
    const { container } = render(<ChatMessage message={makeMsg({ role: "assistant" })} />);
    expect(container.querySelector(".message--assistant")).toBeInTheDocument();
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
  it("shows blinking cursor when isStreaming is true", () => {
    const msg = makeMsg({ role: "assistant" });
    const { container } = render(<ChatMessage message={msg} isStreaming />);
    expect(container.querySelector(".message--streaming")).toBeInTheDocument();
    expect(screen.getByText("▊")).toBeInTheDocument();
  });

  it("does NOT show cursor when isStreaming is false", () => {
    const msg = makeMsg({ role: "assistant" });
    render(<ChatMessage message={msg} isStreaming={false} />);
    expect(screen.queryByText("▊")).not.toBeInTheDocument();
  });
});
