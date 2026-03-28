import React from "react";
import { render, screen } from "@testing-library/react";
import { ChatWindow } from "./ChatWindow.jsx";

// jsdom'da scrollIntoView tanımlı değil — stub ekle
beforeAll(() => {
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});

// ChatMessage bileşenini stub'la — içerik kontrolü için basit gösterim
vi.mock("./ChatMessage.jsx", () => ({
  ChatMessage: ({ message, isStreaming }) => (
    <div data-testid="chat-message" data-streaming={isStreaming ? "true" : "false"}>
      {message.content}
    </div>
  ),
}));

// useChatStore mock — her testte farklı store durumu verebilmek için
const mockStore = {
  messages: [],
  streamingText: "",
  isStreaming: false,
  error: null,
};

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => mockStore,
}));

describe("ChatWindow — boş durum", () => {
  beforeEach(() => {
    mockStore.messages = [];
    mockStore.streamingText = "";
    mockStore.isStreaming = false;
    mockStore.error = null;
  });

  it("shows welcome message when no messages exist and not streaming", () => {
    render(<ChatWindow />);
    expect(screen.getByText(/Merhaba/)).toBeInTheDocument();
  });

  it("shows hint text in empty state", () => {
    render(<ChatWindow />);
    expect(screen.getByText(/Kod yazma/)).toBeInTheDocument();
  });

  it("has role=log and aria-live=polite for accessibility", () => {
    const { container } = render(<ChatWindow />);
    const log = container.querySelector('[role="log"]');
    expect(log).toBeInTheDocument();
    expect(log).toHaveAttribute("aria-live", "polite");
  });
});

describe("ChatWindow — mesaj listesi", () => {
  beforeEach(() => {
    mockStore.streamingText = "";
    mockStore.isStreaming = false;
    mockStore.error = null;
  });

  it("renders each message as ChatMessage", () => {
    mockStore.messages = [
      { id: "1", role: "user", content: "mesaj 1", ts: Date.now() },
      { id: "2", role: "assistant", content: "mesaj 2", ts: Date.now() },
    ];
    render(<ChatWindow />);
    expect(screen.getAllByTestId("chat-message")).toHaveLength(2);
  });

  it("does NOT show empty state when messages exist", () => {
    mockStore.messages = [
      { id: "1", role: "user", content: "bir mesaj", ts: Date.now() },
    ];
    render(<ChatWindow />);
    expect(screen.queryByText(/Merhaba/)).not.toBeInTheDocument();
  });

  it("renders message content correctly", () => {
    mockStore.messages = [
      { id: "1", role: "user", content: "özel mesaj içeriği", ts: Date.now() },
    ];
    render(<ChatWindow />);
    expect(screen.getByText("özel mesaj içeriği")).toBeInTheDocument();
  });
});

describe("ChatWindow — streaming durumu", () => {
  beforeEach(() => {
    mockStore.messages = [];
    mockStore.error = null;
  });

  it("shows streaming message when isStreaming and streamingText are set", () => {
    mockStore.isStreaming = true;
    mockStore.streamingText = "akış metni";
    render(<ChatWindow />);
    const streamingMsg = screen.getByTestId("chat-message");
    expect(streamingMsg).toHaveTextContent("akış metni");
    expect(streamingMsg).toHaveAttribute("data-streaming", "true");
  });

  it("does NOT render streaming ChatMessage when streamingText is empty", () => {
    mockStore.isStreaming = true;
    mockStore.streamingText = "";
    render(<ChatWindow />);
    expect(screen.queryByTestId("chat-message")).not.toBeInTheDocument();
  });

  it("hides empty state when streaming is active", () => {
    mockStore.isStreaming = true;
    mockStore.streamingText = "yükleniyor";
    render(<ChatWindow />);
    expect(screen.queryByText(/Merhaba/)).not.toBeInTheDocument();
  });
});

describe("ChatWindow — hata durumu", () => {
  beforeEach(() => {
    mockStore.messages = [];
    mockStore.streamingText = "";
    mockStore.isStreaming = false;
  });

  it("shows error alert when error is set", () => {
    mockStore.error = "Bağlantı koptu";
    render(<ChatWindow />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Bağlantı koptu");
  });

  it("does NOT show error alert when error is null", () => {
    mockStore.error = null;
    render(<ChatWindow />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows both messages and error simultaneously", () => {
    mockStore.messages = [
      { id: "1", role: "user", content: "bir mesaj", ts: Date.now() },
    ];
    mockStore.error = "Kısmi hata";
    render(<ChatWindow />);
    expect(screen.getByTestId("chat-message")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
