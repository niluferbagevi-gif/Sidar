import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import { BrowserRouter } from "./lib/routerShim.jsx";
import { TOKEN_KEY } from "./lib/api.js";

vi.mock("./components/ChatPanel.jsx", () => ({ ChatPanel: () => <div>ChatPanel Mock</div> }));
vi.mock("./components/P2PDialoguePanel.jsx", () => ({ P2PDialoguePanel: () => <div>P2P Mock</div> }));
vi.mock("./components/SwarmFlowPanel.jsx", () => ({ SwarmFlowPanel: () => <div>Swarm Mock</div> }));
vi.mock("./components/TenantAdminPanel.jsx", () => ({ TenantAdminPanel: () => <div>Tenant Mock</div> }));
vi.mock("./components/PromptAdminPanel.jsx", () => ({ PromptAdminPanel: () => <div>Prompt Mock</div> }));
vi.mock("./components/AgentManagerPanel.jsx", () => ({ AgentManagerPanel: () => <div>Agent Manager Mock</div> }));
vi.mock("./components/PluginMarketplacePanel.jsx", () => ({ PluginMarketplacePanel: () => <div>Plugin Marketplace Mock</div> }));

function renderApp(initialPath = "/") {
  window.history.replaceState({}, "Test", initialPath);
  return render(
    <BrowserRouter>
      <App />
    </BrowserRouter>,
  );
}

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState({}, "Test", "/");
  });

  it("stores the bearer token and updates the token hint", async () => {
    const user = userEvent.setup();
    renderApp();

    const input = screen.getByLabelText("Bearer token");
    await user.type(input, "secret-token");
    await user.click(screen.getByRole("button", { name: "Token Kaydet" }));

    expect(localStorage.getItem(TOKEN_KEY)).toBe("secret-token");
    expect(screen.getByText(/Token hazır/)).toBeInTheDocument();
  });

  it("navigates to the agent manager route from the tab bar", async () => {
    const user = userEvent.setup();
    renderApp("/chat");

    await user.click(screen.getByRole("link", { name: "Agent Manager" }));

    expect(screen.getByText("Agent Manager Mock")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/admin/agents");
  });
});