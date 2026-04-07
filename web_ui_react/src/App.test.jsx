import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";
import * as api from "./lib/api.js";

vi.mock("./components/ChatPanel.jsx", () => ({ ChatPanel: () => <div data-testid="chat-panel">Chat Panel Mock</div> }));
vi.mock("./components/P2PDialoguePanel.jsx", () => ({ P2PDialoguePanel: () => <div>P2P Mock</div> }));
vi.mock("./components/SwarmFlowPanel.jsx", () => ({ SwarmFlowPanel: () => <div>Swarm Mock</div> }));
vi.mock("./components/TenantAdminPanel.jsx", () => ({ TenantAdminPanel: () => <div>Tenant Mock</div> }));
vi.mock("./components/PromptAdminPanel.jsx", () => ({ PromptAdminPanel: () => <div>Prompt Mock</div> }));
vi.mock("./components/AgentManagerPanel.jsx", () => ({ AgentManagerPanel: () => <div>Agent Manager Mock</div> }));
vi.mock("./components/PluginMarketplacePanel.jsx", () => ({ PluginMarketplacePanel: () => <div>Plugin Marketplace Mock</div> }));

vi.mock("./lib/api.js", async () => {
  const actual = await vi.importActual("./lib/api.js");
  return {
    ...actual,
    getStoredToken: vi.fn(),
    setStoredToken: vi.fn(),
  };
});

function renderApp(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getStoredToken.mockReturnValue(null);
  });

  it("başlık bilgisini render eder ve / rotasında chat paneline yönlendirir", () => {
    renderApp("/");

    expect(screen.getByText(/SİDAR/i)).toBeInTheDocument();
    expect(screen.getByText(/Kurumsal Agent Control Center/i)).toBeInTheDocument();
    expect(screen.getByTestId("chat-panel")).toBeInTheDocument();
  });

  it("token kaydet akışında API yardımcılarını doğru çağırır", async () => {
    const user = userEvent.setup();
    api.getStoredToken.mockReturnValue("eski-token");

    renderApp("/chat");

    const input = screen.getByLabelText("Bearer token");
    expect(input).toHaveValue("eski-token");

    await user.clear(input);
    await user.type(input, "yeni-gizli-token");
    await user.click(screen.getByRole("button", { name: "Token Kaydet" }));

    expect(api.setStoredToken).toHaveBeenCalledWith("yeni-gizli-token");
    expect(screen.getByText(/Token hazır/i)).toBeInTheDocument();
  });

  it("navigasyondaki P2P bağlantısının doğru adrese gittiğini gösterir", () => {
    renderApp("/chat");

    const p2pLink = screen.getByRole("link", { name: "P2P Diyalog" });
    expect(p2pLink).toHaveAttribute("href", "/p2p");
  });

  it("Agent Manager ve Plugin Marketplace sekmelerine geçişi doğrular", async () => {
    const user = userEvent.setup();
    renderApp("/chat");

    await user.click(screen.getByRole("link", { name: "Plugin Marketplace" }));
    expect(screen.getByText("Plugin Marketplace Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Agent Manager" }));
    expect(screen.getByText("Agent Manager Mock")).toBeInTheDocument();
  });
});
