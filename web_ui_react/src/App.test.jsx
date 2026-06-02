import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";
import * as api from "./lib/api.js";

const { chatPanelMountSpy } = vi.hoisted(() => ({ chatPanelMountSpy: vi.fn() }));

vi.mock("./components/ChatPanel.jsx", () => ({
  ChatPanel: () => {
    React.useEffect(() => {
      chatPanelMountSpy();
    }, []);
    return <div data-testid="chat-panel">Chat Panel Mock</div>;
  },
}));
vi.mock("./components/P2PDialoguePanel.jsx", () => ({ P2PDialoguePanel: () => <div>P2P Mock</div> }));
vi.mock("./components/SwarmFlowPanel.jsx", () => ({ SwarmFlowPanel: () => <div>Swarm Mock</div> }));
vi.mock("./components/TenantAdminPanel.jsx", () => ({ TenantAdminPanel: () => <div>Tenant Mock</div> }));
vi.mock("./components/PromptAdminPanel.jsx", () => ({ PromptAdminPanel: () => <div>Prompt Mock</div> }));
vi.mock("./components/AgentManagerPanel.jsx", () => ({ AgentManagerPanel: () => <div>Agent Manager Mock</div> }));
vi.mock("./components/PluginMarketplacePanel.jsx", () => ({ PluginMarketplacePanel: () => <div>Plugin Marketplace Mock</div> }));
vi.mock("./components/OperationsQaPanel.jsx", () => ({ OperationsQaPanel: () => <div>Ops QA Mock</div> }));

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

  it("token kaydedildiğinde chat panelini yeniden mount etmez", async () => {
    const user = userEvent.setup();
    renderApp("/chat");

    expect(chatPanelMountSpy).toHaveBeenCalledTimes(1);
    await user.type(screen.getByLabelText("Bearer token"), "yeni-token");
    await user.click(screen.getByRole("button", { name: "Token Kaydet" }));

    expect(chatPanelMountSpy).toHaveBeenCalledTimes(1);
  });

  it("navigasyondaki P2P bağlantısının doğru adrese gittiğini gösterir", () => {
    renderApp("/chat");

    const p2pLink = screen.getByRole("link", { name: "P2P Diyalog" });
    expect(p2pLink).toHaveAttribute("href", "/p2p");
  });

  it("navigates to P2P, Swarm and Tenant panels via nav links", async () => {
    const user = userEvent.setup();
    renderApp("/chat");

    await user.click(screen.getByRole("link", { name: "P2P Diyalog" }));
    expect(screen.getByText("P2P Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Swarm Akışı" }));
    expect(screen.getByText("Swarm Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Poyraz & Coverage" }));
    expect(screen.getByText("Ops QA Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Tenant Admin" }));
    expect(screen.getByText("Tenant Mock")).toBeInTheDocument();
  });

  it("catch-all rotasında bilinmeyen adresleri /chat'e yönlendirir", async () => {
    renderApp("/bilinmeyen-rota");

    expect(await screen.findByTestId("chat-panel")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("link", { name: "Sohbet" })).toHaveClass("is-active"));
  });

  it("shows token-ready hint without a timestamp when a stored token exists before saving", () => {
    api.getStoredToken.mockReturnValue("hazir-token");

    renderApp("/chat");

    expect(screen.getByText("Token hazır")).toBeInTheDocument();
  });

  it("shows default token hint when no token is set", () => {
    api.getStoredToken.mockReturnValue(null);
    renderApp("/");
    expect(screen.getByText(/Admin ve sohbet API/)).toBeInTheDocument();
  });

  it("Prompt Admin, Agent Manager ve Plugin Marketplace sekmelerine geçişi doğrular", async () => {
    const user = userEvent.setup();
    renderApp("/chat");

    await user.click(screen.getByRole("link", { name: "Prompt Admin" }));
    expect(screen.getByText("Prompt Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Plugin Marketplace" }));
    expect(screen.getByText("Plugin Marketplace Mock")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Agent Manager" }));
    expect(screen.getByText("Agent Manager Mock")).toBeInTheDocument();
  });
});
