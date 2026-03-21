import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PluginMarketplacePanel } from "./PluginMarketplacePanel.jsx";

const fetchJson = vi.fn();

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
});
