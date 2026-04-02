import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PluginMarketplacePanel } from "./PluginMarketplacePanel.jsx";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));

vi.mock("../lib/api.js", () => ({ fetchJson }));

describe("PluginMarketplacePanel", () => {
  beforeEach(() => {
    fetchJson.mockReset();
  });

  it("loads catalog data and installs a plugin", async () => {
    const user = userEvent.setup();
    const catalog = {
      items: [{
        plugin_id: "sec-audit",
        name: "Security Audit",
        category: "security",
        summary: "Denetim",
        description: "Açıklama",
        role_name: "security",
        version: "1.0.0",
        entrypoint: "plugins/security.py",
        capabilities: ["audit"],
        installed: false,
        live_registered: false,
      }],
    };
    fetchJson
      .mockResolvedValueOnce(catalog)
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({ items: [{ ...catalog.items[0], installed: true, live_registered: true }] });

    render(<PluginMarketplacePanel />);

    expect(await screen.findByText("Security Audit")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anında Yükle" }));

    await waitFor(() => expect(fetchJson).toHaveBeenCalledWith("/api/plugin-marketplace/install", expect.objectContaining({ method: "POST" })));
    expect(screen.getByText(/Plugin işlemi tamamlandı/)).toBeInTheDocument();
  });

  it("renders API error banner when catalog load fails", async () => {
    fetchJson.mockRejectedValueOnce(new Error("Catalog unavailable"));

    render(<PluginMarketplacePanel />);

    expect(await screen.findByText("Catalog unavailable")).toBeInTheDocument();
  });

  it("enables hot reload for live plugin", async () => {
    const user = userEvent.setup();
    const liveCatalog = {
      items: [{
        plugin_id: "live-plugin",
        name: "Live Plugin",
        category: "ops",
        summary: "Canlı plugin",
        description: "Açıklama",
        role_name: "ops",
        version: "1.0.1",
        entrypoint: "plugins/live.py",
        capabilities: ["ops"],
        installed: true,
        live_registered: true,
      }],
    };

    fetchJson
      .mockResolvedValueOnce(liveCatalog)
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce(liveCatalog);

    render(<PluginMarketplacePanel />);

    expect(await screen.findByText("Live Plugin")).toBeInTheDocument();
    const reloadButton = screen.getByRole("button", { name: "Hot Reload" });
    expect(reloadButton).toBeEnabled();

    await user.click(reloadButton);

    await waitFor(() =>
      expect(fetchJson).toHaveBeenCalledWith(
        "/api/plugin-marketplace/reload",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("renders empty state when catalog has no plugins", async () => {
    fetchJson.mockResolvedValueOnce({ items: [] });
    render(<PluginMarketplacePanel />);

    expect(await screen.findByText("Henüz marketplace girdisi bulunamadı.")).toBeInTheDocument();
  });

  it("sends DELETE for remove action and surfaces action errors", async () => {
    const user = userEvent.setup();
    const liveCatalog = {
      items: [{
        plugin_id: "live-plugin",
        name: "Live Plugin",
        category: "ops",
        summary: "Canlı plugin",
        description: "Açıklama",
        role_name: "ops",
        version: "1.0.1",
        entrypoint: "plugins/live.py",
        capabilities: ["ops"],
        installed: true,
        live_registered: true,
      }],
    };

    fetchJson
      .mockResolvedValueOnce(liveCatalog)
      .mockRejectedValueOnce(new Error("Remove failed"));

    render(<PluginMarketplacePanel />);
    expect(await screen.findByText("Live Plugin")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Devre Dışı Bırak" }));

    await waitFor(() =>
      expect(fetchJson).toHaveBeenCalledWith(
        "/api/plugin-marketplace/install/live-plugin",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    expect(await screen.findByText("Remove failed")).toBeInTheDocument();
  });
});
