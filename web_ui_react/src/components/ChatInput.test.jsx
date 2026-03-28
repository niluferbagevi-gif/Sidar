import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInput } from "./ChatInput.jsx";

// useChatStore mock — isStreaming kontrolü için
const mockStore = { isStreaming: false };

vi.mock("../hooks/useChatStore.js", () => ({
  useChatStore: () => mockStore,
}));

describe("ChatInput", () => {
  beforeEach(() => {
    mockStore.isStreaming = false;
  });

  it("renders textarea and send button", () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gönder" })).toBeInTheDocument();
  });

  it("send button is disabled when textarea is empty", () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Gönder" })).toBeDisabled();
  });

  it("send button becomes enabled when text is typed", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={vi.fn()} />);
    await user.type(screen.getByRole("textbox"), "merhaba");
    expect(screen.getByRole("button", { name: "Gönder" })).toBeEnabled();
  });

  it("calls onSend with trimmed text on button click", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await user.type(screen.getByRole("textbox"), "  merhaba sidar  ");
    await user.click(screen.getByRole("button", { name: "Gönder" }));
    expect(onSend).toHaveBeenCalledWith("merhaba sidar");
  });

  it("clears textarea after sending", async () => {
    const user = userEvent.setup();
    render(<ChatInput onSend={vi.fn()} />);
    const textarea = screen.getByRole("textbox");
    await user.type(textarea, "test mesajı");
    await user.click(screen.getByRole("button", { name: "Gönder" }));
    expect(textarea).toHaveValue("");
  });

  it("sends on Enter key", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await user.type(screen.getByRole("textbox"), "enter ile gönder{Enter}");
    expect(onSend).toHaveBeenCalledWith("enter ile gönder");
  });

  it("does NOT send on Shift+Enter (adds newline instead)", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await user.type(screen.getByRole("textbox"), "satır{Shift>}{Enter}{/Shift}devam");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not call onSend when isStreaming is true", async () => {
    mockStore.isStreaming = true;
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await user.type(screen.getByRole("textbox"), "streaming sırasında");
    await user.click(screen.getByRole("button", { name: "Gönder" }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows ⏳ icon on button when isStreaming", () => {
    mockStore.isStreaming = true;
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Gönder" })).toHaveTextContent("⏳");
  });

  it("shows ➤ icon on button when not streaming", () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Gönder" })).toHaveTextContent("➤");
  });

  it("textarea and button are disabled when disabled prop is true", () => {
    render(<ChatInput onSend={vi.fn()} disabled />);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Gönder" })).toBeDisabled();
  });

  it("does not call onSend on button click when disabled prop is true", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} disabled />);
    await user.type(screen.getByRole("textbox"), "disabled");
    await user.click(screen.getByRole("button", { name: "Gönder" }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("does not call onSend for whitespace-only input", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    await user.type(screen.getByRole("textbox"), "   {Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("textarea has correct aria-label", () => {
    render(<ChatInput onSend={vi.fn()} />);
    expect(screen.getByLabelText("Mesaj giriş alanı")).toBeInTheDocument();
  });
});
